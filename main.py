import os import subprocess import logging import re import openai from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated from telegram.ext import ( ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters, ChatMemberHandler, )

إعداد السجلات

logging.basicConfig(level=logging.INFO)

جلب المتغيرات من البيئة

BOT_TOKEN = os.getenv("BOT_TOKEN") OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) COOKIES_FILE = "cookies.txt" PORT = int(os.getenv("PORT", "8443")) HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

if not BOT_TOKEN or not OPENAI_API_KEY: raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY و ADMIN_ID في إعدادات البيئة.")

إعداد مفتاح OpenAI

openai.api_key = OPENAI_API_KEY

تخزين مؤقت للروابط

url_store = {}

التحقق من صحة الرابط

def is_valid_url(text): pattern = re.compile( r"^(https?://)?(www.)?(youtube.com|youtu.be|tiktok.com|instagram.com|facebook.com|fb.watch)/.+" ) return bool(pattern.match(text))

quality_map = { "720": "best[height<=720][ext=mp4]", "480": "best[height<=480][ext=mp4]", "360": "best[height<=360][ext=mp4]", }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = update.effective_user.id await update.message.reply_text( f"👋 أهلاً بك! 🆔 رقم الـ User ID تبعك هو: {user_id}\n" "🎥 أرسل رابط فيديو لتحميله أو اسأل سؤال عام." )

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE): member: ChatMemberUpdated = update.chat_member if member.new_chat_member.status == "member": user = member.new_chat_member.user await context.bot.send_message( chat_id=update.chat_member.chat.id, text=( f"👋 أهلًا وسهلًا بك يا {user.first_name} 💫\n" "📥 أرسل رابط لتحميل الفيديو أو اسأل أي سؤال." ), )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE): if not update.message or not update.message.text: return

user_id = update.effective_user.id
text = update.message.text.strip()

# رد ذكي باستخدام OpenAI إذا لم يكن الرابط
if not is_valid_url(text):
    if re.search(r"(السلام|مرحبا|أهلا|هلا|الو)", text, re.IGNORECASE):
        await update.message.reply_text("👋 وعليكم السلام! كيف أقدر أساعدك؟")
        return
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

await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer()

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
try:
    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
except:
    pass

if name == "main": application = ApplicationBuilder().token(BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

application.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"https://{HOSTNAME}/{BOT_TOKEN}"
)

