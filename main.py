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
import pytesseract
from PIL import Image

# ————— Logging —————
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ————— Configuration —————
ADMIN_ID = 337597459
BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ضع_مفتاح_OPENAI_هنا")
COOKIES_FILE = "cookies.txt"
USERS_FILE = "users.txt"
SUBSCRIPTIONS_FILE = "subscriptions.json"
LIMITS_FILE = "limits.json"
ORANGE_NUMBER = "0781200500"
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

openai.api_key = OPENAI_API_KEY

# ————— State —————
url_store = {}                   # msg_id → URL
pending_subs = set()             # user_ids awaiting approval
open_chats = set()               # user_ids with open support
admin_reply_to = {}              # ADMIN_ID → user_id for reply
admin_broadcast_mode = False     # if admin is in broadcast mode

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
    """Add user to USERS_FILE if new."""
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if str(user.id) not in [line.split("|",1)[0] for line in lines]:
        entry = f"{user.id}|{user.username or 'NO'}|{user.first_name or ''} {user.last_name or ''}".strip()
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

def get_username(uid):
    """Retrieve stored username by user ID."""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        for line in lines:
            parts = line.split("|", 2)
            if parts[0] == str(uid):
                return parts[1]
    except:
        pass
    return "NO"

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

    # Admin menu
    if user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("📢 إعلان", callback_data="admin_broadcast")],
            [InlineKeyboardButton("💬 محادثات الدعم", callback_data="admin_supports")],
            [InlineKeyboardButton("🟢 مدفوعين", callback_data="admin_paidlist")],
            [InlineKeyboardButton("📊 إحصائيات متقدمة", callback_data="admin_stats")],
            [InlineKeyboardButton("❌ إغلاق", callback_data="admin_panel_close")],
        ]
        kb = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🛠️ *لوحة تحكم الأدمن*\nاختر أحد الخيارات:", 
            reply_markup=kb, parse_mode="Markdown"
        )
        return

    # Regular user menu
    if is_subscribed(user.id):
        subs = load_subs()
        date_iso = subs[str(user.id)]["date"]
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(date_iso)).days
        if days == 0:
            text = (
                "🎉 *تم تفعيل اشتراكك اليوم!* 🎉\n"
                "استمتع بكامل ميزات البوت بدون حدود يومية.\n\n"
                "💬 اضغط دعم لأي مساعدة."
            )
        else:
            text = (
                f"✅ *اشتراكك مفعل منذ {days} يوم*\n"
                "لا حدود اليوم. استمتع!\n\n"
                "💬 اضغط دعم إذا احتجت."
            )
        keyboard = [[InlineKeyboardButton("💬 دعم", callback_data="support_start")]]
    else:
        text = (
            "👋 *مرحباً في بوت التحميل والـ AI!*\n\n"
            f"🔓 للاشتراك بدون حدود يومية، أرسل *2 د.أ* عبر أورنج ماني إلى:\n"
            f"➡️ `{ORANGE_NUMBER}`\n\n"
            "ثم اضغط `اشترك` لإرسال طلبك للأدمن."
        )
        keyboard = [
            [InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")],
            [InlineKeyboardButton("💬 دعم", callback_data="support_start")],
        ]

    kb = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ————— Subscription —————
async def subscribe_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    if u.id in pending_subs:
        await q.answer("❗️ طلبك قيد المراجعة.")
        return
    pending_subs.add(u.id)
    info = (
        f"📥 *طلب اشتراك جديد*\n"
        f"👤 {fullname(u)} | @{u.username or 'NO'}\n"
        f"🆔 {u.id}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{u.id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{u.id}")
    ]])
    await context.bot.send_message(ADMIN_ID, info, reply_markup=kb, parse_mode="Markdown")
    await q.edit_message_text("✅ تم إرسال طلب الاشتراك للأدمن.")

async def confirm_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, uid = q.data.split("|",1)
    activate_subscription(int(uid))
    pending_subs.discard(int(uid))
    await context.bot.send_message(
        int(uid),
        "✅ *تم تفعيل اشتراكك بنجاح!* الآن جميع الميزات متاحة بدون حدود يومية.",
        parse_mode="Markdown"
    )
    await q.edit_message_text("✅ تم تفعيل الاشتراك.")

async def reject_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, uid = q.data.split("|",1)
    pending_subs.discard(int(uid))
    await context.bot.send_message(
        int(uid),
        "❌ *تم رفض طلب اشتراكك.*\nللمساعدة استخدم زر الدعم.",
        parse_mode="Markdown"
    )
    await q.edit_message_text("🚫 تم رفض الاشتراك.")

# ————— OCR Handler —————
async def ocr_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"/tmp/{photo.file_unique_id}.jpg"
    await file.download_to_drive(path)
    try:
        text = pytesseract.image_to_string(Image.open(path), lang="ara+eng")
        if text.strip():
            await update.message.reply_text(f"📄 *النص المستخرج:*\n```\n{text.strip()}\n```", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ لم أستطع استخراج نص من الصورة.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ خطأ أثناء الاستخراج: {e}")
    finally:
        if os.path.exists(path):
            os.remove(path)

# ————— Support —————
async def support_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id
    await q.answer()
    if q.data == "support_start":
        if uid in open_chats:
            await q.answer("الدعم مفتوح بالفعل.")
            return
        open_chats.add(uid)
        await q.edit_message_text(
            "💬 **غرفة الدعم مفتوحة.**\nاكتب رسالتك وسيتم تحويلها للأدمن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق", callback_data="support_end")]]),
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ *دعم جديد* من @{fullname(q.from_user)} ({uid})",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{uid}"),
                InlineKeyboardButton("❌ إنهاء", callback_data=f"admin_close|{uid}")
            ]]),
            parse_mode="Markdown"
        )
    else:
        open_chats.discard(uid)
        await q.edit_message_text("❌ **تم إغلاق الدعم.**", parse_mode="Markdown")

async def support_media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id in open_chats:
        await update.message.forward(chat_id=ADMIN_ID)
        await update.message.reply_text("✅ تم تحويل الوسائط للأدمن.")
        return
    global admin_broadcast_mode
    if u.id == ADMIN_ID and admin_broadcast_mode:
        admin_broadcast_mode = False
        lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
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
        await update.message.reply_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.", parse_mode="Markdown")

# ————— Message Router —————
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global admin_broadcast_mode
    u = update.effective_user
    text = update.message.text.strip()

    # 1) forward support chat
    if u.id in open_chats:
        await context.bot.send_message(
            ADMIN_ID,
            f"*من @{fullname(u)} ({u.id}):*\n{text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{u.id}")]]),
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ تم التحويل للأدمن.")
        return

    # 2) admin reply back
    if u.id == ADMIN_ID and ADMIN_ID in admin_reply_to:
        to_id = admin_reply_to.pop(ADMIN_ID)
        await context.bot.send_message(to_id, f"📩 *رد الأدمن:*\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ تم الإرسال.")
        return

    # 3) admin broadcast text
    if u.id == ADMIN_ID and admin_broadcast_mode and not getattr(update.message, "media_group_id", None):
        admin_broadcast_mode = False
        lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
        sent = 0
        for l in lines:
            uid = int(l.split("|",1)[0])
            try:
                await context.bot.send_message(uid, text)
                sent += 1
            except: pass
        await update.message.reply_text(f"📢 الإعلان أُرسل إلى {sent} مستخدم.", parse_mode="Markdown")
        return

    # 4) AI or download
    store_user(u)
    if not is_valid_url(text):
        if u.id == ADMIN_ID:
            return
        if not check_limits(u.id, "ai"):
            await update.message.reply_text("🚫 انتهى الحد المجاني من استفسارات AI.")
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

    # 5) download flow
    if not check_limits(u.id, "video"):
        await update.message.reply_text("🚫 انتهى الحد المجاني من تنزيل الفيديو.")
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
    kb = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✨ اختر الصيغة المطلوبة:", reply_markup=kb)

# ————— Download Handler —————
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id
    await q.answer()
    action, quality, msg_id = q.data.split("|",2)

    if action == "cancel":
        await q.message.delete()
        url_store.pop(msg_id, None)
        return

    url = url_store.get(msg_id)
    if not url:
        await q.answer("⚠️ انتهت صلاحية الرابط.")
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
        await context.bot.send_message(
            uid,
            f"❌ فشل التحميل بالصيفة المطلوبة ({fmt}). حاول قائمة أخرى أو رابط مختلف.\n\n{e}"
        )
        url_store.pop(msg_id, None)
        return

    with open(outfile, "rb") as f:
        if action == "audio":
            await context.bot.send_audio(uid, f, caption=caption)
        else:
            await context.bot.send_video(uid, f, caption=caption)

    os.remove(outfile)
    url_store.pop(msg_id, None)
    try: await q.message.delete()
    except: pass

# ————— Admin Handlers —————
async def admin_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    _, uid = q.data.split("|",1)
    admin_reply_to[ADMIN_ID] = int(uid)
    await safe_edit(q, "📝 اكتب ردك للمستخدم:")

async def admin_close_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    _, uid = q.data.split("|",1)
    open_chats.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ تم إغلاق الدعم من الأدمن.")
    await safe_edit(q, f"تم إغلاق دعم {uid}.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    data = q.data
    back = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    if data == "admin_users":
        lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
        buttons = [
            [InlineKeyboardButton(f"💬 دعم @{l.split('|')[1]}", callback_data=f"admin_reply|{l.split('|')[0]}")]
            for l in lines
        ]
        kb = InlineKeyboardMarkup(buttons + back)
        await safe_edit(q, f"👥 عدد المستخدمين: {len(lines)}", kb)
    elif data == "admin_broadcast":
        global admin_broadcast_mode
        admin_broadcast_mode = True
        kb = InlineKeyboardMarkup(back)
        await safe_edit(q, "📝 أرسل نص أو وسائط للإعلان ثم اضغط «🔙 رجوع»", kb)
    elif data == "admin_supports":
        if not open_chats:
            kb = InlineKeyboardMarkup(back)
            await safe_edit(q, "💤 لا دردشات دعم حالية.", kb); return
        buttons = [
            [
                InlineKeyboardButton(f"📝 رد {uid}", callback_data=f"admin_reply|{uid}"),
                InlineKeyboardButton(f"❌ إنهاء {uid}", callback_data=f"admin_close|{uid}")
            ] for uid in open_chats
        ]
        kb = InlineKeyboardMarkup(buttons + back)
        await safe_edit(q, "💬 دردشات الدعم المفتوحة:", kb)
    elif data == "admin_paidlist":
        subs = load_subs().keys()
        txt = "💰 مشتركون مدفوعون:\n" + ("\n".join(subs) if subs else "لا أحد")
        kb = InlineKeyboardMarkup(back)
        await safe_edit(q, txt, kb)
    elif data == "admin_stats":
        users = len(open(USERS_FILE, "r", encoding="utf-8").read().splitlines())
        paid = len(load_subs())
        supports = len(open_chats)
        limits = load_json(LIMITS_FILE, {})
        total_v = sum(u.get("video",0) for u in limits.values())
        total_ai = sum(u.get("ai",0) for u in limits.values())
        txt = (
            "📊 **إحصائيات متقدمة**\n"
            f"• مستخدمون: {users}\n"
            f"• مشتركون: {paid}\n"
            f"• دعم مفتوح: {supports}\n"
            f"• تنزيلات اليوم: {total_v}\n"
            f"• استفسارات AI اليوم: {total_ai}"
        )
        kb = InlineKeyboardMarkup(back)
        await safe_edit(q, txt, kb)
    else:
        try: await q.message.delete()
        except: pass

# ————— Register & Run —————
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Commands
app.add_handler(CommandHandler("start", start))

# Callbacks
app.add_handler(CallbackQueryHandler(subscribe_request,    pattern=r"^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_sub,          pattern=r"^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_sub,           pattern=r"^reject_sub\|"))
app.add_handler(CallbackQueryHandler(support_button,       pattern=r"^support_(start|end)$"))
app.add_handler(CallbackQueryHandler(admin_reply_button,   pattern=r"^admin_reply\|"))
app.add_handler(CallbackQueryHandler(admin_close_button,   pattern=r"^admin_close\|"))
app.add_handler(CallbackQueryHandler(admin_panel,          pattern=r"^admin_panel$"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin_"))
app.add_handler(CallbackQueryHandler(button_handler,       pattern=r"^(video|audio|cancel)\|"))

# OCR
app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"^(?:استخراج نص|/ocr)"), ocr_handler))

# Media support
app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, support_media_router))

# Text routing
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

# Errors
app.add_error_handler(error_handler)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8443))
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{host}/{BOT_TOKEN}"
    )
