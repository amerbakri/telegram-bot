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
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8443"))
HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
COOKIES_FILE = "cookies.txt"

url_store = {}

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
    await update.message.reply_text("👋 أرسل رابط فيديو من YouTube أو TikTok لتحميله.")


async def download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.message.from_user.id

    # أمر /broadcast
    if text == "/broadcast" and user_id == ADMIN_ID:
        context.user_data["broadcast_mode"] = True
        await update.message.reply_text("📢 أرسل الرسالة (نص / صورة / فيديو / صوت) الآن لإرسالها للجميع.")
        return

    if context.user_data.get("broadcast_mode") and user_id == ADMIN_ID:
        context.user_data["broadcast_mode"] = False
        with open("users.txt", "r") as f:
            users = f.read().splitlines()

        for uid in users:
            try:
                if update.message.text:
                    await context.bot.send_message(chat_id=int(uid), text=update.message.text)
                elif update.message.photo:
                    await context.bot.send_photo(chat_id=int(uid), photo=update.message.photo[-1].file_id)
                elif update.message.video:
                    await context.bot.send_video(chat_id=int(uid), video=update.message.video.file_id)
                elif update.message.audio:
                    await context.bot.send_audio(chat_id=int(uid), audio=update.message.audio.file_id)
            except:
                continue
        await update.message.reply_text("✅ تم إرسال الرسالة بنجاح.")
        return

    # تخزين المستخدم
    with open("users.txt", "a+") as f:
        f.seek(0)
        users = f.read().splitlines()
        if str(user_id) not in users:
            f.write(f"{user_id}\n")

    if not is_valid_url(text):
        await update.message.reply_text("⚠️ الرجاء إرسال رابط فيديو صالح.")
        return

    key = str(update.message.message_id)
    url_store[key] = text

    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}"),
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")],
    ]

    sent = await update.message.reply_text(
        "📥 اختر نوع التحميل:", reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # حفظ ID رسالة الخيارات لإزالتها لاحقًا
    context.user_data[f"menu_msg_{key}"] = sent.message_id


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except ValueError:
        await query.message.reply_text("⚠️ حدث خطأ.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⛔ الرابط غير صالح.")
        return

    await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    filename = "audio.mp3" if action == "audio" else None

    cmd = [
        "yt-dlp",
        "--cookies",
        COOKIES_FILE,
        "-x" if action == "audio" else "-f",
        "bestaudio" if action == "audio" else quality_map.get(quality, "best"),
        "-o",
        "audio.%(ext)s" if action == "audio" else "video.%(ext)s",
        url,
    ]

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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
        await query.message.reply_text("🚫 لم أستطع تحميل الملف.")

    # حذف الرسالة الأصلية (الرابط) إن وجدت
    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
    except:
        pass

    # حذف رسالة "جاري التحميل..."
    try:
        menu_msg_id = context.user_data.get(f"menu_msg_{key}")
        if menu_msg_id:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=menu_msg_id)
    except:
        pass

    url_store.pop(key, None)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Webhook للرندر
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{HOSTNAME}/{BOT_TOKEN}",
    )


if __name__ == "__main__":
    main()
