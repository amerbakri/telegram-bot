import os
import subprocess
import logging
import re
import json
import openai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# إعدادات عامة
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = 6507290608  # حط هنا رقم الـ ID تبعك
COOKIES_FILE = "cookies.txt"
USERS_FILE = "users.json"

openai.api_key = OPENAI_API_KEY
url_store = {}

# التحقق من وجود ملف المستخدمين
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump([], f)

# إضافة المستخدم لملف users.json
def save_user(user_id):
    try:
        with open(USERS_FILE, "r") as f:
            users = json.load(f)
        if user_id not in users:
            users.append(user_id)
            with open(USERS_FILE, "w") as f:
                json.dump(users, f)
    except Exception as e:
        logging.warning(f"Failed to save user: {e}")

# التحقق من الرابط
def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    save_user(user_id)
    await update.message.reply_text(
        f"👋 أهلاً بك!\n🆔 رقم الـ User ID تبعك هو: {user_id}\n🎥 أرسل رابط فيديو لتحميله أو اسأل سؤال عام."
    )

# استقبال الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.message.from_user.id
    save_user(user_id)

    text = update.message.text.strip()

    if not is_valid_url(text):
        # رد ذكي
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

    # حفظ الرابط
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

    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

# الأزرار
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
            await query.message.reply_text("🚫 فشل في تحميل الفيديو. جرب رابطًا آخر.")
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

# إرسال إعلان
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 ليس لديك صلاحية.")

    await update.message.reply_text("📢 أرسل الآن الرسالة أو الصورة أو الفيديو مع الكابتشن.")
    context.user_data["broadcast"] = True

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("broadcast"):
        return

    context.user_data["broadcast"] = False

    with open(USERS_FILE, "r") as f:
        users = json.load(f)

    text = update.message.caption or update.message.text or ""
    buttons = []

    for line in text.split("\n"):
        if "-" in line and "http" in line:
            try:
                title, link = line.split("-", 1)
                buttons.append([InlineKeyboardButton(title.strip(), url=link.strip())])
            except:
                pass

    markup = InlineKeyboardMarkup(buttons) if buttons else None

    for user_id in users:
        try:
            if update.message.photo:
                await context.bot.send_photo(chat_id=user_id, photo=update.message.photo[-1].file_id, caption=text, reply_markup=markup)
            elif update.message.video:
                await context.bot.send_video(chat_id=user_id, video=update.message.video.file_id, caption=text, reply_markup=markup)
            else:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=markup)
        except Exception as e:
            logging.warning(f"❌ لم يتم الإرسال للمستخدم {user_id}: {e}")

    await update.message.reply_text("✅ تم إرسال الإعلان للجميع.")

# تشغيل البوت
if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()
