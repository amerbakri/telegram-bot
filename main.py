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
USAGE_FILE = "usage.json"
STATS_FILE = "stats.json"
PAID_FILE = "paid.json"
REQUESTS_FILE = "requests.txt"

FREE_VIDEO_LIMIT = 3
FREE_AI_LIMIT = 5

user_waiting_proof = set()  # لمعالجة صورة الاشتراك

# ----------- إنشاء الملفات الفارغة تلقائياً ----------- #
for f in [USERS_FILE, USAGE_FILE, STATS_FILE, PAID_FILE, REQUESTS_FILE]:
    if not os.path.exists(f):
        with open(f, "w", encoding="utf-8") as ff:
            ff.write("{}" if f.endswith(".json") else "")

openai.api_key = OPENAI_API_KEY
url_store = {}
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def store_user(u):
    line = f"{u.id}|{u.username or ''}|{u.first_name or ''} {u.last_name or ''}"
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()
    with open(USERS_FILE, "r+", encoding="utf-8") as f:
        lines = f.read().splitlines()
        if not any(l.startswith(f"{u.id}|") for l in lines):
            f.write(line + "\n")

def is_subscribed(uid):
    data = load_json(PAID_FILE, {})
    return data.get(str(uid), False)

def activate(uid):
    data = load_json(PAID_FILE, {})
    data[str(uid)] = True
    save_json(PAID_FILE, data)

def deactivate(uid):
    data = load_json(PAID_FILE, {})
    data.pop(str(uid), None)
    save_json(PAID_FILE, data)

def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f)
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def check_limit(uid, kind):
    if is_subscribed(uid) or uid == ADMIN_ID:
        return True
    # معالجة الملف إذا كان فارغ أو غير جاهز
    try:
        data = load_json(USAGE_FILE, {"date": "", "video": {}, "ai": {}})
        if not isinstance(data, dict):
            data = {"date": "", "video": {}, "ai": {}}
    except:
        data = {"date": "", "video": {}, "ai": {}}
    today = date.today().isoformat()
    if "date" not in data or "video" not in data or "ai" not in data:
        data = {"date": today, "video": {}, "ai": {}}
    if data["date"] != today:
        data = {"date": today, "video": {}, "ai": {}}
    cnt = data[kind].get(str(uid), 0)
    limit = FREE_VIDEO_LIMIT if kind == "video" else FREE_AI_LIMIT
    if cnt >= limit:
        return False
    data[kind][str(uid)] = cnt + 1
    save_json(USAGE_FILE, data)
    return True

def update_stats(kind, quality):
    st = load_json(STATS_FILE, {"total":0,"counts":{"720":0,"480":0,"360":0,"audio":0}})
    st["total"] += 1
    key = "audio" if kind=="audio" else quality
    st["counts"][key] = st["counts"].get(key,0) + 1
    save_json(STATS_FILE, st)

def is_valid_url(text):
    return bool(re.match(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+", text))

# ----------- أوامر البوت ----------- #

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    store_user(u)
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو من YouTube/Facebook/TikTok/Instagram لتحميله.\n"
        "💡 مجاني: 3 فيديو و5 أسئلة AI يومياً.\n"
        "🔓 للاشتراك، اضغط /subscribe"
    )

async def download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # أي رسالة نصية يرسلها المستخدم
    msg = update.message.text.strip()
    u = update.effective_user
    store_user(u)

    # التحقق هل الأدمن في وضع إعلان؟ (لا ترسل للذكاء الصناعي!)
    if u.id == ADMIN_ID and ctx.user_data.get("broadcast", False):
        # تعامل في handle_admin_message
        return

    # --- AI الرد الذكي ---
    if not is_valid_url(msg):
        if not check_limit(u.id, "ai"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe")]])
            await update.message.reply_text(
                "🚫 تجاوزت حد AI اليومي.\n"
                "📲 0781200500 (Orange Money)\nثم اضغط الزر.",
                reply_markup=kb
            )
            return
        try:
            res = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role":"user","content":msg}]
            )
            await update.message.reply_text(res.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return

    # --- تحميل فيديو ---
    if not check_limit(u.id, "video"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe")]])
        await update.message.reply_text(
            "🚫 تجاوزت حد التحميل اليومي.\n"
            "📲 0781200500 (Orange Money)\nثم اضغط الزر.",
            reply_markup=kb
        )
        return

    key = str(update.message.message_id)
    url_store[key] = msg
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ])
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("اختر الجودة:", reply_markup=kb)

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split("|")
    action = data[0]
    if action=="cancel":
        try: await q.message.delete()
        except: pass
        url_store.pop(data[1],None)
        return

    if action in ("video","audio"):
        if action=="audio":
            _, key = data
            url = url_store.pop(key,"")
            cmd = ["yt-dlp","--cookies",COOKIES_FILE,"-x","--audio-format","mp3","-o","audio.%(ext)s",url]
            fname="audio.mp3"
        else:
            _, qual, key = data
            url = url_store.pop(key,"")
            fmt = quality_map.get(qual)
            cmd = ["yt-dlp","--cookies",COOKIES_FILE,"-f",fmt,"-o","video.%(ext)s",url]
            fname=None
        loading = await q.edit_message_text("⏳ جاري التحميل...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode!=0:
            subprocess.run(["yt-dlp","--cookies",COOKIES_FILE,"-f","best[ext=mp4]","-o","video.%(ext)s",url])
        if not fname:
            for ext in ("mp4","mkv","webm"):
                if os.path.exists(f"video.{ext}"):
                    fname=f"video.{ext}"
                    break
        if fname and os.path.exists(fname):
            with open(fname,"rb") as f:
                if action=="audio":
                    await q.message.reply_audio(f)
                else:
                    await q.message.reply_video(f)
            os.remove(fname)
            update_stats(action, qual if action=="video" else "audio")
        else:
            await q.message.reply_text("❌ فشل التحميل.")
        try: await loading.delete()
        except: pass
        return

    if action=="subscribe":
        u = q.from_user
        user_waiting_proof.add(u.id)
        await q.edit_message_text(
            "💳 لإتمام الاشتراك:\n"
            "أرسل 2 دينار إلى 0781200500\n"
            "ثم أرسل صورة الدفع هنا."
        )
        return

    if action=="confirm":
        uid = int(data[1])
        activate(uid)
        await ctx.bot.send_message(uid, "✅ تم تفعيل اشتراكك.")
        try: await q.message.delete()
        except: pass
        return

    if action=="reject":
        uid = int(data[1])
        await ctx.bot.send_message(uid, "❌ تم رفض اشتراكك.")
        try: await q.message.delete()
        except: pass
        return

    if action.startswith("cancel_sub"):
        uid = action.split("_")[-1]
        deactivate(uid)
        await q.edit_message_text(f"❌ تم إلغاء اشتراك المستخدم ID:{uid}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="subs")]]))
        try:
            await ctx.bot.send_message(int(uid), "❌ تم إلغاء اشتراكك من قبل الأدمن.")
        except: pass

async def receive_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id not in user_waiting_proof:
        await update.message.reply_text("❌ أرسل /subscribe ثم اضغط (اشترك الآن) أولاً.")
        return
    user_waiting_proof.remove(u.id)
    if not update.message.photo: return
    file = await update.message.photo[-1].get_file()
    os.makedirs("proofs", exist_ok=True)
    path = f"proofs/{u.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    await file.download_to_drive(path)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm|{u.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject|{u.id}")
        ]
    ])
    caption=f"📩 إثبات اشتراك جديد:\nالاسم: {u.first_name or ''} {u.last_name or ''}\nالمستخدم: @{u.username or u.id}\nID: {u.id}"
    await ctx.bot.send_photo(
        ADMIN_ID,
        photo=open(path,"rb"),
        caption=caption,
        reply_markup=kb
    )
    await update.message.reply_text("✅ تم استلام إثبات الدفع، سيتم مراجعته من قبل الأدمن.")

# --- لوحة الأدمن ---
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="users")],
        [InlineKeyboardButton("💬 بث إعلان", callback_data="broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="search")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("💎 المشتركين المدفوعين", callback_data="subs")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="close")]
    ])
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=kb)
    else:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=kb)

async def admin_callbacks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    cmd = q.data
    if cmd=="close":
        await q.message.delete()
        return
    if cmd=="users":
        if not os.path.exists(USERS_FILE):
            await q.edit_message_text("لا يوجد مستخدمين.")
            return
        lines = open(USERS_FILE,encoding="utf-8").read().splitlines()
        text = f"👥 {len(lines)} مستخدم:\n"
        for l in lines[-10:]:
            sp = l.split("|")
            text += f"{sp[2]} (@{sp[1]}) — ID:{sp[0]}\n"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]))
    elif cmd=="stats":
        st = load_json(STATS_FILE,{"total":0,"counts":{}})
        txt = f"📊 إجمالي: {st['total']}\n"
        txt += "\n".join(f"{k}: {v}" for k,v in st["counts"].items())
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]))
    elif cmd=="subs":
        data = load_json(PAID_FILE,{})
        if not data:
            await q.edit_message_text("لا يوجد مشتركين مدفوعين.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]))
            return
        buttons=[]; txt="💎 قائمة المشتركين:\n"
        for uid,active in data.items():
            if active:
                uname="NO"
                fullname = ""
                for l in open(USERS_FILE,encoding="utf-8"):
                    sp = l.strip().split("|")
                    if sp[0]==uid:
                        uname=sp[1]
                        fullname=sp[2]
                        break
                txt+=f"👤 {fullname} (@{uname}) — ID:{uid}\n"
                buttons.append([InlineKeyboardButton(f"❌ إلغاء {uname}", callback_data=f"cancel_sub|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(buttons))
    elif cmd=="broadcast":
        await q.edit_message_text("📝 أرسل نص، صورة أو فيديو ليتم بثه لجميع المستخدمين.\nعند الإرسال اختر تأكيد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="back")]]))
        ctx.user_data["broadcast"]=True
    elif cmd=="search":
        await q.edit_message_text("🔍 أرسل اسم المستخدم أو رقم المستخدم أو الاسم الكامل للبحث عنه.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="back")]]))
        ctx.user_data["search"]=True
    elif cmd=="back":
        await admin_panel(update, ctx)

async def handle_admin_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if u.id!=ADMIN_ID: return
    if ctx.user_data.pop("broadcast",None):
        msg=update.message
        ctx.user_data["bc_msg"]=msg
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ إرسال", callback_data="do_broadcast"), InlineKeyboardButton("❌ إلغاء", callback_data="back")]])
        await msg.reply_text("تأكيد الإرسال؟", reply_markup=kb)
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
    msg=ctx.user_data.get("bc_msg")
    sent=0
    with open(USERS_FILE,encoding="utf-8") as ff:
        for l in ff:
            uid=int(l.split("|")[0])
            try:
                if msg.photo:
                    await ctx.bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption or "")
                elif msg.video:
                    await ctx.bot.send_video(uid, msg.video.file_id, caption=msg.caption or "")
                elif msg.text:
                    await ctx.bot.send_message(uid, msg.text)
                sent+=1
            except Exception:
                continue
    await q.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]))

# ------------ تشغيل البوت -------------- #
if __name__=="__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        CommandHandler(
            "subscribe",
            lambda u, c: c.bot.send_message(
                u.effective_user.id,
                "اضغط الزر أدناه للاشتراك.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe")]]
                )
            )
        )
    )
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.PHOTO & filters.User(), receive_proof))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r'^(video|audio|cancel|subscribe|confirm|reject|cancel_sub\|.+)$'))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern=r'^(users|stats|subs|broadcast|search|back)$'))
    app.add_handler(CallbackQueryHandler(do_broadcast, pattern='^do_broadcast$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_admin_message))
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0", port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
