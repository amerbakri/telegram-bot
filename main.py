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
SUBSCRIPTIONS_FILE = "subscriptions.json"
PROOFS_FOLDER = "proofs"

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

def load_subscriptions():
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return {}
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        return json.load(f)

def save_subscriptions(data):
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(data, f)

def is_subscribed(user_id):
    data = load_subscriptions()
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    data = load_subscriptions()
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_subscriptions(data)

def deactivate_subscription(user_id):
    data = load_subscriptions()
    if str(user_id) in data:
        data.pop(str(user_id))
    save_subscriptions(data)

def check_limits(user_id, action):
    if user_id == ADMIN_ID:
        return True
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
        "للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج ماني:\n"
        "📲 الرقم: 0781200500\nثم اضغط على الزر أدناه وأرسل صورة إثبات الدفع.",
        reply_markup=keyboard
    )

# ----------- الاشتراك المدفوع وإثبات الدفع -----------

pending_proofs = {}

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    pending_proofs[user.id] = True  # فعل وضع إثبات الدفع لهذا المستخدم
    await update.callback_query.edit_message_text(
        "💳 للاشتراك:\n"
        "أرسل 2 دينار عبر أورنج ماني إلى الرقم:\n"
        "📱 0781200500\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
    )
    await update.callback_query.answer("✅ أرسل صورة إثبات الدفع هنا.", show_alert=True)

async def receive_subscription_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not pending_proofs.get(user.id):
        return  # المستخدم لم يضغط "اشترك الآن" بعد
    if not update.message.photo:
        await update.message.reply_text("❌ الرجاء إرسال صورة إثبات الدفع فقط.")
        return
    photo_file = await update.message.photo[-1].get_file()
    os.makedirs(PROOFS_FOLDER, exist_ok=True)
    photo_path = f"{PROOFS_FOLDER}/{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    await photo_file.download_to_drive(photo_path)
    caption = f"📩 طلب اشتراك جديد:\nالمستخدم: @{user.username or 'NO_USERNAME'}\nID: {user.id}"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}|{update.message.message_id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}|{update.message.message_id}")
        ]
    ])
    with open(photo_path, "rb") as photo:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo, caption=caption, reply_markup=keyboard)
    await update.message.reply_text("✅ تم استلام إثبات الدفع، جارٍ المراجعة من قبل الأدمن.")
    pending_proofs.pop(user.id, None)  # أزل وضع الانتظار بعد الإرسال

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id, proof_msg_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن الاستخدام غير المحدود.")
    try:
        await query.edit_message_caption("✅ تم تفعيل الاشتراك للمستخدم.")
    except:
        await query.delete_message()

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id, proof_msg_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    try:
        await query.edit_message_caption("🚫 تم رفض الاشتراك.")
    except:
        await query.delete_message()

# ----------- تحميل الفيديو -----------

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)
    if not is_subscribed(user.id) and user.id != ADMIN_ID:
        allowed = check_limits(user.id, "video")
        if not allowed:
            await send_limit_message(update)
            return
    text = update.message.text.strip()
    if not is_valid_url(text):
        if not is_subscribed(user.id) and user.id != ADMIN_ID:
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
        await query.message.reply_text("⚠️ الرابط غير موجود أو منتهي.")
        return
    loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")
    # عملية التحميل
    filename = None
    try:
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
    finally:
        try:
            await loading_msg.delete()
        except:
            pass

# ----------- لوحة تحكم الأدمن -----------

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
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة مشترك مدفوع", callback_data="admin_addpaid")],
        [InlineKeyboardButton("📝 قائمة المشتركين", callback_data="admin_paidusers")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    if data == "admin_users":
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            count = len(users)
            recent = "\n\n📌 آخر 5 مستخدمين:\n"
            for u in users[-5:]:
                uid, username, name = u.split("|")
                recent += f"👤 {name} | @{username} | ID: {uid}\n"
        except:
            count = 0
            recent = ""
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل لي الإعلان (نص أو صورة أو فيديو مع نص):")
        context.user_data["waiting_for_announcement"] = True

    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل لي اسم المستخدم أو رقم المستخدم للبحث:")
        context.user_data["waiting_for_search"] = True

    elif data == "admin_stats":
        stats = load_stats()
        text = (
            f"📊 إحصائيات التحميل:\n"
            f"عدد الفيديوهات المنزلة: {stats['total_downloads']}\n"
            f"جودة 720p: {stats['quality_counts'].get('720',0)} مرات\n"
            f"جودة 480p: {stats['quality_counts'].get('480',0)} مرات\n"
            f"جودة 360p: {stats['quality_counts'].get('360',0)} مرات\n"
            f"تحميل الصوت فقط: {stats['quality_counts'].get('audio',0)} مرات\n"
            f"أكثر جودة مطلوبة: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_addpaid":
        await query.edit_message_text(
            "📥 أرسل آيدي المستخدم الذي تريد إضافته كمشترك مدفوع.\n"
            "مثال: 123456789"
        )
        context.user_data["waiting_for_addpaid"] = True

    elif data == "admin_paidusers":
        subs = load_subscriptions()
        users_list = []
        for uid, info in subs.items():
            fullname, username = uid, "NO_USERNAME"
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, "r") as uf:
                    for line in uf:
                        if line.startswith(uid + "|"):
                            parts = line.strip().split("|")
                            username = parts[1]
                            fullname = parts[2]
                            break
            users_list.append(
                [InlineKeyboardButton(f"❌ إلغاء: {fullname} @{username}", callback_data=f"cancel_subscribe|{uid}")]
            )
        await query.edit_message_text("👑 قائمة المشتركين المدفوعين:", reply_markup=InlineKeyboardMarkup(users_list + [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))

    elif data.startswith("cancel_subscribe|"):
        _, user_id = data.split("|")
        deactivate_subscription(user_id)
        await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_paidusers")]
        ]))
        await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")

    elif data == "admin_close":
        await query.delete_message()

    elif data == "admin_back":
        await admin_panel(update, context)

# ---- استقبال الرسائل الخاصة بالإعلانات أو البحث ----

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        context.user_data["announcement"] = update.message
        await update.message.reply_text("✅ هل تريد تأكيد الإرسال؟", reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ نعم", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")
            ]
        ]))
        return
    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query_text = update.message.text.strip()
        try:
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
        except Exception as e:
            reply = f"⚠️ خطأ في البحث: {e}"
        await update.message.reply_text(reply)
        return
    if context.user_data.get("waiting_for_addpaid"):
        context.user_data["waiting_for_addpaid"] = False
        new_paid_id = update.message.text.strip()
        if not new_paid_id.isdigit():
            await update.message.reply_text("⚠️ آيدي غير صالح. أرسل رقم آيدي صحيح.")
            return
        activate_subscription(new_paid_id)
        await update.message.reply_text(f"✅ تم إضافة المستخدم {new_paid_id} كمشترك مدفوع.")
        return

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = context.user_data.get("announcement")
    if not message:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    try:
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        sent = 0
        for u in users:
            uid = int(u.split("|")[0])
            try:
                if message.photo:
                    await context.bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
                elif message.video:
                    await context.bot.send_video(uid, message.video.file_id, caption=message.caption or "")
                elif message.text:
                    await context.bot.send_message(uid, message.text)
                elif message.voice:
                    await context.bot.send_voice(uid, message.voice.file_id, caption=message.caption or "")
                else:
                    pass
                sent += 1
            except:
                pass
        await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.")
    except Exception as e:
        await query.edit_message_text(f"🚫 خطأ أثناء الإرسال: {e}")

# --------- الأوامر ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو فيسبوك أو إنستا لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، أرسل 2 دينار إلى 0781200500 (أورنج ماني) ثم اضغط اشترك الآن وأرسل صورة التحويل."
    )

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))

app.add_handler(MessageHandler(filters.PHOTO, receive_subscription_proof))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), media_handler))

app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\|"))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\|"))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
