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

# قاموس مؤقت لتخزين روابط الفيديو حسب message_id
url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)/.+"
    )
    return bool(pattern.match(text))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا لأحمله لك 🎥\n\n"
        "ملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt' مع البوت."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not is_valid_url(text):
        await update.message.reply_text("⚠️ يرجى إرسال رابط فيديو صالح من يوتيوب، تيك توك أو إنستا فقط.")
        return

    key = str(update.message.message_id)
    url_store[key] = text

    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{key}"),
            InlineKeyboardButton("🎥 فيديو (MP4)", callback_data=f"video|{key}"),
        ],
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, key = query.data.split("|", 1)
    except ValueError:
        await query.message.reply_text("⚠️ حدث خطأ في اختيار التنزيل.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير موجود أو انتهت صلاحية العملية. أرسل الرابط مرة أخرى.")
        return

    loading_msg = await query.edit_message_text(text=f"⏳ جاري تحميل {action}...")

    if action == "audio":
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-x",
            "--audio-format", "mp3",
            "-o", "audio.%(ext)s",
            url
        ]
        filename = "audio.mp3"
    else:  # فيديو mp4 فقط
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "-o", "video.%(ext)s",
            url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        if action == "video":
            for ext in ["mp4", "mkv", "webm"]:
                if os.path.exists(f"video.{ext}"):
                    filename = f"video.{ext}"
                    break

        if filename and os.path.exists(filename):
            with open(filename, "rb") as f:
                if action == "audio":
                    await query.message.reply_audio(f)
                else:
                    await query.message.reply_video(f)

            os.remove(filename)
            await loading_msg.delete()  # حذف رسالة التحميل
            url_store.pop(key, None)
        else:
            await loading_msg.edit_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
    else:
        await loading_msg.edit_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")

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
