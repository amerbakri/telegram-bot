import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime
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

ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"  # يحتوي المشتركين المدفوعين
REQUESTS_FILE = "subscription_requests.txt"

DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

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
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        }
    with open(STATS_FILE, "r") as f:
        return json.load(f)

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def update_stats(action, quality):
    stats = load_stats()
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    stats["quality_counts"][key] = stats["quality_counts"].get(key, 0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_stats(stats)

def is_subscribed(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return False
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        data = {}
    else:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            data = json.load(f)
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def deactivate_subscription(user_id):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)
    if str(user_id) in data:
        data.pop(str(user_id))
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def check_limits(user_id, action):
    if is_subscribed(user_id):
        return True

    today = datetime.utcnow().strftime("%Y-%m-%d")
    if not os.path.exists(LIMITS_FILE):
        limits = {}
    else:
        with open(LIMITS_FILE, "r") as f:
            limits = json.load(f)

    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}

    if action == "video" and user_limits["video"] >= DAILY_VIDEO_LIMIT:
        return False
    if action == "ai" and user_limits["ai"] >= DAILY_AI_LIMIT:
        return False

    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    with open(LIMITS_FILE, "w") as f:
        json.dump(limits, f)
    return True

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        "🚫 لقد وصلت للحد اليومي المجاني.\n"
        "للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج كاش:\n"
        "📲 الرقم: 0781200500\nثم اضغط على الزر أدناه لتأكيد الاشتراك.",
        reply_markup=keyboard
    )

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    with open(REQUESTS_FILE, "a") as f:
        f.write(f"{user.id}|{user.username or 'NO_USERNAME'}|{datetime.utcnow()}\n")

    await update.callback_query.edit_message_text(
        "💳 للاشتراك:\n"
        "أرسل 2 دينار عبر أورنج كاش إلى الرقم:\n"
        "📱 0781200500\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )

    # إرسال رسالة أدمن مع زر تأكيد/رفض
    msg = f"👤 المستخدم @{user.username or user.id} طلب الاشتراك.\nهل تريد تأكيد الاشتراك؟"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=keyboard)
    await update.callback_query.answer("✅ تم إرسال التعليمات.")

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن الاستخدام غير المحدود.")
    await query.answer("✅ تم التفعيل.")
    await query.edit_message_text("✅ تم تفعيل اشتراك المستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await query.answer("🚫 تم الرفض.")
    await query.edit_message_text("🚫 تم رفض الاشتراك.")

async def show_paid_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    if not os.path.exists(SUBSCRIPTIONS_FILE):
        await update.message.reply_text("لا يوجد مشتركين مدفوعين حالياً.")
        return

    with open(SUBSCRIPTIONS_FILE, "r") as f:
        data = json.load(f)

    if not data:
        await update.message.reply_text("لا يوجد مشتركين مدفوعين حالياً.")
        return

    buttons = []
    text = "👥 قائمة المشتركين المدفوعين:\n\n"
    for uid, info in data.items():
        # عرض اسم المستخدم مع الآيدي، مع زر إلغاء الاشتراك
        username = "NO_USERNAME"
        # نبحث في ملف المستخدمين للاسم أو الاسم الكامل
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as uf:
                for line in uf:
                    if line.startswith(uid + "|"):
                        parts = line.strip().split("|")
                        username = parts[1]
                        fullname = parts[2]
                        break
        text += f"👤 {fullname} (@{username}) — ID: {uid}\n"
        buttons.append([InlineKeyboardButton(f"❌ إلغاء {username}", callback_data=f"cancel_subscribe|{uid}")])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def cancel_subscription_by_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return

    _, user_id = query.data.split("|")
    deactivate_subscription(user_id)

    await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، راسل الأدمن."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    if not is_subscribed(user.id):
        allowed = check_limits(user.id, "video")
        if not allowed:
            await send_limit_message(update)
            return

    text = update.message.text.strip()

    if not is_valid_url(text):
        if not is_subscribed(user.id):
            allowed = check_limits(user.id, "ai")
            if not allowed:
                await send_limit_message(update)
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
        await query.edit_message_text("⚠️ الرابط غير موجود أو منتهي.")
        return

    # هنا يتم تنفيذ التحميل حسب النوع والجودة
    # (ضع كود التحميل الخاص بك هنا)

    update_stats(action, quality)
    await query.edit_message_text(f"✅ تم اختيار: {action} بجودة {quality}.\nسيتم تنفيذ التحميل لاحقاً.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = load_stats()
    msg = (
        f"📊 <b>إحصائيات الاستخدام:</b>\n"
        f"- إجمالي التنزيلات: {stats['total_downloads']}\n"
        f"- 720p: {stats['quality_counts']['720']}\n"
        f"- 480p: {stats['quality_counts']['480']}\n"
        f"- 360p: {stats['quality_counts']['360']}\n"
        f"- صوت فقط: {stats['quality_counts']['audio']}\n"
        f"- الأكثر طلبًا: {stats['most_requested_quality']}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# استقبال صورة إثبات الدفع
async def receive_subscription_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not update.message.photo:
        await update.message.reply_text("❌ الرجاء إرسال صورة إثبات الدفع فقط.")
        return

    photo_file = await update.message.photo[-1].get_file()
    photo_path = f"proofs/{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    os.makedirs("proofs", exist_ok=True)
    await photo_file.download_to_drive(photo_path)

    # إرسال الصورة مع بيانات المستخدم للأدمن مع أزرار تأكيد/رفض
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])

    caption = f"📩 طلب اشتراك جديد:\nالمستخدم: @{user.username or 'NO_USERNAME'}\nID: {user.id}"
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=open(photo_path, "rb"), caption=caption, reply_markup=keyboard)
    await update.message.reply_text("✅ تم استلام إثبات الدفع، جاري المراجعة من قبل الأدمن.")

# أمر عرض المستخدمين (كل المستخدمين)
async def show_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    if not os.path.exists(USERS_FILE):
        await update.message.reply_text("لا يوجد مستخدمين حالياً.")
        return

    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()

    text = f"👥 عدد المستخدمين الكلي: {len(users)}\n\n"
    for line in users:
        parts = line.split("|")
        uid = parts[0]
        username = parts[1]
        fullname = parts[2]
        text += f"👤 {fullname} (@{username}) — ID: {uid}\n"

    await update.message.reply_text(text)

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats_command))
app.add_handler(CommandHandler("subscribe", handle_subscription_request))
app.add_handler(CommandHandler("paid_users", show_paid_users))  # قائمة المشتركين المدفوعين
app.add_handler(CommandHandler("all_users", show_all_users))    # قائمة كل المستخدمين

app.add_handler(MessageHandler(filters.PHOTO & filters.User(), receive_subscription_proof))

app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern="^cancel_subscribe\\|"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
