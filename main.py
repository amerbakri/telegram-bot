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
admin_reply_to = {}              # ADMIN_ID → user_id whom admin will reply to
admin_broadcast_mode = False     # True when admin is typing a broadcast message

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# ————— Helper functions —————
def load_json(path, default=None):
    """Load JSON from file or return default."""
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default if default is not None else {}

def save_json(path, data):
    """Save JSON data to file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def store_user(user):
    """Persist user to USERS_FILE if new."""
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
    entry = f"{user.id}|{user.username or 'NO'}|{user.first_name or ''} {user.last_name or ''}"
    if all(str(user.id) not in line for line in lines):
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

def is_valid_url(text):
    """Check if text is a supported video URL."""
    return re.match(
        r"^(https?://)?(www\.)?"
        r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def is_subscribed(uid):
    """Check if user has active paid subscription."""
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    return str(uid) in subs and subs[str(uid)].get("active", False)

def activate_subscription(uid):
    """Activate paid subscription for user."""
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    subs[str(uid)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, subs)

def deactivate_subscription(uid):
    """Deactivate paid subscription for user."""
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    subs.pop(str(uid), None)
    save_json(SUBSCRIPTIONS_FILE, subs)

def check_limits(uid, action):
    """
    Enforce daily limits for free users.
    action: "video" or "ai"
    """
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
    """Try to edit message text without raising."""
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except Exception:
        pass

def fullname(user):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

# ————— Command /start —————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    kb = [
        [InlineKeyboardButton("💬 دعم", callback_data="support_start")],
        [InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")],
    ]
    if user.id == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠️ لوحة الأدمن", callback_data="admin_panel")])
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو أو استفسار AI.\n"
        f"مجاناً: {DAILY_VIDEO_LIMIT} فيديو و {DAILY_AI_LIMIT} استفسار AI يومياً.\n"
        f"مدفوع: 2 دينار عبر أورنج ماني {ORANGE_NUMBER}.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ————— Limit reached message —————
async def send_limit_message(update: Update):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")]])
    await update.message.reply_text("🚫 انتهى الحد المجاني.", reply_markup=kb)

# ————— Subscription Handlers —————
async def subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicks 'اشترك' → send request to admin."""
    u = update.effective_user
    if u.id in pending_subs:
        await update.callback_query.answer("طلبك قيد المراجعة.")
        return
    pending_subs.add(u.id)
    info = f"📥 طلب اشتراك:\n{fullname(u)} | @{u.username or 'NO'} | ID: {u.id}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{u.id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{u.id}")
    ]])
    await context.bot.send_message(ADMIN_ID, info, reply_markup=kb)
    await update.callback_query.edit_message_text("✅ طلبك أُرسل للأدمن.")

async def confirm_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin approves subscription."""
    _, uid = update.callback_query.data.split("|")
    activate_subscription(uid)
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "✅ اشتراكك مفعل!")
    await safe_edit(update.callback_query, "✅ تم التفعيل.")

async def reject_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin rejects subscription."""
    _, uid = update.callback_query.data.split("|")
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ تم رفض طلبك.")
    await safe_edit(update.callback_query, "🚫 تم الرفض.")

# ————— Support Handlers —————
async def support_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle support start/end buttons."""
    q = update.callback_query
    uid = q.from_user.id
    if q.data == "support_start":
        if uid in open_chats:
            await q.answer("الدعم مفتوح بالفعل.")
            return
        open_chats.add(uid)
        await q.answer("تم فتح الدعم.")
        await q.edit_message_text(
            "💬 الدعم مفتوح. ارسل رسالتك الآن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق", callback_data="support_end")]])
        )
        # Notify admin
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ دعم جديد من المستخدم {uid}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{uid}"),
                InlineKeyboardButton("❌ إنهاء", callback_data=f"admin_close|{uid}")
            ]])
        )
    else:  # support_end
        open_chats.discard(uid)
        await q.answer("تم إغلاق الدعم.")
        await q.edit_message_text("❌ تم إغلاق الدعم.")

# ————— Message Router —————
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Routes incoming text messages to:
    1) support chat
    2) admin reply
    3) admin broadcast
    4) AI chat
    5) video download
    """
    u = update.effective_user
    text = update.message.text.strip()

    # 1) If user in support chat → forward to admin
    if u.id in open_chats:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{u.id}")]])
        await context.bot.send_message(ADMIN_ID, f"من {u.id}:\n{text}", reply_markup=kb)
        await update.message.reply_text("✅ أرسلت للأدمن.")
        return

    # 2) Admin replying to user
    if u.id == ADMIN_ID and ADMIN_ID in admin_reply_to:
        to_id = admin_reply_to.pop(ADMIN_ID)
        await context.bot.send_message(to_id, f"📩 رد الأدمن:\n{text}")
        await update.message.reply_text("✅ تم الإرسال.")
        return

    # 3) Admin broadcast mode
    global admin_broadcast_mode
    if u.id == ADMIN_ID and admin_broadcast_mode:
        admin_broadcast_mode = False
        users = [l.split("|")[0] for l in open(USERS_FILE,"r",encoding="utf-8") if l.strip()]
        sent = 0
        for uid in users:
            try:
                await context.bot.send_message(int(uid), text)
                sent += 1
            except:
                pass
        await update.message.reply_text(f"📢 أرسلت الإعلان إلى {sent} مستخدم.")
        return

    # 4) AI chat for regular users (text that is not URL)
    store_user(u)
    if not is_valid_url(text):
        if u.id == ADMIN_ID:
            return
        if not check_limits(u.id, "ai"):
            await send_limit_message(update)
            return
        try:
            res = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role":"user","content":text}]
            )
            await update.message.reply_text(res.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return

    # 5) Download flow (text is URL)
    if not check_limits(u.id, "video"):
        await send_limit_message(update)
        return

    msg_id = str(update.message.message_id)
    url_store[msg_id] = text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{msg_id}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{msg_id}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{msg_id}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{msg_id}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{msg_id}")]
    ])
    await update.message.reply_text("اختر الجودة أو صوت فقط:", reply_markup=kb)

# ————— Admin reply/close buttons —————
async def admin_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        return
    _, user_id = q.data.split("|")
    admin_reply_to[ADMIN_ID] = int(user_id)
    await q.answer("اكتب ردك الآن.")
    await safe_edit(q, f"اكتب رد للمستخدم {user_id}:")

async def admin_close_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        return
    _, user_id = q.data.split("|")
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
        count = len(open(USERS_FILE,"r",encoding="utf-8").read().splitlines())
        await safe_edit(q, f"👥 عدد المستخدمين: {count}")
    elif data == "admin_broadcast":
        admin_broadcast_mode = True
        await safe_edit(q, "📝 اكتب نص الإعلان:")
    elif data == "admin_paidlist":
        subs = load_json(SUBSCRIPTIONS_FILE, {})
        txt = "💰 مشتركون مدفوعون:\n" + ("\n".join(subs.keys()) or "لا أحد")
        await safe_edit(q, txt)
    else:  # close panel
        try:
            await q.message.delete()
        except:
            pass

# ————— Download / Audio-Video button —————
# ————— Download / Audio-Video button —————
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    action, quality, msg_id = q.data.split("|")

    # إلغاء الطلب
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

    # بعد النجاح، أرسل الملف
    with open(outfile, "rb") as f:
        if action == "audio":
            await context.bot.send_audio(uid, f, caption=caption)
        else:
            await context.bot.send_video(uid, f, caption=caption)

    # تنظيف الملفات المؤقتة
    if os.path.exists(outfile):
        os.remove(outfile)
    url_store.pop(msg_id, None)
    try:
        await q.message.delete()
    except:
        pass


# ————— Register handlers and start —————
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Commands & callbacks
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(subscribe_request,   pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_sub,         pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_sub,          pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(support_button,      pattern="^support_(start|end)$"))
app.add_handler(CallbackQueryHandler(admin_reply_button,  pattern="^admin_reply\\|"))
app.add_handler(CallbackQueryHandler(admin_close_button,  pattern="^admin_close\\|"))
app.add_handler(CallbackQueryHandler(admin_panel,         pattern="^admin_panel$"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
# Messages
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
# Download buttons
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
