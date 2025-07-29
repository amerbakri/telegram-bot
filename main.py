import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime, date
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ---------- الإعدادات ---------- #
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"
ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
REQUESTS_FILE = "subscription_requests.txt"
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5
ORANGE_NUMBER = "0781200500"

# ---------- متغيرات الدردشة ---------- #
admin_chat_with = {}      # {ADMIN_ID: user_id}
user_chat_with = {}       # {user_id: ADMIN_ID}

openai.api_key = OPENAI_API_KEY
url_store = {}
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# ----------- أدوات مساعدة ----------- #
def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f: pass
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r") as f:
        try: return json.load(f)
        except: return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f)

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

def check_limits(user_id, action):
    if is_subscribed(user_id): return True
    today = date.today().isoformat()
    limits = load_json(LIMITS_FILE, {})
    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}
    if action == "video" and user_limits["video"] >= DAILY_VIDEO_LIMIT: return False
    if action == "ai" and user_limits["ai"] >= DAILY_AI_LIMIT: return False
    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    save_json(LIMITS_FILE, limits)
    return True

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        f"🚫 لقد وصلت للحد اليومي المجاني.\n"
        f"للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج ماني:\n"
        f"📲 الرقم: {ORANGE_NUMBER}\nثم أرسل إثبات الدفع للأدمن.",
        reply_markup=keyboard
    )

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

# ------------- أوامر البوت الأساسية ------------- #
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗨️ مراسلة الأدمن", callback_data="chat_admin")]
    ])
    await update.message.reply_text(
        "👋 <b>مرحباً بك في بوت التحميل الشامل!</b>\n\n"
        "أرسل أي رابط <b>YouTube</b> أو <b>TikTok</b> أو <b>Instagram</b> أو <b>Facebook</b> لتحميل الفيديوهات أو الصوت.\n"
        "<b>المميزات المجانية:</b> 3 فيديو يومياً + 5 استخدام ذكاء صناعي.\n"
        "🔓 <b>للاشتراك المدفوع:</b> أرسل 2 دينار إلى أورنج ماني: <code>0781200500</code> ثم أرسل إثبات الدفع هنا.\n"
        "يمكنك كذلك الدردشة مع الأدمن لأي استفسار.",
        parse_mode="HTML", reply_markup=kb
    )

async def download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    user = update.effective_user
    store_user(user)
    if not is_valid_url(msg):
        # ذكاء صناعي
        if not check_limits(user.id, "ai"):
            await send_limit_message(update)
            return
        try:
            res = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": msg}]
            )
            await update.message.reply_text(res.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return
    # تحميل فيديو
    if not check_limits(user.id, "video"):
        await send_limit_message(update)
        return

    key = str(update.message.message_id)
    url_store[key] = msg
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
    await update.message.reply_text("📥 <b>اختر نوع التحميل:</b>", reply_markup=kb, parse_mode="HTML")

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    # fallback في حال فشل الجودة المطلوبة
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

# ---------- اشتراك مدفوع ---------- #
async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username or 'NO_USERNAME'}|{datetime.utcnow()}\n")
    # إشعار الأدمن برسالة جديدة
    caption = (
        f"🔔 <b>طلب اشتراك جديد</b>:\n"
        f"• الاسم: <b>{user.first_name or ''} {user.last_name or ''}</b>\n"
        f"• المستخدم: <b>@{user.username or 'NO_USERNAME'}</b>\n"
        f"• ID: <code>{user.id}</code>\n"
        f"• (رقم الهاتف يضاف يدوياً إن أردت)"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تفعيل الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    await context.bot.send_message(ADMIN_ID, caption, parse_mode="HTML", reply_markup=kb)
    await update.callback_query.edit_message_text(
        "💳 <b>لإتمام الاشتراك:</b>\n"
        "1. أرسل 2 دينار إلى <b>0781200500 (أورنج ماني)</b>.\n"
        "2. ثم انتظر حتى يتم تفعيل اشتراكك من قبل الأدمن.\n\n"
        "📩 سيتم إشعارك بعد تفعيل اشتراكك.", parse_mode="HTML"
    )
    await update.callback_query.answer("✅ تم إرسال طلبك للأدمن!")

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن الاستخدام غير المحدود.")
    await query.answer("✅ تم التفعيل.")
    await query.edit_message_text("✅ تم تفعيل اشتراك المستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await query.answer("🚫 تم الرفض.")
    await query.edit_message_text("🚫 تم رفض الاشتراك.")

# ---------- لوحة الأدمن ---------- #
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
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        count = len(users)
        recent = "\n\n📌 آخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.split("|")
            recent += f"👤 {name} | @{username} | ID: {uid}\n"
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))
    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل لي الإعلان (نص أو صورة أو فيديو أو صوت):")
        context.user_data["waiting_for_announcement"] = True
    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل لي اسم المستخدم أو رقم المستخدم للبحث:")
        context.user_data["waiting_for_search"] = True
    elif data == "admin_stats":
        stats = load_json(STATS_FILE, {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        })
        text = (
            f"📊 إحصائيات التحميل:\n"
            f"عدد الفيديوهات المنزلة: {stats['total_downloads']}\n"
            f"جودة 720p: {stats['quality_counts'].get('720',0)} مرات\n"
            f"جودة 480p: {stats['quality_counts'].get('480',0)} مرات\n"
            f"جودة 360p: {stats['quality_counts'].get('360',0)} مرات\n"
            f"تحميل الصوت فقط: {stats['quality_counts'].get('audio',0)} مرات\n"
            f"أكثر جودة مطلوبة: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))
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
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, "r") as uf:
                    for line in uf:
                        if line.startswith(uid + "|"):
                            parts = line.strip().split("|")
                            username = parts[1]
                            fullname = parts[2]
                            break
            text += f"👤 {fullname} (@{username}) — ID: {uid}\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء {username}", callback_data=f"cancel_subscribe|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())
    elif data == "admin_back":
        await admin_panel(update, context)

# إلغاء اشتراك مشترك مدفوع
async def cancel_subscription_by_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return
    _, user_id = query.data.split("|")
    deactivate_subscription(user_id)
    await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")

# بث إعلان (يدعم نص - صورة - فيديو - صوت)
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        context.user_data["announcement"] = update.message
        await update.message.reply_text("✅ هل تريد تأكيد الإرسال؟", reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ نعم", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")
            ]
        ]))
        return
    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query_text = update.message.text.strip()
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            results = []
            for u in users:
                uid, username, name = u.split("|")
                if query_text.lower() in username.lower() or query_text == uid or query_text in name.lower():
                    results.append(f"👤 {name} | @{username} | ID: {uid}")
            reply = "نتائج البحث:\n" + "\n".join(results) if results else "⚠️ لم يتم العثور على مستخدم."
        except Exception as e:
            reply = f"⚠️ خطأ في البحث: {e}"
        await update.message.reply_text(reply)
        return

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = context.user_data.get("announcement")
    if not message:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    try:
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        sent = 0
        for u in users:
            l = u.strip()
            if not l or l.startswith("{"):
                continue
            uid = int(l.split("|")[0])
            try:
                if message.photo:
                    await context.bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
                elif message.video:
                    await context.bot.send_video(uid, message.video.file_id, caption=message.caption or "")
                elif message.audio:
                    await context.bot.send_audio(uid, message.audio.file_id, caption=message.caption or "")
                elif message.text:
                    await context.bot.send_message(uid, message.text)
                sent += 1
            except: pass
        await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.")
    except Exception as e:
        await query.edit_message_text(f"🚫 خطأ أثناء الإرسال: {e}")

# ============= دردشة المستخدم مع الأدمن ============= #
async def chat_admin_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admin_chat_with[ADMIN_ID] = user.id
    user_chat_with[user.id] = ADMIN_ID
    await ctx.bot.send_message(ADMIN_ID,
        f"🟢 <b>بدأ دردشة معك المستخدم:</b>\n"
        f"• الاسم: <b>{user.first_name or ''} {user.last_name or ''}</b>\n"
        f"• المستخدم: <b>@{user.username or 'NO_USERNAME'}</b>\n"
        f"• ID: <code>{user.id}</code>\n\n"
        f"يمكنك الرد مباشرة بإرسال رسالة هنا ليصله الرد.",
        parse_mode="HTML"
    )
    await update.callback_query.edit_message_text("🟢 تم البدء بالدردشة مع الأدمن. أرسل أي رسالة أو استفسار وسيتم الرد عليك قريباً.", parse_mode="HTML")
    await update.callback_query.answer("تم بدء الدردشة مع الأدمن.")

# الرد الآلي: الأدمن يرد على المستخدم
async def admin_message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and ADMIN_ID in admin_chat_with:
        target_id = admin_chat_with[ADMIN_ID]
        if update.message.text:
            await ctx.bot.send_message(target_id, f"🟢 رد الأدمن:\n{update.message.text}")
        elif update.message.photo:
            await ctx.bot.send_photo(target_id, photo=update.message.photo[-1].file_id, caption=update.message.caption)
        elif update.message.video:
            await ctx.bot.send_video(target_id, video=update.message.video.file_id, caption=update.message.caption)
        elif update.message.audio:
            await ctx.bot.send_audio(target_id, audio=update.message.audio.file_id, caption=update.message.caption)
        await update.message.reply_text("✅ تم إرسال ردك للمستخدم.")

    elif update.effective_user.id in user_chat_with:
        await ctx.bot.send_message(ADMIN_ID, f"🟢 رسالة جديدة من المستخدم:\n{update.message.text}")
        await update.message.reply_text("✅ تم إرسال رسالتك للأدمن.")

# ============= هندلرز البوت ============= #
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(CallbackQueryHandler(chat_admin_request, pattern="^chat_admin$"))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern="^cancel_subscribe\\|"))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), admin_message_handler))
app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.TEXT, media_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
