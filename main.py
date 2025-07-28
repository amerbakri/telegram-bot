# ✅ Telegram Bot with full features
# تحميل فيديوهات (YouTube, TikTok, Instagram, Facebook)
# ذكاء اصطناعي OpenAI
# اشتراك مدفوع مع إرسال صورة
# إدارة كاملة من الأدمن
# Webhook ready

import os
import logging
import subprocess
import datetime
import json
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import openai

# --- إعدادات ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = 337597459  # استبدله برقمك إذا لزم
COOKIES_FILE = "cookies.txt"
USERS_FILE = "users.txt"
PAID_USERS_FILE = "paid_users.txt"
USAGE_FILE = "usage.json"

MAX_FREE_VIDEOS = 3
MAX_FREE_AI = 5

openai.api_key = OPENAI_API_KEY
logging.basicConfig(level=logging.INFO)
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# --- دوال مساعدة ---
def is_valid_url(text):
    return re.match(r"https?://(www\.)?(youtube\.com|youtu\.be|facebook\.com|fb\.watch|tiktok\.com|instagram\.com)/", text)

def store_user(user):
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w").close()
    uid = str(user.id)
    if uid not in open(USERS_FILE).read():
        with open(USERS_FILE, "a") as f:
            f.write(f"{uid}|{user.username}|{user.first_name}\n")

def load_paid_users():
    if not os.path.exists(PAID_USERS_FILE): return set()
    return set(open(PAID_USERS_FILE).read().splitlines())

def save_paid_user(uid):
    with open(PAID_USERS_FILE, "a") as f:
        f.write(f"{uid}\n")

def is_paid(uid):
    return str(uid) in load_paid_users()

def load_usage():
    if not os.path.exists(USAGE_FILE): return {}
    with open(USAGE_FILE) as f: return json.load(f)

def save_usage(data):
    with open(USAGE_FILE, "w") as f: json.dump(data, f)

def can_use(user_id, action):
    usage = load_usage()
    today = datetime.date.today().isoformat()
    if usage.get("date") != today:
        usage = {"date": today, "video": {}, "ai": {}}

    uid = str(user_id)
    if is_paid(uid): return True

    if action == "video":
        count = usage["video"].get(uid, 0)
        if count >= MAX_FREE_VIDEOS: return False
        usage["video"][uid] = count + 1

    elif action == "ai":
        count = usage["ai"].get(uid, 0)
        if count >= MAX_FREE_AI: return False
        usage["ai"][uid] = count + 1

    save_usage(usage)
    return True

# --- الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 مرحبًا بك! أرسل لي رابط فيديو أو اكتب أي شيء لتستخدم الذكاء الاصطناعي 🤖.\n\n"
        "✅ مجاني حتى 3 فيديوهات و5 استخدامات AI يوميًا.\n"
        "🔒 للاشتراك المدفوع: حول إلى 0781200500 عبر أورنج ماني ثم أرسل لقطة الشاشة."
    )

# --- ذكاء اصطناعي ---
async def ai_response(text):
    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": text}]
    )
    return res["choices"][0]["message"]["content"]

# --- تحميل ---
async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url):
    key = str(update.message.message_id)
    url_store[key] = url
    buttons = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{key}")],
        [InlineKeyboardButton("720p", callback_data=f"720|{key}"),
         InlineKeyboardButton("480p", callback_data=f"480|{key}"),
         InlineKeyboardButton("360p", callback_data=f"360|{key}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")],
    ]
    await update.message.reply_text("📥 اختر الجودة: ", reply_markup=InlineKeyboardMarkup(buttons))

# --- الزر ---
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, key = query.data.split("|")
    await query.answer()
    url = url_store.get(key)
    if not url:
        await query.edit_message_text("❌ الرابط غير موجود.")
        return

    await query.edit_message_text("⏳ جاري التحميل...")
    
    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    cmd = ["yt-dlp", "--cookies", COOKIES_FILE]
    out_name = "video.mp4" if action != "audio" else "audio.mp3"

    if action == "audio":
        cmd += ["-x", "--audio-format", "mp3", "-o", out_name, url]
    else:
        cmd += ["-f", quality_map.get(action, "best"), "-o", out_name, url]

    subprocess.run(cmd)

    if os.path.exists(out_name):
        with open(out_name, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(out_name)
    else:
        await query.message.reply_text("🚫 فشل التنزيل.")

    url_store.pop(key, None)

# --- الاشتراك ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    file_id = update.message.photo[-1].file_id
    caption = f"📸 اشتراك جديد\n👤 {user.full_name}\n🆔 {user.id}\n@{user.username}"
    buttons = [[InlineKeyboardButton("✅ تفعيل", callback_data=f"subok|{user.id}"),
                InlineKeyboardButton("❌ رفض", callback_data="ignore")]]
    await context.bot.send_photo(ADMIN_ID, file_id, caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
    await update.message.reply_text("📩 تم استلام الاشتراك، سنقوم بمراجعته خلال وقت قصير.")

async def handle_subscription_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if "subok" in query.data:
        uid = query.data.split("|")[1]
        save_paid_user(uid)
        await query.edit_message_caption(caption=f"✅ تم تفعيل اشتراك المستخدم ID {uid}")
    else:
        await query.edit_message_caption(caption="🚫 تم رفض الاشتراك.")

# --- رسائل ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    store_user(user)

    if is_valid_url(text):
        if not can_use(user.id, "video"):
            await update.message.reply_text("🚫 الحد اليومي للفيديوهات تم تجاوزه. اشترك لمتابعة الاستخدام.")
            return
        await process_url(update, context, text)
    else:
        if not can_use(user.id, "ai"):
            await update.message.reply_text("🚫 الحد اليومي للذكاء الاصطناعي تم تجاوزه.")
            return
        reply = await ai_response(text)
        await update.message.reply_text(reply)

# --- الأدمن ---
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط الأدمن يمكنه استخدام هذا الأمر.")
        return

    paid_users = load_paid_users()
    btns = [[InlineKeyboardButton(f"❌ {uid}", callback_data=f"delpaid|{uid}")]
            for uid in paid_users]
    await update.message.reply_text("👑 المشتركين المدفوعين:", reply_markup=InlineKeyboardMarkup(btns))

async def handle_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if "delpaid" in query.data:
        uid = query.data.split("|")[1]
        users = list(load_paid_users())
        users.remove(uid)
        with open(PAID_USERS_FILE, "w") as f:
            f.write("\n".join(users))
        await query.edit_message_text(f"✅ تم إزالة الاشتراك لـ {uid}")

# --- التشغيل ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button, pattern=r"^(720|480|360|audio|cancel)\|"))
    app.add_handler(CallbackQueryHandler(handle_subscription_approval, pattern=r"^(subok|ignore)"))
    app.add_handler(CallbackQueryHandler(handle_admin_buttons, pattern=r"^delpaid\|"))

    port = int(os.environ.get("PORT", 8443))
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")

    app.run_webhook(listen="0.0.0.0", port=port, url_path=BOT_TOKEN,
                    webhook_url=f"https://{host}/{BOT_TOKEN}")
