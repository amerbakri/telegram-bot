import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime, date
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# إعدادات أساسية
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"
ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5
ORANGE_NUMBER = "0781200500"

openai.api_key = OPENAI_API_KEY
url_store = {}
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w", encoding="utf-8"): pass
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def is_subscribed(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, data)

def deactivate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    if str(user_id) in data: data.pop(str(user_id))
    save_json(SUBSCRIPTIONS_FILE, data)

def check_limits(user_id, action):
    if is_subscribed(user_id) or user_id == ADMIN_ID: return True
    today = date.today().isoformat()
    limits = load_json(LIMITS_FILE, {})
    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}
    if action == "video" and user_limits["video"] >= DAILY_VIDEO_LIMIT: return False
    if action == "ai" and user_limits["ai"] >= DAILY_AI_LIMIT: return False
    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    save_json(LIMITS_FILE, limits)
    return True

def update_stats(action, quality):
    stats = load_json(STATS_FILE, {
        "total_downloads": 0,
        "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
        "most_requested_quality": None
    })
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    stats["quality_counts"][key] = stats["quality_counts"].get(key, 0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_json(STATS_FILE, stats)

# =========== رسالة تجاوز الحد المجاني ============
async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        f"🚫 لقد وصلت للحد المجاني اليومي.\n\n"
        f"للاستخدام غير محدود، اشترك بـ <b>2 دينار</b> شهريًا عبر أورنج ماني:\n"
        f"📲 الرقم: <b>{ORANGE_NUMBER}</b>\nثم اضغط الزر وارسِل اسمك واسم المستخدم فقط.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# == استقبال طلب الاشتراك == #
async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.callback_query.edit_message_text(
        f"💳 للاشتراك:\nأرسل 2 دينار عبر أورنج كاش إلى الرقم:\n<b>{ORANGE_NUMBER}</b>\n\n"
        f"ثم أرسل اسمك واسم المستخدم فقط ليتم تفعيل الاشتراك.",
        parse_mode="HTML"
    )
    await context.bot.send_message(
        ADMIN_ID,
        f"طلب اشتراك جديد من:\nاسم المستخدم: @{user.username or 'NO_USERNAME'}\nالآيدي: {user.id}\nالاسم: {user.first_name or ''} {user.last_name or ''}"
    )
    await update.callback_query.answer("✅ تم إرسال التعليمات.")

# == استقبال اسم/مستخدم لتوثيق الاشتراك == #
async def receive_subscription_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.text:
        info_msg = f"🟢 طلب اشتراك جديد:\n"
        info_msg += f"الاسم: <b>{user.first_name or ''} {user.last_name or ''}</b>\n"
        info_msg += f"اسم المستخدم: @{user.username or 'NO_USERNAME'}\n"
        info_msg += f"ID: <code>{user.id}</code>"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
                InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
            ]
        ])
        await context.bot.send_message(
            ADMIN_ID, info_msg, reply_markup=keyboard, parse_mode="HTML"
        )
        await update.message.reply_text(
            "✅ تم استلام بيانات الاشتراك، جاري المراجعة من قبل الأدمن..."
        )
    else:
        await update.message.reply_text("❌ أرسل اسمك واسم المستخدم فقط، بدون صور.")

# == تأكيد / رفض الاشتراك من الأدمن == #
async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await context.bot.send_message(chat_id=int(user_id), text="✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن استخدام جميع ميزات البوت.")
    await query.answer("✅ تم التفعيل.")
    await query.edit_message_text("✅ تم تفعيل اشتراك المستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await context.bot.send_message(chat_id=int(user_id), text="❌ تم رفض طلب الاشتراك.")
    await query.answer("🚫 تم الرفض.")
    await query.edit_message_text("🚫 تم رفض الاشتراك.")

# == تحميل الفيديوهات وكل شيء == #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 <b>مرحبًا بك في بوت التحميل والذكاء الاصطناعي!</b>\n\n"
        "✨ أرسل رابط فيديو من YouTube أو TikTok أو Facebook أو Instagram للتحميل.\n"
        "🎵 أو أرسل أي سؤال وسنجيبك باستخدام الذكاء الاصطناعي.\n\n"
        "🟢 الاستخدام المجاني: 3 فيديو و5 استفسارات يوميًا.\n"
        f"🔒 للاشتراك المدفوع: أرسل 2 دينار إلى <b>{ORANGE_NUMBER}</b>، ثم اضغط /subscribe وأرسل اسمك واسم المستخدم.",
        parse_mode="HTML"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)
    msg = update.message.text.strip()
    # ذكاء اصطناعي
    if not is_valid_url(msg):
        if not check_limits(user.id, "ai"):
            await send_limit_message(update)
            return
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": msg}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
        return

    # تحميل فيديو
    if not check_limits(user.id, "video"):
        await send_limit_message(update)
        return

    key = str(update.message.message_id)
    url_store[key] = msg
    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("📥 <b>اختر الجودة أو نوع التحميل:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

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
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")
    url_store.pop(key, None)
    try: await loading_msg.delete()
    except: pass

# == لوحة تحكم الأدمن: إعلانات نص/صورة/فيديو ==
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        elif update.callback_query:
            await update.callback_query.answer("⚠️ هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🟢 قائمة المشتركين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- أدمن: استقبال الإعلان وحفظه مؤقتاً بانتظار التأكيد
async def admin_callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return
    if data == "admin_broadcast":
        await query.edit_message_text(
            "📝 أرسل نص أو صورة أو فيديو ليتم إرساله إعلان لجميع المستخدمين.\n"
            "بعد الإرسال سيظهر لك زر التأكيد."
        )
        ctx.user_data["waiting_for_announcement"] = True
        ctx.user_data["announcement_message"] = None
    elif data == "admin_paidlist":
        data = load_json(SUBSCRIPTIONS_FILE, {})
        if not data:
            await query.edit_message_text("لا يوجد مشتركين مدفوعين.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")]
            ]))
            return
        buttons = []
        text = "🟢 قائمة المشتركين:\n\n"
        for uid, info in data.items():
            username = "NO_USERNAME"
            fullname = ""
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, "r", encoding="utf-8") as uf:
                    for line in uf:
                        if line.startswith(uid + "|"):
                            parts = line.strip().split("|")
                            username = parts[1]
                            fullname = parts[2]
                            break
            text += f"👤 {fullname} (@{username}) — ID: {uid}\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء {username}", callback_data=f"cancel_subscribe|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())

# --- استقبال إعلان (نص أو صورة أو فيديو) وحفظه مؤقتاً
async def media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("waiting_for_announcement"):
        return
    ctx.user_data["announcement_message"] = update.message
    ctx.user_data["waiting_for_announcement"] = False
    await update.message.reply_text(
        "✅ هل تريد تأكيد الإرسال؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ إرسال الإعلان", callback_data="confirm_broadcast")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_close")]
        ])
    )

async def confirm_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = ctx.user_data.get("announcement_message")
    if not message:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    sent = 0
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if not l or l.startswith("{"): continue
            uid = int(l.split("|")[0])
            try:
                if message.photo:
                    await ctx.bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
                elif message.video:
                    await ctx.bot.send_video(uid, message.video.file_id, caption=message.caption or "")
                elif message.text:
                    await ctx.bot.send_message(uid, message.text)
                sent += 1
            except Exception:
                continue
    await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.")

# == ربط جميع الهاندلرز ==
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", handle_subscription_request))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
    app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
    app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO) & filters.User(ADMIN_ID),
        media_handler
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.User(ADMIN_ID), receive_subscription_info))

    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
