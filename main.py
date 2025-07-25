import os
import subprocess
import logging
import re
import openai

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

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
COOKIES_FILE = "cookies.txt"
CHANNEL_USERNAME = "@gsm4x"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("â‌Œ BOT_TOKEN not set in environment variables.")

openai.api_key = OPENAI_API_KEY
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
        "ًں‘‹ ط£ظ‡ظ„ط§ظ‹! ط£ط±ط³ظ„ ظ„ظٹ ط±ط§ط¨ط· ظپظٹط¯ظٹظˆ ظ…ظ† ظٹظˆطھظٹظˆط¨طŒ طھظٹظƒ طھظˆظƒطŒ ط¥ظ†ط³طھط§ ط£ظˆ ظپظٹط³ط¨ظˆظƒ ظ„ط£ط­ظ…ظ„ظ‡ ظ„ظƒ ًںژ¥\n\n"
        "ظ…ظ„ط§ط­ط¸ط©: ظ„طھط­ظ…ظٹظ„ ظپظٹط¯ظٹظˆظ‡ط§طھ ظ…ط­ظ…ظٹط© ظ…ظ† ظٹظˆطھظٹظˆط¨طŒ طھط£ظƒط¯ ظ…ظ† ط±ظپط¹ ظ…ظ„ظپ ط§ظ„ظƒظˆظƒظٹط² 'cookies.txt' ظ…ط¹ ط§ظ„ط¨ظˆطھ."
    )

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member: ChatMemberUpdated = update.chat_member
    if member.new_chat_member.status == "member":
        user = member.new_chat_member.user
        await context.bot.send_message(
            chat_id=update.chat_member.chat.id,
            text=(
                f"ًں‘‹ ط£ظ‡ظ„ظ‹ط§ ظˆط³ظ‡ظ„ظ‹ط§ ط¨ظƒ ظٹط§ {user.first_name} ًں’«\n"
                "ًں› ï¸ڈ طµظٹط§ظ†ط© ظˆط§ط³طھط´ط§ط±ط§طھ ظˆط¹ط±ظˆط¶ ظˆظ„ط§ ط£ط­ظ„ظ‰!\n"
                "ًں“¥ ط£ط±ط³ظ„ ط±ط§ط¨ط· ظ„طھط­ظ…ظٹظ„ ط§ظ„ظپظٹط¯ظٹظˆ ط£ظˆ ط§ط³ط£ظ„ ط¹ظ† ط£ظٹ ط´ظٹط، ط¨ط®طµظˆطµ ط§ظ„ط®ط¯ظ…ط©."
            ),
        )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ("group", "supergroup"):
        if not update.message.text or not is_valid_url(update.message.text.strip()):
            return

    if not update.message or not update.message.text:
        return

    user_id = update.message.from_user.id
    if not await check_subscription(user_id, context):
        await update.message.reply_text(
            f"âڑ ï¸ڈ ط¹ط°ط±ط§ظ‹طŒ ظٹط¬ط¨ ط¹ظ„ظٹظƒ ط§ظ„ط§ط´طھط±ط§ظƒ ظپظٹ ط§ظ„ظ‚ظ†ط§ط© {CHANNEL_USERNAME} ظ„ط§ط³طھط®ط¯ط§ظ… ظ‡ط°ط§ ط§ظ„ط¨ظˆطھ."
        )
        return

    text = update.message.text.strip()

    if not is_valid_url(text):
        if any(greet in text.lower() for greet in ["ط³ظ„ط§ظ…", "ط§ظ„ط³ظ„ط§ظ… ط¹ظ„ظٹظƒظ…", "ظ…ط±ط­ط¨ط§", "ط§ظ‡ظ„ط§"]):
            await update.message.reply_text("ًں‘‹ ظˆط¹ظ„ظٹظƒظ… ط§ظ„ط³ظ„ط§ظ…! ظƒظٹظپ ظپظٹظ†ظٹ ط£ط³ط§ط¹ط¯ظƒطں")
        elif OPENAI_API_KEY:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}],
            )
            await update.message.reply_text(response["choices"][0]["message"]["content"])
        else:
            await update.message.reply_text("âڑ ï¸ڈ ظٹط±ط¬ظ‰ ط¥ط±ط³ط§ظ„ ط±ط§ط¨ط· ظپظٹط¯ظٹظˆ طµط§ظ„ط­ ظ…ظ† ظٹظˆطھظٹظˆط¨طŒ طھظٹظƒ طھظˆظƒطŒ ط¥ظ†ط³طھط§ ط£ظˆ ظپظٹط³ط¨ظˆظƒ ظپظ‚ط·.")
        return

    key = str(update.message.message_id)
    url_store[key] = text

    keyboard = [
        [InlineKeyboardButton("ًںژµ طµظˆطھ ظپظ‚ط·", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("ًںژ¥ ظپظٹط¯ظٹظˆ 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("ًںژ¥ ظپظٹط¯ظٹظˆ 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("ًںژ¥ ظپظٹط¯ظٹظˆ 360p", callback_data=f"video|360|{key}"),
        ],
        [InlineKeyboardButton("â‌Œ ط¥ظ„ط؛ط§ط،", callback_data=f"cancel|{key}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("ًں“¥ ط§ط®طھط± ظ†ظˆط¹ ط§ظ„طھظ†ط²ظٹظ„ ظˆط§ظ„ط¬ظˆط¯ط© ط£ظˆ ط¥ظ„ط؛ط§ط، ط§ظ„ط¹ظ…ظ„ظٹط©:", reply_markup=reply_markup)

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
        await query.message.reply_text("âڑ ï¸ڈ ط­ط¯ط« ط®ط·ط£ ظپظٹ ط§ط®طھظٹط§ط± ط§ظ„طھظ†ط²ظٹظ„.")
        return

    if action == "cancel":
        await query.edit_message_text("â‌Œ طھظ… ط¥ظ„ط؛ط§ط، ط§ظ„ط¹ظ…ظ„ظٹط© ط¨ظ†ط¬ط§ط­.")
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
        except Exception:
            pass
        url_store.pop(key, None)
        return

    if not os.path.exists(COOKIES_FILE):
        await query.message.reply_text("âڑ ï¸ڈ ظ…ظ„ظپ ط§ظ„ظƒظˆظƒظٹط² 'cookies.txt' ط؛ظٹط± ظ…ظˆط¬ظˆط¯. ظٹط±ط¬ظ‰ ط±ظپط¹ظ‡.")
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("âڑ ï¸ڈ ط§ظ„ط±ط§ط¨ط· ط؛ظٹط± ظ…ظˆط¬ظˆط¯ ط£ظˆ ط§ظ†طھظ‡طھ طµظ„ط§ط­ظٹط© ط§ظ„ط¹ظ…ظ„ظٹط©.")
        return

    await query.edit_message_text(text=f"âڈ³ ط¬ط§ط±ظٹ طھط­ظ…ظٹظ„ {action} ط¨ط¬ظˆط¯ط© {quality_or_key}...")

    filename = None

    if action == "audio":
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url
        ]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", f"{format_code}/best", "-o", "video.%(ext)s", url
        ]

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
                    else:
                        await query.message.reply_video(f)
                    await query.message.reply_text("âœ… طھظ… ط¥ط±ط³ط§ظ„ ط§ظ„ظ…ظ„ظپ ط¨ظ†ط¬ط§ط­.")
                except Exception as e:
                    await query.message.reply_text(f"âڑ ï¸ڈ ط®ط·ط£ ط£ط«ظ†ط§ط، ط§ظ„ط¥ط±ط³ط§ظ„: {e}")
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
            await query.message.reply_text("ًںڑ« ظ„ظ… ظٹطھظ… ط§ظ„ط¹ط«ظˆط± ط¹ظ„ظ‰ ط§ظ„ظ…ظ„ظپ.")
    else:
        await query.message.reply_text(f"ًںڑ« ظپط´ظ„ ط§ظ„طھظ†ط²ظٹظ„: {result.stderr}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
            )
