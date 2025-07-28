import os
import subprocess
import logging
import re
import json
from datetime import datetime, date
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# إعدادات
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"
ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
ORANGE_NUMBER = "0781200500"
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ BOT_TOKEN أو OPENAI_API_KEY غير معرفين في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# ---------- أدوات الملفات ----------
for f in [USERS_FILE, STATS_FILE, LIMITS_FILE, SUBSCRIPTIONS_FILE]:
    if not os.path.exists(f):
        with open(f, "w", encoding="utf-8") as ff:
            if f.endswith(".json"):
                ff.write("{}")

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w", encoding="utf-8") as f: pass
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =============== إدارة الاشتراك المدفوع =================
def is_subscribed(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, data)

def deactivate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    if str(user_id) in data: data.pop(str(user_id))
    save_json(SUBSCRIPTIONS_FILE, data)

# =============== حدود الاستخدام المجاني =================
def check_limits(user_id, action):
    if is_subscribed(user_id) or user_id == ADMIN_ID:
        return True
    today = date.today().isoformat()
    limits = load_json(LIMITS_FILE, {})
    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}
    if action == "video" and user_limits["video"] >= DAILY_VIDEO_LIMIT:
        return False
    if action == "ai" and user_limits["ai"] >= DAILY_AI_LIMIT:
        return False
    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    save_json(LIMITS_FILE, limits)
    return True

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        f"🚫 <b>انتهت حصتك المجانية اليوم!</b>\n\n"
        f"للاستخدام غير محدود: اشترك فقط بـ <b>2 دينار</b> عبر أورنج ماني\n"
        f"رقم الدفع: <b>{ORANGE_NUMBER}</b>\n"
        f"ثم اضغط زر الاشتراك وأرسل اسمك أو رقم هاتفك ليتم تفعيلك فورًا.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# ================ الأوامر ================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "<b>👋 أهلاً بك!</b>\n\n"
        "أرسل أي رابط فيديو من <b>يوتيوب، تيك توك، إنستغرام، فيسبوك</b> للتحميل\n"
        "💡 مجاني: 3 فيديو يومياً و5 أسئلة ذكاء اصطناعي.\n\n"
        "<b>للاشتراك المدفوع:</b>\n"
        "حول 2 دينار إلى أورنج ماني\n"
        f"رقم: <b>{ORANGE_NUMBER}</b>\n"
        "ثم اضغط زر الاشتراك أدناه وأرسل اسمك أو رقمك ليتم التفعيل مباشرة.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
        ]),
        parse_mode="HTML"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)
    text = update.message.text.strip()

    # ذكاء صناعي
    if not is_valid_url(text):
        if not check_limits(user.id, "ai"):
            await send_limit_message(update)
            return
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(f"🤖 <b>الذكاء الاصطناعي:</b>\n{reply}", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
        return

    # فيديو
    if not check_limits(user.id, "video"):
        await send_limit_message(update)
        return

    key = str(update.message.message_id)
    url_store[key] = text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ])
    try: await update.message.delete()
    except: pass
    await update.message.reply_text(
        "<b>اختر الجودة أو التحميل كصوت فقط:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )

def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, quality, key = query.data.split("|")
    except:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return
    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return
    url = url_store.get(key)
    if not url:
        await query.edit_message_text("⚠️ الرابط غير موجود أو منتهي.")
        return
    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")
    # تحميل الفيديو
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", format_code, "-o", "video.%(ext)s", url]
        filename = None
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        fallback = subprocess.run(
            ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best[ext=mp4]", "-o", "video.%(ext)s", url],
            capture_output=True, text=True
        )
        if fallback.returncode != 0:
            await query.edit_message_text("🚫 فشل في تحميل الفيديو.")
            url_store.pop(key, None)
            return
    if action == "video":
        for ext in ["mp4", "mkv", "webm"]:
            if os.path.exists(f"video.{ext}"):
                filename = f"video.{ext}"
                break
    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")
    url_store.pop(key, None)
    try: await loading_msg.delete()
    except: pass

# ============ اشتراك مدفوع ==============
async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.callback_query.edit_message_text(
        f"💳 للاشتراك:\n"
        f"أرسل 2 دينار عبر أورنج كاش للرقم:\n<b>{ORANGE_NUMBER}</b>\n\n"
        "ثم أرسل اسمك أو رقم هاتفك هنا ليتم تفعيل اشتراكك بسرعة.",
        parse_mode="HTML"
    )
    context.user_data["waiting_for_info"] = True

async def receive_subscription_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.user_data.get("waiting_for_info"):  # أرسل رسالة نصية عادية وليس اشتراك
        return
    context.user_data["waiting_for_info"] = False
    text = update.message.text.strip()
    # أرسل إشعار للأدمن
    msg = f"🆕 طلب اشتراك جديد:\n<b>الاسم/البيانات:</b> <code>{text}</code>\n<b>المستخدم:</b> @{user.username or 'NO_USERNAME'}\n<b>ID:</b> <code>{user.id}</code>"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{user.id}")],
        [InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{user.id}")]
    ])
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=kb, parse_mode="HTML")
    await update.message.reply_text("✅ تم استلام معلومات الاشتراك وسيتم مراجعته وتفعيله قريبًا.\nانتظر رسالة التأكيد.")

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن التحميل بشكل غير محدود.")
    await query.edit_message_text("✅ تم تفعيل اشتراك المستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await query.edit_message_text("🚫 تم رفض الاشتراك.")

# ============ لوحة تحكم الأدمن =============
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        elif update.callback_query:
            await update.callback_query.answer("⚠️ هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("🟢 قائمة المشتركين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return
    if data == "admin_users":
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = [l for l in f if l.strip() and not l.strip().startswith("{")]
        count = len(users)
        recent = "\n\n📌 آخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.strip().split("|")
            recent += f"👤 <b>{name}</b> | <code>@{username}</code> | <code>{uid}</code>\n"
        await query.edit_message_text(
            f"👥 <b>عدد المستخدمين المسجلين:</b> <code>{count}</code>{recent}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]),
            parse_mode="HTML"
        )
    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل نص الإعلان ليتم بثه لجميع المستخدمين.\n\nيمكنك إرسال صورة أو فيديو مع نص.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]]))
        context.user_data["waiting_for_announcement"] = True
    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل اسم المستخدم أو رقم المستخدم للبحث:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]]))
        context.user_data["waiting_for_search"] = True
    elif data == "admin_stats":
        stats = load_json(STATS_FILE, {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        })
        text = (
            f"📊 <b>إحصائيات التحميل:</b>\n"
            f"عدد الفيديوهات المنزلة: <code>{stats['total_downloads']}</code>\n"
            f"720p: <code>{stats['quality_counts'].get('720',0)}</code>\n"
            f"480p: <code>{stats['quality_counts'].get('480',0)}</code>\n"
            f"360p: <code>{stats['quality_counts'].get('360',0)}</code>\n"
            f"صوت فقط: <code>{stats['quality_counts'].get('audio',0)}</code>\n"
            f"أكثر جودة مطلوبة: <b>{stats['most_requested_quality']}</b>"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]), parse_mode="HTML")
    elif data == "admin_paidlist":
        data = load_json(SUBSCRIPTIONS_FILE, {})
        if not data:
            await query.edit_message_text("لا يوجد مشتركين مدفوعين حالياً.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]))
            return
        buttons = []
        text = "👥 قائمة المشتركين المدفوعين:\n\n"
        for uid, info in data.items():
            username = "NO_USERNAME"
            fullname = ""
            with open(USERS_FILE, "r", encoding="utf-8") as uf:
                for line in uf:
                    if line.startswith(uid + "|"):
                        parts = line.strip().split("|")
                        username = parts[1]
                        fullname = parts[2]
                        break
            text += f"👤 <b>{fullname}</b> | <code>@{username}</code> | <code>{uid}</code>\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء {username}", callback_data=f"cancel_subscribe|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())
    elif data == "admin_back":
        await admin_panel(update, context)

# معالجة حذف المشتركين من الأدمن
async def cancel_subscription_by_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return
    _, user_id = query.data.split("|")
    deactivate_subscription(user_id)
    await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم <code>{user_id}</code>.", parse_mode="HTML")
    try:
        await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    except:
        pass

# استقبال الرسائل النصية (للإعلانات - بحث مستخدم - معلومات الاشتراك)
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # استقبال نص الاشتراك المدفوع
    if context.user_data.get("waiting_for_info"):
        await receive_subscription_info(update, context)
        return
    # استقبال الإعلان من الأدمن
    if user.id == ADMIN_ID and context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        context.user_data["announcement"] = update.message
        await update.message.reply_text(
            "✅ هل تريد تأكيد الإرسال لجميع المستخدمين؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم", callback_data="confirm_broadcast")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]
            ])
        )
        return
    # استقبال نص البحث عن مستخدم
    if user.id == ADMIN_ID and context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query_text = update.message.text.strip()
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = f.read().splitlines()
            results = []
            for u in users:
                if not u or u.startswith("{"): continue
                uid, username, name = u.split("|")
                if query_text.lower() in username.lower() or query_text == uid or query_text in name.lower():
                    results.append(f"👤 <b>{name}</b> | <code>@{username}</code> | <code>{uid}</code>")
            reply = "نتائج البحث:\n" + "\n".join(results) if results else "⚠️ لم يتم العثور على مستخدم."
        except Exception as e:
            reply = f"⚠️ خطأ في البحث: {e}"
        await update.message.reply_text(reply, parse_mode="HTML")
        return

    # استقبال آيدي إضافة مشترك مدفوع (لو رغبت مستقبلاً)
    if user.id == ADMIN_ID and context.user_data.get("waiting_for_addpaid"):
        context.user_data["waiting_for_addpaid"] = False
        new_paid_id = update.message.text.strip()
        if not new_paid_id.isdigit():
            await update.message.reply_text("⚠️ آيدي غير صالح. أرسل رقم آيدي صحيح.")
            return
        activate_subscription(new_paid_id)
        await update.message.reply_text(f"✅ تم إضافة المستخدم {new_paid_id} كمشترك مدفوع.")
        return

# بث الإعلان
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = context.user_data.get("announcement")
    if not message:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    sent = 0
    with open(USERS_FILE, "r", encoding="utf-8") as ff:
        for l in ff:
            l = l.strip()
            if not l or l.startswith("{"):  # تخطي السطور الفارغة أو الخاطئة
                continue
            try:
                uid = int(l.split("|")[0])
                if message.photo:
                    await context.bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
                elif message.video:
                    await context.bot.send_video(uid, message.video.file_id, caption=message.caption or "")
                elif message.text:
                    await context.bot.send_message(uid, message.text)
                sent += 1
            except Exception:
                continue
    await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))

# تحديث إحصائيات التحميل
def update_stats(action, quality):
    stats = load_json(STATS_FILE, {
        "total_downloads": 0,
        "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
        "most_requested_quality": None
    })
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    stats["quality_counts"][key] = stats["quality_counts"].get(key, 0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_json(STATS_FILE, stats)

# =========== ربط الهاندلرز ============
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern="^cancel_subscribe\\|"))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), media_handler))
app.add_handler(MessageHandler(filters.TEXT & filters.User(), media_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
