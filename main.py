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

# تخزين روابط الفيديو مؤقتًا (message_id -> url)
url_store = {}

# فلاتر الروابط
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

    # نعرض نوع التنزيل أولاً (صوت أو فيديو)
    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"type|audio|{key}"),
            InlineKeyboardButton("🎥 فيديو", callback_data=f"type|video|{key}"),
        ],
        [
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية.")
        return

    parts = query.data.split("|")
    if len(parts) < 3:
        await query.message.reply_text("⚠️ خطأ في بيانات الزرار.")
        return

    action = parts[0]

    if action == "type":
        # نوع التنزيل + نوع الملف + المفتاح
        choice = parts[1]  # audio or video
        key = parts[2]

        url = url_store.get(key)
        if not url:
            await query.message.reply_text("⚠️ الرابط غير موجود أو انتهت صلاحية العملية. أرسل الرابط مرة أخرى.")
            return

        # بعد اختيار النوع، نعرض خيارات الجودة
        keyboard = [
            [
                InlineKeyboardButton("عالي (best)", callback_data=f"quality|best|{choice}|{key}"),
                InlineKeyboardButton("متوسط (medium)", callback_data=f"quality|medium|{choice}|{key}"),
                InlineKeyboardButton("منخفض (worst)", callback_data=f"quality|worst|{choice}|{key}"),
            ],
            [
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"📊 اختر جودة {choice}:", reply_markup=reply_markup)

    elif action == "quality":
        # جودة + نوع + المفتاح
        quality = parts[1]  # best, medium, worst
        choice = parts[2]   # audio or video
        key = parts[3]

        url = url_store.get(key)
        if not url:
            await query.message.reply_text("⚠️ الرابط غير موجود أو انتهت صلاحية العملية. أرسل الرابط مرة أخرى.")
            return

        await query.edit_message_text(text=f"⏳ جاري تحميل {choice} بجودة {quality}...")

        # بناء أمر yt-dlp حسب النوع والجودة
        if choice == "audio":
            # صيغة الصوت فقط
            cmd = [
                "yt-dlp",
                "--cookies", COOKIES_FILE,
                "-x",
                "--audio-format", "mp3",
                "-f", f"bestaudio{'/worstaudio' if quality=='worst' else ''}",
                "-o", "audio.%(ext)s",
                url
            ]
            filename = "audio.mp3"
        else:
            # صيغة الفيديو حسب الجودة
            if quality == "best":
                fmt = "bestvideo+bestaudio/best"
            elif quality == "medium":
                fmt = "bv[height<=480]+ba/best[height<=480]"
            else:  # worst
                fmt = "worstvideo+worstaudio/worst"

            cmd = [
                "yt-dlp",
                "--cookies", COOKIES_FILE,
                "-f", fmt,
                "-o", "video.%(ext)s",
                url
            ]
            filename = None

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")
            return

        if choice == "video":
            for ext in ["mp4", "mkv", "webm"]:
                if os.path.exists(f"video.{ext}"):
                    filename = f"video.{ext}"
                    break

        if filename and os.path.exists(filename):
            size_mb = os.path.getsize(filename) / (1024 * 1024)
            if size_mb > 50:
                await query.message.reply_text(f"🚫 حجم الملف كبير جداً ({int(size_mb)} ميجابايت). لا يمكنني إرساله عبر تيليجرام.")
                os.remove(filename)
                return

            with open(filename, "rb") as f:
                if choice == "audio":
                    await query.message.reply_audio(f)
                else:
                    await query.message.reply_video(f)
            os.remove(filename)
        else:
            await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")

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
