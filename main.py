import os
import json
import subprocess
import logging
import re
import openai

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# إعدادات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8443"))
COOKIES_FILE = "cookies.txt"

openai.api_key = OPENAI_API_KEY
logging.basicConfig(level=logging.INFO)

# ملف حفظ المستخدمين
USERS_FILE = "users.json"
url_store = {}

def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

def is_valid_url(text):
    pattern = re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|facebook\.com|instagram\.com|fb\.watch)/.+")
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text("👋 مرحباً! أرسل رابط فيديو لتحميله أو اسأل سؤالاً.")

async def download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not is_valid_url(text):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response["choices"][0]["message"]["content"]
            await update.message.reply_text(reply)
        except Exception as e:
            logging.error(f"OpenAI Error: {e}")
            await update.message.reply_text("⚠️ حدث خطأ أثناء الاتصال بـ OpenAI.")
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

    await update.message.reply_text(
        "📥 اختر نوع التنزيل:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except ValueError:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو انتهت صلاحيته.")
        return

    await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    if action == "audio":
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-x", "--audio-format", "mp3",
            "-o", "audio.%(ext)s", url
        ]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", format_code,
            "-o", "video.%(ext)s", url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        fallback_cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", "best[ext=mp4]",
            "-o", "video.%(ext)s", url
        ]
        fallback = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if fallback.returncode != 0:
            await query.message.reply_text("🚫 فشل في تحميل الفيديو. جرّب رابطاً آخر.")
            return

    if action == "video":
        for ext in ["mp4", "mkv", "webm"]:
            f = f"video.{ext}"
            if os.path.exists(f):
                filename = f
                break

    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)

    try:
        await context.bot.delete_message(chat_id=query.message.chat.id, message_id=int(key))
        await context.bot.delete_message(chat_id=query.message.chat.id, message_id=query.message.message_id)
    except:
        pass

    url_store.pop(key, None)

# أمر للإرسال الجماعي من قبل المدير فقط
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص للمسؤول فقط.")
        return
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("📝 أرسل الآن رسالة نص، صورة، فيديو أو صوت ليتم إرسالها لجميع المستخدمين.")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast_mode"):
        return
    context.user_data["broadcast_mode"] = False
    users = load_users()
    msg = update.message

    for uid in users:
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=msg.text)
            elif msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption)
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption)
            elif msg.audio:
                await context.bot.send_audio(chat_id=uid, audio=msg.audio.file_id, caption=msg.caption)
        except Exception:
            continue

    await update.message.reply_text("✅ تم إرسال الرسالة لجميع المستخدمين.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
