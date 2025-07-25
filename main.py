import os import subprocess import logging import re import openai from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated from telegram.ext import ( ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters, ChatMemberHandler, )

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN") OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME") COOKIES_FILE = "cookies.txt" CHANNEL_USERNAME = "@gsm4x"

openai.api_key = OPENAI_API_KEY

if not BOT_TOKEN: raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

url_store = {}

def is_valid_url(text): pattern = re.compile(r"^(https?://)?(www.)?(youtube.com|youtu.be|tiktok.com|instagram.com|facebook.com|fb.watch)/.+") return bool(pattern.match(text))

quality_map = { "720": "best[height<=720][ext=mp4]", "480": "best[height<=480][ext=mp4]", "360": "best[height<=360][ext=mp4]", }

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool: try: member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id) return member.status not in ("left", "kicked") except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "👋 أهلاً! أرسل رابط فيديو أو اسأل سؤالاً وسأساعدك 🤖\n" "📥 يدعم يوتيوب، تيك توك، إنستا، فيسبوك.\n" "🔒 لتنزيل المحمي، استخدم cookies.txt" )

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE): member: ChatMemberUpdated = update.chat_member if member.new_chat_member.status == "member": user = member.new_chat_member.user await context.bot.send_message( chat_id=update.chat_member.chat.id, text=( f"👋 أهلًا وسهلًا بك يا {user.first_name} 💫\n" "🛠️ صيانة واستشارات وعروض ولا أحلى!\n" "📥 أرسل رابط لتحميل فيديو أو اسأل عن خدمات الجوال." ), )

async def ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE): if is_valid_url(update.message.text): return await download(update, context)

if not await check_subscription(update.message.from_user.id, context):
    await update.message.reply_text(f"⚠️ يجب الاشتراك في القناة {CHANNEL_USERNAME} أولاً.")
    return

prompt = update.message.text.strip()
try:
    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    reply = res.choices[0].message.content
    await update.message.reply_text(reply)
except Exception as e:
    await update.message.reply_text(f"⚠️ حصل خطأ أثناء الرد الذكي: {e}")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE): if not update.message or not update.message.text: return

text = update.message.text.strip()
key = str(update.message.message_id)
url_store[key] = text

keyboard = [
    [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
    [
        InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
        InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
        InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}"),
    ],
    [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
]
await update.message.reply_text("📥 اختر نوع التنزيل والجودة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer()

try:
    action, quality_or_key, maybe_key = query.data.split("|")
    if action == "cancel":
        key = quality_or_key
    else:
        quality = quality_or_key
        key = maybe_key
except:
    return await query.message.reply_text("⚠️ خطأ في المعالجة.")

if action == "cancel":
    await query.edit_message_text("❌ تم إلغاء العملية.")
    url_store.pop(key, None)
    return

url = url_store.get(key)
if not url:
    return await query.message.reply_text("⚠️ لم أجد الرابط.")

await query.edit_message_text(f"⏳ تحميل {action} بجودة {quality_or_key}...")
filename = "audio.mp3" if action == "audio" else "video.mp4"

cmd = [
    "yt-dlp", "--cookies", COOKIES_FILE,
    "-x" if action == "audio" else "-f",
    "best" if action == "audio" else quality_map.get(quality, "best"),
    "-o", filename, url
]
subprocess.run(cmd, capture_output=True)

if os.path.exists(filename):
    with open(filename, "rb") as f:
        if action == "audio":
            await query.message.reply_audio(f)
        else:
            await query.message.reply_video(f)
    os.remove(filename)
    await query.delete_message()
    url_store.pop(key, None)
else:
    await query.message.reply_text("🚫 فشل التنزيل أو الملف غير موجود.")

if name == 'main': port = int(os.getenv("PORT", "8443")) app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_assistant))

app.run_webhook(
    listen="0.0.0.0",
    port=port,
    url_path=BOT_TOKEN,
    webhook_url=f"https://{RENDER_HOST}/{BOT_TOKEN}"
)

