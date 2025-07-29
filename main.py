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

openai.api_key = OPENAI_API_KEY
url_store = {}
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def activate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, data)

def is_subscribed(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    return str(user_id) in data and data[str(user_id)]["active"]

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r") as f:
        try: return json.load(f)
        except: return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f)

# الذكاء الاصطناعي
async def ai_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    limits = load_json(LIMITS_FILE, {})
    if not is_subscribed(user_id):
        usage = limits.get(user_id, {"ai": 0})
        if usage["ai"] >= DAILY_AI_LIMIT:
            await update.message.reply_text(f"❌ الحد اليومي للاستخدام المجاني هو {DAILY_AI_LIMIT} استفسارات. اشترك عبر إرسال صورة الاشتراك.")
            return
        usage["ai"] += 1
        limits[user_id] = usage
        save_json(LIMITS_FILE, limits)
    prompt = update.message.text
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    reply = response.choices[0].message.content
    await update.message.reply_text(reply)

# تحميل الفيديوهات
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    url = update.message.text.strip()
    if not any(x in url for x in ["youtube.com", "tiktok.com", "facebook.com", "instagram.com"]):
        return
    limits = load_json(LIMITS_FILE, {})
    if not is_subscribed(user_id):
        usage = limits.get(user_id, {"video": 0})
        if usage["video"] >= DAILY_VIDEO_LIMIT:
            await update.message.reply_text(f"❌ الحد اليومي للتحميل المجاني هو {DAILY_VIDEO_LIMIT} فيديوهات. اشترك بإرسال صورة الاشتراك.")
            return
        usage["video"] += 1
        limits[user_id] = usage
        save_json(LIMITS_FILE, limits)
    await update.message.reply_text("⏳ جاري التحميل...")
    try:
        output = subprocess.check_output([
            "yt-dlp", url,
            "-f", quality_map["720"],
            "-o", "temp_video.%(ext)s",
            "--cookies", COOKIES_FILE
        ])
        for ext in ["mp4", "mkv", "webm"]:
            path = f"temp_video.{ext}"
            if os.path.exists(path):
                await update.message.reply_video(video=open(path, "rb"))
                os.remove(path)
                return
        await update.message.reply_text("❌ تعذر التحميل. حاول لاحقًا أو تحقق من الرابط.")
    except:
        await update.message.reply_text("❌ حدث خطأ أثناء التحميل.")

# start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 مرحبًا بك في البوت! أرسل رابط فيديو لتحميله أو اكتب سؤالك لاستخدام الذكاء الاصطناعي. للمزيد من الاستخدام، اشترك عبر إرسال صورة إثبات الدفع.")

# استلام إثبات الاشتراك
async def receive_subscription_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        return
    user_id = str(update.effective_user.id)
    name = update.effective_user.full_name
    file_id = update.message.photo[-1].file_id
    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user_id}|{name}|{file_id}\n")
    await update.message.reply_text("📨 تم استلام إثبات الدفع. سيتم مراجعته من قبل الأدمن قريبًا.")
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_sub|{user_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{user_id}")]
        ])
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=f"طلب اشتراك من {name} ({user_id})",
            reply_markup=keyboard
        )
    except:
        pass

# إحصائيات المشتركين
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    total_paid = len(subs)
    limits = load_json(LIMITS_FILE, {})
    total_users = len(set(list(subs.keys()) + list(limits.keys())))
    await update.message.reply_text(f"📊 إحصائيات:\n- مستخدمين إجمالاً: {total_users}\n- مشتركين مدفوعين: {total_paid}")

# إرسال إعلان للمشتركين
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    await update.message.reply_text("✍️ أرسل الآن نص الإعلان ليتم إرساله للمشتركين المدفوعين.")
    context.user_data["awaiting_broadcast"] = True

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_broadcast"):
        context.user_data["awaiting_broadcast"] = False
        text = update.message.text
        subs = load_json(SUBSCRIPTIONS_FILE, {})
        for uid in subs:
            try:
                await context.bot.send_message(chat_id=int(uid), text=text)
            except: pass
        await update.message.reply_text("✅ تم إرسال الإعلان.")

# وظائف إدارية أخرى يجب أن تكون مضافة مسبقاً (مثل admin_addpaid, admin_send_message, إلخ)

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin_stats", admin_stats))
app.add_handler(CommandHandler("admin_broadcast", admin_broadcast))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_auto))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast))
app.add_handler(MessageHandler(filters.PHOTO, receive_subscription_proof))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
