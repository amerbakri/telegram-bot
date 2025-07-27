# main.py
import os
import subprocess
import logging
import re
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 337597459
COOKIES_FILE = "cookies.txt"
USERS_FILE = "users.txt"
url_store = {}
user_ids = set()

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً! أرسل رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥")

def save_user(user_id):
    if user_id not in user_ids:
        user_ids.add(user_id)
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.message.from_user.id
    save_user(user_id)

    text = update.message.text.strip()

    if not is_valid_url(text):
        await update.message.reply_text("🚫 الرابط غير مدعوم.")
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

    await update.message.delete()
    await update.message.chat.send_message("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو منتهي.")
        return

    status_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", format_code, "-o", "video.%(ext)s", url]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        await query.message.reply_text("🚫 فشل في تحميل الفيديو.")
        await status_msg.delete()
        return

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

    await status_msg.delete()
    url_store.pop(key, None)

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    keyboard = [
        [
            InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin|count"),
            InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin|broadcast")
        ],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin|close")]
    ]
    await update.message.reply_text("اختر أمر:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return await query.answer("🚫 غير مصرح")

    await query.answer()
    action = query.data.split("|")[1]

    if action == "count":
        try:
            with open(USERS_FILE) as f:
                count = len(set(f.read().splitlines()))
        except:
            count = 0
        await query.edit_message_text(f"👥 عدد المستخدمين: {count}")

    elif action == "broadcast":
        context.user_data["broadcast"] = True
        await query.edit_message_text("📢 أرسل الرسالة الآن ليتم إرسالها لكل المستخدمين.")

    elif action == "close":
        await query.message.delete()

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("broadcast") and update.message.from_user.id == ADMIN_ID:
        try:
            with open(USERS_FILE) as f:
                users = set(f.read().splitlines())
        except:
            users = set()

        for uid in users:
            try:
                await context.bot.copy_message(chat_id=int(uid), from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            except:
                pass

        await update.message.reply_text("✅ تم إرسال الإعلان.")
        context.user_data["broadcast"] = False

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("amer", admin_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(audio|video|cancel)\|"))
    app.add_handler(CallbackQueryHandler(admin_actions, pattern=r"^admin\|"))
    app.add_handler(MessageHandler(filters.ALL, handle_broadcast))

  
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
