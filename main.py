import os import subprocess import logging import re import openai from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated from telegram.ext import ( ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters, ChatMemberHandler, )

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN") OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") COOKIES_FILE = "cookies.txt" CHANNEL_USERNAME = "@gsm4x"

openai.api_key = OPENAI_API_KEY

if not BOT_TOKEN: raise RuntimeError("❌ BOT_TOKEN not set in environment variables.")

url_store = {}

def is_valid_url(text): pattern = re.compile( r"^(https?://)?(www.)?(youtube.com|youtu.be|tiktok.com|instagram.com|facebook.com|fb.watch)/.+" ) return bool(pattern.match(text))

quality_map = { "720": "best[height<=720][ext=mp4]", "480": "best[height<=480][ext=mp4]", "360": "best[height<=360][ext=mp4]", }

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool: try: member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id) return member.status not in ("left", "kicked") except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب، تيك توك، إنستا أو فيسبوك لأحمله لك 🎥\n" "🔧 ويمكنك طرح أي سؤال متعلق بالصيانة أيضًا!" )

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE): member: ChatMemberUpdated = update.chat_member if member.new_chat_member.status == "member": user = member.new_chat_member.user await context.bot.send_message( chat_id=update.chat_member.chat.id, text=( f"👋 أهلًا وسهلًا بك يا {user.first_name} 💫\n" "🛠️ صيانة واستشارات وعروض ولا أحلى!\n" "📥 أرسل رابط لتحميل الفيديو أو اسأل عن أي شيء في الصيانة." ), )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE): if not update.message or not update.message.text: return

text = update.message.text.strip()
user_id = update.message.from_user.id

if not await check_subscription(user_id, context):
    await update.message.reply_text(f"⚠️ يجب عليك الاشتراك في القناة {CHANNEL_USERNAME} لاستخدام البوت.")
    return

if not is_valid_url(text):
    if any(w in text.lower() for w in ["سلام", "مرحبا"]):
        await update.message.reply_text("👋 وعليكم السلام ورحمة الله! كيف يمكنني مساعدتك؟")
        return
    elif text.endswith("?"):
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "أنت مساعد ذكي وخبير في الصيانة وخدمات الموبايلات."},
                    {"role": "user", "content": text},
                ]
            )
            await update.message.reply_text(response.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في الرد الذكي: {e}")
        return
    else:
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

await update.message.reply_text("📥 اختر الجودة أو نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer()

try:
    action, quality, key = query.data.split("|")
except:
    await query.message.reply_text("❌ خطأ في المعالجة.")
    return

if action == "cancel":
    await query.edit_message_text("❌ تم إلغاء العملية.")
    url_store.pop(key, None)
    return

url = url_store.get(key)
if not url:
    await query.message.reply_text("⚠️ انتهت صلاحية الرابط. أرسل مجددًا.")
    return

await query.edit_message_text("⏳ جاري التنزيل...")

cmd = [
    "yt-dlp", "--cookies", COOKIES_FILE,
    "-o", "output.%(ext)s"
]

if action == "audio":
    cmd += ["-x", "--audio-format", "mp3"]
else:
    format_code = quality_map.get(quality, "best")
    cmd += ["-f", format_code]

cmd.append(url)
result = subprocess.run(cmd, capture_output=True, text=True)

file = "output.mp3" if action == "audio" else "output.mp4"

for ext in ["mp4", "mkv", "webm", "mov"]:
    if os.path.exists(f"output.{ext}"):
        file = f"output.{ext}"
        break

if os.path.exists(file):
    with open(file, "rb") as f:
        if action == "audio":
            await query.message.reply_audio(f)
        else:
            await query.message.reply_video(f)
    os.remove(file)
else:
    await query.message.reply_text("❌ فشل التنزيل. تأكد من أن الرابط صحيح.")

url_store.pop(key, None)

if name == 'main': port = int(os.getenv("PORT", "8443")) hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

app.run_webhook(
    listen="0.0.0.0",
    port=port,
    url_path=BOT_TOKEN,
    webhook_url=f"https://{hostname}/{BOT_TOKEN}"
)

