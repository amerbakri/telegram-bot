import os
import logging
from flask import Flask, request
from pytube import YouTube
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Dispatcher, MessageHandler, CallbackQueryHandler, filters
from io import BytesIO

# إعداد المتغيرات من البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# كائنات البوت والسيرفر
bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# لتخزين البيانات المؤقتة حسب المستخدم
user_video_data = {}

# استخراج الجودات من رابط اليوتيوب
def get_youtube_streams(url):
    yt = YouTube(url)
    streams = yt.streams.filter(progressive=True, file_extension="mp4")
    quality_map = {}
    for stream in streams:
        res = stream.resolution
        if res and res not in quality_map:
            quality_map[res] = stream.itag
    return yt.title, quality_map, yt.video_id

# عند إرسال رابط
def handle_message(update: Update, context):
    text = update.message.text.strip()
    if "youtube.com" in text or "youtu.be" in text:
        update.message.reply_text("🔍 جاري استخراج الجودات...")
        try:
            title, qualities, video_id = get_youtube_streams(text)
            user_id = update.message.from_user.id
            user_video_data[user_id] = {
                "url": text,
                "qualities": qualities,
                "title": title
            }
            buttons = [
                [InlineKeyboardButton(f"📥 {q}", callback_data=f"download_{q}")]
                for q in sorted(qualities.keys(), reverse=True)
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            update.message.reply_text(
                f"🎬 اختر الجودة المطلوبة للفيديو:\n*{title}*",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            update.message.reply_text(f"❌ خطأ: {e}")
    else:
        update.message.reply_text("📌 أرسل رابط فيديو من YouTube فقط.")

# عند اختيار الجودة من الأزرار
def handle_quality_choice(update: Update, context):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()

    if user_id not in user_video_data:
        query.edit_message_text("⚠️ انتهت صلاحية الرابط. الرجاء إعادة الإرسال.")
        return

    selected_quality = query.data.replace("download_", "")
    info = user_video_data[user_id]
    url = info["url"]
    itag = info["qualities"].get(selected_quality)
    title = info["title"]

    try:
        yt = YouTube(url)
        stream = yt.streams.get_by_itag(itag)
        buffer = BytesIO()
        stream.stream_to_buffer(buffer)
        buffer.seek(0)
        bot.send_video(chat_id=user_id, video=InputFile(buffer, filename=f"{title}.mp4"))
        query.edit_message_text("✅ تم إرسال الفيديو بنجاح.")
        del user_video_data[user_id]
    except Exception as e:
        query.edit_message_text(f"❌ فشل التحميل: {e}")

# إعداد البوت
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=1, use_context=True)
dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
dispatcher.add_handler(CallbackQueryHandler(handle_quality_choice))

# استقبال التحديثات من Telegram عبر Webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

# تفعيل Webhook عند زيارة الرابط الجذري
@app.route("/")
def set_webhook():
    bot.delete_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    return "✅ Webhook تم تفعيله"

# تشغيل السيرفر
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
