import os
import subprocess
import logging
import re
import json
import datetime
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
USAGE_FILE = "usage.json"
PAID_FILE = "paid.json"            # بيانات المشتركين المدفوعين
REQUESTS_FILE = "requests.txt"     # طلبات الاشتراك المعلقة

FREE_VIDEO_LIMIT = 3
FREE_AI_LIMIT = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# --- Utilities --- #

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def store_user(user):
    os.makedirs(os.path.dirname(USERS_FILE) or ".", exist_ok=True)
    line = f"{user.id}|{user.username or ''}|{user.first_name or ''} {user.last_name or ''}".strip()
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w").close()
    with open(USERS_FILE, "r+") as f:
        users = f.read().splitlines()
        if not any(u.split("|")[0] == str(user.id) for u in users):
            f.write(line + "\n")

def is_valid_url(text):
    return bool(re.match(r"^(https?://)?(www\.)?"
                        r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+", text))

def is_paid(user_id):
    data = load_json(PAID_FILE, {})
    return str(user_id) in data and data[str(user_id)]["active"]

def activate(user_id):
    data = load_json(PAID_FILE, {})
    data[str(user_id)] = {"active": True, "since": datetime.datetime.utcnow().isoformat()}
    save_json(PAID_FILE, data)

def deactivate(user_id):
    data = load_json(PAID_FILE, {})
    data.pop(str(user_id), None)
    save_json(PAID_FILE, data)

def reset_usage(usage):
    today = datetime.date.today().isoformat()
    if usage.get("date") != today:
        usage["date"] = today
        usage["video"] = {}
        usage["ai"] = {}
    return usage

def check_limit(user_id, kind):
    if is_paid(user_id):
        return True
    usage = load_json(USAGE_FILE, {"date": "", "video": {}, "ai": {}})
    usage = reset_usage(usage)
    cnt = usage[kind].get(str(user_id), 0)
    limit = FREE_VIDEO_LIMIT if kind == "video" else FREE_AI_LIMIT
    if cnt >= limit:
        return False
    usage[kind][str(user_id)] = cnt + 1
    save_json(USAGE_FILE, usage)
    return True

def load_stats():
    return load_json(STATS_FILE, {
        "total": 0,
        "counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
        "top": None
    })

def save_stats(stats):
    save_json(STATS_FILE, stats)

def update_stats(kind, quality):
    s = load_stats()
    s["total"] += 1
    key = "audio" if kind == "audio" else quality
    s["counts"][key] = s["counts"].get(key, 0) + 1
    s["top"] = max(s["counts"], key=lambda k: s["counts"][k])
    save_stats(s)

# --- Handlers --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو (YouTube, TikTok, Insta, FB) أو أي نص لـ AI.\n"
        f"💡 مجاني: {FREE_VIDEO_LIMIT} فيديوهات و{FREE_AI_LIMIT} أسئلة AI يومياً.\n"
        "🔓 للغير محدود، اضغط \"اشترك الآن\" عند انتهاء الحد."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    text = update.message.text.strip()

    if not is_valid_url(text):
        # AI flow
        if not check_limit(user.id, "ai"):
            return await send_limit(update)
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            await update.message.reply_text(resp.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return

    # download flow
    if not check_limit(user.id, "video"):
        return await send_limit(update)

    key = str(update.message.message_id)
    url_store[key] = text

    kb = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("📥 اختر ما تريد تنزيله:", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    action, quality, key = data
    if action == "cancel":
        url_store.pop(key, None)
        return await query.edit_message_text("❌ تم الإلغاء.")
    url = url_store.get(key)
    if not url:
        return await query.edit_message_text("⚠️ انتهى الطلب، أرسل الرابط مجدداً.")

    msg = await query.edit_message_text(f"⏳ جارٍ التحميل {quality}...")
    # build command
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        fname = "audio.mp3"
    else:
        fmt = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", fmt, "-o", "video.%(ext)s", url]
        fname = None

    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 and action != "audio":
        # fallback
        subprocess.run(["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best", "-o", "video.%(ext)s", url])
    # find file
    if action == "video":
        for ext in ("mp4","mkv","webm"):
            if os.path.exists(f"video.{ext}"):
                fname = f"video.{ext}"
                break

    if fname and os.path.exists(fname):
        with open(fname, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(fname)
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")
    url_store.pop(key, None)
    try: await msg.delete()
    except: pass

async def send_limit(update: Update):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        "🚫 انتهى حلك المجاني اليوم.\n"
        "للاستخدام غير المحدود، أرسل 2 د.ع إلى Orange Money:\n"
        "📲 0781200500\n"
        "ثم اضغط أدناه.",
        reply_markup=kb
    )

# --- Subscription Flow --- #

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    # سجل الطلب
    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username or ''}|{datetime.datetime.utcnow().isoformat()}\n")
    # اطلب الإثبات
    await query.edit_message_text(
        "💳 للاشتراك: أرسل 2 د.ع إلى 0781200500\n"
        "ثم أرسل صورة إثبات الدفع هنا."
    )
    # أخبر الأدمن
    await context.bot.send_message(
        ADMIN_ID,
        f"👤 @{user.username or user.id} طلب اشتراك—في انتظار إثبات الدفع."
    )
    await query.answer()

async def receive_subscription_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message.photo:
        return await update.message.reply_text("❌ الرجاء إرسال صورة.")
    photo_id = update.message.photo[-1].file_id
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأكيد", callback_data=f"sub_confirm|{user.id}"),
        InlineKeyboardButton("❌ رفض",   callback_data=f"sub_reject|{user.id}")
    ]])
    cap = f"📩 إثبات من @{user.username or user.id} (ID: {user.id})"
    await context.bot.send_photo(
        ADMIN_ID, photo=photo_id, caption=cap, reply_markup=kb
    )
    await update.message.reply_text("✅ استلمت، جارٍ المراجعة.")

async def subscription_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, uid = query.data.split("|")
    activate(uid)
    await context.bot.send_message(int(uid), "✅ تم تفعيل اشتراكك بنجاح!")
    await query.message.delete()
    await query.answer("✅ تم التفعيل.")

async def subscription_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, uid = query.data.split("|")
    await context.bot.send_message(int(uid), "❌ عذراً، تم رفض طلبك.")
    await query.message.delete()
    await query.answer("🚫 تم الرفض.")

# --- Broadcast Flow --- #

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    kb = [
        [InlineKeyboardButton("نص",   callback_data="bc_type_text")],
        [InlineKeyboardButton("صورة", callback_data="bc_type_photo")],
        [InlineKeyboardButton("فيديو", callback_data="bc_type_video")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]
    ]
    await query.edit_message_text("اختر نوع الإعلان:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_broadcast_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, _, t = query.data.partition("_type_")
    context.user_data["bc_type"] = t  # text/photo/video
    await query.edit_message_text(f"أرسل الآن الـ{'النص' if t=='text' else t}:")

async def admin_receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    t = context.user_data.get("bc_type")
    if not t:
        return
    context.user_data["bc_msg"] = update.message
    kb = [[
        InlineKeyboardButton("✅ إرسال", callback_data="bc_confirm"),
        InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")
    ]]
    await update.message.reply_text("تأكيد الإرسال؟", reply_markup=InlineKeyboardMarkup(kb))

async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    msg = context.user_data.get("bc_msg")
    t   = context.user_data.get("bc_type")
    sent = 0
    with open(USERS_FILE) as f:
        uids = [int(l.split("|")[0]) for l in f]
    for uid in uids:
        try:
            if t == "text":
                await context.bot.send_message(uid, msg.text)
            elif t == "photo":
                await context.bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption or "")
            else:
                await context.bot.send_video(uid, msg.video.file_id, caption=msg.caption or "")
            sent += 1
        except:
            pass
    await query.message.delete()
    await context.bot.send_message(ADMIN_ID, f"📢 أُرسل الإعلان إلى {sent} مستخدم.")
    await query.answer()

# --- Admin Panel --- #

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 هذا للأدمن فقط.")
    kb = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📋 المشتركين",   callback_data="admin_subscribers")],
        [InlineKeyboardButton("📢 إعلان",        callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات",     callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة يدوي",  callback_data="admin_addpaid")],
        [InlineKeyboardButton("❌ إغلاق",       callback_data="admin_close")]
    ]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        return await query.answer("🚫 ممنوع.")
    # المستخدمين الكلي
    if data == "admin_users":
        with open(USERS_FILE) as f:
            lines = f.read().splitlines()
        txt = f"👥 إجمالي المستخدمين: {len(lines)}\n\n"
        txt += "\n".join(f"• {l.split('|')[2]} (@{l.split('|')[1]})" for l in lines[-5:])
        await query.edit_message_text(txt)
    # المشتركين المدفوعين
    elif data == "admin_subscribers":
        paid = load_json(PAID_FILE, {})
        if not paid:
            return await query.edit_message_text("لا يوجد مشتركين مدفوعين.")
        txt = "💎 المشتركين المدفوعين:\n"
        kb = []
        for uid, info in paid.items():
            # ابحث عن الاسم
            name = uid
            if os.path.exists(USERS_FILE):
                for l in open(USERS_FILE):
                    if l.startswith(uid + "|"):
                        name = l.split("|")[2]
                        break
            txt += f"• {name} — ID: {uid}\n"
            kb.append([InlineKeyboardButton(f"❌ إلغاء {name}", callback_data=f"cancel_subscribe|{uid}")])
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    # إعلان
    elif data == "admin_broadcast":
        await admin_broadcast_start(update, context)
    # اختيار نوع إعلان
    elif data.startswith("bc_type_"):
        await admin_broadcast_type_chosen(update, context)
    # تأكيد بث
    elif data == "bc_confirm":
        await admin_broadcast_confirm(update, context)
    # إلغاء
    elif data == "admin_close":
        await query.edit_message_text("❌ تم الإغلاق.")
    # بحث مستخدم
    elif data == "admin_search":
        context.user_data["waiting_for_search"] = True
        await query.edit_message_text("🔍 أرسل اسم أو ID للبحث:")
    # إحصائيات
    elif data == "admin_stats":
        s = load_stats()
        txt = (
            f"📊 إحصائيات:\n"
            f"- التنزيلات: {s['total']}\n"
            f"- 720p: {s['counts']['720']}\n"
            f"- 480p: {s['counts']['480']}\n"
            f"- 360p: {s['counts']['360']}\n"
            f"- صوت فقط: {s['counts']['audio']}\n"
            f"- الأكثر: {s['top']}"
        )
        await query.edit_message_text(txt)
    # إضافة يدوي
    elif data == "admin_addpaid":
        context.user_data["waiting_for_addpaid"] = True
        await query.edit_message_text("📥 أرسل ID لإضافته اشتراك مدفوع:")
    # إلغاء اشتراك
    elif data.startswith("cancel_subscribe|"):
        _, uid = data.split("|")
        deactivate(uid)
        await context.bot.send_message(int(uid), "❌ أُلغِي اشتراكك من الأدمن.")
        await query.edit_message_text(f"✅ أُلغِي اشتراك {uid}.")
    # تأكيد/رفض اشتراك user_flow
    elif data.startswith("sub_confirm|"):
        await subscription_confirm(update, context)
    elif data.startswith("sub_reject|"):
        await subscription_reject(update, context)
    # اشتراك مجاني
    elif data == "subscribe_request":
        await handle_subscription_request(update, context)
    # العودة
    elif data == "admin_back":
        await admin_panel(update, context)

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # بحث مستخدم
    if context.user_data.pop("waiting_for_search", False):
        q = update.message.text.strip().lower()
        res = []
        if os.path.exists(USERS_FILE):
            for l in open(USERS_FILE):
                uid, uname, name = l.strip().split("|")
                if q in uid or q in uname.lower() or q in name.lower():
                    res.append(f"👤 {name} (@{uname}) — ID: {uid}")
        await update.message.reply_text("\n".join(res) or "⚠️ لا يوجد نتائج.")
    # إضافة يدوي
    elif context.user_data.pop("waiting_for_addpaid", False):
        uid = update.message.text.strip()
        if uid.isdigit():
            activate(uid)
            await update.message.reply_text(f"✅ {uid} تم تفعيله مدفوعاً.")
        else:
            await update.message.reply_text("⚠️ ID غير صالح.")
    # لا غير

# --- Main --- #

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # أوامر عامة
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    # تنزيل + AI
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(?:video|audio|cancel)\|"))

    # اشتراك
    app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    app.add_handler(MessageHandler(filters.PHOTO, receive_subscription_proof))
    app.add_handler(CallbackQueryHandler(subscription_confirm, pattern=r"^sub_confirm\|"))
    app.add_handler(CallbackQueryHandler(subscription_reject, pattern=r"^sub_reject\|"))

    # بث إعلان
    app.add_handler(CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_type_chosen, pattern="^bc_type_"))
    app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), admin_receive_broadcast))
    app.add_handler(CallbackQueryHandler(admin_broadcast_confirm, pattern="^bc_confirm$"))

    # لوحة الأدمن
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    # البحث والإضافة
    app.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=ADMIN_ID), media_handler))

    # Webhook
    port     = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
