import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
import subprocess

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً! أرسل رابط الفيديو 📎")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{url}"),
            InlineKeyboardButton("🎬 فيديو", callback_data=f"video|{url}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر الصيغة:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice, url = query.data.split("|")

    if choice == "audio":
        file_path = "output_audio.mp3"
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", file_path, url]
    else:
        file_path = "output_video.mp4"
        cmd = ["yt-dlp", "-f", "mp4", "-o", file_path, url]

    await query.edit_message_text(text="⏳ جاري التحميل...")

    try:
        subprocess.run(cmd, check=True)
        await query.message.reply_document(open(file_path, "rb"))
    except Exception as e:
        await query.message.reply_text(f"❌ حدث خطأ: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()
