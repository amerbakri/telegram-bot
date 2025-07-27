import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove, InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

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
    return str(user_id) in data

def activate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        data = {}
    else:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            data = json.load(f)
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def cancel_subscription_user(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    if str(user_id) in data:
        del data[str(user_id)]
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

    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username or 'NO_USERNAME'}|{datetime.utcnow()}\n")

    await update.callback_query.edit_message_text(
        "💳 للاشتراك:\n"
        "أرسل 2 دينار عبر أورنج كاش إلى الرقم:\n"
        "📱 0781200500\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )

    msg = f"👤 المستخدم @{user.username or user.id} طلب الاشتراك.\nهل تريد تأكيد الاشتراك؟"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
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

# قائمة المشتركين للأدمن مع زر إلغاء الاشتراك
async def subscribers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        await update.message.reply_text("لا يوجد مشتركين حالياً.")
        return

    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)

    if not data:
        await update.message.reply_text("لا يوجد مشتركين حالياً.")
        return

    keyboard = []
    for user_id in data:
        btn_text = f"❌ إلغاء اشتراك {user_id}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"cancel_subscriber|{user_id}")])

    await update.message.reply_text(
        "📋 قائمة المشتركين:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")

    cancel_subscription_user(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من الأدمن.")
    await query.answer("✅ تم إلغاء الاشتراك.")
    await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.")

# تحميل الفيديو باستخدام yt-dlp
async def download_video(url, quality="720"):
    # بناء أمر yt-dlp لتنزيل الفيديو بالجودة المطلوبة
    # هنا مثال بسيط جداً، تحتاج تعديل حسب مكتبة yt-dlp لديك

    # تأكد أن yt-dlp مثبت في البيئة
    ytdlp_cmd = [
        "yt-dlp",
        "-f",
        quality_map.get(quality, "best"),
        "-o",
        "video.%(ext)s",
        url
    ]

    process = subprocess.run(ytdlp_cmd, capture_output=True, text=True)
    if process.returncode == 0:
        # نبحث عن ملف الفيديو الذي تم تنزيله (video.mp4 غالبًا)
        for file in os.listdir("."):
            if file.startswith("video.") and file.endswith(("mp4", "mkv", "webm")):
                return file
    else:
        logging.error(f"yt-dlp error: {process.stderr}")
    return None

# أمر تحميل الفيديو
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)

    if len(context.args) < 1:
        await update.message.reply_text("❌ الرجاء إرسال رابط الفيديو بعد الأمر.")
        return

    url = context.args[0]

    if not is_valid_url(url):
        await update.message.reply_text("❌ الرابط غير صالح.")
        return

    # تحقق من الحد
    if not check_limits(user.id, "video"):
        await send_limit_message(update)
        return

    await update.message.reply_text("⏳ جاري تحميل الفيديو...")

    quality = "720"
    if len(context.args) >= 2 and context.args[1] in quality_map:
        quality = context.args[1]

    file_path = await download_video(url, quality)
    if file_path:
        with open(file_path, "rb") as f:
            await update.message.reply_document(f, caption="✅ تم تحميل الفيديو.")
        os.remove(file_path)
        update_stats("video", quality)
    else:
        await update.message.reply_text("❌ حدث خطأ أثناء تحميل الفيديو.")

# أمر الذكاء الاصطناعي (استدعاء OpenAI)
async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)

    if not check_limits(user.id, "ai"):
        await send_limit_message(update)
        return

    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("❌ الرجاء إرسال نص بعد الأمر.")
        return

    try:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150,
            temperature=0.7
        )
        answer = response.choices[0].text.strip()
        await update.message.reply_text(answer)
        update_stats("ai", "ai")
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء معالجة الطلب.")

# إحصائيات الاستخدام
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
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
    await update.message.reply_text(msg, parse_mode="HTML")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر
    app.add_handler(CommandHandler("start", lambda update, context: update.message.reply_text("🤖 مرحبًا بك! أرسل رابط فيديو أو استخدم الأوامر.")))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("subscribers", subscribers_list))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CommandHandler("ai", ai_command))

    # ردود أزرار الاشتراك
    app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
    app.add_handler(CallbackQueryHandler(cancel_subscription, pattern="^cancel_sub\\|"))
    app.add_handler(CallbackQueryHandler(cancel_subscriber, pattern="^cancel_subscriber\\|"))

    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
