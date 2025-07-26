import os
import subprocess
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# إعداد المتغيرات
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")  # مثل: https://your-app-name.onrender.com

# إعداد Flask
flask_app = Flask(__name__)

# إعداد بوت تليجرام
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلا! أرسل رابط فيديو وسأقوم بتحميله لك 🎥")

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
                    await update.message.reply_video(open(filename, "rb"))
                    os.remove(filename)
                    break
        else:
            await update.message.reply_text(f"🚫 لم أتمكن من التحميل.\n📄 التفاصيل:\n{result.stderr}")
    except Exception as e:
        await update.message.reply_text(f"🚫 حصل خطأ:\n{e}")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

# نقطة الدخول للويبهوك (Telegram يستدعيها)
@flask_app.post(f"/{BOT_TOKEN}")
async def webhook_handler():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    await telegram_app.process_update(update)
    return "ok"

# نقطة اختبار (غير ضرورية للبوت، فقط للمتصفح)
@flask_app.route("/")
def home():
    return "البوت شغال ✅"

# تهيئة الويبهوك وتشغيل السيرفر
if __name__ == '__main__':
    import asyncio

    async def set_webhook():
        await telegram_app.bot.set_webhook(f"{APP_URL}/{BOT_TOKEN}")

    asyncio.run(set_webhook())
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
