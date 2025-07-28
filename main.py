import os
import subprocess
import logging
import re
import json
from datetime import datetime, timezone
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 337597459

USERS_FILE = "users.txt"
SUBSCRIPTIONS_FILE = "subscriptions.json"
REQUESTS_FILE = "subscription_requests.txt"

if not BOT_TOKEN:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN في .env")


def is_subscribed(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return False
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    return str(user_id) in data


def activate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        data = {}
    else:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            data = json.load(f)
    data[str(user_id)] = {"active": True, "date": datetime.now(timezone.utc).isoformat()}
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)


def remove_subscription(user_id):
    if os.path.exists(SUBSCRIPTIONS_FILE):
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            data = json.load(f)
        if str(user_id) in data:
            del data[str(user_id)]
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(data, f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_subscribed(user.id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
        ])
        await update.message.reply_text("🔒 لا يمكنك استخدام البوت بدون اشتراك.\nاشترك الآن للاستمرار.", reply_markup=keyboard)
        return

    await update.message.reply_text("🤖 أهلاً بك! يمكنك الآن إرسال رابط فيديو أو أمر /ask للذكاء الصناعي.")


async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username or 'NO_USERNAME'}|{datetime.now(timezone.utc)}\n")

    await update.callback_query.edit_message_text(
        "💳 للاشتراك:\n"
        "أرسل 2 دينار عبر أورنج كاش إلى الرقم:\n"
        "📱 0781200500\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_sub|{user.id}")
        ]
    ])
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📥 طلب اشتراك جديد من @{user.username or user.id}", reply_markup=keyboard)
    await update.callback_query.answer("✅ تم إرسال الطلب.")


async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح!")
    await query.edit_message_text("✅ تم التفعيل.")


async def cancel_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض الاشتراك.")
    await query.edit_message_text("❌ تم إلغاء الاشتراك.")


async def list_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        await update.message.reply_text("📭 لا يوجد مشتركين بعد.")
        return

    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)

    buttons = []
    for user_id in data:
        user_info = f"👤 {user_id}"
        buttons.append([
            InlineKeyboardButton(user_info, callback_data="noop"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"remove_sub|{user_id}")
        ])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("📋 قائمة المشتركين:", reply_markup=reply_markup)


async def remove_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    remove_subscription(user_id)
    await query.answer("❌ تم إلغاء اشتراك المستخدم.")
    await query.edit_message_text(f"🚫 تم إلغاء اشتراك المستخدم {user_id}.")


if __name__ == "__main__":
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribers", list_subscribers))
    application.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    application.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
    application.add_handler(CallbackQueryHandler(cancel_subscription, pattern="^cancel_sub\\|"))
    application.add_handler(CallbackQueryHandler(remove_sub_callback, pattern="^remove_sub\\|"))

    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
