import os
import json
import subprocess
import re
import logging
from datetime import datetime, timezone
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

# ————— State —————
url_store = {}             # msg_id → URL
pending_subs = set()       # user_ids awaiting subscription approval
open_chats = set()         # user_ids in active support chat
admin_reply_to = {}        # mapping ADMIN_ID → user_id to reply to
admin_broadcast_mode = False

# ————— Quality map —————
quality_map = {
    "720": "bestvideo[height<=720]+bestaudio/best",
    "480": "bestvideo[height<=480]+bestaudio/best",
    "360": "bestvideo[height<=360]+bestaudio/best",
}

# ————— Helper functions —————
def load_json(path, default=None):
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default or {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def store_user(user):
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    existing = set()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            existing.add(line.split("|",1)[0])
    entry = f"{user.id}|{user.username or 'NO'}|{user.first_name or ''} {user.last_name or ''}".strip()
    if str(user.id) not in existing:
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")


def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None


def is_subscribed(uid):
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    return subs.get(str(uid), {}).get("active", False)


def activate_subscription(uid):
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    subs[str(uid)] = {"active": True, "date": datetime.now(timezone.utc).isoformat()}
    save_json(SUBSCRIPTIONS_FILE, subs)


def deactivate_subscription(uid):
    subs = load_json(SUBSCRIPTIONS_FILE, {})
    subs.pop(str(uid), None)
    save_json(SUBSCRIPTIONS_FILE, subs)


def check_limits(uid, action):
    if is_subscribed(uid):
        return True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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

# ————— Handlers —————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    if user.id == ADMIN_ID:
        kb = [[InlineKeyboardButton("🛠️ لوحة الأدمن", callback_data="admin_panel")]]
    else:
        kb = [
            [InlineKeyboardButton("💬 دعم", callback_data="support_start")],
            [InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")]
        ]
    await update.message.reply_text(
        f"👋 أهلاً! أرسل رابط فيديو أو استفسار AI.\n"
        f"مجاناً: {DAILY_VIDEO_LIMIT} فيديو و {DAILY_AI_LIMIT} استفسار يومياً.\n"
        f"مدفوع: 2 دينار عبر أورنج ماني {ORANGE_NUMBER}.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def send_limit_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")]
    ])
    await update.message.reply_text("🚫 انتهى الحد المجاني.", reply_markup=kb)

async def subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id in pending_subs:
        await update.callback_query.answer("طلبك قيد المراجعة.")
        return
    pending_subs.add(u.id)
    info = f"📥 طلب اشتراك: @{u.username or 'NO'} | ID: {u.id}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{u.id}"),
         InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{u.id}")]
    ])
    await context.bot.send_message(ADMIN_ID, info, reply_markup=kb)
    await update.callback_query.edit_message_text("✅ طلبك أُرسل للأدمن.")

async def confirm_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, uid = update.callback_query.data.split("|", 1)
    activate_subscription(int(uid))
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "✅ اشتراكك مفعل!")
    await safe_edit(update.callback_query, "✅ تم التفعيل.")

async def reject_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, uid = update.callback_query.data.split("|", 1)
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ تم رفض طلبك.")
    await safe_edit(update.callback_query, "🚫 تم الرفض.")

async def support_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if q.data == "support_start":
        open_chats.add(uid)
        await q.answer("تم فتح الدعم.")
        await q.edit_message_text("💬 الدعم مفتوح. أرسل رسالتك.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق", callback_data="support_end")]]))
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ دعم جديد من {uid}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{uid}"), InlineKeyboardButton("❌ إنهاء", callback_data=f"admin_close|{uid}")]])
        )
    else:
        open_chats.discard(uid)
        await q.answer("تم إغلاق الدعم.")
        await q.edit_message_text("❌ تم إغلاق الدعم.")

async def support_media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id in open_chats:
        await update.message.forward(chat_id=ADMIN_ID)
        await update.message.reply_text("✅ أرسلت للأدمن.")
        return
    if u.id == ADMIN_ID and admin_broadcast_mode:
        users = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
        sent = 0
        if update.message.photo:
            media = update.message.photo[-1].file_id
            caption = update.message.caption or ''
            for line in users:
                try:
                    await context.bot.send_photo(int(line.split("|",1)[0]), media, caption=caption)
                    sent += 1
                except:
                    pass
        elif update.message.video:
            media = update.message.video.file_id
            caption = update.message.caption or ''
            for line in users:
                try:
                    await context.bot.send_video(int(line.split("|",1)[0]), media, caption=caption)
                    sent += 1
                except:
                    pass
        admin_broadcast_mode = False
        await update.message.reply_text(f"📢 أرسلت الإعلان إلى {sent} مستخدم.")

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_broadcast_mode
    u = update.effective_user
    text = update.message.text or ''
    # Support chat
    if u.id in open_chats:
        await context.bot.send_message(ADMIN_ID, f"من {u.id}: {text}")
        await update.message.reply_text("✅ أرسلت للأدمن.")
        return
    # Admin broadcast
    if u.id == ADMIN_ID and admin_broadcast_mode:
        users = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
        sent = 0
        for line in users:
            try:
                await context.bot.send_message(int(line.split("|",1)[0]), text)
                sent += 1
            except:
                pass
        admin_broadcast_mode = False
        await update.message.reply_text(f"📢 أرسلت الإعلان إلى {sent} مستخدم.")
        return
    store_user(u)
    # AI chat
    if text and not is_valid_url(text):
        if not check_limits(u.id, "ai"):
            await send_limit_message(update, context)
            return
        res = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":text}])
        await update.message.reply_text(res.choices[0].message.content)
        return
    # Video flow
    if is_valid_url(text):
        if not check_limits(u.id, "video"):
            await send_limit_message(update, context)
            return
        msg_id = str(update.message.message_id)
        url_store[msg_id] = text
        keyboard = [
            [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{msg_id}")],
            [InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{msg_id}"), InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{msg_id}"), InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{msg_id}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{msg_id}")]
        ]
        kb = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("اختر الجودة أو صوت فقط:", reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    action, qual, msg_id = q.data.split("|", 2)
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
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", "bestaudio[ext=m4a]/bestaudio/best", "--extract-audio", "--audio-format", "mp3", "-o", outfile, url]
        cap = "🎵 صوت فقط"
    else:
        fmt = quality_map.get(qual, "best")
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", fmt, "-o", outfile, url]
        cap = f"🎬 جودة {qual}p"
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        await context.bot.send_message(uid, f"❌ خطأ: {e}")
        url_store.pop(msg_id, None)
        return
    with open(outfile, "rb") as f:
        if action == "audio":
            await context.bot.send_audio(uid, f, caption=cap)
        else:
            await context.bot.send_video(uid, f, caption=cap)
    if os.path.exists(outfile): os.remove(outfile)
    url_store.pop(msg_id, None)
    try:
        await q.message.delete()
    except:
        pass

async def admin_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID: return
    _, uid = q.data.split("|",1)
    admin_reply_to[ADMIN_ID] = int(uid)
    await q.answer("اكتب ردك الآن.")
    await safe_edit(q, f"اكتب رد للمستخدم {uid}:")

async def admin_close_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID: return
    _, uid = q.data.split("|",1)
    open_chats.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ أُغلق الدعم.")
    await safe_edit(q, f"تم إغلاق دعم {uid}.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🟢 مدفوعين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_panel_close")],
    ])
    if update.callback_query: await update.callback_query.edit_message_text("🛠️ لوحة الأدمن:", reply_markup=kb)
    else: await update.message.reply_text("🛠️ لوحة الأدمن:", reply_markup=kb)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID: return
    data = q.data; global admin_broadcast_mode
    if data == "admin_users":
        lines = open(USERS_FILE,"r",encoding="utf-8").read().splitlines()
        users = [l.split("|",2)[1] or l.split("|",2)[0] for l in lines]
        txt = f"👥 مستخدمون ({len(users)}):\n" + "\n".join(users)
        await safe_edit(q, txt)
    elif data == "admin_broadcast":
        admin_broadcast_mode = True
        await safe_edit(q, "📝 اكتب نص / وسائط للإعلان:")
    elif data == "admin_paidlist":
        subs = load_json(SUBSCRIPTIONS_FILE,{})
        p = [f"@{k}" for k in subs.keys()]
        await safe_edit(q, "💰 مشتركون مدفوعون:\n" + ("\n".join(p) if p else "لا أحد"))
    else:
        await q.message.delete()

# ————— Register & Run —————
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(subscribe_request, pattern=r"^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_sub,    pattern=r"^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_sub,     pattern=r"^reject_sub\|"))
app.add_handler(CallbackQueryHandler(support_button, pattern=r"^support_(start|end)$"))
app.add_handler(MessageHandler((filters.PHOTO|filters.VIDEO|filters.Document.ALL)&~filters.COMMAND, support_media_router))
app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND, message_router))
app.add_handler(CallbackQueryHandler(button_handler,        pattern=r"^(video|audio|cancel)\|"))
app.add_handler(CallbackQueryHandler(admin_reply_button,   pattern=r"^admin_reply\|"))
app.add_handler(CallbackQueryHandler(admin_close_button,   pattern=r"^admin_close\|"))
app.add_handler(CallbackQueryHandler(admin_panel,          pattern=r"^admin_panel$"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin_"))

if __name__ == '__main__':
    port = int(os.getenv("PORT", 8443))
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen='0.0.0.0',
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{host}/{BOT_TOKEN}"
    )
