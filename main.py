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

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459  # غيّرها لآيدي الأدمن عندك
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

# --- دوال تحميل/حفظ JSON ---
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

# --- دوال إدارة المشتركين المدفوعين ---
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

# --- دوال إدارة المستخدمين العام ---
def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                pass
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.full_name}"
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

# --- دعم استخدام الفيديوهات و AI ---
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
        count = usage_data["video_downloads"].get(user_id_str, 0)
        if count >= MAX_VIDEO_DOWNLOADS_FREE:
            return False
        usage_data["video_downloads"][user_id_str] = count + 1

    elif usage_type == "ai":
        count = usage_data["ai_requests"].get(user_id_str, 0)
        if count >= MAX_AI_REQUESTS_FREE:
            return False
        usage_data["ai_requests"][user_id_str] = count + 1

    save_json(USAGE_FILE, usage_data)
    return True

# --- التحقق من الروابط ---
def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# --- الأمر /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، اضغط 'اشترك الآن' في أي وقت."
    )

# --- تحميل الفيديو أو استخدام AI ---
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    if not is_paid_user(user.id):
        allowed = increment_usage(user.id, "video")
        if not allowed:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")
            ]])
            await update.message.reply_text(
                "🚫 وصلت إلى الحد المجاني اليومي (3 فيديوهات).\n"
                "للمتابعة، اشترك بـ 2 دينار شهريًا عبر أورنج كاش:\n"
                "📲 الرقم: 0781200500\n"
                "اضغط الزر أدناه للاشتراك.",
                reply_markup=keyboard
            )
            return

    text = update.message.text.strip()

    if not is_valid_url(text):
        if not is_paid_user(user.id):
            allowed = increment_usage(user.id, "ai")
            if not allowed:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")
                ]])
                await update.message.reply_text(
                    "🚫 وصلت إلى الحد المجاني اليومي لاستفسارات AI (5 مرات).\n"
                    "للمتابعة، اشترك بـ 2 دينار شهريًا عبر أورنج كاش:\n"
                    "📲 الرقم: 0781200500\n"
                    "اضغط الزر أدناه للاشتراك.",
                    reply_markup=keyboard
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
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
        return

    # حفظ الرابط مؤقتاً
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

    try:
        await update.message.delete()
    except:
        pass

    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- التعامل مع أزرار تحميل الفيديو ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو منتهي.")
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
            await query.edit_message_text("🚫 فشل في تحميل الفيديو.")
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
        # يمكن هنا تحديث إحصائيات التحميل إذا أردت
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")

    url_store.pop(key, None)
    try:
        await loading_msg.delete()
    except:
        pass

# --- لوحة تحكم الأدمن ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        elif update.callback_query:
            await update.callback_query.answer("⚠️ هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("👑 قائمة المشتركين", callback_data="admin_paid_list")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]

    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- التعامل مع أزرار لوحة الأدمن ---
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر خاص بالأدمن فقط.", show_alert=True)
        return

    data = query.data

    if data == "admin_users":
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            count = len(users)
            recent_users = users[-5:] if len(users) >= 5 else users
            text = f"👥 عدد المستخدمين: {count}\n\nآخر 5 مستخدمين:\n"
            for u in recent_users:
                uid, username, name = u.split("|")
                text += f"- {name} | @{username} | ID: {uid}\n"
        except Exception as e:
            text = f"⚠️ حدث خطأ في قراءة المستخدمين: {e}"

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_paid_list":
        users = load_paid_users()
        if not users:
            await query.edit_message_text("⚠️ لا يوجد مشتركين مدفوعين.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]))
            return
        buttons = [
            [InlineKeyboardButton(f"❌ إلغاء {uid}", callback_data=f"remove_subscriber|{uid}")]
            for uid in users
        ]
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(
            f"👑 قائمة المشتركين المدفوعين (العدد: {len(users)}):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data == "admin_broadcast":
        await query.edit_message_text("✉️ أرسل رسالة الإعلان الآن:")
        context.user_data["awaiting_broadcast"] = True

    elif data == "admin_search":
        await query.edit_message_text("🔍 اكتب اسم أو معرف المستخدم للبحث:")
        context.user_data["awaiting_search"] = True

    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.")

    elif data == "admin_back":
        await admin_panel(update, context)

# --- استقبال رسالة الإعلان ---
async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_broadcast"):
        return
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    message = update.message.text
    users = []
    try:
        with open(USERS_FILE, "r") as f:
            users = [line.split("|")[0] for line in f.read().splitlines()]
    except:
        pass

    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=message)
            count += 1
        except:
            pass

    await update.message.reply_text(f"✅ تم إرسال الإعلان إلى {count} مستخدمًا.")
    context.user_data["awaiting_broadcast"] = False

# --- استقبال رسالة البحث ---
async def handle_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_search"):
        return
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    query_text = update.message.text.lower()
    results = []
    try:
        with open(USERS_FILE, "r") as f:
            for line in f.read().splitlines():
                uid, username, name = line.split("|")
                if query_text in uid or query_text in username.lower() or query_text in name.lower():
                    results.append(f"- {name} | @{username} | ID: {uid}")
    except:
        pass

    if results:
        text = "🔎 نتائج البحث:\n" + "\n".join(results)
    else:
        text = "⚠️ لم يتم العثور على نتائج."

    await update.message.reply_text(text)
    context.user_data["awaiting_search"] = False

# --- زر الاشتراك ---
async def handle_subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.message.reply_text("📸 أرسل صورة التحويل لإتمام الاشتراك.")
    context.user_data["awaiting_payment_proof"] = True
    await query.answer()

# --- استقبال صورة التحويل ---
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

# --- تأكيد أو رفض الدفع من الأدمن ---
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

# --- أمر /list_subscribers لعرض المشتركين المدفوعين ---
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

# --- إزالة مشترك ---
async def remove_subscriber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.data.split("|")[1]
    remove_paid_user(uid)
    await context.bot.send_message(chat_id=uid, text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    await query.edit_message_text(f"❌ تم إلغاء اشتراك المستخدم {uid}.")
    await query.answer("تمت المعالجة.")

# --- هاندلر للرسائل العامة: الإعلان والبحث ---
async def general_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_broadcast"):
        await handle_broadcast_message(update, context)
        return
    if context.user_data.get("awaiting_search"):
        await handle_search_message(update, context)
        return
    # لا ننسى إضافة استقبال روابط الفيديوهات
    await download(update, context)

# --- التطبيق وتشغيل webhook ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("HOSTNAME", "example.com")  # عدّلها إلى نطاقك

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # أوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list_subscribers", list_subscribers))
    app.add_handler(CommandHandler("admin", admin_panel))

    # الرسائل والصور
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), general_message_handler))

    # أزرار callback
    app.add_handler(CallbackQueryHandler(handle_subscribe_request, pattern="^subscribe_request$"))
    app.add_handler(CallbackQueryHandler(handle_admin_payment_decision, pattern="^(confirm_payment|reject_payment)\|"))
    app.add_handler(CallbackQueryHandler(remove_subscriber, pattern="^remove_subscriber\|"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))

import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
hostname = "telegram-bot-fyro.onrender.com"
port = int(os.getenv("PORT", "8443"))

app = ApplicationBuilder().token(BOT_TOKEN).build()

# إضافة الـ handlers ...

app.run_webhook(
    listen="0.0.0.0",
    port=port,
    url_path=BOT_TOKEN,
    webhook_url=f"https://{hostname}/{BOT_TOKEN}"
)

