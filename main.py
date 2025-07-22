import os
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import subprocess

BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)

user_links = {}  # لتخزين الرابط مؤقتاً حسب المستخدم

@app.route('/')
def home():
    return "Bot is running!"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلا! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا لأحمله لك 🎥")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.message.from_user.id
    user_links[user_id] = url  # خزّن الرابط للمستخدم

    keyboard = [
        [
            InlineKeyboardButton("تحميل الفيديو 🎥", callback_data='download_video'),
            InlineKeyboardButton("تحميل الصوت 🎧", callback_data='download_audio'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر ما تريد تحميله:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    url = user_links.get(user_id)

    if not url:
        await query.edit_message_text("❌ لم يتم العثور على رابط. الرجاء إرسال الرابط أولاً.")
        return

    if query.data == "download_video":
        await query.edit_message_text("⏳ جاري تحميل الفيديو...")
        cmd = ["yt-dlp", "-f", "bestvideo+bestaudio", "-o", "video.%(ext)s", url]
        file_type = "video"
    else:
        await query.edit_message_text("⏳ جاري تحميل الصوت...")
        cmd = ["yt-dlp", "-f", "bestaudio", "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        file_type = "audio"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # ابحث عن الملف المناسب
            if file_type == "video":
                exts = ["mp4", "mkv", "webm"]
                for ext in exts:
                    if os.path.exists(f"video.{ext}"):
                        with open(f"video.{ext}", "rb") as f:
                            await query.message.reply_video(f)
                        os.remove(f"video.{ext}")
                        break
            else:
                exts = ["mp3", "m4a", "webm"]
                for ext in exts:
                    if os.path.exists(f"audio.{ext}"):
                        with open(f"audio.{ext}", "rb") as f:
                            await query.message.reply_audio(f)
                        os.remove(f"audio.{ext}")
                        break
        else:
            await query.message.reply_text(f"🚫 لم أتمكن من التحميل.\n📄 التفاصيل: {result.stderr}")
    except Exception as e:
        await query.message.reply_text(f"🚫 حصل خطأ: {e}")

if __name__ == '__main__':
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    bot_app.add_handler(CallbackQueryHandler(button))

    bot_app.run_polling()
    app.run(host='0.0.0.0', port=8080)
