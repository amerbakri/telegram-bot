from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import subprocess
import os
import uuid

user_links = {}  # نخزن رابط كل مستخدم مؤقتاً

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً! ابعتلي رابط يوتيوب لتحميله 🎬")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    url = update.message.text.strip()

    # تخزين الرابط
    user_links[chat_id] = url

    keyboard = [
        [
            InlineKeyboardButton("🎤 صوت", callback_data='audio'),
            InlineKeyboardButton("🎥 فيديو", callback_data='video')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🔷 اختر الصيغة يلي بدك إياها:",
        reply_markup=reply_markup
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    chat_id = query.message.chat_id
    url = user_links.get(chat_id)

    if not url:
        await query.edit_message_text("❌ ما عندي رابط عندك! ابعته من جديد.")
        return

    await query.edit_message_text(f"⏳ جاري تحميل: {choice.upper()} ...")

    filename = f"{uuid.uuid4()}"
    if choice == "audio":
        output_path = f"{filename}.mp3"
        ytdlp_cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "-o", output_path,
            url
        ]
    else:  # video
        output_path = f"{filename}.mp4"
        ytdlp_cmd = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio",
            "--merge-output-format", "mp4",
            "-o", output_path,
            url
        ]

    try:
        subprocess.run(ytdlp_cmd, check=True)

        with open(output_path, "rb") as file:
            if choice == "audio":
                await context.bot.send_audio(chat_id=chat_id, audio=file)
            else:
                await context.bot.send_video(chat_id=chat_id, video=file)

        os.remove(output_path)

    except subprocess.CalledProcessError:
        await context.bot.send_message(chat_id=chat_id, text="❌ حدث خطأ أثناء التحميل.")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ خطأ: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button))

    app.run_polling()
