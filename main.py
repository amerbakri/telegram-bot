import os
import json
import re
import subprocess
import logging
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    CallbackQueryHandler, ChatMemberHandler, filters
)

# إعدادات
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
COOKIES_FILE = "cookies.txt"
openai.api_key = OPENAI_API_KEY

# تخزين روابط المستخدمين
url_store = {}
users_file = "users.json"

# تحميل المستخدمين
def load_users():
    if not os.path.exists(users_file):
        return []
    with open(users_file, "r") as f:
        return json.load(f)

def save_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        with open(users_file, "w") as f:
            json.dump(users, f)

def is_valid_url(text):
    pattern = re.compile(
        r"(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|facebook\.com|fb\.watch|instagram\.com)/[^\s]+"
    )
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# استقبال /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    await update.message.reply_text(
        f"👋 أهلاً في بوت التنزيل والذكاء!\n🆔 ID: {user_id}\n\n"
        "🎥 أرسل رابط فيديو لتحميله أو اكتب أي شيء!"
    )

# استقبال الرسائل العامة
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user(user_id)
    text = update.message.text.strip()

    if is_valid_url(text):
        key = str(update.message.message_id)
        url_store[key] = text

        keyboard = [
            [InlineKeyboardButton("🎵 صوت MP3", callback_data=f"audio|best|{key}")],
            [
                InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
                InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
                InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
            ],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
        ]
        sent = await update.message.reply_text(
            "📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data[f"msg_{key}"] = sent.message_id
    else:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ: {e}")

# تحميل الفيديو أو الصوت
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except ValueError:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        url_store.pop(key, None)
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    url = url_store.get(key)
    if not url:
        await query.edit_message_text("⚠️ الرابط غير صالح.")
        return

    await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    if action == "audio":
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-x", "--audio-format", "mp3",
            "-o", "audio.%(ext)s", url
        ]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", format_code,
            "-o", "video.%(ext)s", url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        await query.message.reply_text("🚫 لم أستطع تحميل الملف.")
        return

    if action == "video":
        for ext in ["mp4", "mkv", "webm"]:
            f = f"video.{ext}"
            if os.path.exists(f):
                filename = f
                break

    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)
    else:
        await query.message.reply_text("🚫 الملف غير موجود.")

    url_store.pop(key, None)

    # حذف رسالة المستخدم
    try:
        await context.bot.delete_message(
            chat_id=query.message.chat_id,
            message_id=int(key)
        )
    except:
        pass

# إعلان من الأدمن
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص للإدارة فقط.")
        return

    context.user_data["broadcast"] = True
    await update.message.reply_text("📝 أرسل الآن محتوى الإعلان (نص، صورة، صوت، فيديو).")

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast"):
        return

    users = load_users()
    msg = update.message
    context.user_data["broadcast"] = False

    for uid in users:
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=msg.text)
            elif msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption)
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption)
            elif msg.audio:
                await context.bot.send_audio(chat_id=uid, audio=msg.audio.file_id, caption=msg.caption)
        except Exception:
            continue

    await update.message.reply_text("✅ تم إرسال الإعلان.")

# تهيئة التطبيق
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    port = int(os.getenv("PORT", "8080"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
