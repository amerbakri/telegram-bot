import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime
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
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"

DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                pass
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

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

def check_limits(user_id, action):
    if is_subscribed(user_id):
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

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        "🚫 لقد وصلت للحد اليومي المجاني.\n"
        "للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج كاش:\n"
        "📲 الرقم: 0781200500\nثم اضغط على الزر أدناه لتأكيد الاشتراك.",
        reply_markup=keyboard
    )

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # نبدأ بطلب رقم الهاتف أولاً
    await update.callback_query.edit_message_text(
        "📲 رجاءً أرسل رقم هاتفك لطلب الاشتراك (مثل: 0781234567):"
    )
    context.user_data["awaiting_phone"] = True
    await update.callback_query.answer()

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن الاستخدام غير المحدود.")
    await query.answer("✅ تم التفعيل.")
    await query.edit_message_text("✅ تم تفعيل اشتراك المستخدم.")

async def cancel_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await query.answer("🚫 تم الإلغاء.")
    await query.edit_message_text("🚫 تم إلغاء الاشتراك.")

async def process_subscription_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_phone"):
        return  # ليس في انتظار رقم الهاتف

    phone = update.message.text.strip()
    # تحقق بسيط من رقم الهاتف (يمكن تطويره حسب الحاجة)
    if not re.match(r"^\d{7,15}$", phone):
        await update.message.reply_text("⚠️ رقم الهاتف غير صالح. الرجاء إدخال رقم صحيح بدون حروف أو رموز.")
        return

    context.user_data["awaiting_phone"] = False
    context.user_data["subscription_phone"] = phone

    await update.message.reply_text(
        f"📸 الآن، أرسل صورة الإيصال (لقطة شاشة الدفع) لتأكيد الاشتراك."
    )

    context.user_data["awaiting_receipt"] = True

async def process_subscription_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_receipt"):
        return

    if not update.message.photo:
        await update.message.reply_text("⚠️ الرجاء إرسال صورة الإيصال فقط.")
        return

    photo_file = update.message.photo[-1].file_id
    phone = context.user_data.get("subscription_phone", "غير معروف")
    user = update.effective_user

    # إرسال الصورة مع رقم الهاتف والأي دي للأدمن
    caption = (
        f"📢 طلب اشتراك جديد:\n"
        f"👤 المستخدم: @{user.username or user.id}\n"
        f"🆔 آيدي: {user.id}\n"
        f"📞 رقم الهاتف: {phone}\n"
        f"📸 صورة الإيصال المرفقة"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"cancel_sub|{user.id}")
        ]
    ])

    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo_file, caption=caption, reply_markup=keyboard)

    await update.message.reply_text("✅ تم استلام طلب الاشتراك، في انتظار تأكيد الأدمن.")
    context.user_data["awaiting_receipt"] = False
    context.user_data.pop("subscription_phone", None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، اضغط زر الاشتراك أدناه."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text("👇", reply_markup=keyboard)

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    # تحقق الاشتراك أو الحد اليومي
    if not is_subscribed(user.id):
        allowed = check_limits(user.id, "video")
        if not allowed:
            await send_limit_message(update)
            return

    text = update.message.text.strip()

    if not is_valid_url(text):
        # AI usage limit check
        if not is_subscribed(user.id):
            allowed = check_limits(user.id, "ai")
            if not allowed:
                await send_limit_message(update)
                return
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
        return

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

    try:
        await update.message.delete()
    except:
        pass

    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        await query.message.reply_text("⚠️ الرابط غير صالح أو منتهي.")
        return

    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

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
    try:
        await loading_msg.delete()
    except:
        pass

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return
    stats = load_stats()
    msg = (
        f"📊 إحصائيات الاستخدام:\n"
        f"- إجمالي التنزيلات: {stats['total_downloads']}\n"
        f"- 720p: {stats['quality_counts']['720']}\n"
        f"- 480p: {stats['quality_counts']['480']}\n"
        f"- 360p: {stats['quality_counts']['360']}\n"
        f"- صوت فقط: {stats['quality_counts']['audio']}\n"
        f"- الأكثر طلبًا: {stats['most_requested_quality']}"
    )
    await update.message.reply_text(msg)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة مشترك مدفوع", callback_data="admin_addpaid")],
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
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            count = len(users)
            recent = "\n\n📌 آخر 5 مستخدمين:\n"
            for u in users[-5:]:
                uid, username, name = u.split("|")
                recent += f"👤 {name} | @{username} | ID: {uid}\n"
        except:
            count = 0
            recent = ""
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل لي الإعلان (نص أو صورة أو فيديو مع نص):")
        context.user_data["waiting_for_announcement"] = True

    elif data == "admin_search":
        await query.edit_message_text
