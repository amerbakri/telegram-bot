import os
import json
import subprocess
import logging
from datetime import datetime
import re
import openai

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# إعدادات عامة
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459
ORANGE_PHONE = "0781200500"

USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
PROOFS_DIR = "proofs"

DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

logging.basicConfig(level=logging.INFO)
openai.api_key = OPENAI_API_KEY
url_store = {}

# إعداد الجودات
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+" )
    return bool(pattern.match(text))

def store_user(user):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w"): pass
    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()
    entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
    if not any(str(user.id) in u for u in users):
        with open(USERS_FILE, "a") as f:
            f.write(f"{entry}\n")

def get_username(user_id):
    if not os.path.exists(USERS_FILE): return "NO_USERNAME", ""
    with open(USERS_FILE, "r") as f:
        for line in f:
            parts = line.strip().split("|")
            if parts[0] == str(user_id):
                return parts[1], parts[2]
    return "NO_USERNAME", ""

def is_subscribed(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return False
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        data = {}
    else:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            data = json.load(f)
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def deactivate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE): return
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    if str(user_id) in data:
        data.pop(str(user_id))
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def check_limits(user_id, action):
    if is_subscribed(user_id) or user_id == ADMIN_ID:
        return True
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if not os.path.exists(LIMITS_FILE):
        limits = {}
    else:
        with open(LIMITS_FILE, "r") as f:
            limits = json.load(f)
    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}
    if action == "video" and user_limits["video"] >= DAILY_VIDEO_LIMIT:
        return False
    if action == "ai" and user_limits["ai"] >= DAILY_AI_LIMIT:
        return False
    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    with open(LIMITS_FILE, "w") as f:
        json.dump(limits, f)
    return True

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        }
    with open(STATS_FILE, "r") as f:
        return json.load(f)

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def update_stats(action, quality):
    stats = load_stats()
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    stats["quality_counts"][key] = stats["quality_counts"].get(key, 0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_stats(stats)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو (يوتيوب/تيك توك/انستجرام/فيسبوك) لتحميله 🎥\n"
        "أو أي سؤال للذكاء الصناعي مباشرة\n"
        f"🆓 الحد المجاني: {DAILY_VIDEO_LIMIT} فيديو و{DAILY_AI_LIMIT} استفسارات يومياً\n"
        f"🔔 للاشتراك المدفوع (غير محدود) حوّل {ORANGE_PHONE} وأرسل إثبات الدفع بالبوت"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)
    text = update.message.text.strip()

    # ذكاء صناعي (AI) بدون أمر
    if not is_valid_url(text):
        if not check_limits(user.id, "ai"):
            await send_limit_message(update)
            return
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            await update.message.reply_text(resp["choices"][0]["message"]["content"])
        except Exception as e:
            await update.message.reply_text("⚠️ حدث خطأ في الذكاء الاصطناعي: " + str(e))
        return

    # حد التحميل للفيديو
    if not check_limits(user.id, "video"):
        await send_limit_message(update)
        return

    # قائمة الجودات
    key = str(update.message.message_id)
    url_store[key] = text
    keyboard = [
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
    await update.message.reply_text("📥 اختر نوع التحميل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: action, quality, key = query.data.split("|")
    except: await query.answer("خطأ!"); return
    user_id = query.from_user.id

    # زر الإلغاء
    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.edit_message_text("⚠️ الرابط منتهي أو غير موجود.")
        return

    # جاري التحميل
    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")
    # تحميل الفيديو أو الصوت
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", format_code, "-o", "video.%(ext)s", url]
        filename = None
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # جرب أي جودة فيديو متاحة
        fallback = subprocess.run(
            ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "bestvideo+bestaudio/best", "-o", "video.%(ext)s", url],
            capture_output=True, text=True
        )
        if fallback.returncode != 0:
            await loading_msg.edit_text("🚫 فشل التحميل، لم أجد جودة متاحة.")
            url_store.pop(key, None)
            return
    # حدد اسم الملف الناتج
    if action == "video":
        for ext in ["mp4", "mkv", "webm"]:
            if os.path.exists(f"video.{ext}"):
                filename = f"video.{ext}"
                break
    # أرسل الفيديو أو الصوت
    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم أجد الملف بعد التحميل.")
    url_store.pop(key, None)
    try: await loading_msg.delete()
    except: pass

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        f"🚫 وصلت للحد المجاني اليومي ({DAILY_VIDEO_LIMIT} فيديو أو {DAILY_AI_LIMIT} استفسارات AI).\n"
        f"للاستخدام غير محدود: حول {ORANGE_PHONE} أورنج ماني وأرسل إثبات الدفع بالبوت.",
        reply_markup=keyboard
    )

# استقبال إثبات الدفع (صورة فقط بعد الضغط على زر اشترك الآن)
subscription_pending = set()  # users who clicked subscribe_request

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    subscription_pending.add(user.id)
    await update.callback_query.edit_message_text(
        f"💳 للاشتراك:\nحوّل 2 دينار عبر أورنج كاش للرقم:\n📱 {ORANGE_PHONE}\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )
    await update.callback_query.answer("أرسل صورة إثبات التحويل هنا مباشرة.")

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in subscription_pending:
        return
    # حفظ الصورة
    photo_file = await update.message.photo[-1].get_file()
    os.makedirs(PROOFS_DIR, exist_ok=True)
    photo_path = f"{PROOFS_DIR}/{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    await photo_file.download_to_drive(photo_path)
    username, fullname = get_username(user.id)
    # إرسال للأدمن مع زر تأكيد/رفض
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    caption = f"📩 طلب اشتراك جديد\n👤: {fullname}\n@{username}\nID: {user.id}"
    with open(photo_path, "rb") as img:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=img, caption=caption, reply_markup=keyboard)
    await update.message.reply_text("✅ تم استلام إثبات الدفع. بانتظار موافقة الأدمن.")
    subscription_pending.discard(user.id)

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    username, fullname = get_username(user_id)
    await context.bot.send_message(
        chat_id=int(user_id),
        text="✅ تم تفعيل اشتراكك! استمتع بخدمات غير محدودة 🌟"
    )
    await query.edit_message_text(f"✅ تم تفعيل اشتراك المستخدم {fullname} @{username} (ID: {user_id})")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(
        chat_id=int(user_id),
        text="❌ تم رفض طلب الاشتراك. إذا كنت تظن أن هناك خطأ تواصل مع الأدمن."
    )
    await query.edit_message_text("🚫 تم إلغاء طلب الاشتراك.")

# --- لوحة الأدمن ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الزر مخصص للأدمن فقط.")
        return
    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة مشترك مدفوع", callback_data="admin_addpaid")],
        [InlineKeyboardButton("📝 قائمة المشتركين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        last5 = "\n\n📌 آخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.split("|")
            last5 += f"👤 {name} | @{username} | ID: {uid}\n"
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{last5}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        )

    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل الإعلان (نص/صورة/فيديو/صوت):")
        context.user_data["waiting_for_announcement"] = True

    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل اسم المستخدم أو رقم المستخدم للبحث:")
        context.user_data["waiting_for_search"] = True

    elif data == "admin_stats":
        stats = load_stats()
        msg = (
            f"📊 <b>إحصائيات الاستخدام:</b>\n"
            f"- إجمالي التنزيلات: {stats['total_downloads']}\n"
            f"- 720p: {stats['quality_counts']['720']}\n"
            f"- 480p: {stats['quality_counts']['480']}\n"
            f"- 360p: {stats['quality_counts']['360']}\n"
            f"- صوت فقط: {stats['quality_counts']['audio']}\n"
            f"- الأكثر طلبًا: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(msg, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        )

    elif data == "admin_addpaid":
        await query.edit_message_text(
            "📥 أرسل آيدي المستخدم الذي تريد إضافته كمشترك مدفوع.\nمثال: 123456789"
        )
        context.user_data["waiting_for_addpaid"] = True

    elif data == "admin_paidlist":
        # قائمة المشتركين المدفوعين
        if not os.path.exists(SUBSCRIPTIONS_FILE):
            await query.edit_message_text("لا يوجد مشتركين.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))
            return
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            dataj = json.load(f)
        text = "👑 قائمة المشتركين المدفوعين:\n\n"
        buttons = []
        for uid in dataj:
            username, fullname = get_username(uid)
            text += f"👤 {fullname} (@{username}) — ID: {uid}\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء @{username}", callback_data=f"cancel_subscribe|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("cancel_subscribe"):
        _, user_id = data.split("|")
        deactivate_subscription(user_id)
        username, fullname = get_username(user_id)
        await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {fullname} @{username} (ID: {user_id})")
        await context.bot.send_message(
            chat_id=int(user_id),
            text="❌ تم إلغاء اشتراكك من قبل الأدمن."
        )

    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())

    elif data == "admin_back":
        await admin_panel(query, context)

# معالجة البحث والإعلان في الأدمن
async def admin_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        context.user_data["announcement"] = update.message
        await update.message.reply_text("✅ هل تريد تأكيد الإرسال؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم", callback_data="confirm_broadcast"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]
            ])
        )
        return
    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query_text = update.message.text.strip()
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        results = []
        for u in users:
            uid, username, name = u.split("|")
            if query_text.lower() in username.lower() or query_text == uid or query_text in name.lower():
                results.append(f"👤 {name} | @{username} | ID: {uid}")
        reply = "نتائج البحث:\n" + "\n".join(results) if results else "⚠️ لم يتم العثور على مستخدم."
        await update.message.reply_text(reply)
        return
    if context.user_data.get("waiting_for_addpaid"):
        context.user_data["waiting_for_addpaid"] = False
        new_paid_id = update.message.text.strip()
        if not new_paid_id.isdigit():
            await update.message.reply_text("⚠️ آيدي غير صالح. أرسل رقم آيدي صحيح.")
            return
        activate_subscription(new_paid_id)
        await update.message.reply_text(f"✅ تم إضافة المستخدم {new_paid_id} كمشترك مدفوع.")
        return

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = context.user_data.get("announcement")
    if not message:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()
    sent = 0
    for u in users:
        uid = int(u.split("|")[0])
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

# ---- إعداد التطبيق ----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\|"))
    application.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    application.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
    application.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^cancel_subscribe\\|"))
    application.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
    application.add_handler(MessageHandler(filters.PHOTO, receive_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), admin_media_handler))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
