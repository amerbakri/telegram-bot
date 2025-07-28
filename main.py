import os
import subprocess
import logging
import re
import json
from datetime import datetime
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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
SUBSCRIPTIONS_FILE = "subscriptions.json"
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

def load_subscribers():
    data = load_json(SUBSCRIPTIONS_FILE)
    return data if isinstance(data, dict) else {}

def is_subscribed(user_id):
    data = load_subscribers()
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    data = load_subscribers()
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, data)

def deactivate_subscription(user_id):
    data = load_subscribers()
    if str(user_id) in data:
        data.pop(str(user_id))
    save_json(SUBSCRIPTIONS_FILE, data)

def reset_daily_usage_if_needed(usage_data):
    today_str = datetime.now().strftime("%Y-%m-%d")
    if usage_data.get("date") != today_str:
        usage_data["date"] = today_str
        usage_data["video_downloads"] = {}
        usage_data["ai_requests"] = {}
    return usage_data

def increment_usage(user_id, usage_type):
    if is_subscribed(user_id) or user_id == ADMIN_ID:
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

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        "🚫 لقد وصلت للحد اليومي المجاني.\n"
        "للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج ماني:\n"
        "📲 الرقم: 0781200500\nثم اضغط على الزر أدناه وأرسل صورة التحويل.",
        reply_markup=keyboard
    )

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["waiting_for_proof"] = True

    await update.callback_query.edit_message_text(
        "💳 للاشتراك:\n"
        "أرسل 2 دينار عبر أورنج ماني إلى الرقم:\n"
        "📱 0781200500\n\n"
        "ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك.\n"
        "بمجرد إرسال صورة إثبات الدفع ستصل للأدمن مباشرة!"
    )

async def receive_subscription_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.user_data.get("waiting_for_proof"):
        return  # تجاهل أي صور ليست كإثبات دفع

    photo_file = await update.message.photo[-1].get_file()
    os.makedirs(PROOFS_DIR, exist_ok=True)
    photo_path = f"{PROOFS_DIR}/{user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    await photo_file.download_to_drive(photo_path)
    context.user_data["waiting_for_proof"] = False

    # أرسل الصورة للأدمن مع أزرار تأكيد ورفض
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    caption = f"📩 طلب اشتراك جديد\nاسم المستخدم: @{user.username or 'NO_USERNAME'}\nID: {user.id}"
    with open(photo_path, "rb") as f:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=f,
            caption=caption,
            reply_markup=keyboard
        )
    await update.message.reply_text("✅ تم استلام إثبات الدفع، سيقوم الأدمن بمراجعة الاشتراك.")

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن الاستخدام غير المحدود.")
    await query.edit_message_text("✅ تم تفعيل اشتراك المستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await query.edit_message_text("🚫 تم رفض الاشتراك.")

# ========= فيديو وصوت ============
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    # حدود الاستخدام
    if not is_subscribed(user.id) and user.id != ADMIN_ID:
        allowed = increment_usage(user.id, "video")
        if not allowed:
            await send_limit_message(update)
            return

    text = update.message.text.strip()

    if not is_valid_url(text):
        if not is_subscribed(user.id) and user.id != ADMIN_ID:
            allowed = increment_usage(user.id, "ai")
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
        # جرب أي جودة موجودة
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
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")

    url_store.pop(key, None)
    try:
        await loading_msg.delete()
    except:
        pass

# ============ لوحة الأدمن =============
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
        [InlineKeyboardButton("📝 المشتركين", callback_data="admin_paidusers")],
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
        if not os.path.exists(USERS_FILE):
            await query.edit_message_text("لا يوجد مستخدمين حالياً.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]))
            return
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        count = len(users)
        recent = "\n\n📌 آخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.split("|")
            recent += f"👤 {name} | @{username} | ID: {uid}\n"
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل لي الإعلان (نص أو صورة أو فيديو أو صوت):")
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
            "📥 أرسل آيدي المستخدم الذي تريد إضافته كمشترك مدفوع.\nمثال: 123456789",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]])
        )
        context.user_data["waiting_for_addpaid"] = True

    elif data == "admin_paidusers":
        subs = load_subscribers()
        text = "👑 قائمة المشتركين المدفوعين:\n\n"
        buttons = []
        if not subs:
            text += "لا يوجد مشتركين حالياً."
        else:
            for uid, info in subs.items():
                # جلب الاسم واليوزر
                username, fullname = "NO_USERNAME", ""
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
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.")

    elif data == "admin_back":
        await admin_panel(update, context)

    elif data.startswith("cancel_subscribe|"):
        _, user_id = data.split("|")
        deactivate_subscription(user_id)
        await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_paidusers")]
        ]))
        await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")

# =========== استقبال الإعلان ===========
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
            btns = []
            for u in users:
                uid, username, name = u.split("|")
                if query_text == uid or query_text.lower() in username.lower() or query_text in name.lower():
                    results.append(f"👤 {name} | @{username} | ID: {uid}")
                    if username != "NO_USERNAME":
                        btns.append([InlineKeyboardButton("مراسلة", url=f"https://t.me/{username}")])
            reply = "نتائج البحث:\n" + "\n".join(results) if results else "⚠️ لم يتم العثور على مستخدم."
        except Exception as e:
            reply = f"⚠️ خطأ في البحث: {e}"
        await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(btns) if btns else None)
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
                elif message.audio:
                    await context.bot.send_audio(uid, message.audio.file_id, caption=message.caption or "")
                elif message.text:
                    await context.bot.send_message(uid, message.text)
                sent += 1
            except:
                pass
        await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.")
    except Exception as e:
        await query.edit_message_text(f"🚫 خطأ أثناء الإرسال: {e}")

# ========== أوامر ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، أرسل إثبات الدفع إلى أورنج ماني: 0781200500 واضغط اشترك الآن."
    )

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

# ========== الربط وتشغيل الويب هوك ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("admin", admin_panel))

    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_subscription_proof))

    application.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    application.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
    application.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^cancel_subscribe\\|"))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\|"))
    application.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    application.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), media_handler))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
