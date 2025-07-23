import os
import subprocess
import re
import uuid

from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    Dispatcher,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = f"/{BOT_TOKEN}"

app = Flask(__name__)

# تحقق من أن ملف الكوكيز موجود
COOKIES_FILE = "cookies.txt"
if not os.path.exists(COOKIES_FILE):
    print("⚠️ ملف cookies.txt غير موجود! ستواجه مشاكل مع بعض الفيديوهات.")

def is_url(text):
    return re.match(r'https?://', text) is not None

# استخدم ApplicationBuilder لبناء التطبيق
application = ApplicationBuilder().token(BOT_TOKEN).build()

@app.route("/")
def home():
    return "Bot is running!"

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب، تيك توك أو إنستا لأحمله لك 🎥"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not is_url(url):
        await update.message.reply_text("🚫 من فضلك أرسل رابط فيديو صالح.")
        return

    keyboard = [
        [
            InlineKeyboardButton("🎵 MP3", callback_data=f"audio_mp3|{url}"),
            InlineKeyboardButton("🎵 M4A", callback_data=f"audio_m4a|{url}"),
        ],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video_720|{url}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video_480|{url}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video_360|{url}"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ اختر صيغة الصوت أو جودة الفيديو:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    choice = data[0]  # audio_mp3 أو video_720 مثلاً
    url = data[1]

    unique_id = str(uuid.uuid4())[:8]

    if choice.startswith("audio"):
        ext = choice.split("_")[1]
        filename = f"audio_{unique_id}.{ext}"
        await query.edit_message_text(text=f"⏳ جاري تحميل الصوت بصيغة {ext}…")
        cmd = [
            "yt-dlp",
            "-x",
            f"--audio-format={ext}",
            "-o",
            filename,
            "--cookies",
            COOKIES_FILE,
            url,
        ]
    else:
        quality = choice.split("_")[1]
        filename = f"video_{unique_id}.mp4"
        await query.edit_message_text(text=f"⏳ جاري تحميل الفيديو بجودة {quality}p…")
        cmd = [
            "yt-dlp",
            "-f",
            f"bestvideo[height<={quality}]+bestaudio/best",
            "-o",
            filename,
            "--cookies",
            COOKIES_FILE,
            url,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)

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

# إضافة الهاندلرز
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
application.add_handler(CallbackQueryHandler(button_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8443"))
    print(f"Starting server on port {port}...")

    # تعيين webhook للتيليجرام
    WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"
    print(f"Webhook URL is {WEBHOOK_URL}")

    # ضبط webhook على Telegram
    bot = Bot(BOT_TOKEN)
    bot.delete_webhook(drop_pending_updates=True)  # امسح أي ويب هوك قديم
    bot.set_webhook(WEBHOOK_URL)

    # تشغيل flask app لاستقبال التحديثات
    app.run(host="0.0.0.0", port=port)
