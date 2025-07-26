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

# إعداد المفاتيح من المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))

# إعداد OpenAI
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# ملف المستخدمين
USERS_FILE = "users.json"

# تسجيل الأحداث
logging.basicConfig(level=logging.INFO)

# تحميل قائمة المستخدمين
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

# أمر البدء
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text(
        f"👋 أهلاً بك!\n🆔 رقمك: {user_id}\n\n"
        "🎥 أرسل رابط فيديو أو اسألني أي سؤال."
    )

# الرد على الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    text = update.message.text

    if not text:
        return

    # رابط يوتيوب
    if "http://" in text or "https://" in text:
        await update.message.reply_text("📥 جاري التحميل...")
        try:
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': 'video.%(ext)s',
                'noplaylist': True,
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                video_path = ydl.prepare_filename(info)

            with open(video_path, "rb") as video_file:
                await update.message.reply_video(video_file)
            os.remove(video_path)
        except Exception as e:
            logging.error(f"❌ خطأ أثناء التحميل: {e}")
            await update.message.reply_text("❌ فشل تحميل الفيديو.")
    else:
        await update.message.reply_text("🤖 لحظة من فضلك...")
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response.choices[0].message.content
            await update.message.reply_text(reply)
        except Exception as e:
            logging.error(f"❌ خطأ OpenAI: {e}")
            await update.message.reply_text("⚠️ حدث خطأ في الذكاء الاصطناعي.")

# أمر الإرسال الجماعي
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر للمسؤول فقط.")
        return
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("✉️ أرسل الرسالة الآن لإرسالها للجميع.")

# تنفيذ الإرسال الجماعي
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast_mode"):
        return
    context.user_data["broadcast_mode"] = False
    users = load_users()
    msg = update.message
    count = 0
    for uid in users:
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=msg.text)
            elif msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption)
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption)
            count += 1
        except Exception as e:
            logging.warning(f"⚠️ فشل إرسال إلى {uid}: {e}")
    await update.message.reply_text(f"✅ تم الإرسال إلى {count} مستخدم.")

# تشغيل التطبيق
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
