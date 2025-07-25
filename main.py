import os
import logging
import json
import openai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# إعداد السجلات
logging.basicConfig(level=logging.INFO)

# مفاتيح البيئة
TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# ملف المستخدمين
USERS_FILE = "users.json"

# تحميل المستخدمين
def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

# حفظ المستخدمين
def save_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

# الرد على /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text(
        f"👋 أهلاً بك!\n🆔 رقم الـ User ID تبعك هو: {user_id}\n🎥 أرسل رابط فيديو لتحميله أو اسأل سؤال عام."
    )

# استقبال الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    text = update.message.text

    if "http" in text:
        await update.message.reply_text("📥 جاري تحميل الفيديو (تجريبي)...")
        # هنا تقدر تضيف كود التحميل الحقيقي
        await update.message.reply_text("✅ تم (محاكاة تحميل)")
    else:
        await update.message.reply_text("💬 جاري التفكير...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}],
            )
            reply = response["choices"][0]["message"]["content"]
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text("❌ حدث خطأ أثناء الاتصال بـ OpenAI.")

# أمر إرسال إعلان
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != int(os.environ.get("ADMIN_ID", "0")):
        await update.message.reply_text("❌ هذا الأمر مخصص للمسؤول فقط.")
        return
    context.user_data["broadcast"] = True
    await update.message.reply_text("📝 أرسل الرسالة التي تريد بثها (نص/صورة/فيديو):")

# استلام الإعلان من الأدمن
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast"):
        return
    context.user_data["broadcast"] = False
    users = load_users()
    media = update.message

    for uid in users:
        try:
            if media.text:
                await context.bot.send_message(chat_id=uid, text=media.text)
            elif media.photo:
                await context.bot.send_photo(chat_id=uid, photo=media.photo[-1].file_id, caption=media.caption)
            elif media.video:
                await context.bot.send_video(chat_id=uid, video=media.video.file_id, caption=media.caption)
        except:
            continue
    await update.message.reply_text("✅ تم إرسال الإعلان.")

# إعداد التطبيق
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(MessageHandler(filters.TEXT & filters.User(int(os.environ.get("ADMIN_ID", "0"))), handle_broadcast))
app.add_handler(MessageHandler(filters.TEXT | filters.VIDEO | filters.PHOTO, handle_message))

# إعداد Webhook لتشغيل على Render
import asyncio

async def main():
    await app.initialize()
    await app.bot.set_webhook("https://telegram-bot-fyro.onrender.com/webhook")
    await app.start()
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        webhook_path="/webhook",
    )
    await app.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
