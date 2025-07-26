import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import subprocess

# احصل على التوكن واسم الهوست من المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN")
HOSTNAME = os.getenv("HOSTNAME")  # مثل: telegram-bot-fyro.onrender.com
PORT = int(os.environ.get('PORT', 8080))  # Render يستخدم PORT ديناميكيًا

# تأكد من وجود التوكن والهوست
if not BOT_TOKEN or not HOSTNAME:
    raise RuntimeError("يجب تحديد BOT_TOKEN و HOSTNAME كمتغيرات بيئية")

# إعداد Flask
flask_app = Flask(__name__)

# تعريف الدوال الخاصة بالبوت
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

# دالة تشغيل التطبيق
async def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # إضافة الهاندلرز
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

    # تعيين Webhook
    webhook_url = f"https://{HOSTNAME}/{BOT_TOKEN}"
    await app.bot.set_webhook(webhook_url)

    # تشغيل البوت باستخدام Flask
    return app

# نقطة النهاية لتلقي التحديثات من Telegram
@flask_app.post(f"/{BOT_TOKEN}")
async def webhook_handler():
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    await bot_app.process_update(update)
    return "OK", 200

# نقطة اختبار
@flask_app.route('/')
def home():
    return "✅ البوت يعمل باستخدام Webhook!"

# تشغيل الخادم
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    # تشغيل البوت مع Flask
    bot_app = asyncio.run(run_bot())
    flask_app.run(host="0.0.0.0", port=PORT)
