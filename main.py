import os
import subprocess
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")  # يجب أن يكون بصيغة: https://your-app-name.onrender.com

# إعداد Flask
flask_app = Flask(__name__)

# تعريف الأوامر
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
                if os.path.exists(f"video.{ext}"):
                    await update.message.reply_video(open(f"video.{ext}", "rb"))
                    os.remove(f"video.{ext}")
                    break
        else:
            await update.message.reply_text(f"🚫 لم أتمكن من تحميل الفيديو.\n📄 التفاصيل: {result.stderr}")
    except Exception as e:
        await update.message.reply_text(f"🚫 حصل خطأ: {e}")

# إعداد تطبيق التليجرام
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

# إعداد Webhook
@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
async def telegram_webhook():
    if request.method == "POST":
        await telegram_app.update_queue.put(Update.de_json(request.get_json(force=True), telegram_app.bot))
        return "OK", 200

@flask_app.route("/")
def home():
    return "🤖 البوت شغال عبر Webhook!"

if __name__ == '__main__':
    import asyncio

    async def setup():
        await telegram_app.bot.delete_webhook()
        await telegram_app.bot.set_webhook(url=f"{APP_URL}/{BOT_TOKEN}")

    asyncio.run(setup())
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
