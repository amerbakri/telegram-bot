import os
import json
import logging
import openai
import yt_dlp
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# إعدادات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID")  # مثال: "@yourchannel"
HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")  # ل render.com
PORT = int(os.getenv("PORT", "8080"))
USERS_FILE = "users.json"

# إعداد API مفتاح OpenAI
openai.api_key = OPENAI_API_KEY

# تسجيل الأخطاء
logging.basicConfig(level=logging.INFO)

# تحميل المستخدمين
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return []

def save_user(user_id: int):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

# التحقق من الاشتراك
async def is_user_member(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    if not await is_user_member(context.bot, user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك الآن", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]
        ])
        await update.message.reply_text("❗ يجب عليك الاشتراك بالقناة أولاً:", reply_markup=keyboard)
        return

    await update.message.reply_text(
        f"👋 أهلاً بك! أرسل رابط فيديو أو اسأل سؤالاً.\n🆔 User ID: {user_id}"
    )

# معالجة الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)

    if not await is_user_member(context.bot, user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك الآن", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]
        ])
        await update.message.reply_text("❗ يجب عليك الاشتراك بالقناة أولاً:", reply_markup=keyboard)
        return

    text = update.message.text

    if "http://" in text or "https://" in text:
        await update.message.reply_text("📥 جاري تحميل الفيديو...")
        try:
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': 'video.%(ext)s',
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                video_path = ydl.prepare_filename(info)

            with open(video_path, "rb") as video:
                await update.message.reply_video(video)
            os.remove(video_path)
        except Exception as e:
            logging.error(f"خطأ تحميل الفيديو: {e}")
            await update.message.reply_text("❌ فشل تحميل الفيديو. سأحاول تنزيل أفضل جودة متاحة.")
    else:
        await update.message.reply_text("🤔 جاري التفكير...")
        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            await update.message.reply_text(response.choices[0].message.content)
        except Exception as e:
            logging.error(f"خطأ OpenAI: {e}")
            await update.message.reply_text("⚠️ حدث خطأ أثناء توليد الرد.")

# أمر المسؤول /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 هذا الأمر للمسؤول فقط.")
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text("📣 أرسل الرسالة الآن لإرسالها لكل المستخدمين.")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast_mode"):
        return
    context.user_data["broadcast_mode"] = False
    users = load_users()
    for uid in users:
        try:
            if update.message.text:
                await context.bot.send_message(chat_id=uid, text=update.message.text)
            elif update.message.video:
                await context.bot.send_video(chat_id=uid, video=update.message.video.file_id)
        except Exception as e:
            logging.warning(f"❌ فشل الإرسال لـ {uid}: {e}")
    await update.message.reply_text("✅ تم إرسال الرسالة للجميع.")

# تشغيل التطبيق
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    webhook_url = f"https://{HOSTNAME}/{BOT_TOKEN}"
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    main()
