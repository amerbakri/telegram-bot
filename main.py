import os
import subprocess
import logging
import re
import json
from datetime import datetime, date
import openai
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"

ADMIN_ID = 337597459
ORANGE_NUMBER = "0781200500"
USERS_FILE = "users.txt"
USAGE_FILE = "usage.json"
STATS_FILE = "stats.json"
SUBS_FILE = "subs.json"
FREE_VIDEO_LIMIT = 3
FREE_AI_LIMIT = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def ensure_file(path, init="{}"):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f: f.write(init)

for file in [USERS_FILE, USAGE_FILE, STATS_FILE, SUBS_FILE]:
    ensure_file(file, "{}")

def store_user(u):
    entry = f"{u.id}|{u.username or 'NO_USERNAME'}|{u.first_name or ''} {u.last_name or ''}|{u.phone_number if hasattr(u,'phone_number') else ''}".strip()
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    with open(USERS_FILE, "r+", encoding="utf-8") as f:
        lines = f.read().splitlines()
        if not any(l.startswith(f"{u.id}|") for l in lines):
            f.write(entry + "\n")

def load_json(f, default=None):
    try:
        with open(f, "r", encoding="utf-8") as ff: return json.load(ff)
    except: return default if default is not None else {}

def save_json(f, d):
    with open(f, "w", encoding="utf-8") as ff: json.dump(d, ff, ensure_ascii=False, indent=2)

def is_subscribed(uid):
    d = load_json(SUBS_FILE, {})
    return str(uid) in d and d[str(uid)]["active"]

def activate(uid):
    d = load_json(SUBS_FILE, {})
    d[str(uid)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBS_FILE, d)

def deactivate(uid):
    d = load_json(SUBS_FILE, {})
    if str(uid) in d: d.pop(str(uid))
    save_json(SUBS_FILE, d)

def check_limit(uid, kind):
    if is_subscribed(uid) or uid == ADMIN_ID: return True
    today = date.today().isoformat()
    d = load_json(USAGE_FILE, {"date": "", "video": {}, "ai": {}})
    if d.get("date") != today:
        d = {"date": today, "video": {}, "ai": {}}
    cnt = d[kind].get(str(uid), 0)
    limit = FREE_VIDEO_LIMIT if kind == "video" else FREE_AI_LIMIT
    if cnt >= limit:
        save_json(USAGE_FILE, d)
        return False
    d[kind][str(uid)] = cnt + 1
    save_json(USAGE_FILE, d)
    return True

def update_stats(kind, quality):
    st = load_json(STATS_FILE, {"total":0,"counts":{"720":0,"480":0,"360":0,"audio":0}})
    st["total"] += 1
    key = "audio" if kind=="audio" else quality
    st["counts"][key] = st["counts"].get(key,0) + 1
    save_json(STATS_FILE, st)

def is_valid_url(text):
    return bool(re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+", text))

def msg_start():
    return (
        "<b>👋 أهلاً بك في بوت التحميل الذكي!</b>\n\n"
        "<b>🎥 حمل من:</b> <i>YouTube, TikTok, Facebook, Instagram</i>\n"
        "<b>🤖 ذكاء اصطناعي:</b> أرسل أي سؤال وسيتم الرد تلقائياً\n"
        "<b>💰 مجاني يومياً:</b> <u>3 فيديو</u> و<u>5 استفسارات</u>\n"
        f"<b>🔓 للاشتراك المدفوع:</b> أرسل 2 دينار إلى أورنج ماني: <code>{ORANGE_NUMBER}</code>\n"
        "ثم اضغط /subscribe أو زر الاشتراك."
    )

def msg_limit(kind):
    if kind == "video":
        return (
            "<b>🚫 وصلت للحد اليومي المجاني للتحميل.</b>\n"
            f"للاستخدام غير محدود، اشترك بـ <b>2 دينار</b> شهرياً عبر أورنج ماني:\n"
            f"<b>📲 {ORANGE_NUMBER}</b>\nثم اضغط <b>اشترك الآن</b> وسيتم إرسال طلبك مباشرة."
        )
    else:
        return (
            "<b>🚫 وصلت للحد اليومي المجاني لاستفسارات الذكاء الاصطناعي.</b>\n"
            f"للاستخدام غير محدود، اشترك بـ <b>2 دينار</b> شهرياً عبر أورنج ماني:\n"
            f"<b>📲 {ORANGE_NUMBER}</b>\nثم اضغط <b>اشترك الآن</b> وسيتم إرسال طلبك مباشرة."
        )

def msg_subscribe():
    return (
        "<b>💳 للاشتراك المدفوع:</b>\n"
        f"أرسل <b>2 دينار</b> على أورنج ماني <b>{ORANGE_NUMBER}</b>\n"
        "ثم اضغط على زر <b>اشترك الآن</b> وسيصل طلبك للأدمن فوراً بدون إرسال صورة."
    )

def msg_paid_accepted():
    return "<b>✅ تم تفعيل اشتراكك المدفوع! استمتع بالخدمة غير المحدودة.</b>"

def msg_paid_rejected():
    return "<b>❌ تم رفض طلب الاشتراك المدفوع.</b>"

def msg_choose_quality():
    return "<b>📥 اختر نوع وجودة التنزيل المطلوبة:</b>"

def msg_failed_download():
    return "<b>🚫 فشل في تحميل الفيديو. حاول لاحقاً أو تحقق من الرابط.</b>"

def msg_wait_download(q):
    return f"<b>⏳ جاري التحميل{' بجودة ' + q if q!='best' else ''}...</b>"

def msg_confirm_proof(u):
    # محاولة إيجاد رقم الهاتف من ملف المستخدمين
    phone = ""
    with open(USERS_FILE, encoding="utf-8") as f:
        for line in f:
            if line.startswith(f"{u.id}|"):
                parts = line.strip().split("|")
                phone = parts[3] if len(parts) > 3 else ""
                break
    return (
        f"<b>📩 طلب اشتراك جديد:</b>\n"
        f"<b>👤 الاسم:</b> {u.first_name or ''} {u.last_name or ''}\n"
        f"<b>المستخدم:</b> @{u.username or u.id}\n"
        f"<b>ID:</b> <code>{u.id}</code>\n"
        f"{'<b>📞 الهاتف:</b> ' + phone if phone else ''}"
    )

def msg_paid_removed(uid):
    return f"<b>❌ تم إلغاء اشتراك المستخدم ID:<code>{uid}</code>.</b>"

def msg_stats(st):
    c = st["counts"]
    return (
        f"<b>📊 إحصائيات البوت:</b>\n"
        f"🔢 إجمالي التحميل: <b>{st['total']}</b>\n"
        f"720p: <b>{c.get('720',0)}</b> | 480p: <b>{c.get('480',0)}</b> | 360p: <b>{c.get('360',0)}</b> | صوت فقط: <b>{c.get('audio',0)}</b>"
    )

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    store_user(update.effective_user)
    await update.message.reply_text(
        msg_start(), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

async def download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    store_user(user)

    if not is_valid_url(text):
        # ذكاء اصطناعي AI
        if ctx.user_data.get("broadcast"): return
        if not check_limit(user.id, "ai"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe")]])
            await update.message.reply_text(msg_limit("ai"), reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        try:
            res = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role":"user","content":text}]
            )
            await update.message.reply_text(f"<b>🤖 إجابة الذكاء الاصطناعي:</b>\n{res.choices[0].message.content}",
                parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return

    # تحميل فيديو
    if not check_limit(user.id, "video"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe")]])
        await update.message.reply_text(msg_limit("video"), reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    key = str(update.message.message_id)
    url_store[key] = text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ])
    try: await update.message.delete()
    except: pass
    await update.message.reply_text(msg_choose_quality(), reply_markup=kb, parse_mode=ParseMode.HTML)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "subscribe":
        # عند الاشتراك يصل إشعار للأدمن فقط (اسم - معرف - آيدي - رقم هاتف)
        u = query.from_user
        store_user(u)
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm|{u.id}"),
                InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject|{u.id}")
            ]
        ])
        await ctx.bot.send_message(
            ADMIN_ID, msg_confirm_proof(u), reply_markup=kb, parse_mode=ParseMode.HTML
        )
        await query.edit_message_text(
            "✅ تم إرسال طلب الاشتراك. انتظر موافقة الأدمن خلال دقائق.",
            parse_mode=ParseMode.HTML
        )
        return
    try:
        action, quality, key = query.data.split("|")
    except:
        await query.answer("⚠️ خطأ في المعالجة.", show_alert=True)
        return

    if action == "cancel":
        try: await query.message.delete()
        except: pass
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.edit_message_text("⚠️ الرابط غير موجود أو منتهي.")
        return

    loading_msg = await query.edit_message_text(msg_wait_download(quality), parse_mode=ParseMode.HTML)
    # تحميل الفيديو
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
            await query.edit_message_text(msg_failed_download(), parse_mode=ParseMode.HTML)
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
        await query.message.reply_text(msg_failed_download(), parse_mode=ParseMode.HTML)
    url_store.pop(key, None)
    try: await loading_msg.delete()
    except: pass

# تأكيد/رفض الاشتراك من الأدمن
async def confirm_or_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, uid = query.data.split("|")
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ هذا الخيار للأدمن فقط.", show_alert=True)
        return
    if action == "confirm":
        activate(uid)
        await ctx.bot.send_message(uid, msg_paid_accepted(), parse_mode=ParseMode.HTML)
        await query.edit_message_text("✅ تم التفعيل.", reply_markup=None)
    else:
        deactivate(uid)
        await ctx.bot.send_message(uid, msg_paid_rejected(), parse_mode=ParseMode.HTML)
        await query.edit_message_text("❌ تم الرفض.", reply_markup=None)

# --- لوحة الأدمن وكل الميزات ---
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="search")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("🟢 قائمة المشتركين", callback_data="subs")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="close")]
    ])
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=kb)


async def admin_callbacks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; user = q.from_user
    if user.id != ADMIN_ID:
        await q.answer("❌ هذا الخيار للأدمن فقط.", show_alert=True); return
    d = q.data
    if d == "close":
        await q.message.delete()
        return
    if d == "users":
        lines = open(USERS_FILE,encoding="utf-8").read().splitlines()
        text = f"<b>👥 عدد المستخدمين:</b> <code>{len(lines)}</code>\n\n"
        text += "\n".join([f"{l.split('|')[2]} | @{l.split('|')[1]} | ID:{l.split('|')[0]}" for l in lines[-5:]])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif d == "stats":
        st = load_json(STATS_FILE, {"total":0,"counts":{"720":0,"480":0,"360":0,"audio":0}})
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        await q.edit_message_text(msg_stats(st), parse_mode=ParseMode.HTML, reply_markup=kb)
    elif d == "subs":
        data = load_json(SUBS_FILE,{})
        if not data:
            await q.edit_message_text("لا يوجد مشتركين مدفوعين.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]))
            return
        buttons=[]; txt="💎 <b>قائمة المشتركين:</b>\n\n"
        for uid, info in data.items():
            uname = "NO_USERNAME"; fullname = ""; phone = ""
            for l in open(USERS_FILE,encoding="utf-8"):
                if l.startswith(f"{uid}|"):
                    p = l.strip().split("|"); uname = p[1]; fullname = p[2]; phone = p[3] if len(p)>3 else ""; break
            txt+=f"👤 {fullname} (@{uname}) — ID:<code>{uid}</code> {'— 📞 ' + phone if phone else ''}\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء {uname}", callback_data=f"cancel|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
    elif d == "broadcast":
        ctx.user_data["broadcast"] = True
        await q.edit_message_text("📝 أرسل الآن (نص/صورة/فيديو/صوت) للإعلان الجماعي.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="back")]]))
    elif d == "search":
        ctx.user_data["search"] = True
        await q.edit_message_text("🔍 أرسل رقم أو اسم مستخدم أو الاسم الكامل للبحث عنه.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="back")]]))
    elif d == "back":
        await admin_panel(update, ctx)
    elif d.startswith("cancel|"):
        uid = d.split("|")[1]
        deactivate(uid)
        await q.edit_message_text(msg_paid_removed(uid), parse_mode=ParseMode.HTML, reply_markup=None)
        try: await ctx.bot.send_message(int(uid), "❌ تم إلغاء اشتراكك من قبل الأدمن.", parse_mode=ParseMode.HTML)
        except: pass

async def handle_admin_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if u.id!=ADMIN_ID: return
    if ctx.user_data.pop("broadcast",None):
        ctx.user_data["announcement"]=update.message
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ إرسال", callback_data="do_broadcast")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="back")]
        ])
        await update.message.reply_text("تأكيد الإرسال؟", reply_markup=kb)
        return
    if ctx.user_data.pop("search",None):
        term=update.message.text.strip().lower()
        found=[]
        for l in open(USERS_FILE,encoding="utf-8"):
            if term in l.lower(): found.append(l)
        await update.message.reply_text("\n".join(found) or "لا نتائج.")
        return

async def do_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    msg=ctx.user_data.get("announcement")
    sent=0
    for l in open(USERS_FILE,encoding="utf-8"):
        uid=int(l.split("|")[0])
        try:
            if msg.photo:
                await ctx.bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption or "")
            elif msg.video:
                await ctx.bot.send_video(uid, msg.video.file_id, caption=msg.caption or "")
            elif msg.audio:
                await ctx.bot.send_audio(uid, msg.audio.file_id, caption=msg.caption or "")
            elif msg.text:
                await ctx.bot.send_message(uid, msg.text)
            sent+=1
        except: pass
    await q.edit_message_text(f"📢 <b>تم إرسال الإعلان إلى {sent} مستخدم.</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]))

# ------------ تشغيل البوت --------------
if __name__=="__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", lambda u,c: c.bot.send_message(
        u.effective_user.id, msg_subscribe(), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe")]]))))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(MessageHandler(filters.ALL & filters.User(ADMIN_ID), handle_admin_message))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(audio|video|cancel)\|"))
    app.add_handler(CallbackQueryHandler(confirm_or_reject, pattern="^(confirm|reject)\|"))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^(users|stats|subs|broadcast|search|back|close|cancel\|.+)$"))
    app.add_handler(CallbackQueryHandler(do_broadcast, pattern="^do_broadcast$"))
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
