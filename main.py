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
from dotenv import load_dotenv

# تحميل المتغيرات من .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", 8080))

openai.api_key = OPENAI_API_KEY
USERS_FILE = "users.json"

logging.basicConfig(level=logging.INFO)

# إدارة المستخدمين
def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

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
        "🎥 أرسل رابط فيديو لتحميله أو اسأل سؤال."
    )

# التعامل مع الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    text = update.message.text
    if not text:
        return

    if "http" in text:
        await update.message.reply_text("📥 جاري تحميل الفيديو...")
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
            logging.error(f"❌ خطأ تحميل الفيديو: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء تحميل الفيديو.")
    else:
        await update.message.reply_text("🤖 أفكر...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}],
            )
            reply = response["choices"][0]["message"]["content"]
            await update.message.reply_text(reply)
        except Exception as e:
            logging.error(f"❌ خطأ OpenAI: {e}")
            await update.message.reply_text("⚠️ حدث خطأ من OpenAI.")

# أمر للنشر
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر للمسؤول فقط.")
        return
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("📣 أرسل الرسالة لإرسالها للجميع.")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast_mode"):
        return
    context.user_data["broadcast_mode"] = False
    users = load_users()
    msg = update.message
    for uid in users:
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=msg.text)
            elif msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption)
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption)
        except Exception as e:
            logging.warning(f"⚠️ فشل الإرسال إلى {uid}: {e}")
    await update.message.reply_text("✅ تم إرسال الرسالة.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
