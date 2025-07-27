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
REQUESTS_FILE = "subscription_requests.txt"

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

def deactivate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    if str(user_id) in data:
        data[str(user_id)]["active"] = False
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
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="sub_req")]
    ])
    await update.message.reply_text(
        "🚫 لقد وصلت للحد اليومي المجاني.\n"
        "للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج كاش:\n"
        "📲 الرقم: 0781200500\nثم اضغط على الزر أدناه لتأكيد الاشتراك.",
        reply_markup=keyboard
    )

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username or 'NO_USERNAME'}|{datetime.utcnow().isoformat()}\n")

    await update.callback_query.edit_message_text(
        "💳 للاشتراك:\n"
        "أرسل 2 دينار عبر أورنج كاش إلى الرقم:\n"
        "📱 0781200500\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )

    msg = f"👤 المستخدم @{user.username or user.id} طلب الاشتراك.\nهل تريد تأكيد الاشتراك؟"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد", callback_data=f"conf_sub|{user.id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_sub|{user.id}")
        ]
    ])
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=keyboard)
    await update.callback_query.answer("✅ تم إرسال التعليمات.")

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، اضغط /admin (للأدمن فقط)."
    )

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
                await update.message.reply_text(
                    "🚫 وصلت إلى الحد المجاني اليومي لاستفسارات AI (5 مرات).\n"
                    "للمتابعة، اشترك عبر زر الاشتراك في الرسالة السابقة."
                )
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
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"aud|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"vid|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"vid|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"vid|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"can|{key}")]
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

    if action == "can":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو منتهي.")
        return

    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    if action == "aud":
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

    if action == "vid":
        for ext in ["mp4", "mkv", "webm"]:
            if os.path.exists(f"video.{ext}"):
                filename = f"video.{ext}"
                break

    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "aud":
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

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="adm_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="adm_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="adm_search")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="adm_stats")],
        [InlineKeyboardButton("💳 تأكيد اشتراك", callback_data="adm_sub_confirm")],
        [InlineKeyboardButton("❌ إلغاء اشتراك", callback_data="adm_sub_cancel")]
    ]
    await update.message.reply_text("لوحة التحكم (الأدمن):", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if user.id != ADMIN_ID:
        await query.answer("🚫 غير مصرح")
        return

    data = query.data
    await query.answer()

    if data == "adm_users":
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                lines = f.read().splitlines()
            msg = f"👥 عدد المستخدمين: {len(lines)}"
        else:
            msg = "لا يوجد مستخدمين."
        await query.edit_message_text(msg)

    elif data == "adm_stats":
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
        await query.edit_message_text(msg)

    elif data == "adm_sub_confirm":
        await query.edit_message_text("استخدم /conf_sub <user_id> لتأكيد الاشتراك.")

    elif data == "adm_sub_cancel":
        await query.edit_message_text("استخدم /cancel_sub <user_id> لإلغاء الاشتراك.")

    elif data == "adm_broadcast":
        await query.edit_message_text("أرسل رسالتك للإعلان:")

    elif data == "adm_search":
        await query.edit_message_text("أرسل معرف المستخدم للبحث:")

async def conf_sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر خاص بالأدمن فقط.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❗ استخدم: /conf_sub <user_id>")
        return
    user_id = context.args[0]
    activate_subscription(user_id)
    await update.message.reply_text(f"✅ تم تفعيل الاشتراك للمستخدم {user_id}.")
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك من الأدمن.")

async def cancel_sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر خاص بالأدمن فقط.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❗ استخدم: /cancel_sub <user_id>")
        return
    user_id = context.args[0]
    deactivate_subscription(user_id)
    await update.message.reply_text(f"❌ تم إلغاء الاشتراك للمستخدم {user_id}.")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من الأدمن.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("conf_sub", conf_sub_command))
    app.add_handler(CommandHandler("cancel_sub", cancel_sub_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download))
    app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^sub_req$"))
    app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^conf_sub\\|"))
    app.add_handler(CallbackQueryHandler(cancel_subscription, pattern="^cancel_sub\\|"))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(vid|aud|can)\\|"))
    app.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^adm_"))

    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
