import os
import subprocess
import re
import uuid

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def is_url(text):
    return re.match(r'https?://', text) is not None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك!\n"
        "أرسل لي رابط فيديو من **يوتيوب** أو **تيك توك** أو **إنستغرام**، "
        "وسأقوم بتحميله لك 🎥\n\n"
        "اختر لاحقاً صيغة الصوت أو جودة الفيديو.",
        parse_mode="Markdown"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_url(url):
        await update.message.reply_text("🚫 من فضلك أرسل رابط فيديو صالح.")
        return

    keyboard = [
        [
            InlineKeyboardButton("🎵 MP3", callback_data=f"audio_mp3|{url}"),
            InlineKeyboardButton("🎵 M4A", callback_data=f"audio_m4a|{url}")
        ],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video_720|{url}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video_480|{url}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video_360|{url}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ اختر صيغة الصوت أو جودة الفيديو:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    choice = data[0]  # مثل audio_mp3 أو video_720
    url = data[1]

    unique_id = str(uuid.uuid4())[:8]

    if choice.startswith("audio"):
        ext = choice.split("_")[1]
        filename = f"audio_{unique_id}.{ext}"
        await query.edit_message_text(text=f"⏳ جاري تحميل الصوت بصيغة {ext}…")
        cmd = [
            "yt-dlp", "-x", f"--audio-format={ext}", "-o", filename,
            "--cookies", "cookies.txt", url
        ]
    else:
        quality = choice.split("_")[1]
        filename = f"video_{unique_id}.mp4"
        await query.edit_message_text(text=f"⏳ جاري تحميل الفيديو بجودة {quality}p…")
        cmd = [
            "yt-dlp",
            "-f", f"bestvideo[height<={quality}]+bestaudio/best",
            "-o", filename,
            "--cookies", "cookies.txt",
            url
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # تنظيف الملفات المؤقتة لو موجودة
    def cleanup():
        if os.path.exists(filename):
            os.remove(filename)

    if result.returncode == 0 and os.path.exists(filename):
        with open(filename, "rb") as f:
            if choice.startswith("audio"):
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        cleanup()
        await query.message.reply_text("✅ تم التنزيل بنجاح!")
    else:
        cleanup()
        if "Too Many Requests" in result.stderr:
            msg = (
                "🚫 يبدو أنك أرسلت طلبات كثيرة بسرعة.\n"
                "🕒 انتظر دقائق وحاول مجددًا، أو جرب من شبكة إنترنت مختلفة."
            )
        elif "Sign in to confirm" in result.stderr:
            msg = (
                "🚫 لا يمكن تحميل هذا الفيديو لأن يوتيوب يطلب تسجيل الدخول لتأكيد أنك إنسان.\n"
                "📝 جرّب فيديو آخر بدون قيود."
            )
        else:
            msg = (
                "🚫 فشل التنزيل. حاول مجددًا أو تحقق من الرابط.\n\n"
                f"📄 التفاصيل:\n`{result.stderr.strip()}`"
            )
        await query.message.reply_text(msg, parse_mode="Markdown")


if __name__ == '__main__':
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    bot_app.add_handler(CallbackQueryHandler(button_handler))

    bot_app.run_polling()
    app.run(host='0.0.0.0', port=8080)
