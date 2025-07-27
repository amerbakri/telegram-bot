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

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
USAGE_FILE = "usage.json"
PAID_USERS_FILE = "paid_users.txt"
PENDING_SUBS_FILE = "pending_subs.json"

MAX_VIDEO_DOWNLOADS_FREE = 3
MAX_AI_REQUESTS_FREE = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

# load/save json

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

def load_paid_users():
    return set(open(PAID_USERS_FILE).read().splitlines()) if os.path.exists(PAID_USERS_FILE) else set()

def save_paid_user(user_id):
    with open(PAID_USERS_FILE, "a") as f:
        f.write(f"{user_id}\n")

def remove_paid_user(user_id):
    users = load_paid_users()
    users.discard(str(user_id))
    with open(PAID_USERS_FILE, "w") as f:
        f.write("\n".join(users))

def is_paid_user(user_id):
    return str(user_id) in load_paid_users()

# زر الاشتراك من المستخدم
async def handle_subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.message.reply_text("📸 أرسل صورة التحويل لإتمام الاشتراك.")
    context.user_data["awaiting_payment_proof"] = True
    await query.answer()

# استقبال صورة التحويل
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
        caption=f"🧾 طلب اشتراك جديد من المستخدم:\n👤 {user.full_name} (@{user.username})\n🆔 {user.id}",
        reply_markup=buttons
    )
    await update.message.reply_text("📨 تم إرسال صورة التحويل للأدمن بانتظار التأكيد.")

# تأكيد أو رفض الدفع من الأدمن
async def handle_admin_payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    decision, uid = query.data.split("|")
    uid = int(uid)
    pending = load_json(PENDING_SUBS_FILE)

    if decision == "confirm_payment":
        save_paid_user(uid)
        await context.bot.send_message(chat_id=uid, text="✅ تم تأكيد اشتراكك. شكراً لك!")
        await query.edit_message_caption(query.message.caption + "\n✅ تم التأكيد.")
    elif decision == "reject_payment":
        await context.bot.send_message(chat_id=uid, text="❌ تم رفض صورة التحويل. الرجاء التأكد والمحاولة مجددًا.")
        await query.edit_message_caption(query.message.caption + "\n❌ تم الرفض.")

    pending.pop(str(uid), None)
    save_json(PENDING_SUBS_FILE, pending)
    await query.answer("تمت المعالجة.")

# أمر /list_subscribers
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
    buttons.append([InlineKeyboardButton("➕ اشترك الآن", callback_data="subscribe_request")])
    await update.message.reply_text(
        f"👑 قائمة المشتركين المدفوعين (العدد: {len(users)}):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# إزالة مشترك
async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.data.split("|")[1]
    remove_paid_user(uid)
    await context.bot.send_message(chat_id=uid, text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    await query.edit_message_text(f"❌ تم إلغاء اشتراك المستخدم {uid}.")
    await query.answer("تمت المعالجة.")

# إضافة إلى التطبيق
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CallbackQueryHandler(handle_subscribe_request, pattern="^subscribe_request$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_photo))
    app.add_handler(CallbackQueryHandler(handle_admin_payment_decision, pattern="^(confirm_payment|reject_payment)\|"))
    app.add_handler(CommandHandler("list_subscribers", list_subscribers))
    app.add_handler(CallbackQueryHandler(remove_subscriber, pattern="^remove_subscriber\|"))
    
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
