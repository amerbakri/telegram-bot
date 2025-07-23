import os
import subprocess
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running!"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا لأحمله لك 🎥"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    choice, url = query.data.split("|", 1)
    await query.edit_message_text(text=f"⏳ جاري تحميل {choice}...")

    if choice == "audio":
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        cmd = ["yt-dlp", "-o", "video.%(ext)s", url]
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
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Webhook mode for Render
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", "8443")),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}"
    )

    app.run(host='0.0.0.0', port=8080)
