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

# قاموس مؤقت لتخزين روابط الفيديو وخيارات الجودة حسب message_id
url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل لي رابط فيديو من يوتيوب، تيك توك، إنستا أو فيسبوك لأحمله لك 🎥\n\n"
        "ملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt' مع البوت."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not is_valid_url(text):
        await update.message.reply_text("⚠️ يرجى إرسال رابط فيديو صالح من يوتيوب، تيك توك، إنستا أو فيسبوك فقط.")
        return

    key = str(update.message.message_id)
    url_store[key] = {'url': text, 'quality': None}

    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{key}"),
        ],
        [
            InlineKeyboardButton("🎬 فيديو 720p (HD)", callback_data=f"video720|{key}"),
            InlineKeyboardButton("🎬 فيديو 480p", callback_data=f"video480|{key}"),
            InlineKeyboardButton("🎬 فيديو 360p", callback_data=f"video360|{key}"),
        ],
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل أو إلغاء العملية:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, key = query.data.split("|", 1)
    except ValueError:
        await query.message.reply_text("⚠️ حدث خطأ في اختيار التنزيل.")
        return

    if action == "cancel":
        # حذف رسالة الخيارات وأيضًا رسالة الرابط
        await query.edit_message_text("❌ تم إلغاء العملية بنجاح. لا تنسى ترجع تشوف شي مضحك تاني! 😂")
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
        except Exception:
            pass
        url_store.pop(key, None)
        return

    if not os.path.exists(COOKIES_FILE):
        await query.message.reply_text("⚠️ ملف الكوكيز 'cookies.txt' غير موجود. يرجى رفعه.")
        return

    info = url_store.get(key)
    if not info:
        await query.message.reply_text("⚠️ الرابط غير موجود أو انتهت صلاحية العملية. أرسل الرابط مرة أخرى.")
        return

    url = info['url']

    # تعيين رسالة تحميل فكاهية حسب النوع
    funny_msgs = {
        "audio": "🎧 حضر سماعاتك، عم نحمل الصوت بس!",
        "video720": "📺 جودتك 720p على الطريق!",
        "video480": "📺 بنزلك فيديو 480p مش بطال!",
        "video360": "📺 جودتك 360p، تحس بالحنين؟",
    }
    await query.edit_message_text(text=funny_msgs.get(action, "⏳ جاري التحميل..."))

    # بناء أمر yt-dlp حسب الجودة المطلوبة
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
    else:
        # جودة الفيديو المطلوبة
        quality_map = {
            "video720": "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720][ext=mp4]",
            "video480": "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480][ext=mp4]",
            "video360": "bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360][ext=mp4]",
        }
        fmt = quality_map.get(action, "best[ext=mp4]/best")
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-f", fmt,
            "-o", "video.%(ext)s",
            url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        if action.startswith("video"):
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

            # حذف رسالة الرابط بعد الإرسال
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
            except Exception:
                pass

            url_store.pop(key, None)

            # حذف رسالة "جاري التحميل"
            try:
                await query.delete_message()
            except Exception:
                pass
        else:
            await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
    else:
        await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")

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
