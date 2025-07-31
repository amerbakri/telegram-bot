import os
import json
import subprocess
import re
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import openai

# ————— Logging —————
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ————— Configuration —————
ADMIN_ID = 337597459
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ضع_توكن_البوت_هنا"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "ضع_مفتاح_OPENAI_هنا"
COOKIES_FILE = "cookies.txt"
USERS_FILE = "users.txt"
SUBSCRIPTIONS_FILE = "subscriptions.json"
LIMITS_FILE = "limits.json"
ORANGE_NUMBER = "0781200500"
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

openai.api_key = OPENAI_API_KEY

# ————— State variables —————
url_store = {}                   # message_id → URL for download
pending_subs = set()             # user_ids awaiting subscription approval
open_chats = set()               # user_ids in active support chat
admin_reply_to = {}              # ADMIN_ID → user_id for next reply
admin_broadcast_mode = False     # True when admin is typing broadcast

# ————— Quality map updated —————
quality_map = {
    "720": "bestvideo[height<=720]+bestaudio/best",
    "480": "bestvideo[height<=480]+bestaudio/best",
    "360": "bestvideo[height<=360]+bestaudio/best",
}

# ————— Helper functions —————
def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default if default is not None else {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def store_user(user):
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
    entry = f"{user.id}|{user.username or 'NO'}|{user.first_name or ''} {user.last_name or ''}".strip()
    if all(str(user.id) not in line for line in lines):
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")


def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?"
        r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None


def is_subscribed(uid):
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    return str(uid) in subs and subs[str(uid)].get("active", False)


def activate_subscription(uid):
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    subs[str(uid)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, subs)


def deactivate_subscription(uid):
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    subs.pop(str(uid), None)
    save_json(SUBSCRIPTIONS_FILE, subs)


def check_limits(uid, action):
    if is_subscribed(uid):
        return True
    today = datetime.utcnow().strftime("%Y-%m-%d")
    limits = load_json(LIMITS_FILE, {})
    u = limits.get(str(uid), {})
    if u.get("date") != today:
        u = {"date": today, "video": 0, "ai": 0}
    if action == "video" and u["video"] >= DAILY_VIDEO_LIMIT:
        return False
    if action == "ai" and u["ai"] >= DAILY_AI_LIMIT:
        return False
    u[action] += 1
    limits[str(uid)] = u
    save_json(LIMITS_FILE, limits)
    return True


async def safe_edit(query, text, kb=None):
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except:
        pass


def fullname(user):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

# ————— /start —————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    kb = [
        [InlineKeyboardButton("💬 دعم", callback_data="support_start")],
        [InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")]
    ]
    if user.id == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠️ لوحة الأدمن", callback_data="admin_panel")])
    await update.message.reply_text(
        f"👋 أهلاً! أرسل رابط فيديو أو استفسار AI.\n"
        f"مجاناً: {DAILY_VIDEO_LIMIT} فيديو و {DAILY_AI_LIMIT} استفسار يومياً.\n"
        f"مدفوع: 2 دينار عبر أورنج ماني {ORANGE_NUMBER}.",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def send_limit_message(update: Update):
    keyboard = [
    [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{msg_id}")],
    [
        InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{msg_id}"),
        InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{msg_id}"),
        InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{msg_id}")
    ],
    [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{msg_id}")]
]
kb = InlineKeyboardMarkup(keyboard)
await update.message.reply_text("اختر الجودة أو صوت فقط:", reply_markup=kb))

# ————— Admin reply/close buttons —————
async def admin_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        return
    _, user_id = q.data.split("|", 1)
    admin_reply_to[ADMIN_ID] = int(user_id)
    await q.answer("اكتب ردك الآن.")
    await safe_edit(q, f"اكتب رد للمستخدم {user_id}:")


async def admin_close_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        return
    _, user_id = q.data.split("|", 1)
    open_chats.discard(int(user_id))
    await context.bot.send_message(int(user_id), "❌ أُغلق الدعم من الأدمن.")
    await safe_edit(q, f"تم إغلاق دعم {user_id}.")

# ————— Admin panel —————
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🟢 مدفوعين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_panel_close")],
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text("🛠️ لوحة تحكم الأدمن:", reply_markup=kb)
    else:
        await update.message.reply_text("🛠️ لوحة تحكم الأدمن:", reply_markup=kb)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        return
    data = q.data
    global admin_broadcast_mode
    if data == "admin_users":
        lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
        users = []
        for line in lines:
            uid, username, fullname = line.split("|", 2)
            if username and username != "NO":
                users.append(f"@{username}")
            elif fullname.strip():
                users.append(fullname.strip())
            else:
                users.append(uid)
        txt = f"👥 عدد المستخدمين: {len(users)}\n" + "\n".join(users)
        await safe_edit(q, txt)
    elif data == "admin_broadcast":
        admin_broadcast_mode = True
        await safe_edit(q, "📝 اكتب نص الإعلان:")
    elif data == "admin_paidlist":
        subs = load_json(SUBSCRIPTIONS_FILE, {})
        txt = "💰 مشتركون مدفوعون:\n" + ("\n".join(subs.keys()) or "لا أحد")
        await safe_edit(q, txt)
    else:
        try:
            await q.message.delete()
        except:
            pass

# ————— Download / Audio-Video button —————
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    action, quality, msg_id = q.data.split("|", 2)

    # cancel
    if action == "cancel":
        await q.message.delete()
        url_store.pop(msg_id, None)
        return

    url = url_store.get(msg_id)
    if not url:
        await q.answer("انتهت صلاحية الرابط.")
        return

    await q.edit_message_text("⏳ جاري التحميل...")

    outfile = "video.mp4"
    if action == "audio":
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "--extract-audio", "--audio-format", "mp3",
            "-o", outfile, url
        ]
        caption = "🎵 صوت فقط"
    else:
        fmt = quality_map.get(quality, "best")
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", fmt,
            "-o", outfile, url
        ]
        caption = f"🎬 جودة {quality}p"

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        await context.bot.send_message(
            uid,
            f"❌ فشل التحميل بالصيفة المطلوبة ({fmt}). حاول جودة أخرى أو رابط مختلف.\n\n{e}"
        )
        url_store.pop(msg_id, None)
        return

    # إرسال الملف
    with open(outfile, "rb") as f:
        if action == "audio":
            await context.bot.send_audio(uid, f, caption=caption)
        else:
            await context.bot.send_video(uid, f, caption=caption)

    # تنظيف
    if os.path.exists(outfile):
        os.remove(outfile)
    url_store.pop(msg_id, None)
    try:
        await q.message.delete()
    except:
        pass

# ————— Register handlers and start —————
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(subscribe_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_sub, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_sub, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(support_button, pattern="^support_(start|end)$"))
app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, support_media_router))
app.add_handler(MessageHandler(filters.VIDEO & ~filters.COMMAND, support_media_router))
app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, support_media_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
app.add_handler(CallbackQueryHandler(admin_reply_button, pattern="^admin_reply\\|"))
app.add_handler(CallbackQueryHandler(admin_close_button, pattern="^admin_close\\|"))
app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8443))
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{host}/{BOT_TOKEN}"
    )
