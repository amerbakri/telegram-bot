import os
import subprocess
import logging
import re
import json
import datetime
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove, InputMediaPhoto, InputMediaVideo
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
ORANGE_MONEY_NUMBER = "0781200500"

USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
USAGE_FILE = "usage.json"
PAID_USERS_FILE = "paid_users.txt"
PROOFS_DIR = "proofs"

MAX_VIDEO_DOWNLOADS_FREE = 3
MAX_AI_REQUESTS_FREE = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# ---------- Helper Functions ----------

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
    if not os.path.exists(PAID_USERS_FILE):
        return
    with open(PAID_USERS_FILE, "r") as f:
        lines = f.readlines()
    with open(PAID_USERS_FILE, "w") as f:
        for line in lines:
            if str(user_id) not in line.strip():
                f.write(line)

def is_paid_user(user_id):
    paid_users = load_paid_users()
    return str(user_id) in paid_users or user_id == ADMIN_ID

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
    if key in stats["quality_counts"]:
        stats["quality_counts"][key] += 1
    else:
        stats["quality_counts"][key] = 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_stats(stats)

# ---------- Core Bot Logic ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو (YouTube, TikTok, Instagram, Facebook) لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع وتحميل غير محدود، حول 2 دينار أورنج ماني على الرقم: 0781200500 ثم أرسل صورة التحويل."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    # الذكاء الاصطناعي مباشرة (أي رسالة ليست رابط)
    text = update.message.text.strip()
    if not is_valid_url(text):
        if not is_paid_user(user.id):
            allowed = increment_usage(user.id, "ai")
            if not allowed:
                return await send_limit_message(update)
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

    # حد التحميل للفيديو
    if not is_paid_user(user.id):
        allowed = increment_usage(user.id, "video")
        if not allowed:
            return await send_limit_message(update)

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

    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    filename = None
    # تحديد أمر yt-dlp لكل جودة
    if action == "audio":
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", format_code, "-o", "video.%(ext)s", url]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # fallback: أي جودة متاحة mp4
        fallback = subprocess.run(
            ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best[ext=mp4]", "-o", "video.%(ext)s", url],
            capture_output=True, text=True
        )
        if fallback.returncode != 0:
            await loading_msg.edit_text("🚫 فشل في تحميل الفيديو.")
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
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")

    url_store.pop(key, None)
    try:
        await loading_msg.delete()
    except:
        pass

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        f"🚫 لقد وصلت للحد المجاني اليومي (3 فيديوهات أو 5 استفسارات AI).\n"
        f"للاستخدام غير محدود:\n1️⃣ حول 2 دينار أورنج ماني إلى {ORANGE_MONEY_NUMBER}\n2️⃣ أرسل لقطة شاشة (صورة) التحويل هنا.",
        reply_markup=keyboard
    )

# استقبال صورة الاشتراك وتفعيل الاشتراك بالادمن فقط
async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        return  # الأدمن مستثنى

    if not update.message.photo:
        await update.message.reply_text("❌ الرجاء إرسال صورة إثبات التحويل فقط.")
        return

    photo_file = await update.message.photo[-1].get_file()
    os.makedirs(PROOFS_DIR, exist_ok=True)
    photo_path = f"{PROOFS_DIR}/{user.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    await photo_file.download_to_drive(photo_path)

    caption = f"🆕 طلب اشتراك جديد:\nالاسم: @{user.username or 'NO_USERNAME'}\nID: {user.id}"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"approve_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=open(photo_path, "rb"), caption=caption, reply_markup=keyboard)
    await update.message.reply_text("✅ تم استلام إثبات الدفع، سيتم مراجعة الطلب قريباً.")

# زر "اشترك الآن"
async def handle_subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        f"💳 للاشتراك:\n1️⃣ حول 2 دينار عبر أورنج ماني إلى الرقم:\n{ORANGE_MONEY_NUMBER}\n2️⃣ أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )
    await update.callback_query.answer("أرسل صورة التحويل هنا.")

# تأكيد/رفض الاشتراك من الأدمن
async def admin_approve_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    save_paid_user(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك! يمكنك الآن التحميل غير المحدود.")
    await query.edit_message_text("✅ تم تفعيل الاشتراك.")

async def admin_reject_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك. يمكنك التواصل مع الأدمن للمراجعة.")
    await query.edit_message_text("❌ تم رفض الطلب.")

# ---------- Admin Panel ----------

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return
    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة مشترك مدفوع", callback_data="admin_addpaid")],
        [InlineKeyboardButton("📝 قائمة المشتركين", callback_data="admin_paid_list")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    if data == "admin_users":
        if not os.path.exists(USERS_FILE):
            await query.edit_message_text("لا يوجد مستخدمين.")
            return
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        count = len(users)
        recent = "\n\n📌 آخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.split("|")
            recent += f"👤 {name} | @{username} | ID: {uid}\n"
        await query.edit_message_text(f"عدد المستخدمين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))
    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل الآن (نص، صورة، فيديو، أو صوت):")
        context.user_data["waiting_for_announcement"] = True
    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل اسم المستخدم أو رقم المستخدم:")
        context.user_data["waiting_for_search"] = True
    elif data == "admin_stats":
        stats = load_stats()
        text = (
            f"📊 إحصائيات التحميل:\n"
            f"- الفيديوهات: {stats['total_downloads']}\n"
            f"- 720p: {stats['quality_counts'].get('720',0)} مرات\n"
            f"- 480p: {stats['quality_counts'].get('480',0)} مرات\n"
            f"- 360p: {stats['quality_counts'].get('360',0)} مرات\n"
            f"- الصوت فقط: {stats['quality_counts'].get('audio',0)} مرات\n"
            f"- الأكثر طلباً: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))
    elif data == "admin_addpaid":
        await query.edit_message_text("📥 أرسل آيدي المستخدم لإضافته كمشترك مدفوع.")
        context.user_data["waiting_for_addpaid"] = True
    elif data == "admin_paid_list":
        await show_paid_list(query)
    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())
    elif data == "admin_back":
        await admin_panel(query, context)

    # اشتراك جديد من زر "اشترك الآن"
    elif data == "subscribe_request":
        await handle_subscribe_request(update, context)
    elif data.startswith("approve_sub|"):
        await admin_approve_sub(update, context)
    elif data.startswith("reject_sub|"):
        await admin_reject_sub(update, context)
    elif data.startswith("cancel_paid|"):
        uid = data.split("|")[1]
        remove_paid_user(uid)
        await query.edit_message_text(f"❌ تم إلغاء اشتراك {uid}")
        try:
            await context.bot.send_message(chat_id=int(uid), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
        except:
            pass

# عرض قائمة المشتركين المدفوعين مع زر إلغاء لكل مشترك
async def show_paid_list(query):
    if not os.path.exists(PAID_USERS_FILE):
        await query.edit_message_text("لا يوجد مشتركين مدفوعين.")
        return
    with open(PAID_USERS_FILE, "r") as f:
        users = [u.strip() for u in f if u.strip()]
    if not users:
        await query.edit_message_text("لا يوجد مشتركين مدفوعين.")
        return
    text = "👑 المشتركين المدفوعين:\n"
    buttons = []
    for uid in users:
        name = "NO_USERNAME"
        username = "NO_USERNAME"
        # جلب الاسم من users.txt
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as uf:
                for line in uf:
                    if line.startswith(uid + "|"):
                        parts = line.strip().split("|")
                        username = parts[1]
                        name = parts[2]
                        break
        text += f"\n{uid} | @{username} | {name}"
        buttons.append([InlineKeyboardButton(f"إلغاء {uid}", callback_data=f"cancel_paid|{uid}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# استقبال ردود الأدمن - إعلان/بحث/إضافة مدفوع
async def admin_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        message = update.message
        sent = 0
        if not os.path.exists(USERS_FILE):
            await update.message.reply_text("لا يوجد مستخدمين.")
            return
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        for u in users:
            uid = int(u.split("|")[0])
            try:
                if message.photo:
                    await context.bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
                elif message.video:
                    await context.bot.send_video(uid, message.video.file_id, caption=message.caption or "")
                elif message.audio:
                    await context.bot.send_audio(uid, message.audio.file_id, caption=message.caption or "")
                elif message.text:
                    await context.bot.send_message(uid, message.text)
                sent += 1
            except:
                continue
        await update.message.reply_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.")
        return

    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query_text = update.message.text.strip()
        if not os.path.exists(USERS_FILE):
            await update.message.reply_text("لا يوجد مستخدمين.")
            return
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        results = []
        for u in users:
            uid, username, name = u.split("|")
            if query_text.lower() in username.lower() or query_text == uid or query_text in name.lower():
                results.append(f"👤 {name} | @{username} | ID: {uid}")
        if results:
            reply = "نتائج البحث:\n" + "\n".join(results)
        else:
            reply = "⚠️ لم يتم العثور على مستخدم."
        await update.message.reply_text(reply)
        return

    if context.user_data.get("waiting_for_addpaid"):
        context.user_data["waiting_for_addpaid"] = False
        new_paid_id = update.message.text.strip()
        if not new_paid_id.isdigit():
            await update.message.reply_text("⚠️ آيدي غير صالح. أرسل رقم آيدي صحيح.")
            return
        if is_paid_user(new_paid_id):
            await update.message.reply_text(f"⚠️ المستخدم {new_paid_id} مضاف مسبقاً كمشترك مدفوع.")
            return
        save_paid_user(new_paid_id)
        await update.message.reply_text(f"✅ تم إضافة المستخدم {new_paid_id} كمشترك مدفوع.")
        return

# ---------- Main ----------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(video|audio|cancel)\|"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.User(user_id=ADMIN_ID), receive_proof))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), admin_media_handler))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
