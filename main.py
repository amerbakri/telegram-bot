import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          CallbackContext, CallbackQueryHandler)
import yt_dlp
import datetime
from uuid import uuid4

# === إعدادات ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
PORT = int(os.environ.get("PORT", 8443))
HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

logging.basicConfig(level=logging.INFO)

# === الملفات ===
SUBSCRIBERS_FILE = "subscribers.txt"
REQUESTS_FILE = "subscription_requests.txt"
LIMIT = 3
AI_LIMIT = 5

user_usage = {}
user_ai_usage = {}

# === الوظائف ===

def save_subscriber(user_id, username):
    with open(SUBSCRIBERS_FILE, "a") as f:
        f.write(f"{user_id}|{username}|{datetime.datetime.utcnow()}\n")

def get_subscribers():
    if not os.path.exists(SUBSCRIBERS_FILE):
        return []
    with open(SUBSCRIBERS_FILE) as f:
        return [line.strip().split("|") for line in f if line.strip()]

def is_subscriber(user_id):
    return any(str(user_id) == sub[0] for sub in get_subscribers())

def reset_usage(user_id):
    user_usage[user_id] = 0
    user_ai_usage[user_id] = 0

# === تحميل الفيديوهات ===

def download_video(url):
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'cookiefile': 'cookies.txt',
    }
    os.makedirs("downloads", exist_ok=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename

# === الأحداث ===

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("أرسل رابط فيديو للتحميل أو اكتب أي شيء لبدء المحادثة مع الذكاء الاصطناعي.")

async def handle_video(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id

    if not is_subscriber(uid) and user_usage.get(uid, 0) >= LIMIT:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("اشترك الآن", callback_data="subscribe")]])
        await update.message.reply_text("وصلت للحد المسموح، اشترك لمتابعة الاستخدام.", reply_markup=keyboard)
        return

    url = update.message.text.strip()
    try:
        filename = download_video(url)
        with open(filename, 'rb') as f:
            await update.message.reply_video(video=InputFile(f))
        user_usage[uid] = user_usage.get(uid, 0) + 1
    except Exception as e:
        await update.message.reply_text(f"فشل التحميل: {e}")

async def handle_ai(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_subscriber(uid) and user_ai_usage.get(uid, 0) >= AI_LIMIT:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("اشترك الآن", callback_data="subscribe")]])
        await update.message.reply_text("تم استهلاك الحد المسموح من الأسئلة للذكاء الصناعي، اشترك للاستمرار.", reply_markup=keyboard)
        return

    question = update.message.text
    # رد وهمي مؤقت بدلاً من GPT (يجب ربط GPT لاحقًا)
    await update.message.reply_text(f"🤖 رد الذكاء الصناعي على: {question}")
    user_ai_usage[uid] = user_ai_usage.get(uid, 0) + 1

async def handle_subscription_request(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("📸 أرسل الآن صورة إيصال الدفع لتأكيد الاشتراك.")

async def handle_photo(update: Update, context: CallbackContext):
    user = update.effective_user
    if is_subscriber(user.id): return

    photo_file = await update.message.photo[-1].get_file()
    file_id = str(uuid4()) + ".jpg"
    await photo_file.download_to_drive(file_id)

    caption = f"📥 طلب اشتراك جديد\nالاسم: {user.full_name}\nالايدي: {user.id}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد", callback_data=f"approve|{user.id}|{user.username}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"reject|{user.id}")]
    ])
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=open(file_id, 'rb'), caption=caption, reply_markup=keyboard)

async def admin_buttons(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("approve"):
        _, uid, username = data.split("|")
        save_subscriber(uid, username)
        await context.bot.send_message(chat_id=int(uid), text="✅ تم تفعيل اشتراكك بنجاح.")
        await query.edit_message_caption(caption="✅ تم التفعيل.")
    elif data.startswith("reject"):
        _, uid = data.split("|")
        await context.bot.send_message(chat_id=int(uid), text="❌ تم رفض اشتراكك. يرجى التواصل مع الإدارة.")
        await query.edit_message_caption(caption="❌ تم الرفض.")

async def admin_panel(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 المشتركين", callback_data="list_subs")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📣 إرسال إعلان", callback_data="broadcast")]
    ])
    await update.message.reply_text("لوحة تحكم الأدمن", reply_markup=keyboard)

async def admin_actions(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == "list_subs":
        subs = get_subscribers()
        if not subs:
            await query.edit_message_text("لا يوجد مشتركين.")
            return
        text = "👤 قائمة المشتركين:\n"
        for sub in subs:
            uid, uname, _ = sub
            text += f"{uname} - {uid} /cancel_{uid}\n"
        await query.edit_message_text(text)

    elif query.data == "stats":
        subs = get_subscribers()
        await query.edit_message_text(f"📊 عدد المشتركين: {len(subs)}")

    elif query.data == "broadcast":
        context.user_data['broadcast'] = True
        await query.edit_message_text("📢 أرسل الرسالة التي تريد نشرها لجميع المشتركين (نص أو صورة أو فيديو).")

async def handle_broadcast(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.user_data.get('broadcast'):
        return
    context.user_data['broadcast'] = False
    subs = get_subscribers()
    for sub in subs:
        uid = int(sub[0])
        try:
            if update.message.text:
                await context.bot.send_message(chat_id=uid, text=update.message.text)
            elif update.message.photo:
                await context.bot.send_photo(chat_id=uid, photo=update.message.photo[-1].file_id)
            elif update.message.video:
                await context.bot.send_video(chat_id=uid, video=update.message.video.file_id)
        except:
            continue
    await update.message.reply_text("✅ تم إرسال الإعلان.")

# === الإعداد ===
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_panel))
application.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe$"))
application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(approve|reject)\|"))
application.add_handler(CallbackQueryHandler(admin_actions))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_video))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai))
application.add_handler(MessageHandler(filters.ALL, handle_broadcast))

application.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"https://{HOSTNAME}/{BOT_TOKEN}"
)
