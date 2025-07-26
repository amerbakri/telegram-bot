import os
import json
import logging
import openai
import yt_dlp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# إعدادات السجل
logging.basicConfig(level=logging.INFO)

# متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "10000"))

# تفعيل مفتاح OpenAI
openai.api_key = OPENAI_API_KEY

USERS_FILE = "users.json"

# تحميل المستخدمين
def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

# حفظ مستخدم جديد
def save_user(user_id: int):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text(
        f"👋 أهلاً بك!\n🆔 User ID: {user_id}\n"
        "🎥 أرسل رابط فيديو لتحميله أو اكتب أي سؤال!"
    )

# الرد على الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    msg = update.message

    if not msg.text:
        return await msg.reply_text("📩 أرسل رابط فيديو أو سؤال نصي.")

    text = msg.text.strip()

    if text.startswith("http://") or text.startswith("https://"):
        # رد جاري التحميل
        wait_msg = await msg.reply_text("📥 جاري التحميل...")
        try:
            ydl_opts = {
                "format": "best[ext=mp4]",
                "outtmpl": "video.%(ext)s",
                "quiet": True,
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                filename = ydl.prepare_filename(info)

            with open(filename, "rb") as f:
                await msg.reply_video(f)

            os.remove(filename)
            await wait_msg.delete()
            await msg.delete()
        except Exception as e:
            logging.error(e)
            await wait_msg.edit_text("❌ فشل تحميل الفيديو.")
    else:
        thinking_msg = await msg.reply_text("💬 لحظة أفكر...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response["choices"][0]["message"]["content"]
            await thinking_msg.edit_text(reply)
        except Exception as e:
            logging.error(f"OpenAI Error: {e}")
            await thinking_msg.edit_text("⚠️ فشل الاتصال بـ OpenAI.")

# أمر الإرسال الجماعي
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 هذا الأمر فقط للمسؤول.")
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("📝 أرسل الرسالة (نص، صورة، فيديو) للإرسال لجميع المستخدمين.")

# تنفيذ الإرسال
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast_mode"):
        return
    context.user_data["broadcast_mode"] = False

    users = load_users()
    msg = update.message
    sent = 0

    for uid in users:
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=msg.text)
            elif msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption)
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption)
            sent += 1
        except Exception as e:
            logging.warning(f"لم يتم الإرسال إلى {uid}: {e}")

    await msg.reply_text(f"✅ تم إرسال الرسالة إلى {sent} مستخدم.")

# بدء التطبيق
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    webhook_url = f"https://telegram-bot-fyro.onrender.com/{BOT_TOKEN}"
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url,
    )

if __name__ == "__main__":
    main()
