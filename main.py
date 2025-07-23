import os
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
import logging
import re

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com)/.+"
    )
    return bool(pattern.match(text))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل لي رابط فيديو من يوتيوب، تيك توك، إنستا أو فيسبوك لأحمله لك 🎥\n\n"
        "ملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt'."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم إلغاء العملية. إذا بدك تحمل فيديو، أرسل الرابط :)")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text.lower() == "إلغاء":
        await cancel(update, context)
        return

    if not is_valid_url(text):
        await update.message.reply_text("⚠️ ههههه، مش رابط فيديو صالح! جرب ترسل رابط صحيح من يوتيوب، تيك توك، إنستا أو فيسبوك.")
        return

    key = str(update.message.message_id)
    url_store[key] = text

    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{key}"),
            InlineKeyboardButton("🎥 فيديو (MP4)", callback_data=f"video|{key}|mp4"),
        ],
        [
            InlineKeyboardButton("🎥 فيديو (MKV)", callback_data=f"video|{key}|mkv"),
            InlineKeyboardButton("🎥 فيديو (WEBM)", callback_data=f"video|{key}|webm"),
        ],
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل أو إلغاء:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not os.path.exists(COOKIES_FILE):
        await query.message.reply_text("⚠️ ملف الكوكيز 'cookies.txt' غير موجود. رجاءً حمّله لأتمكن من تنزيل الفيديوهات المحمية.")
        return

    data = query.data.split("|")
    action = data[0]

    if action == "cancel":
        await query.edit_message_text("❌ العملية ألغيت، يلا بعتلي رابط تاني إذا بدك! 😉")
        return

    if len(data) < 2:
        await query.message.reply_text("⚠️ خطأ في اختيار التنزيل، حاول مرة تانية.")
        return

    key = data[1]
    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط مش موجود أو انتهى وقت العملية. أبعت الرابط من جديد.")
        return

    if action == "audio":
        await query.edit_message_text("⏳ عم نزل الصوت، خليك معي شوي... 🎧")
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-x",
            "--audio-format", "mp3",
            "-o", "audio.%(ext)s",
            url
        ]
        filename = "audio.mp3"

    elif action == "video":
        if len(data) < 3:
            await query.message.reply_text("⚠️ لازم تختار صيغة الفيديو.")
            return
        ext = data[2]
        await query.edit_message_text(f"⏳ عم نزل الفيديو بصيغة {ext.upper()}... انتظر شوية 😎")
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-f", f"bestvideo[ext={ext}]+bestaudio/best[ext={ext}]/best",
            "-o", f"video.{ext}",
            url
        ]
        filename = f"video.{ext}"
    else:
        await query.message.reply_text("⚠️ خيار غير معروف.")
        return

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        if "Request Entity Too Large" in result.stderr or "HTTP Error 413" in result.stderr:
            await query.edit_message_text("🚫 الفيديو كبير كتير! حاول تختار فيديو أصغر أو صوت بس 🎧")
        else:
            await query.edit_message_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")
        return

    if filename and os.path.exists(filename):
        try:
            with open(filename, "rb") as f:
                if action == "audio":
                    await query.message.reply_audio(f)
                else:
                    await query.message.reply_video(f)
            os.remove(filename)
            await query.delete_message()
            await query.message.reply_text("✅ تم التحميل بنجاح! إذا بدك، أرسل رابط تاني 😉")
        except Exception as e:
            await query.message.reply_text(f"🚫 حصل خطأ أثناء الإرسال: {e}")
    else:
        await query.message.reply_text("🚫 ما لقيت الملف بعد التنزيل!")

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
