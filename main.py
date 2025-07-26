import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# دالة /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي أي رابط وسأقوم بمعالجته.")

# دالة للرد على أي رسالة نصية
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text(f"لقد أرسلت: {user_message}")

# الدالة الرئيسية
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # تعريف الأوامر والمعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # بدء البوت
    print("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
