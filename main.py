import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")  # ضيف هذا المتغير في بيئة Render: APP_URL=https://telegram-bot-fyro.onrender.com

app = Flask(__name__)

# Telegram bot setup
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً! أرسل الرابط وسأقوم بتحميله لك.")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري التحميل...")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

# Webhook endpoint
@app.post(f"/{BOT_TOKEN}")
async def webhook_handler():
    data = request.get_json(force=True)
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return "ok"

# إعداد الويب هوك
@app.before_first_request
async def set_webhook():
    webhook_url = f"{APP_URL}/{BOT_TOKEN}"
    await telegram_app.bot.set_webhook(url=webhook_url)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)
