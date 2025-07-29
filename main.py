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
ORANGE_NUMBER = "0781200500"

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
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w"): pass
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        f"🔔 للاشتراك المدفوع، أرسل 2 دينار إلى أورنج ماني على الرقم: {ORANGE_NUMBER} ثم أرسل صورة التحويل هنا."
    )

def check_limits(user_id, action):
    if is_subscribed(user_id): return True
    today = datetime.utcnow().strftime("%Y-%m-%d")
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

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.data.split("|")[1]
    activate_subscription(user_id)
    await query.edit_message_text(f"✅ تم تفعيل اشتراك المستخدم {user_id}.")
    try:
        await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك، شكراً لك!")
    except:
        pass

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.data.split("|")[1]
    await query.edit_message_text(f"❌ تم رفض اشتراك المستخدم {user_id}.")
    try:
        await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض اشتراكك من قبل الأدمن. يرجى المحاولة مرة أخرى.")
    except:
        pass

# باقي الدوال توضع كما هي (download، admin_panel، button_handler، media_handler، وغيرها...)

# ربط الهاندلرز
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_subscription_proof))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern=r"^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern=r"^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern=r"^reject_sub\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern=r"^cancel_subscribe\|"))
app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(video|audio|cancel)\|"))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern=r"^(admin_users|admin_broadcast|admin_search|admin_stats|admin_addpaid|admin_paidlist|admin_close|admin_back|cancel_subscribe\|.+)$"))
app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern=r"^confirm_broadcast$"))
app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), media_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
