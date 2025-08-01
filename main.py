import os
import json
import re
import logging
import asyncio
import functools
import glob
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import openai
import pytesseract
import yt_dlp
from PIL import Image

# ————— فلترة الكوكيز —————
filtered = []
with open("cookies.txt", "r", encoding="utf-8") as f:
    for line in f:
        if re.match(r"^(?:\.?youtube\.com|\.?facebook\.com|\.?instagram\.com|\.?tiktok\.com)", line):
            filtered.append(line)
with open("filtered_cookies.txt", "w", encoding="utf-8") as f:
    f.writelines(filtered)
COOKIES_FILE = "filtered_cookies.txt"

# ————— Configuration —————
ADMIN_ID = 337597459
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_KEY")
ORANGE_NUMBER = "0781200500"
SUB_DURATION_DAYS = 30
DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

openai.api_key = OPENAI_API_KEY

# ————— State —————
url_store = {}             # msg_id → URL
pending_subs = set()       # awaiting approval
open_chats = set()         # support chat open
admin_reply_to = {}        # ADMIN_ID → user_id
admin_broadcast_mode = False

# ————— Logging —————
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ————— Helpers —————
def load_json(path, default=None):
    if not os.path.exists(path): return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default or {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def store_user(user):
    if not os.path.exists("users.txt"): open("users.txt","w").close()
    with open("users.txt","r", encoding="utf-8") as f:
        ids = [l.split("|",1)[0] for l in f.read().splitlines()]
    if str(user.id) not in ids:
        ent = f"{user.id}|{user.username or 'NO'}|{user.first_name or ''} {user.last_name or ''}".strip()
        with open("users.txt","a", encoding="utf-8") as f:
            f.write(ent + "\n")

def fullname(u):
    return f"{u.first_name or ''} {u.last_name or ''}".strip()

def is_valid_url(text):
    return re.match(r"https?://.+", text)

# Subscription & limits
SUB_FILE = "subscriptions.json"
LIMIT_FILE = "limits.json"

def load_subs(): return load_json(SUB_FILE, {})
def is_subscribed(uid): return load_subs().get(str(uid), {}).get("active", False)

def activate_subscription(uid):
    subs = load_subs()
    subs[str(uid)] = {"active": True, "date": datetime.now(timezone.utc).isoformat()}
    save_json(SUB_FILE, subs)

def deactivate_subscription(uid):
    subs = load_subs(); subs.pop(str(uid), None)
    save_json(SUB_FILE, subs)

def check_limits(uid, action):
    if uid == ADMIN_ID or is_subscribed(uid): return True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = load_json(LIMIT_FILE, {})
    u = data.get(str(uid), {})
    if u.get("date") != today:
        u = {"date": today, "video": 0, "ai": 0}
    if action == "video" and u["video"] >= DAILY_VIDEO_LIMIT: return False
    if action == "ai" and u["ai"] >= DAILY_AI_LIMIT: return False
    u[action] += 1
    data[str(uid)] = u
    save_json(LIMIT_FILE, data)
    return True

async def safe_edit(q, text, kb=None):
    try: await q.edit_message_text(text, reply_markup=kb)
    except: pass

# ————— Eye-animation helper —————
async def animate_eyes(msg, stop_event):
    frames = ["👀↻", "↻👀", "👀↺", "↺👀"]
    i = 0
    while not stop_event.is_set():
        try: await msg.edit_text(frames[i % len(frames)] + " جاري التحميل في الخلفية...")
        except: pass
        i += 1
        await asyncio.sleep(0.5)

# ————— Error Handler —————
async def error_handler(update, context):
    logger.error("Exception:", exc_info=context.error)

# ————— /start —————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    if user.id == ADMIN_ID:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
            [InlineKeyboardButton("📢 إعلان", callback_data="admin_broadcast")],
            [InlineKeyboardButton("💬 دعم", callback_data="admin_supports")],
            [InlineKeyboardButton("🟢 مدفوعين", callback_data="admin_paidlist")],
            [InlineKeyboardButton("🚫 إلغاء اشتراك", callback_data="admin_unsub")],
            [InlineKeyboardButton("❌ إغلاق", callback_data="admin_panel_close")]
        ])
        await update.message.reply_text("🛠️ *لوحة تحكم الأدمن*", reply_markup=kb, parse_mode="Markdown")
        return
    # user menu
    if is_subscribed(user.id):
        date = load_subs()[str(user.id)]["date"][:10]
        text = f"✅ اشتراكك مفعل منذ {date}"
        buttons = [[InlineKeyboardButton("💬 دعم", callback_data="support_start")]]
    else:
        text = (
            "👋 مرحباً!\n" +
            f"🔓 للإشتراك أرسل 2 د.أ. إلى {ORANGE_NUMBER} ثم اضغط زر 'اشترك'."
        )
        buttons = [[InlineKeyboardButton("🔓 اشترك", callback_data="subscribe_request")],
                   [InlineKeyboardButton("💬 دعم", callback_data="support_start")]]
    kb = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ————— Subscription Handlers —————
async def subscribe_request(update, context):
    q = update.callback_query; await q.answer()
    u = q.from_user
    if u.id in pending_subs:
        return await q.answer("❗️ قيد المراجعة.")
    pending_subs.add(u.id)
    info = f"📥 طلب اشتراك من {fullname(u)} ({u.id})"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{u.id}"),
                                InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{u.id}") ]])
    await context.bot.send_message(ADMIN_ID, info, reply_markup=kb, parse_mode="Markdown")
    await q.edit_message_text("✅ أرسل للأدمن.")

async def confirm_sub(update, context):
    q = update.callback_query; await q.answer()
    _, uid = q.data.split("|",1)
    activate_subscription(int(uid)); pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "✅ اشتراكك مفعل!", parse_mode="Markdown")
    await q.edit_message_text("✅ تم التفعيل.")

async def reject_sub(update, context):
    q = update.callback_query; await q.answer()
    _, uid = q.data.split("|",1)
    pending_subs.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ رُفض طلبك.", parse_mode="Markdown")
    await q.edit_message_text("🚫 تم الرفض.")

# ————— Unsubscribe Command —————
async def unsub_command(update, context):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("❗Usage: /unsub <user_id>")
    uid = int(context.args[0]); deactivate_subscription(uid)
    await update.message.reply_text(f"✅ أُلغى اشتراك {uid}")
    try: await context.bot.send_message(uid, "🚫 تم إلغاء اشتراكك.")
    except: pass

# ————— OCR Handler —————
async def ocr_handler(update, context):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"/tmp/{photo.file_unique_id}.jpg"
    await file.download_to_drive(path)
    try:
        text = pytesseract.image_to_string(Image.open(path), lang="ara+eng").strip()
        await update.message.reply_text(f"📄 النص: \n{text}" if text else "⚠️ لا نص.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ خطأ: {e}")
    finally:
        if os.path.exists(path): os.remove(path)

# ————— Support Handlers —————
async def support_button(update, context):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    if q.data == "support_start":
        if uid in open_chats: return await q.answer("مفتوح.")
        open_chats.add(uid)
        await q.edit_message_text("💬 الدعم مفتوح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق", callback_data="support_end")]]))
        await context.bot.send_message(ADMIN_ID, f"دعم من {fullname(q.from_user)} ({uid})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{uid}")]]))
    else:
        open_chats.discard(uid)
        await q.edit_message_text("❌ أغلقت الدعم.")

async def support_media_router(update, context):
    u = update.effective_user
    if u.id in open_chats:
        await update.message.forward(chat_id=ADMIN_ID)
        return await update.message.reply_text("✅ تم تحويل.")
    global admin_broadcast_mode
    if u.id == ADMIN_ID and admin_broadcast_mode:
        admin_broadcast_mode = False
        lines = open("users.txt","r").read().splitlines()
        for l in lines:
            uid = int(l.split("|",1)[0])
            try:
                if update.message.photo:
                    await context.bot.send_photo(uid, update.message.photo[-1].file_id, caption=update.message.caption or "")
                elif update.message.video:
                    await context.bot.send_video(uid, update.message.video.file_id, caption=update.message.caption or "")
            except: pass
        return

# ————— Message Router —————
async def message_router(update, context):
    u, msg = update.effective_user, update.message
    text = msg.text.strip()
    if u.id in open_chats:
        await context.bot.send_message(ADMIN_ID, f"من {fullname(u)}: {text}")
        return await msg.reply_text("✅ تم.")
    if u.id == ADMIN_ID and ADMIN_ID in admin_reply_to:
        to_id = admin_reply_to.pop(ADMIN_ID)
        await context.bot.send_message(to_id, f"📩 رد الأدمن:\n{text}")
        return await msg.reply_text("✅ تم الإرسال.")
    if u.id == ADMIN_ID and admin_broadcast_mode:
        admin_broadcast_mode = False
        lines = open("users.txt").read().splitlines()
        for l in lines:
            uid = int(l.split("|",1)[0])
            try: await context.bot.send_message(uid, text)
            except: pass
        return await msg.reply_text(f"📢 أرسل لـ {len(lines)}")
    store_user(u)
    if not is_valid_url(text):
        if not check_limits(u.id, "ai"): return await msg.reply_text("🚫 انتهى حد AI.")
        try:
            res = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":text}])
            return await msg.reply_text(res.choices[0].message.content)
        except Exception as e:
            return await msg.reply_text(f"⚠️ AI خطأ: {e}")
    # download menu
    if not check_limits(u.id, "video"): return await msg.reply_text("🚫 انتهى حد الفيديو.")
    msg_id = str(msg.message_id)
    url_store[msg_id] = text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{msg_id}"), InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{msg_id}")]
    ])
    await msg.reply_text("✨ اختر جودة:", reply_markup=kb)

# ————— Download Handler —————
async def button_handler(update, context):
    q = update.callback_query; await q.answer(); uid = q.from_user.id
    action, quality, msg_id = q.data.split("|",2)
    if action == "cancel":
        url_store.pop(msg_id, None)
        return await q.message.delete()
    url = url_store.get(msg_id)
    if not url: return await q.answer("⚠️ انتهى.")
    # start eye animation
    stop_evt = asyncio.Event()
    task = asyncio.create_task(animate_eyes(q.message, stop_evt))
    # download
    ext = ".mp4" if action == "video" else ".mp3"
    out = f"{msg_id}{ext}"
    fmt = f"bestvideo[height<={quality}]+bestaudio/best" if action=="video" else "bestaudio"
    cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", fmt, "-o", out, url]
    try:
        await asyncio.get_running_loop().run_in_executor(None, functools.partial(subprocess.run, cmd, check=True))
    except Exception as e:
        stop_evt.set(); await task
        return await context.bot.send_message(uid, f"❌ فشل: {e}")
    # stop animation
    stop_evt.set(); await task
    files = glob.glob(f"{msg_id}.*")
    if not files: return await context.bot.send_message(uid, "❌ لا ملف!")
    with open(files[0], "rb") as f:
        if action=="video": await context.bot.send_video(uid, f)
        else: await context.bot.send_audio(uid, f)
    for fn in files: os.remove(fn)
    url_store.pop(msg_id, None)

# ————— Admin Panel Handlers —————
async def admin_reply_button(update, context):
    q=update.callback_query; await q.answer()
    _, uid = q.data.split("|",1)
    admin_reply_to[ADMIN_ID] = int(uid)
    await safe_edit(q, "📝 اكتب رد:")

async def admin_close_button(update, context):
    q=update.callback_query; await q.answer()
    _, uid = q.data.split("|",1)
    open_chats.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ أغلق الأدمن الدعم.")
    await safe_edit(q, f"أغلقت {uid}")

async def admin_panel(update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("💬 دعم مفتوح", callback_data="admin_supports")],
        [InlineKeyboardButton("🟢 مدفوعين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("🚫 إلغاء اشتراك", callback_data="admin_unsub")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_panel_close")]
    ])
    await update.callback_query.edit_message_text("🛠️ لوحة الأدمن", reply_markup=kb)

async def admin_panel_callback(update, context):
    q=update.callback_query; await q.answer()
    data=q.data; back=[[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]
    if data=="admin_users":
        lines=open("users.txt").read().splitlines()
        await safe_edit(q, f"👥 {len(lines)} مستخدم", InlineKeyboardMarkup(back))
    elif data=="admin_broadcast":
        global admin_broadcast_mode
        admin_broadcast_mode=True
        await safe_edit(q, "أرسل الإعلان ثم 🔙", InlineKeyboardMarkup(back))
    elif data=="admin_supports":
        buts=[[InlineKeyboardButton(f"📝 رد {uid}",callback_data=f"admin_reply|{uid}"),InlineKeyboardButton(f"❌ إنهاء {uid}",callback_data=f"admin_close|{uid}")] for uid in open_chats]
        await safe_edit(q, "💬 دعم مفتوح:", InlineKeyboardMarkup(buts+back))
    elif data=="admin_paidlist":
        subs=load_subs().keys()
        txt="مدفوعون:\n"+"\n".join(subs)
        await safe_edit(q, txt, InlineKeyboardMarkup(back))
    elif data=="admin_unsub":
        await safe_edit(q, "❗ استخدم /unsub <user_id>", InlineKeyboardMarkup(back))
    else:
        await q.message.delete()

# ————— Register & Run —————
app = ApplicationBuilder().token(BOT_TOKEN).build()
# commands & handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("unsub", unsub_command))
app.add_handler(CallbackQueryHandler(subscribe_request, pattern=r"^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_sub, pattern=r"^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_sub, pattern=r"^reject_sub\|"))
app.add_handler(CallbackQueryHandler(support_button, pattern=r"^support_(start|end)$"))
app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(video|cancel)\|"))
app.add_handler(CallbackQueryHandler(admin_reply_button, pattern=r"^admin_reply\|"))
app.add_handler(CallbackQueryHandler(admin_close_button, pattern=r"^admin_close\|"))
app.add_handler(CallbackQueryHandler(admin_panel, pattern=r"^admin_panel$"))
app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin_"))
app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"^(?:استخراج نص|/ocr)"), ocr_handler))
app.add_handler(MessageHandler((filters.PHOTO|filters.VIDEO) & ~filters.COMMAND, support_media_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
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
```
