import os
import json
import subprocess
import logging
import re
import openai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# إعدادات
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"
ADMIN_ID = 123456789  # ←←← استبدل هذا برقمك بعد ما تعرفه من أول رسالة

# إعدادات عامة
logging.basicConfig(level=logging.INFO)
openai.api_key = OPENAI_API_KEY
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}
url_store = {}

USERS_FILE = "users.json"

# حفظ المستخدم في ملف
def save_user(user_id: int):
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                users = json.load(f)
        else:
            users = []

        if user_id not in users:
            users.append(user_id)
            with open(USERS_FILE, "w") as f:
                json.dump(users, f)
    except Exception as e:
        logging.error(f"خطأ في حفظ المستخدم: {e}")

# تحقق إذا الرابط من المواقع المسموحة
def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

# /start - ترحيب + إرسال ID
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    save_user(user_id)
    await update.message.reply_text(
        f"👋 أهلاً بك!\n🆔 رقم الـ User ID تبعك هو: `{user_id}`\n\n"
        "🎥 أرسل رابط فيديو لتحميله أو اسأل سؤال عام.",
        parse_mode="Markdown"
    )

# أمر البث الإداري /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.message.from_user.id
    if sender_id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر خاص بالإدارة.")
        return

    if not context.args:
        await update.message.reply_text("❗ أرسل رسالة بعد الأمر مثل:\n`/broadcast أهلاً بالجميع!`", parse_mode="Markdown")
        return

    message = ' '.join(context.args)

    # إرسال للمستخدمين
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            users = json.load(f)
    else:
        users = []

    success, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            success += 1
        except:
            failed += 1

    await update.message.reply_text(f"✅ تم إرسال الرسالة لـ {success} مستخدم.\n❌ فشل الإرسال لـ {failed}.")

# تحميل الفيديو أو الرد الذكي
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.message.from_user.id
    save_user(user_id)

    text = update.message.text.strip()

    # رد ذكي من ChatGPT
    if not is_valid_url(text):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ في الرد الذكي: {e}")
        return

    key = str(update.message.message_id)
    url_store[key] = text

    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]

    await update.message.reply_text("📥 اختر نوع التحميل:", reply_markup=InlineKeyboardMarkup(keyboard))

# أزرار التحميل
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except ValueError:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو انتهت صلاحيته.")
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
        fallback_cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", "best[ext=mp4]",
            "-o", "video.%(ext)s", url
        ]
        fallback = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if fallback.returncode != 0:
            await query.message.reply_text("🚫 فشل في تحميل الفيديو.")
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

# تشغيل البوت
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Bot is running...")
    app.run_polling()
