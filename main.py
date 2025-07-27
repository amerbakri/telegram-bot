import os
import json
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
APP_URL = os.getenv("APP_URL")  # مثل: https://yourapp.onrender.com
PORT = int(os.getenv("PORT", "8443"))

FREE_LIMIT = 3
FREE_USERS_FILE = 'free_users.json'
PAID_USERS_FILE = 'paid_users.json'

def load_users(file):
    if not os.path.exists(file): return []
    with open(file, 'r') as f: return json.load(f)

def save_users(file, users):
    with open(file, 'w') as f: json.dump(users, f)

def get_free_users(): return load_users(FREE_USERS_FILE)
def get_paid_users(): return load_users(PAID_USERS_FILE)

def is_paid_user(user_id): return str(user_id) in get_paid_users()

def add_free_user(user_id):
    users = get_free_users()
    uid = str(user_id)
    if uid not in users:
        users.append(uid)
        save_users(FREE_USERS_FILE, users)

def save_paid_user(user_id):
    users = get_paid_users()
    uid = str(user_id)
    if uid not in users:
        users.append(uid)
        save_users(PAID_USERS_FILE, users)

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📥 تحميل فيديو", callback_data=f"video|{user.id}")],
        [InlineKeyboardButton("🎧 تحميل صوت", callback_data=f"audio|{user.id}")],
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request_user")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{user.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("أهلاً! اختر نوع التحميل:", reply_markup=reply_markup)

# === طلب الاشتراك من المستخدم ===
async def subscribe_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"admin_confirm_subscribe|{user.id}"),
            InlineKeyboardButton("❌ إلغاء الاشتراك", callback_data=f"admin_cancel_subscribe|{user.id}")
        ]
    ])
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"📥 طلب اشتراك جديد:\n"
            f"👤 الاسم: {user.full_name}\n"
            f"📎 المعرف: @{user.username or 'غير متوفر'}\n"
            f"🆔 آيدي: {user.id}",
            reply_markup=admin_keyboard
        )
        await query.edit_message_text("✅ تم إرسال طلبك للإدارة. يرجى الانتظار.")
    except Exception as e:
        await query.edit_message_text(f"❌ حدث خطأ: {e}")

# === تأكيد / إلغاء من الأدمن ===
async def admin_subscription_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للإدارة فقط.", show_alert=True)
        return

    data = query.data
    action, user_id_str = data.split("|")
    user_id = int(user_id_str)

    if action == "admin_confirm_subscribe":
        save_paid_user(user_id_str)
        await query.edit_message_text(f"✅ تم تفعيل الاشتراك لـ {user_id}")
        try:
            await context.bot.send_message(user_id, "🎉 تم تفعيل اشتراكك المدفوع. شكراً لك!")
        except:
            pass

    elif action == "admin_cancel_subscribe":
        await query.edit_message_text(f"❌ تم رفض الاشتراك لـ {user_id}")
        try:
            await context.bot.send_message(user_id, "❌ تم رفض طلب الاشتراك.")
        except:
            pass

# === تحميل الفيديو أو الصوت ===
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    if not message.text.startswith("http"):
        await message.reply_text("📎 الرجاء إرسال رابط يوتيوب صالح.")
        return

    if not is_paid_user(user_id):
        add_free_user(user_id)
        user_usage = get_free_users().count(str(user_id))
        if user_usage > FREE_LIMIT:
            await message.reply_text("⚠️ تجاوزت الحد المجاني. اشترك للوصول الكامل.")
            return

    url = message.text
    ydl_opts = {'outtmpl': 'downloads/%(title)s.%(ext)s'}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'video')
            formats = info.get('formats', [])
            video_url = formats[-1]['url']

        await message.reply_text(f"✅ تم تحليل الرابط: {title}\n🎬 الرابط المباشر:\n{video_url}")
    except Exception as e:
        await message.reply_text(f"❌ خطأ في التحميل: {e}")

# === معالجات الأزرار ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, uid = data.split("|")

    if str(update.effective_user.id) != uid:
        await query.answer("❌ هذا الزر ليس لك!", show_alert=True)
        return

    if action == "video":
        await query.edit_message_text("📎 أرسل رابط الفيديو:")
    elif action == "audio":
        await query.edit_message_text("🎵 أرسل رابط الفيديو لتحويله إلى صوت:")
    elif action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")

# === Webhook handler ===
async def handle(request):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.update_queue.put(update)
    return web.Response(text="OK")

# === إنشاء البوت وتسجيل المعالجات ===
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(subscribe_request_handler, pattern="^subscribe_request_user$"))
app.add_handler(CallbackQueryHandler(admin_subscription_response_handler, pattern="^admin_(confirm|cancel)_subscribe\|"))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\|"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))

# === إعداد سيرفر aiohttp لتلقي Webhook ===
web_app = web.Application()
web_app.router.add_post(f"/{BOT_TOKEN}", handle)

async def on_startup(app_web):
    await app.bot.set_webhook(f"{APP_URL}/{BOT_TOKEN}")

async def on_cleanup(app_web):
    await app.bot.delete_webhook()

web_app.on_startup.append(on_startup)
web_app.on_cleanup.append(on_cleanup)

# === تشغيل الخادم ===
if __name__ == "__main__":
    print("🚀 Webhook Bot is running...")
    web.run_app(web_app, host="0.0.0.0", port=PORT)
