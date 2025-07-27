import os
import subprocess
import logging
import re
import json
import datetime
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)
from asyncio import create_task, sleep

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
USAGE_FILE = "usage.json"
PAID_USERS_FILE = "paid_users.json"
PENDING_SUBS_FILE = "pending_subs.json"

MAX_VIDEO_DOWNLOADS_FREE = 3
MAX_AI_REQUESTS_FREE = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

# --- ملفات JSON ---
def load_json(file_path):
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f)

# --- اشتراك مدفوع ---
def load_paid_users():
    return load_json(PAID_USERS_FILE)

def save_paid_user(user_id):
    users = load_paid_users()
    expiry_date = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    users[str(user_id)] = expiry_date
    save_json(PAID_USERS_FILE, users)

def remove_paid_user(user_id):
    users = load_paid_users()
    users.pop(str(user_id), None)
    save_json(PAID_USERS_FILE, users)

def is_paid_user(user_id):
    users = load_paid_users()
    expiry_str = users.get(str(user_id))
    if not expiry_str:
        return False
    expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%d")
    return datetime.datetime.utcnow() < expiry

# --- حفظ المستخدمين ---
def save_user(user_id):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            f.write("")
    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")

# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id)
    buttons = [
        [InlineKeyboardButton("💳 اشترك الآن", callback_data="subscribe_request")]
    ]
    await update.message.reply_text(
        "👋 مرحبًا بك في البوت!\n\n🔹 يمكنك استخدام البوت بعد الاشتراك.\n🔸 اضغط الزر أدناه للاشتراك:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# --- زر الاشتراك ---
async def handle_subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.message.reply_text("📸 أرسل صورة التحويل لإتمام الاشتراك.")
    context.user_data["awaiting_payment_proof"] = True
    await query.answer()

# --- استلام صورة التحويل ---
async def handle_payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.user_data.get("awaiting_payment_proof"):
        return

    context.user_data["awaiting_payment_proof"] = False
    photo = update.message.photo[-1]
    file_id = photo.file_id

    pending = load_json(PENDING_SUBS_FILE)
    pending[str(user.id)] = file_id
    save_json(PENDING_SUBS_FILE, pending)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_payment|{user.id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"reject_payment|{user.id}")
        ]
    ])
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=file_id,
        caption=f"🧾 طلب اشتراك جديد:\n👤 {user.full_name} (@{user.username})\n🆔 {user.id}",
        reply_markup=buttons
    )
    await update.message.reply_text("📨 تم إرسال صورة التحويل للأدمن بانتظار التأكيد.")

# --- تأكيد أو رفض من الأدمن ---
async def handle_admin_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    decision, uid = query.data.split("|")
    uid = int(uid)
    pending = load_json(PENDING_SUBS_FILE)

    if decision == "confirm_payment":
        save_paid_user(uid)
        await context.bot.send_message(chat_id=uid, text="✅ تم تأكيد اشتراكك. شكراً لك! الاشتراك صالح لمدة 30 يومًا.")
        await query.edit_message_caption(query.message.caption + "\n✅ تم التأكيد.")
    elif decision == "reject_payment":
        await context.bot.send_message(chat_id=uid, text="❌ تم رفض صورة التحويل. الرجاء التأكد والمحاولة مجددًا.")
        await query.edit_message_caption(query.message.caption + "\n❌ تم الرفض.")

    pending.pop(str(uid), None)
    save_json(PENDING_SUBS_FILE, pending)
    await query.answer("تمت المعالجة.")

# --- قائمة المشتركين ---
async def list_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر مخصص للأدمن فقط.")
        return
    users = load_paid_users()
    if not users:
        await update.message.reply_text("⚠️ لا يوجد مشتركين مدفوعين.")
        return

    buttons = [
        [InlineKeyboardButton(f"❌ إلغاء {uid}", callback_data=f"remove_subscriber|{uid}")]
        for uid in users
    ]
    await update.message.reply_text(
        f"👑 قائمة المشتركين المدفوعين (العدد: {len(users)}):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# --- إزالة مشترك ---
async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.data.split("|")[1]
    remove_paid_user(uid)
    await context.bot.send_message(chat_id=uid, text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    await query.edit_message_text(f"❌ تم إلغاء اشتراك المستخدم {uid}.")
    await query.answer("تمت المعالجة.")

# --- لوحة الأدمن ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر مخصص للأدمن فقط.")
        return

    total_users = len(open(USERS_FILE).read().splitlines()) if os.path.exists(USERS_FILE) else 0
    total_paid = len(load_paid_users())

    buttons = [
        [InlineKeyboardButton("📋 عرض المشتركين", callback_data="show_subscribers")],
    ]
    await update.message.reply_text(
        f"📊 لوحة التحكم:\n👥 المستخدمين: {total_users}\n💳 المشتركين: {total_paid}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# --- تحميل الفيديو ---
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_paid_user(user_id):
        await update.message.reply_text("🚫 هذه الميزة متاحة فقط للمشتركين المدفوعين.")
        return

    if not context.args:
        await update.message.reply_text("❗️استخدم الأمر بهذا الشكل:\n/download [رابط يوتيوب]")
        return

    url = context.args[0]
    await update.message.reply_text("⏬ يتم تحميل الفيديو، يرجى الانتظار...")

    try:
        output_file = f"video_{user_id}.mp4"
        cmd = [
            "yt-dlp",
            "-f", "best[ext=mp4]",
            "-o", output_file,
            url
        ]
        subprocess.run(cmd, check=True)

        await update.message.reply_video(video=InputFile(output_file))
        os.remove(output_file)

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء تحميل الفيديو:\n{e}")

# --- مهمة دورية لفحص الاشتراكات ---
async def check_expired_subscriptions(app):
    while True:
        users = load_paid_users()
        now = datetime.datetime.utcnow()
        for uid, expiry in list(users.items()):
            expiry_date = datetime.datetime.strptime(expiry, "%Y-%m-%d")
            if now >= expiry_date:
                remove_paid_user(uid)
                try:
                    await app.bot.send_message(chat_id=int(uid), text="❌ انتهى اشتراكك. يمكنك التجديد بالضغط على زر الاشتراك.")
                except:
                    pass
            elif (expiry_date - now).days == 1:
                try:
                    await app.bot.send_message(chat_id=int(uid), text="⚠️ تذكير: تبقى يوم واحد على انتهاء اشتراكك.")
                except:
                    pass
        await sleep(86400)

# --- إضافة إلى التطبيق ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("download", download_video))
    app.add_handler(CallbackQueryHandler(handle_subscribe_request, pattern="^subscribe_request$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_photo))
    app.add_handler(CallbackQueryHandler(handle_admin_payment_decision, pattern="^(confirm_payment|reject_payment)\\|"))
    app.add_handler(CommandHandler("list_subscribers", list_subscribers))
    app.add_handler(CallbackQueryHandler(remove_subscriber, pattern="^remove_subscriber\\|"))
    app.add_handler(CallbackQueryHandler(list_subscribers, pattern="^show_subscribers$"))

    create_task(check_expired_subscriptions(app))

    import socket
    PORT = int(os.environ.get("PORT", 8443))
    HOSTNAME = os.environ.get("HOSTNAME")  # مثل: telegram-bot.onrender.com
    if HOSTNAME:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"https://{HOSTNAME}/{BOT_TOKEN}"
        )
    else:
        app.run_polling()
