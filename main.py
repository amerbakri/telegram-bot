import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import subprocess

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلا! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا لأحمله لك 🎥")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    await update.message.reply_text("⏳ جاري تحميل الفيديو...")

    try:
        result = subprocess.run(
            ["yt-dlp", "-o", "video.%(ext)s", url],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for ext in ["mp4", "mkv", "webm"]:
                filename = f"video.{ext}"
                if os.path.exists(filename):
                    with open(filename, "rb") as video_file:
                        await update.message.reply_video(video_file)
                    os.remove(filename)
                    break
        else:
            await update.message.reply_text(f"🚫 لم أتمكن من تحميل الفيديو.\n📄 التفاصيل: {result.stderr}")
    except Exception as e:
        await update.message.reply_text(f"🚫 حصل خطأ: {e}")

if __name__ == '__main__':
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

    bot_app.run_polling()
