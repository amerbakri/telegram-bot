import os
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
import logging

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا لأحمله لك 🎥\n\n"
        "ملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt' مع البوت."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()
    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{url}"),
            InlineKeyboardButton("🎥 فيديو", callback_data=f"video|{url}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not os.path.exists(COOKIES_FILE):
        await query.message.reply_text("⚠️ ملف الكوكيز 'cookies.txt' غير موجود. يرجى رفعه.")
        return

    choice, url = query.data.split("|", 1)
    await query.edit_message_text(text=f"⏳ جاري تحميل {choice}...")

    if choice == "audio":
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-x",
            "--audio-format", "mp3",
            "-o", "audio.%(ext)s",
            url
        ]
        filename = "audio.mp3"
    else:
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-o", "video.%(ext)s",
            url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        if choice == "video":
            for ext in ["mp4", "mkv", "webm"]:
                if os.path.exists(f"video.{ext}"):
                    filename = f"video.{ext}"
                    break

        if filename and os.path.exists(filename):
            with open(filename, "rb") as f:
                if choice == "audio":
                    await query.message.reply_audio(f)
                else:
                    await query.message.reply_video(f)
            os.remove(filename)
        else:
            await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
    else:
        await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")

if __name__ == '__main__':
    port = int(os.getenv("PORT"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
