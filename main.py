import os
import json
import logging
import uuid
import openai
import yt_dlp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, AIORateLimiter
)

# إعداد المتغيرات البيئية
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8080"))

# تحقق من المفاتيح الأساسية
if not BOT_TOKEN or not OPENAI_API_KEY or not WEBHOOK_URL:
    raise ValueError("❌ تأكد من تحديد BOT_TOKEN و OPENAI_API_KEY و WEBHOOK_URL")

# إعداد OpenAI
openai.api_key = OPENAI_API_KEY

# إعداد السجل
logging.basicConfig(level=logging.INFO)

# ملف المستخدمين
USERS_FILE = "users.json"

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

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
        f"👋 أهلاً بك!\n🆔 رقمك: {user_id}\n\n🎥 أرسل رابط فيديو أو اسألني أي سؤال."
    )

# التعامل مع الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    text = update.message.text or ""

    if "http://" in text or "https://" in text:
        await update.message.reply_text("📥 جاري تحميل الفيديو...")
        try:
            filename = f"{uuid.uuid4()}.mp4"
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': filename,
                'noplaylist': True,
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                video_path = ydl.prepare_filename(info)

            if os.path.getsize(video_path) > 50 * 1024 * 1024:
                await update.message.reply_text("⚠️ الفيديو أكبر من الحد المسموح لتليجرام.")
            else:
                with open(video_path, "rb") as video_file:
                    await update.message.reply_video(video_file)
            os.remove(video_path)
        except Exception as e:
            logging.error(f"❌ خطأ أثناء تحميل الفيديو: {e}")
            await update.message.reply_text("❌ فشل تحميل الفيديو.")
    else:
        await update.message.reply_text("🤖 لحظة من فضلك...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response.choices[0].message.content
            await update.message.reply_text(reply)
        except Exception as e:
            logging.error(f"❌ خطأ في الذكاء الاصطناعي: {e}")
            await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة السؤال.")

# أمر الإرسال الجماعي
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر للمسؤول فقط.")
        return
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("✉️ أرسل الرسالة الآن ليتم إرسالها لجميع المستخدمين.")

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
    await update.message.reply_text(f"✅ تم إرسال الرسالة إلى {count} مستخدم.")

# تشغيل البوت باستخدام Webhook
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()
