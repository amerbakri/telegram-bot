import os
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
import logging
import re
import random

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

funny_welcome_msgs = [
    "هاي! بعث لي رابط فيديو، وأنا جاهز أحمله مثل السنافر لما يشوفوا تفاحة 🍎😄",
    "أرسل رابط، وخلي الفيديو ينزل أسرع من برق ⚡️!",
    "هات الرابط بسرعة قبل ما أروح أصنعلي شاي ☕️",
]

funny_choose_msgs = [
    "اختار يا بطل: صوت بس ولا فيديو كامل؟ 🎧🎬",
    "أنا جاهز أنفذ، بس قرر شو بدك! 😎",
    "يلا، اختار قبل ما أروح أكل بطيخة 🍉",
]

funny_cancel_msgs = [
    "أوكي، تم الإلغاء! كنت رح أبدأ أحمل بس بطلنا فكر مرتين 😂",
    "حلو، لو غيرت رأيك أنا هون دائماً مثل ظلك 😅",
]

funny_success_msgs = [
    "ها قد نزلت! شد حالك وصوت عالي 🎉🎶",
    "تم التحميل بنجاح، خلينا نسمع ونشوف! 👀🎵",
    "فيديوك وصل، مثل القهوة الصباحية — لازم تستمتع فيه ☕️😄",
]

funny_error_msgs = [
    "أوف، حصلت مشكلة! بس ما تقلق، رح حاول تاني 😅",
    "الغرباء خانوا الرابط 😢، جرب مرة تانية.",
    "يبدو الفيديو كان مختفي، حاول تبعتلي رابط ثاني.",
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = random.choice(funny_welcome_msgs)
    await update.message.reply_text(
        f"{msg}\n\nملاحظة: لتحميل فيديوهات محمية من يوتيوب، تأكد من رفع ملف الكوكيز 'cookies.txt' مع البوت."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not is_valid_url(text):
        await update.message.reply_text("⚠️ يرجى إرسال رابط فيديو صالح من يوتيوب، تيك توك، إنستا أو فيسبوك فقط.")
        return

    key = str(update.message.message_id)
    url_store[key] = text

    keyboard = [
        [
            InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{key}"),
            InlineKeyboardButton("🎥 فيديو", callback_data=f"video|{key}"),
        ],
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = random.choice(funny_choose_msgs)
    await update.message.reply_text(msg, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, key = query.data.split("|", 1)
    except ValueError:
        await query.message.reply_text("⚠️ حدث خطأ في اختيار التنزيل.")
        return

    if action == "cancel":
        await query.edit_message_text(random.choice(funny_cancel_msgs))
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

    await query.edit_message_text(f"⏳ جاري تحميل {action}...")

    if action == "audio":
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-x",
            "--audio-format", "mp3",
            "-o", "audio.%(ext)s",
            url
        ]
        filename = "audio.mp3"
    else:  # video
        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-f", "best[ext=mp4]/best",
            "-o", "video.%(ext)s",
            url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
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

            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
            except Exception:
                pass

            url_store.pop(key, None)

            try:
                await query.delete_message()
            except Exception:
                pass

            await query.message.reply_text(random.choice(funny_success_msgs))
        else:
            await query.message.reply_text("🚫 لم أتمكن من إيجاد الملف بعد التنزيل.")
    else:
        await query.message.reply_text(random.choice(funny_error_msgs) + f"\n\n📄 التفاصيل:\n{result.stderr}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
