import os
import json
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 337597459
USERS_FILE = "users.txt"
CHATS_FILE = "active_chats.json"

logging.basicConfig(level=logging.INFO)

# متغير لحفظ المحادثات الجارية
def load_chats():
    if not os.path.exists(CHATS_FILE):
        return {}
    with open(CHATS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_chats(chats):
    with open(CHATS_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False)

# تخزين المستخدمين الجدد
def store_user(user):
    entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    with open(USERS_FILE, "r+", encoding="utf-8") as f:
        users = f.read().splitlines()
        if not any(str(user.id) in u for u in users):
            f.write(f"{entry}\n")

# رسالة البداية
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store_user(update.effective_user)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 مراسلة الأدمن", callback_data="contact_admin")]
    ])
    await update.message.reply_text(
        "<b>👋 أهلاً بك!</b>\n\n"
        "يمكنك تحميل الفيديو أو استخدام الذكاء الاصطناعي كالعادة.\n"
        "أو تواصل مع الأدمن لأي استفسار عبر الزر أدناه.",
        reply_markup=kb,
        parse_mode="HTML"
    )

# تفعيل المحادثة مع الأدمن
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if query.data == "contact_admin":
        chats = load_chats()
        chats[str(user_id)] = True
        save_chats(chats)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إنهاء المحادثة مع الأدمن", callback_data="end_admin_chat")]
        ])
        await query.message.reply_text(
            "<b>✉️ تم تفعيل المحادثة مع الأدمن.\nأرسل رسالتك الآن.</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await query.answer("أرسل أي رسالة ليتم تحويلها مباشرة للأدمن.")
    elif query.data == "end_admin_chat":
        chats = load_chats()
        chats.pop(str(user_id), None)
        save_chats(chats)
        await query.message.reply_text(
            "❌ تم إنهاء المحادثة مع الأدمن. يمكنك استخدام البوت بشكل طبيعي.",
            reply_markup=ReplyKeyboardRemove()
        )
        await query.answer("تم إنهاء المحادثة.")

# رسائل المستخدم (لوضع المحادثة مع الأدمن)
async def user_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chats = load_chats()
    if str(user.id) in chats:
        # رسالة موجهة للأدمن فقط
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"↩️ رد على {user.first_name}", callback_data=f"replyto_{user.id}")]
        ])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💬 رسالة جديدة من <b>{user.first_name}</b> (ID: <code>{user.id}</code>):\n\n{update.message.text}",
            parse_mode="HTML",
            reply_markup=kb
        )
        await update.message.reply_text("✅ تم إرسال رسالتك للأدمن. سين reply عليك هنا.")
    else:
        # الوضع العادي (ذكاء اصطناعي أو تحميل فيديو...)
        await update.message.reply_text(
            "استخدم /start لتفعيل خيارات البوت أو لمراسلة الأدمن."
        )

# الأدمن يضغط رد
async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("هذا الزر خاص بالأدمن.", show_alert=True)
        return
    if query.data.startswith("replyto_"):
        context.user_data["reply_target"] = int(query.data.replace("replyto_", ""))
        await query.message.reply_text("✏️ اكتب ردك ليتم إرساله للمستخدم.")
        await query.answer("اكتب الآن الرسالة التي تريد إرسالها للمستخدم.")

# رسالة الأدمن (رد على المستخدم)
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    target_id = context.user_data.pop("reply_target", None)
    if target_id:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"✉️ رسالة من الأدمن:\n\n{update.message.text}"
        )
        await update.message.reply_text("✅ تم إرسال الرد للمستخدم.")
    else:
        await update.message.reply_text("❗️ لا يوجد مستخدم للرد عليه. اضغط زر (رد) أولاً.")

# ربط الهاندلرز
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.User(ADMIN_ID), user_message_handler))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(contact_admin|end_admin_chat)$"))
app.add_handler(CallbackQueryHandler(admin_reply_handler, pattern="^replyto_"))
app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), admin_text_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
