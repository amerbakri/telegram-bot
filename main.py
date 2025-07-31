import os
import json
import subprocess
import re
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import openai

# ————— Configuration —————
ADMIN_ID           = 337597459
BOT_TOKEN          = os.getenv("BOT_TOKEN") or "ضع_توكن_البوت_هنا"
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY") or "ضع_مفتاح_OPENAI_هنا"
COOKIES_FILE       = "cookies.txt"
USERS_FILE         = "users.txt"
SUBSCRIPTIONS_FILE = "subscriptions.json"
LIMITS_FILE        = "limits.json"
ORANGE_NUMBER      = "0781200500"
DAILY_VIDEO_LIMIT  = 3
DAILY_AI_LIMIT     = 5

openai.api_key = OPENAI_API_KEY

# ————— Logging —————
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ————— State variables —————
url_store           = {}   # msg_id → URL
pending_subs        = set()
open_chats          = set()
admin_reply_to      = {}
admin_broadcast_mode = False

# ————— Quality map —————
quality_map = {
    "720": "bestvideo[height<=720]+bestaudio/best",
    "480": "bestvideo[height<=480]+bestaudio/best",
    "360": "bestvideo[height<=360]+bestaudio/best",
}

# ————— Helpers —————
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
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not any(line.split("|",1)[0] == str(user.id) for line in lines):
        entry = f"{user.id}|{user.username or 'NO'}|{user.first_name or ''} {user.last_name or ''}".strip()
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?"
        r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def load_subs():
    return load_json(SUBSCRIPTIONS_FILE, {})

def is_subscribed(uid):
    subs = load_subs()
    return subs.get(str(uid), {}).get("active", False)

def activate_subscription(uid):
    subs = load_subs()
    subs[str(uid)] = {"active": True, "date": datetime.now(timezone.utc).isoformat()}
    save_json(SUBSCRIPTIONS_FILE, subs)

def deactivate_subscription(uid):
    subs = load_subs()
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

def fullname(user):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

# ————— Error Handler —————
async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)

# ————— /start —————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)

    # Admin menu immediately
    if user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("📢 إعلان",           callback_data="admin_broadcast")],
            [InlineKeyboardButton("💬 دعم مباشر",      callback_data="admin_supports")],
            [InlineKeyboardButton("🟢 مدفوعين",        callback_data="admin_paidlist")],
            [InlineKeyboardButton("📊 إحصائيات",       callback_data="admin_stats")],
            [InlineKeyboardButton("❌ إغلاق",          callback_data="admin_panel_close")],
        ]
        await update.message.reply_text("اختر من القائمة:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Regular user
    if is_subscribed(user.id):
        subs = load_subs()
        date_iso = subs[str(user.id)]["date"]
        activated = datetime.fromisoformat(date_iso)
        days = (datetime.now(timezone.utc) - activated).days
        text = f"✅ اشتراكك مفعل منذ {days} يوم."
        keyboard = [[InlineKeyboardButton("💬 دعم", callback_data="support_start")]]
    else:
        text = "👋 أهلاً! استخدم الأزرار أدناه:"
        keyboard = [
            [InlineKeyboardButton("💬 دعم",     callback_data="support_start")],
            [InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")],
        ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ————— Subscription —————
async def subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id in pending_subs:
        await update.callback_query.answer("طلبك قيد المراجعة.")
        return
    pending_subs.add(u.id)
    info = f"📥 طلب اشتراك: {fullname(u)} | @{u.username or 'NO'} | ID: {u.id}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{u.id}"),
        InlineKeyboardButton("❌ رفض",    callback_data=f"reject_sub|{u.id}")
    ]])
    await context.bot.send_message(ADMIN_ID, info, reply_markup=kb)
    await update.callback_query.edit_message_text("✅ طلبك أُرسل للأدمن.")

async def confirm_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, uid = update.callback_query.data.split("|",1)
    activate_subscription(int(uid))
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "✅ اشتراكك مفعل!")
    await safe_edit(update.callback_query, "✅ تم التفعيل.")

async def reject_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, uid = update.callback_query.data.split("|",1)
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ تم رفض طلبك.")
    await safe_edit(update.callback_query, "🚫 تم الرفض.")

# ————— Support —————
async def support_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if q.data == "support_start":
        if uid in open_chats:
            await q.answer("الدعم مفتوح بالفعل.")
            return
        open_chats.add(uid)
        await q.answer("تم فتح الدعم.")
        await q.edit_message_text(
            "💬 الدعم مفوح. أرسل رسالتك الآن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق", callback_data="support_end")]])
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ دعم جديد من @{fullname(q.from_user)} ({uid})",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 رد",    callback_data=f"admin_reply|{uid}"),
                InlineKeyboardButton("❌ إنهاء", callback_data=f"admin_close|{uid}")
            ]])
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
    global admin_broadcast_mode
    if u.id == ADMIN_ID and admin_broadcast_mode:
        admin_broadcast_mode = False
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        sent = 0
        if update.message.photo:
            media = update.message.photo[-1].file_id
            cap = update.message.caption or ""
            for l in lines:
                uid = int(l.split("|",1)[0])
                try:
                    await context.bot.send_photo(uid, media, caption=cap)
                    sent += 1
                except: pass
        elif update.message.video:
            media = update.message.video.file_id
            cap = update.message.caption or ""
            for l in lines:
                uid = int(l.split("|",1)[0])
                try:
                    await context.bot.send_video(uid, media, caption=cap)
                    sent += 1
                except: pass
        await update.message.reply_text(f"📢 أرسلت الإعلان إلى {sent} مستخدم.")

# ————— Message Router —————
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_broadcast_mode
    u = update.effective_user
    text = (update.message.text or "").strip()

    # 1) Support chat
    if u.id in open_chats:
        await context.bot.send_message(
            ADMIN_ID,
            f"من @{fullname(u)} ({u.id}):\n{text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{u.id}")]])
        )
        await update.message.reply_text("✅ أرسلت للأدمن.")
        return

    # 2) Admin reply to user
    if u.id == ADMIN_ID and ADMIN_ID in admin_reply_to:
        to_id = admin_reply_to.pop(ADMIN_ID)
        await context.bot.send_message(to_id, f"📩 رد الأدمن:\n{text}")
        await update.message.reply_text("✅ تم الإرسال.")
        return

    # 3) Admin broadcast text
    if u.id == ADMIN_ID and admin_broadcast_mode and not getattr(update.message, "media_group_id", None):
        admin_broadcast_mode = False
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        sent = 0
        for l in lines:
            uid = int(l.split("|",1)[0])
            try:
                await context.bot.send_message(uid, text)
                sent += 1
            except: pass
        await update.message.reply_text(f"📢 أرسلت الإعلان إلى {sent} مستخدم.")
        return

    # 4) AI chat or URL
    store_user(u)
    if text and not is_valid_url(text):
        if not check_limits(u.id, "ai"):
            await update.message.reply_text("🚫 انتهى الحد المجاني.")
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

    # 5) Video download flow
    if is_valid_url(text):
        if not check_limits(u.id, "video"):
            await update.message.reply_text("🚫 انتهى الحد المجاني.")
            return
        msg_id = str(update.message.message_id)
        url_store[msg_id] = text
        keyboard = [
            [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{msg_id}")],
            [
                InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{msg_id}"),
                InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{msg_id}"),
                InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{msg_id}")
            ],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{msg_id}")]
        ]
        await update.message.reply_text("اختر الجودة أو صوت فقط:", reply_markup=InlineKeyboardMarkup(keyboard))

# ————— Download Handler —————
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    action, quality, msg_id = q.data.split("|",2)

    if action == "cancel":
        try: await q.message.delete()
        except: pass
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
        cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", fmt, "-o", outfile, url]
        caption = f"🎬 جودة {quality}p"

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        await context.bot.send_message(uid, f"❌ فشل التحميل: {e}")
        url_store.pop(msg_id, None)
        return

    with open(outfile, "rb") as f:
        if action == "audio":
            await context.bot.send_audio(uid, f, caption=caption)
        else:
            await context.bot.send_video(uid, f, caption=caption)

    if os.path.exists(outfile): os.remove(outfile)
    url_store.pop(msg_id, None)
    try: await q.message.delete()
    except: pass

# ————— Admin Handlers —————
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
    await start(update, context)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID: return
    data = q.data
    back = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]

    if data == "admin_users":
        with open(USERS_FILE,"r",encoding="utf-8") as f:
            lines = f.read().splitlines()
        buttons = [[InlineKeyboardButton(f"💬 دعم {l.split('|',1)[1]}", callback_data=f"admin_reply|{l.split('|',1)[0]}")]
                   for l in lines]
        await safe_edit(q, f"👥 عدد المستخدمين: {len(lines)}", InlineKeyboardMarkup(buttons + back))

    elif data == "admin_broadcast":
        global admin_broadcast_mode
        admin_broadcast_mode = True
        await safe_edit(q, "📝 أرسل نصاً أو وسائط للإعلان ثم اضغط رجوع عند الانتهاء.", InlineKeyboardMarkup(back))

    elif data == "admin_supports":
        if not open_chats:
            await safe_edit(q, "💤 لا توجد دردشات دعم مفتوحة.", InlineKeyboardMarkup(back))
            return
        buttons = [
            [
                InlineKeyboardButton(f"📝 رد {uid}", callback_data=f"admin_reply|{uid}"),
                InlineKeyboardButton(f"❌ إنهاء {uid}", callback_data=f"admin_close|{uid}")
            ]
            for uid in open_chats
        ]
        await safe_edit(q, "💬 دردشات الدعم:", InlineKeyboardMarkup(buttons + back))

    elif data == "admin_paidlist":
        subs = load_subs().keys()
        txt = "💰 مشتركون مدفوعون:\n" + ("\n".join(subs) if subs else "لا أحد")
        await safe_edit(q, txt, InlineKeyboardMarkup(back))

    elif data == "admin_stats":
        users   = len(open(USERS_FILE,"r",encoding="utf-8").read().splitlines())
        paid    = len(load_subs())
        support = len(open_chats)
        txt = f"📊 إحصائيات:\n• مستخدمون: {users}\n• مدفوعون: {paid}\n• دعم مفتوح: {support}"
        await safe_edit(q, txt, InlineKeyboardMarkup(back))

    else:
        try: await q.message.delete()
        except: pass

# ————— Register & Run —————
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_error_handler(error_handler)
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(subscribe_request, pattern=r"^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_sub,        pattern=r"^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_sub,         pattern=r"^reject_sub\|"))
app.add_handler(CallbackQueryHandler(support_button,     pattern=r"^support_(start|end)$"))
app.add_handler(CallbackQueryHandler(admin_reply_button, pattern=r"^admin_reply\|"))
app.add_handler(CallbackQueryHandler(admin_close_button, pattern=r"^admin_close\|"))
app.add_handler(CallbackQueryHandler(admin_panel,        pattern=r"^admin_panel$"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin_"))
app.add_handler(CallbackQueryHandler(button_handler,     pattern=r"^(video|audio|cancel)\|"))
app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, support_media_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8443))
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{host}/{BOT_TOKEN}"
    )
