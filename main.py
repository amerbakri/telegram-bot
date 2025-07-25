import os
import logging
import openai
import subprocess
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

openai.api_key = OPENAI_API_KEY
url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 أهلاً بك!🆔 رقم الـ User ID تبعك هو: {user.id}\n🎥 أرسل رابط فيديو لتحميله أو اسأل سؤال عام."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    if not is_valid_url(user_text):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": user_text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ: {e}")
        return

    key = str(update.message.message_id)
    url_store[key] = user_text

    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]

    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        await query.message.reply_text("⚠️ الرابط غير صالح.")
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
            await query.message.reply_text("🚫 فشل في تحميل الفيديو.")
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
    else:
        await query.message.reply_text("🚫 الملف غير موجود.")

    url_store.pop(key, None)

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await update.message.reply_text("📸 صورة جميلة!")
    elif update.message.video:
        await update.message.reply_text("🎞️ شكرًا على الفيديو!")

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != os.getenv("OWNER_ID"):
        await update.message.reply_text("🚫 الأمر مخصص فقط للمسؤول.")
        return

    text = update.message.text.split(" ", 1)
    if len(text) < 2:
        await update.message.reply_text("📝 استخدم الأمر هكذا:\n/announce رسالتك هنا")
        return

    msg = text[1]
    for user_id in context.application.chat_data.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text=msg)
        except:
            continue
    await update.message.reply_text("📢 تم إرسال الإعلان.")

if __name__ == "__main__":
    import asyncio

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("announce", announce))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, media_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    async def main():
        await app.initialize()
        await app.start()
        await app.bot.set_webhook("https://telegram-bot-fyro.onrender.com/webhook")
        await app.updater.start_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            webhook_path="/webhook",
        )

    asyncio.run(main())
