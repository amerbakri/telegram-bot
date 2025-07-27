import os
import subprocess
import logging
import re
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459
USERS_FILE = "users.txt"

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

# تأكد من أن المستخدم مسجل
def store_user(user_id):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                pass
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        if str(user_id) not in users:
            with open(USERS_FILE, "a") as f:
                f.write(f"{user_id}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    store_user(user_id)
    await update.message.reply_text("👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_id = update.message.from_user.id
    store_user(user_id)

    text = update.message.text.strip()

    if not is_valid_url(text):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
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

    try:
        await update.message.delete()
    except:
        pass

    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

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

    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    filename = None
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", format_code, "-o", "video.%(ext)s", url]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        fallback = subprocess.run(
            ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best[ext=mp4]", "-o", "video.%(ext)s", url],
            capture_output=True, text=True
        )
        if fallback.returncode != 0:
            await query.edit_message_text("🚫 فشل في تحميل الفيديو.")
            url_store.pop(key, None)
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
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")

    url_store.pop(key, None)

    try:
        await loading_msg.delete()
    except:
        pass

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 عرض عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_announce")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    await update.message.reply_text("🎛️ لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.message.edit_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    if data == "admin_users":
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            count = len(users)
            recent = "\n".join(users[-5:]) if users else "لا يوجد"
        except:
            count = 0
            recent = "لا يوجد"
        await query.edit_message_text(
            f"👥 عدد المستخدمين: {count}\n\n🕵️ آخر 5 مستخدمين:\n{recent}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ])
        )

    elif data == "admin_announce":
        context.user_data["waiting_for_announcement"] = True
        context.user_data["media"] = None
        await query.edit_message_text("📝 أرسل الآن نص أو صورة أو فيديو للإعلان:")

    elif data == "admin_back":
        await admin_panel(update, context)

    elif data == "admin_close":
        await query.edit_message_text("✅ تم إغلاق لوحة التحكم.")

async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    if context.user_data.get("waiting_for_announcement"):
        media = None
        if update.message.photo:
            media = update.message.photo[-1].file_id
            context.user_data["media"] = ("photo", media)
        elif update.message.video:
            media = update.message.video.file_id
            context.user_data["media"] = ("video", media)

        announcement = update.message.caption or update.message.text or ""
        context.user_data["announcement_text"] = announcement

        keyboard = [
            [
                InlineKeyboardButton("✅ تأكيد الإرسال", callback_data="confirm_announce"),
                InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")
            ]
        ]

        await update.message.reply_text(
            f"📢 إعلان:\n\n{announcement}\n\nهل تريد المتابعة؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def confirm_announce_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    announcement = context.user_data.get("announcement_text", "")
    media_info = context.user_data.get("media")

    try:
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        sent = 0
        for uid in users:
            try:
                if media_info:
                    if media_info[0] == "photo":
                        await context.bot.send_photo(chat_id=int(uid), photo=media_info[1], caption=announcement)
                    elif media_info[0] == "video":
                        await context.bot.send_video(chat_id=int(uid), video=media_info[1], caption=announcement)
                else:
                    await context.bot.send_message(chat_id=int(uid), text=announcement)
                sent += 1
            except:
                pass
        await query.edit_message_text(f"✅ تم إرسال الإعلان إلى {sent} مستخدم.")
    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ أثناء الإرسال: {e}")
    context.user_data.clear()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, admin_command_handler))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(audio|video|cancel)"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(confirm_announce_callback, pattern="^confirm_announce"))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
