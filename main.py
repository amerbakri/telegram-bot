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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# State
url_store = {}
user_pending_sub = set()
open_chats = set()
admin_reply_to_user = {}
admin_mode = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return default if default is not None else {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_valid_url(text):
    return re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+", text)

def store_user(user):
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    lines = open(USERS_FILE, "r", encoding="utf-8").read().splitlines()
    entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}"
    if all(str(user.id) not in l for l in lines):
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

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
    ul = limits.get(str(uid), {})
    if ul.get("date") != today:
        ul = {"date": today, "video": 0, "ai": 0}
    if action=="video" and ul["video"]>=DAILY_VIDEO_LIMIT: return False
    if action=="ai" and ul["ai"]>=DAILY_AI_LIMIT: return False
    ul[action]+=1
    limits[str(uid)] = ul
    save_json(LIMITS_FILE, limits)
    return True

async def safe_edit_message_text(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except:
        pass

def user_fullname(user):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

# -------- Handlers --------

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    kb = [
        [InlineKeyboardButton("💬 ابدأ الدعم", callback_data="support_start")],
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ]
    if user.id==ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠️ لوحة الأدمن", callback_data="admin_panel")])
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو أو استفسار AI.\n"
        f"الحد المجاني: {DAILY_VIDEO_LIMIT} فيديو و {DAILY_AI_LIMIT} AI يومياً.\n"
        f"للاشتراك: 2 دينار عبر أورنج ماني {ORANGE_NUMBER}.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# Limit reached message
async def send_limit_message(update: Update):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
    await update.message.reply_text("🚫 انتهى الحد المجاني، اشترك الآن.", reply_markup=kb)

# Subscription requests
async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id in user_pending_sub:
        await update.callback_query.answer("✅ طلبك قيد المراجعة.")
        return
    user_pending_sub.add(u.id)
    info = f"طلب اشتراك:\n{user_fullname(u)} | @{u.username or 'NO'} | ID: {u.id}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تفعيل", callback_data=f"confirm_sub|{u.id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{u.id}")
    ]])
    await context.bot.send_message(ADMIN_ID, info, reply_markup=kb)
    await update.callback_query.edit_message_text("✅ طلبك أُرسل للأدمن.")

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, uid = update.callback_query.data.split("|")
    activate_subscription(uid)
    user_pending_sub.discard(int(uid))
    await context.bot.send_message(int(uid), "✅ اشتراكك مفعل!")
    await safe_edit_message_text(update.callback_query, "✅ تم التفعيل.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, uid = update.callback_query.data.split("|")
    user_pending_sub.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ تم الرفض.")
    await safe_edit_message_text(update.callback_query, "🚫 تم الرفض.")

# Support start/end
async def support_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if q.data=="support_start":
        if uid in open_chats:
            await q.answer("قناة الدعم مفتوحة.")
            return
        open_chats.add(uid)
        await q.answer("تم فتح الدعم.")
        await q.edit_message_text(
            "💬 اكتب رسالتك.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق", callback_data="support_end")]])
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ دعم من: {uid}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{uid}"),
                InlineKeyboardButton("❌ إنهاء", callback_data=f"admin_close|{uid}")
            ]])
        )
    else:  # support_end
        open_chats.discard(uid)
        await q.answer("أغلقت الدعم.")
        await q.edit_message_text("❌ أغلقت قناة الدعم.")

# User → Admin messages
async def support_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in open_chats:
        return  # let other handlers run
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 رد", callback_data=f"admin_reply|{uid}")]])
    await context.bot.send_message(ADMIN_ID, f"من {uid}:\n{update.message.text}", reply_markup=kb)
    await update.message.reply_text("✅ أرسلت للأدمن.")

# Admin reply button
async def admin_reply_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id!=ADMIN_ID: return
    _, uid = q.data.split("|")
    admin_reply_to_user[ADMIN_ID] = int(uid)
    await q.answer("اكتب ردك الآن.")
    await safe_edit_message_text(q, f"اكتب رد للمستخدم {uid}:")

# Admin text handler (for replies & announcements)
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Admin → User reply
    if uid==ADMIN_ID and ADMIN_ID in admin_reply_to_user:
        to_uid = admin_reply_to_user.pop(ADMIN_ID)
        await context.bot.send_message(to_uid, f"📩 رد الأدمن:\n{update.message.text}")
        await update.message.reply_text("✅ تم الإرسال.")
        return
    # Admin broadcast
    if uid==ADMIN_ID and context.user_data.get("waiting_announce"):
        context.user_data["waiting_announce"]=False
        users = [l.split("|")[0] for l in open(USERS_FILE,"r",encoding="utf-8") if l.strip()]
        sent=0
        for u in users:
            try:
                await context.bot.send_message(int(u), update.message.text)
                sent+=1
            except: pass
        await update.message.reply_text(f"📢 أرسلت لـ{sent} مستخدم.")

# Admin close support
async def admin_close_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id!=ADMIN_ID: return
    _, uid = q.data.split("|")
    open_chats.discard(int(uid))
    await context.bot.send_message(int(uid), "❌ أغلق الأدمن الدعم.")
    await safe_edit_message_text(q, f"أغلقت دردشة {uid}.")

# Admin panel
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🟢 مدفوعين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_panel_close")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text("لوحة الأدمن:", reply_markup=kb)
    else:
        await update.message.reply_text("لوحة الأدمن:", reply_markup=kb)

async def admin_panel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; d=q.data
    if q.from_user.id!=ADMIN_ID: return
    if d=="admin_users":
        cnt=len(open(USERS_FILE,"r",encoding="utf-8").read().splitlines())
        await safe_edit_message_text(q, f"👥 عدد المستخدمين: {cnt}")
    elif d=="admin_broadcast":
        context.user_data["waiting_announce"]=True
        await safe_edit_message_text(q, "📝 ارسل نص الإعلان:")
    elif d=="admin_paidlist":
        subs = load_json(SUBSCRIPTIONS_FILE,{})
        txt="مدفوعين:\n"+("\n".join(subs.keys()) or "لا أحد")
        await safe_edit_message_text(q, txt)
    else:  # close
        try: await q.message.delete()
        except: pass

# Download & AI
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in open_chats:
        return
    msg = update.message.text.strip()
    store_user(update.effective_user)
    if not is_valid_url(msg):
        if uid==ADMIN_ID: return
        if not check_limits(uid,"ai"):
            await send_limit_message(update); return
        try:
            res = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                               messages=[{"role":"user","content":msg}])
            await update.message.reply_text(res.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ AI خطأ: {e}")
        return
    if not check_limits(uid,"video"):
        await send_limit_message(update); return
    key = str(update.message.message_id)
    url_store[key]=msg
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
         InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
         InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ])
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("اختر:", reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data; uid=q.from_user.id
    if "|" not in data:
        await q.answer("باطل."); return
    action,quality,key = data.split("|")
    if action=="cancel":
        try: await q.message.delete()
        except: pass
        url_store.pop(key,None)
        return
    url=url_store.get(key)
    if not url:
        await q.answer("انتهت."); return
    await q.edit_message_text("⏳ جاري ...")
    out="video.mp4"; cap=""
    if action=="audio":
        cmd=["yt-dlp","-f","bestaudio","--extract-audio","--audio-format","mp3","-o",out,"--cookies",COOKIES_FILE,url]
        cap="🎵 صوت"
    else:
        fmt=quality_map.get(quality,"best")
        cmd=["yt-dlp","-f",fmt,"-o",out,"--cookies",COOKIES_FILE,url]
        cap=f"🎬 {quality}p"
    try:
        subprocess.run(cmd,check=True)
        with open(out,"rb") as f:
            if action=="audio":
                await context.bot.send_audio(uid,f,caption=cap)
            else:
                await context.bot.send_video(uid,f,caption=cap)
    except Exception as e:
        await context.bot.send_message(uid,f"❌ خطأ: {e}")
    finally:
        if os.path.exists(out): os.remove(out)
        url_store.pop(key,None)
    try: await q.message.delete()
    except: pass

# --- Register handlers ---
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(support_button_handler, pattern="^support_(start|end)$"))
app.add_handler(CallbackQueryHandler(admin_reply_button_handler, pattern="^admin_reply\\|"))
app.add_handler(CallbackQueryHandler(admin_close_button_handler, pattern="^admin_close\\|"))
app.add_handler(CallbackQueryHandler(admin_panel_callback_handler, pattern="^admin_"))
app.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=ADMIN_ID), admin_text_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, support_message_handler))

if __name__=="__main__":
    port=int(os.environ.get("PORT",8443))
    host=os.environ.get("RENDER_EXTERNAL_HOSTNAME","localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{host}/{BOT_TOKEN}"
    )
