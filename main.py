import os
import subprocess
import logging
import re
import json
import datetime
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

logging.basicConfig(level=logging.INFO)

# --- الإعدادات من البيئة ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", "8443"))
HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

ADMIN_ID = int(os.getenv("ADMIN_ID", "337597459"))  # عدل حسب رقمك

USERS_FILE = "users.txt"
PAID_USERS_FILE = "paid_users.txt"
PENDING_SUBS_FILE = "pending_subs.json"
USAGE_FILE = "usage.json"

COOKIES_FILE = "cookies.txt"

MAX_VIDEO_DOWNLOADS_FREE = 3
MAX_AI_REQUESTS_FREE = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ BOT_TOKEN و OPENAI_API_KEY غير معرّفين في البيئة")

openai.api_key = OPENAI_API_KEY

url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# --- دوال مساعدة ---

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
    if not os.path.exists(PAID_USERS_FILE):
        return set()
    with open(PAID_USERS_FILE, "r") as f:
        return set(line.strip() for line in f)

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

def reset_daily_usage_if_needed(usage_data):
    today_str = datetime.date.today().isoformat()
    if usage_data.get("date") != today_str:
        usage_data["date"] = today_str
        usage_data["video_downloads"] = {}
        usage_data["ai_requests"] = {}
    return usage_data

def increment_usage(user_id, usage_type):
    if is_paid_user(user_id):
        return True
    usage_data = load_json(USAGE_FILE)
    usage_data = reset_daily_usage_if_needed(usage_data)

    user_id_str = str(user_id)
    if usage_type == "video":
        count = usage_data.get("video_downloads", {}).get(user_id_str, 0)
        if count >= MAX_VIDEO_DOWNLOADS_FREE:
            return False
        usage_data.setdefault("video_downloads", {})[user_id_str] = count + 1

    elif usage_type == "ai":
        count = usage_data.get("ai_requests", {}).get(user_id_str, 0)
        if count >= MAX_AI_REQUESTS_FREE:
            return False
        usage_data.setdefault("ai_requests", {})[user_id_str] = count + 1

    save_json(USAGE_FILE, usage_data)
    return True

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                pass
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.full_name}"
        if not any(str(user.id) == u.split("|")[0] for u in users):
            with open(USERS_FILE, "a") as f:
                f.write(entry + "\n")
    except Exception as e:
        logging.error(f"خطأ تخزين المستخدم: {e}")

# --- أوامر وأحداث البوت ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 مرحباً! أرسل لي رابط فيديو (يوتيوب، تيك توك، إنستا، فيسبوك) لتحميله.\n"
        f"💡 الحد المجاني: {MAX_VIDEO_DOWNLOADS_FREE} فيديوهات و{MAX_AI_REQUESTS_FREE} استفسارات يومياً.\n"
        "🔔 للاشتراك المدفوع، اضغط على زر الاشتراك أدناه.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
    )

async def download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    text = update.message.text.strip()

    if not is_valid_url(text):
        # AI request limit
        if not is_paid_user(user.id):
            allowed = increment_usage(user.id, "ai")
            if not allowed:
                await update.message.reply_text(
                    "🚫 وصلت الحد المجاني اليومي لاستفسارات AI.\n"
                    "للاشتراك المدفوع، اضغط زر الاشتراك أدناه.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
                )
                return
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ في استدعاء AI: {e}")
        return

    # الفيديو
    if not is_paid_user(user.id):
        allowed = increment_usage(user.id, "video")
        if not allowed:
            await update.message.reply_text(
                "🚫 وصلت الحد المجاني اليومي لتحميل الفيديوهات.\n"
                "للاشتراك المدفوع، اضغط زر الاشتراك أدناه.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
            )
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
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]
    try:
        await update.message.delete()
    except:
        pass
    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        action, quality, key = query.data.split("|")
    except:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو انتهى.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", format_code, "-o", "video.%(ext)s", url]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        fallback = subprocess.run(
            ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best[ext=mp4]", "-o", "video.%(ext)s", url],
            capture_output=True, text=True
        )
        if fallback.returncode != 0:
            await query.edit_message_text("🚫 فشل تحميل الفيديو.")
            url_store.pop(key, None)
            return

    if action == "video":
        for ext in ["mp4", "mkv", "webm"]:
            if os.path.exists(f"video.{ext}"):
                filename = f"video.{ext}"
                break

    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")

    url_store.pop(key, None)
    try:
        await loading_msg.delete()
    except:
        pass

# --- نظام الاشتراك ---

async def handle_subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.message.reply_text("📸 أرسل صورة التحويل لإتمام الاشتراك.")
    context.user_data["awaiting_payment_proof"] = True
    await query.answer()

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
        await context.bot.send_message(chat_id=uid, text="❌ تم رفض صورة التحويل. حاول مجدداً.")
        await query.edit_message_caption(query.message.caption + "\n❌ تم الرفض.")

    pending.pop(str(uid), None)
    save_json(PENDING_SUBS_FILE, pending)
    await query.answer("تمت المعالجة.")

# --- إدارة المشتركين ---

async def list_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر خاص بالأدمن فقط.")
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

async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.data.split("|")[1]
    remove_paid_user(uid)
    await context.bot.send_message(chat_id=uid, text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    await query.edit_message_text(f"❌ تم إلغاء اشتراك المستخدم {uid}.")
    await query.answer("تمت المعالجة.")

# --- لوحة الأدمن الأساسية ---

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("🚫 هذا الأمر خاص بالأدمن فقط.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 عرض المشتركين المدفوعين", callback_data="list_subscribers")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="close_admin")]
    ]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 مخصص للأدمن فقط", show_alert=True)
        return

    if data == "list_subscribers":
        await list_subscribers(update, context)

    elif data == "close_admin":
        await query.edit_message_text("❌ تم إغلاق لوحة الأدمن.")

    elif data.startswith("remove_subscriber|"):
        await remove_subscriber(update, context)

    elif data == "subscribe_request":
        await handle_subscribe_request(update, context)

    elif data.startswith("confirm_payment") or data.startswith("reject_payment"):
        await handle_admin_payment_decision(update, context)

# --- بدء البوت webhook ---

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_handler))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(audio|video|cancel)\|"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(list_subscribers|close_admin|remove_subscriber\|subscribe_request|confirm_payment|reject_payment)"))

    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_photo))

    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("list_subscribers", list_subscribers))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{HOSTNAME}/{BOT_TOKEN}"
    )
