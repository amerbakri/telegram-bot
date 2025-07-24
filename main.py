import os
import subprocess
import logging
import re

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberUpdated,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"
CHANNEL_USERNAME = "@gsm4x"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

url_store = {}

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

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status not in ("left", "kicked")
    except:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو من يوتيوب، تيك توك، إنستا أو فيسبوك لأحمله لك 🎥"
    )

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member: ChatMemberUpdated = update.chat_member
    if member.new_chat_member.status == "member":
        user = member.new_chat_member.user
        await context.bot.send_message(
            chat_id=update.chat_member.chat.id,
            text=(
                f"👋 أهلًا وسهلًا بك يا {user.first_name} 💫\n"
                "🛠️ صيانة واستشارات وعروض ولا أحلى!\n"
                "📥 أرسل رابط لتحميل الفيديو أو اسأل أي سؤال في مجال الجوال."
            )
        )

async def greetings_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if any(word in text for word in ["السلام عليكم", "مرحبا", "هلا", "مساء الخير", "صباح الخير"]):
        await update.message.reply_text("وعليكم السلام ورحمة الله ✨")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ("group", "supergroup"):
        if not is_valid_url(update.message.text or ""):
            return

    if not update.message or not update.message.text:
        return

    user_id = update.message.from_user.id
    if not await check_subscription(user_id, context):
        await update.message.reply_text(f"⚠️ يجب الاشتراك في القناة {CHANNEL_USERNAME} لاستخدام البوت.")
        return

    text = update.message.text.strip()

    if not is_valid_url(text):
        await update.message.reply_text("⚠️ يرجى إرسال رابط فيديو صالح من يوتيوب، تيك توك، إنستا أو فيسبوك فقط.")
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
        quality = quality_or_key if action != "cancel" else None
    except ValueError:
        await query.message.reply_text("⚠️ خطأ في معالجة الطلب.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        try:
            await context.bot.delete_message(query.message.chat_id, int(key))
        except:
            pass
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير موجود أو انتهت صلاحيته.")
        return

    await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    filename = None
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        fmt = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", fmt, "-o", "video.%(ext)s", url]

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
                        msg = "🎧 خذ الصوت وانطلق! 😄"
                    else:
                        await query.message.reply_video(f)
                        msg = "📽️ تفضل الفيديو، مشاهدة ممتعة! 🍿"
                    await query.message.reply_text(msg)
                except Exception as e:
                    await query.message.reply_text(f"⚠️ خطأ في الإرسال: {e}")
            os.remove(filename)
            url_store.pop(key, None)
            try:
                await context.bot.delete_message(query.message.chat_id, int(key))
            except:
                pass
            try:
                await query.delete_message()
            except:
                pass
        else:
            await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف.")
    else:
        await query.message.reply_text(f"🚫 فشل التنزيل:\n{result.stderr}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, greetings_reply))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
