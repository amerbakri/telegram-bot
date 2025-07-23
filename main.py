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

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 ميجابايت

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا لأحمله لك 🎥\n\n"
        "ملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt' مع البوت."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"choose_audio_quality|{url}")],
        [InlineKeyboardButton("🎥 فيديو", callback_data=f"choose_video_quality|{url}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية.")
        return

    if "|" not in data:
        await query.edit_message_text("⚠️ أمر غير معروف.")
        return

    action, url = data.split("|", 1)

    if action == "choose_audio_quality":
        keyboard = [
            [InlineKeyboardButton("🎵 عالي (320kbps)", callback_data=f"download_audio|bestaudio[abr>192]|{url}")],
            [InlineKeyboardButton("🎵 متوسط (128kbps)", callback_data=f"download_audio|bestaudio[abr<=192]|{url}")],
            [InlineKeyboardButton("🎵 منخفض (64kbps)", callback_data=f"download_audio|bestaudio[abr<=64]|{url}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
        ]
        await query.edit_message_text("اختر جودة الصوت:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "choose_video_quality":
        keyboard = [
            [InlineKeyboardButton("🎥 عالي (1080p)", callback_data=f"download_video|bestvideo[height<=1080]+bestaudio/best|{url}")],
            [InlineKeyboardButton("🎥 متوسط (720p)", callback_data=f"download_video|bestvideo[height<=720]+bestaudio/best|{url}")],
            [InlineKeyboardButton("🎥 منخفض (480p)", callback_data=f"download_video|bestvideo[height<=480]+bestaudio/best|{url}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
        ]
        await query.edit_message_text("اختر جودة الفيديو:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "download_audio":
        format_code, url = url.split("|", 1) if "|" in url else (url, "")
        format_selector = format_code if format_code else "bestaudio"
        await query.edit_message_text("⏳ جاري تحميل الصوت ...")

        if not os.path.exists(COOKIES_FILE):
            await query.message.reply_text("⚠️ ملف الكوكيز 'cookies.txt' غير موجود. يرجى رفعه.")
            return

        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-x",
            "--audio-format", "mp3",
            "-f", format_selector,
            "-o", "audio.%(ext)s",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            filename = "audio.mp3"
            if os.path.exists(filename):
                filesize = os.path.getsize(filename)
                if filesize > MAX_FILE_SIZE:
                    await query.message.reply_text(
                        "🚫 حجم الملف كبير جداً (أكثر من 50 ميجابايت).\n"
                        "يرجى اختيار جودة أقل أو إلغاء التنزيل."
                    )
                    os.remove(filename)
                    return
                with open(filename, "rb") as f:
                    await query.message.reply_audio(f)
                os.remove(filename)
            else:
                await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
        else:
            await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")

    elif action == "download_video":
        format_code, url = url.split("|", 1) if "|" in url else (url, "")
        format_selector = format_code if format_code else "best"
        await query.edit_message_text("⏳ جاري تحميل الفيديو ...")

        if not os.path.exists(COOKIES_FILE):
            await query.message.reply_text("⚠️ ملف الكوكيز 'cookies.txt' غير موجود. يرجى رفعه.")
            return

        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-f", format_selector,
            "-o", "video.%(ext)s",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            filename = None
            for ext in ["mp4", "mkv", "webm"]:
                if os.path.exists(f"video.{ext}"):
                    filename = f"video.{ext}"
                    break

            if filename and os.path.exists(filename):
                filesize = os.path.getsize(filename)
                if filesize > MAX_FILE_SIZE:
                    await query.message.reply_text(
                        "🚫 حجم الملف كبير جداً (أكثر من 50 ميجابايت).\n"
                        "يرجى اختيار جودة أقل أو إلغاء التنزيل."
                    )
                    os.remove(filename)
                    return
                with open(filename, "rb") as f:
                    await query.message.reply_video(f)
                os.remove(filename)
            else:
                await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
        else:
            await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")

if __name__ == '__main__':
    port = int(os.getenv("PORT"))
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
