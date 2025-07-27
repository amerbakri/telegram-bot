import os
import json
import re
import logging
import subprocess
import openai
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# الإعدادات
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = 337597459
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

# ملفات
USERS_FILE = "users.txt"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
REQUESTS_FILE = "subscription_requests.txt"
STATS_FILE = "stats.json"

logging.basicConfig(level=logging.INFO)
openai.api_key = OPENAI_API_KEY

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
    "audio": "bestaudio[ext=m4a]"
}

# أدوات
def is_valid_url(text):
    return re.match(r"https?://", text)

def is_subscribed(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return False
    with open(SUBSCRIPTIONS_FILE) as f:
        data = json.load(f)
    return str(user_id) in data

def activate_subscription(user_id):
    data = {}
    if os.path.exists(SUBSCRIPTIONS_FILE):
        with open(SUBSCRIPTIONS_FILE) as f:
            data = json.load(f)
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def check_limits(user_id, action):
    if is_subscribed(user_id):
        return True

    today = datetime.utcnow().strftime("%Y-%m-%d")
    limits = {}
    if os.path.exists(LIMITS_FILE):
        with open(LIMITS_FILE) as f:
            limits = json.load(f)

    user_limits = limits.get(str(user_id), {"date": today, "video": 0, "ai": 0})
    if user_limits["date"] != today:
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

def update_stats(quality):
    stats = {
        "total": 0,
        "720": 0,
        "480": 0,
        "360": 0,
        "audio": 0
    }
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            stats = json.load(f)
    stats["total"] += 1
    stats[quality] += 1
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

# الوظائف
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 أهلاً! أرسل رابط فيديو أو استخدم /ask لسؤال الذكاء الاصطناعي.")

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_limits(user_id, "ai"):
        return await send_limit_message(update)

    prompt = " ".join(context.args)
    if not prompt:
        return await update.message.reply_text("❗ أرسل سؤالك بعد الأمر /ask")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        await update.message.reply_text(response.choices[0].message.content.strip())
    except Exception as e:
        await update.message.reply_text("⚠️ حدث خطأ أثناء التواصل مع OpenAI.")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    if not is_valid_url(url):
        return

    if not check_limits(user_id, "video"):
        return await send_limit_message(update)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📹 720p", callback_data=f"d|720|{url}"),
         InlineKeyboardButton("📺 480p", callback_data=f"d|480|{url}"),
         InlineKeyboardButton("📱 360p", callback_data=f"d|360|{url}")],
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"d|audio|{url}")]
    ])
    await update.message.reply_text("اختر الجودة:", reply_markup=keyboard)

async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, quality, url = query.data.split("|")
    await query.edit_message_text("⏳ جارٍ التحميل...")

    try:
        out_file = f"video_{datetime.utcnow().timestamp()}.mp4"
        subprocess.run([
            "yt-dlp", "-f", quality_map[quality],
            "-o", out_file, url
        ], check=True)

        update_stats(quality)
        await context.bot.send_video(chat_id=query.message.chat.id, video=open(out_file, "rb"))
        os.remove(out_file)
    except Exception as e:
        await query.edit_message_text("❌ فشل التحميل.")

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        "🚫 وصلت إلى الحد المجاني اليومي.\n"
        "للاستخدام غير محدود، اشترك بـ 2 دينار عبر أورنج كاش 0781200500.\n"
        "ثم اضغط الزر أدناه.",
        reply_markup=keyboard
    )

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username}|{datetime.utcnow()}\n")

    await update.callback_query.edit_message_text(
        "💳 أرسل 2 دينار عبر أورنج كاش إلى الرقم:\n📱 0781200500\nثم أرسل صورة الدفع هنا."
    )

    admin_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_sub|{user.id}")
        ]
    ])
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"طلب اشتراك من @{user.username}", reply_markup=admin_buttons)

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, user_id = update.callback_query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح.")
    await update.callback_query.edit_message_text("تم التفعيل.")

async def cancel_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, user_id = update.callback_query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await update.callback_query.edit_message_text("تم الرفض.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            stats = json.load(f)
    else:
        stats = {}

    msg = f"📊 إحصائيات:\n" + "\n".join([f"{k}: {v}" for k, v in stats.items()])
    await update.message.reply_text(msg)

# Main
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_video))
    app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
    app.add_handler(CallbackQueryHandler(cancel_subscription, pattern="^cancel_sub\\|"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))

    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
