import os
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
    ChatMemberHandler,
)
import logging
import re
import asyncio

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
        if member.status not in ("left", "kicked"):
            return True
    except Exception as e:
        logging.warning(f"Subscription check failed: {e}")
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب، تيك توك، إنستا أو فيسبوك لأحمله لك 🎥\n\n"
        "ملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt' مع البوت."
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
                "📥 أرسل رابط لتحميل الفيديو بأي جودة أو اسأل أي سؤال عن الصيانة والعروض في خدمات الجوال."
            ),
        )

async def group_greetings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type not in ("group", "supergroup"):
        return
    text = update.message.text.lower()
    greetings = ["السلام عليكم", "مرحبا", "اهلا", "أهلا", "هلا"]
    if any(greet in text for greet in greetings):
        await update.message.reply_text("وعليكم السلام ورحمة الله 😊")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ("group", "supergroup"):
        if not update.message.text or not is_valid_url(update.message.text.strip()):
            return

    if not update.message or not update.message.text:
        return

    user_id = update.message.from_user.id
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"⚠️ عذراً، يجب عليك الاشتراك في القناة {CHANNEL_USERNAME} لاستخدام هذا البوت."
        )
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
            InlineKeyboardButton("🎥 فيديو 360p", callback_data=f"video|360|{key}"),
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📥 اختر نوع التنزيل والجودة أو إلغاء العملية:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality_or_key, maybe_key = query.data.split("|")
        if action == "cancel":
            key = quality_or_key
        else:
            quality = quality_or_key
            key = maybe_key
    except ValueError:
        await query.message.reply_text("⚠️ حدث خطأ في اختيار التنزيل.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم إلغاء العملية بنجاح.")
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
        except Exception:
            pass
        url_store.pop(key, None)
        return

    if not os.path.exists(COOKIES_FILE):
        await query.message.reply_text("⚠️ ملف الكوكيز 'cookies.txt' غير موجود. يرجى رفعه.")
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير موجود أو انتهت صلاحية العملية. أرسل الرابط مرة أخرى.")
        return

    await query.edit_message_text(text=f"⏳ جاري تحميل {action} بجودة {quality_or_key}...")

    filename = None

    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", f"{format_code}/best", "-o", "video.%(ext)s", url]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        if action == "video":
            for ext in ["mp4", "mkv", "webm", "mpg", "mov"]:
                if os.path.exists(f"video.{ext}"):
                    filename = f"video.{ext}"
                    break

        if filename and os.path.exists(filename):
            with open(filename, "rb") as f:
                try:
                    if action == "audio":
                        await query.message.reply_audio(f)
                        funny_msg = "🎧 هاي الموسيقى لك! بس لا ترقص كتير 😄"
                    else:
                        await query.message.reply_video(f)
                        funny_msg = "📺 الفيديو وصل! جهز نفسك للمشاهدة 🍿"
                    await query.message.reply_text(funny_msg)
                except Exception as e:
                    await query.message.reply_text(f"⚠️ حدث خطأ أثناء إرسال الملف: {e}")
            os.remove(filename)
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
            except Exception:
                pass
            url_store.pop(key, None)
            try:
                await query.delete_message()
            except Exception:
                pass
        else:
            await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
    else:
        if "Requested format is not available" in result.stderr:
            await query.message.reply_text(
                "⚠️ الجودة المطلوبة غير متوفرة لهذا الفيديو، سأحاول تحميل أفضل جودة متاحة بدون تحديد."
            )
            fallback_cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best", "-o", "video.%(ext)s", url]
            fallback_result = subprocess.run(fallback_cmd, capture_output=True, text=True)
            if fallback_result.returncode == 0:
                for ext in ["mp4", "mkv", "webm", "mpg", "mov"]:
                    if os.path.exists(f"video.{ext}"):
                        filename = f"video.{ext}"
                        break
                if filename and os.path.exists(filename):
                    with open(filename, "rb") as f:
                        await query.message.reply_video(f)
                    os.remove(filename)
                    try:
                        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
                    except Exception:
                        pass
                    url_store.pop(key, None)
                    try:
                        await query.delete_message()
                    except Exception:
                        pass
                    return
                else:
                    await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
                    return
            else:
                await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{fallback_result.stderr}")
                return
        else:
            await query.message.reply_text(f"🚫 فشل التنزيل.\n📄 التفاصيل:\n{result.stderr}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_greetings))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
