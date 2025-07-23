import os
import subprocess
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, ChatMemberHandler, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"
url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720]",
    "480": "best[height<=480]",
    "360": "best[height<=360]",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلا! أرسل رابط فيديو من يوتيوب، تيك توك، إنستا أو فيسبوك لأقوم بتحميله لك 🎬"
    )

async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    replies = {
        "السلام عليكم": "وعليكم السلام ورحمة الله 🌟",
        "مرحبا": "أهلًا وسهلًا! 😄",
        "هلا": "هلا وغلا 💫",
        "صباح الخير": "صباح الورد ☀️",
        "مساء الخير": "مساء الفل 🌙"
    }
    for keyword, response in replies.items():
        if keyword in text:
            await update.message.reply_text(response)
            return

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not is_valid_url(text):
        return
    key = str(update.message.message_id)
    url_store[key] = text
    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 فيديو 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 فيديو 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 فيديو 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]
    await update.message.reply_text("📥 اختر نوع التنزيل والجودة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, quality_or_key, maybe_key = query.data.split("|")
        key = maybe_key if action != "cancel" else quality_or_key
    except ValueError:
        await query.message.reply_text("⚠️ خطأ في التنزيل.")
        return
    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
        except: pass
        url_store.pop(key, None)
        return
    if not os.path.exists(COOKIES_FILE):
        await query.message.reply_text("⚠️ ملف الكوكيز غير موجود.")
        return
    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح.")
        return
    await query.edit_message_text("⏳ جاري التحميل...")
    filename = None
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality_or_key, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", f"{format_code}/best", "-o", "video.%(ext)s", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        if action == "video":
            for ext in ["mp4", "mkv", "webm"]:
                if os.path.exists(f"video.{ext}"):
                    filename = f"video.{ext}"
                    break
        if filename and os.path.exists(filename):
            with open(filename, "rb") as f:
                try:
                    if action == "audio":
                        await query.message.reply_audio(f)
                        funny = "🎧 جاهز للطرب؟ 😄"
                    else:
                        await query.message.reply_video(f)
                        funny = "📺 استمتع بالمشاهدة! 🍿"
                    await query.message.reply_text(funny)
                except Exception as e:
                    await query.message.reply_text(f"⚠️ خطأ في الإرسال: {e}")
            os.remove(filename)
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
            except: pass
            url_store.pop(key, None)
            try:
                await query.delete_message()
            except: pass
        else:
            await query.message.reply_text("🚫 الملف غير موجود بعد التحميل.")
    else:
        await query.message.reply_text(f"❌ فشل التحميل.\n{result.stderr}")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if chat_member.new_chat_member.status == "member":
        user = chat_member.new_chat_member.user
        name = user.first_name or "صديق جديد"
        await context.bot.send_message(
            chat_id=update.chat_member.chat.id,
            text=f"👋 أهلًا وسهلًا بك يا {name} 💫\n🛠️ صيانة واستشارات وعروض ولا أحلى!\n📥 أرسل رابط لتحميل الفيديو أو اسأل عن أي خدمة."
        )

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ✅ ترتيب الـ handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
