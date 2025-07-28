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

admin_chats = {}

# =========== جميع الهاندلرز الخاصة بالإعلانات ============= #
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
    # باقي أوامر الأدمن (نسخ كما بالكود السابق...)

# استقبال الإعلان (نص أو صورة أو فيديو) وحفظه مؤقتًا بانتظار التأكيد
async def media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("waiting_for_announcement"):
        return
    ctx.user_data["announcement_message"] = update.message
    ctx.user_data["waiting_for_announcement"] = False
    await update.message.reply_text(
        "✅ هل تريد تأكيد الإرسال؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ إرسال الإعلان", callback_data="confirm_broadcast")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]
        ])
    )

# عند تأكيد الإرسال من الأدمن: إرسال الإعلان (أي نوع) لكل المستخدمين
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

# باقي الكود كما في النسخة السابقة
# ...

# -- إضافة الهاندلرز المناسبة --
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # ... باقي الهاندلرز
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern=r'^admin_broadcast$'))
    app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern=r'^confirm_broadcast$'))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO) & filters.User(ADMIN_ID),
        media_handler
    ))
    # ... باقي الهاندلرز
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
