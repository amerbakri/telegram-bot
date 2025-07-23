import os
import subprocess
import re
import uuid

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"


def is_url(text):
    return re.match(r'https?://', text) is not None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك!\n"
        "أرسل لي رابط فيديو من **يوتيوب** أو **تيك توك** أو **إنستغرام**، "
        "وسأقوم بتحميله لك 🎥\n\n"
        "اختر لاحقاً إذا كنت تريد تحميله كـ 🎵 صوت أو كـ 🎥 فيديو.",
        parse_mode="Markdown"
    )


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_url(url):
        await update.message.reply_text("🚫 من فضلك أرسل رابط فيديو صالح.")
        return

    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{url}"),
            InlineKeyboardButton("🎥 فيديو", callback_data=f"video|{url}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ اختر نوع التنزيل:", reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    choice = data[0]  # audio or video
    url = data[1]

    unique_id = str(uuid.uuid4())[:8]
    await query.edit_message_text(text=f"⏳ جاري التحميل كـ {'صوت' if choice == 'audio' else 'فيديو'}…")

    if choice == "audio":
        filename = f"audio_{unique_id}.mp3"
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", filename, url]
    else:
        filename = f"video_{unique_id}.mp4"
        cmd = ["yt-dlp", "-f", "mp4", "-o", filename, url]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0 and os.path.exists(filename):
        with open(filename, "rb") as f:
            if choice == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)
    else:
        await query.message.reply_text(
            "🚫 فشل التنزيل. حاول مجددًا أو تحقق من الرابط.\n\n"
            f"📄 التفاصيل:\n`{result.stderr.strip()}`",
            parse_mode="Markdown"
        )


if __name__ == '__main__':
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    bot_app.add_handler(CallbackQueryHandler(button_handler))

    bot_app.run_polling()
    app.run(host='0.0.0.0', port=8080)
