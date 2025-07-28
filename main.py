import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
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
REQUESTS_FILE = "subscription_requests.txt"

DAILY_VIDEO_LIMIT = 3
DAILY_AI_LIMIT = 5

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def is_valid_url(text):
    return bool(re.match(
        r"^(https?://)?(www\.)?"
        r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ))

def store_user(user):
    os.makedirs(os.path.dirname(USERS_FILE) or ".", exist_ok=True)
    entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
    if not os.path.exists(USERS_FILE) or entry not in open(USERS_FILE).read():
        with open(USERS_FILE, "a") as f:
            f.write(entry + "\n")

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"total_downloads":0, "quality_counts":{"720":0,"480":0,"360":0,"audio":0}, "most_requested_quality":None}
    return json.load(open(STATS_FILE))

def save_stats(stats):
    json.dump(stats, open(STATS_FILE,"w"))

def update_stats(action, quality):
    stats = load_stats()
    stats["total_downloads"] += 1
    key = "audio" if action=="audio" else quality
    stats["quality_counts"][key] = stats["quality_counts"].get(key,0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_stats(stats)

def is_subscribed(uid):
    if not os.path.exists(SUBSCRIPTIONS_FILE): return False
    data = json.load(open(SUBSCRIPTIONS_FILE))
    return str(uid) in data and data[str(uid)].get("active",False)

def activate_subscription(uid):
    data = json.load(open(SUBSCRIPTIONS_FILE,"r")) if os.path.exists(SUBSCRIPTIONS_FILE) else {}
    data[str(uid)] = {"active":True, "date":datetime.utcnow().isoformat()}
    json.dump(data, open(SUBSCRIPTIONS_FILE,"w"))

def deactivate_subscription(uid):
    if not os.path.exists(SUBSCRIPTIONS_FILE): return
    data = json.load(open(SUBSCRIPTIONS_FILE))
    data.pop(str(uid),None)
    json.dump(data, open(SUBSCRIPTIONS_FILE,"w"))

def check_limits(uid, action):
    if uid==ADMIN_ID or is_subscribed(uid): return True
    today = datetime.utcnow().strftime("%Y-%m-%d")
    limits = json.load(open(LIMITS_FILE,"r")) if os.path.exists(LIMITS_FILE) else {}
    ul = limits.get(str(uid),{"date":None,"video":0,"ai":0})
    if ul["date"] != today:
        ul = {"date":today,"video":0,"ai":0}
    if ul[action] >= (DAILY_VIDEO_LIMIT if action=="video" else DAILY_AI_LIMIT):
        return False
    ul[action] += 1
    limits[str(uid)] = ul
    json.dump(limits, open(LIMITS_FILE,"w"))
    return True

async def send_limit_message(msg):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
    await msg.reply_text(
        "🚫 وصلت للحد المجاني اليومي.\n"
        "للاشتراك: 2 دينار عبر أورنج كاش 0781200500.\n"
        "ثم اضغط الزر أدناه لإرسال صورة إثبات الدفع.",
        reply_markup=kb
    )

async def photo_handler(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("waiting_for_proof"): return
    ctx.user_data["waiting_for_proof"] = False
    user = update.effective_user
    file = await update.message.photo[-1].get_file()
    os.makedirs("proofs",exist_ok=True)
    path = f"proofs/{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    await file.download_to_drive(path)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_sub|{user.id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"reject_sub|{user.id}")
    ]])
    cap = f"📩 طلب اشتراك:\n@{user.username or user.id}\nID: {user.id}"
    await ctx.bot.send_photo(ADMIN_ID, photo=open(path,"rb"), caption=cap, reply_markup=kb)
    await update.message.reply_text("✅ إثبات الدفع وصل للأدمن.")

async def handle_subscription_request(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    ctx.user_data["waiting_for_proof"] = True
    await q.message.reply_text(
        "💳 للاشتراك أرسل 2 دينار أورنج كاش 0781200500 ثم صورة الإثبات."
    )

async def confirm_subscription(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=q.data.split("|")[1]; activate_subscription(uid)
    await ctx.bot.send_message(int(uid),"✅ اشتراكك مفعل. شكرًا لك.")
    try: await q.edit_message_text("✅ تم تفعيل الاشتراك.")
    except: pass

async def reject_subscription(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=q.data.split("|")[1]
    await ctx.bot.send_message(int(uid),"❌ تم رفض اشتراكك.")
    try: await q.edit_message_text("🚫 اشتراك مرفوض.")
    except: pass

async def show_paid_users(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    msg=update.message if update.message else update.callback_query.message
    if update.effective_user.id!=ADMIN_ID:
        await msg.reply_text("🚫 فقط للأدمن."); return
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return await msg.reply_text("لا مشتركين مدفوعين.")
    data=json.load(open(SUBSCRIPTIONS_FILE))
    if not data:
        return await msg.reply_text("لا مشتركين مدفوعين.")
    text="👥 مشتركين مدفوعين:\n"
    kb=[]
    for uid in data:
        # اسم المستخدم
        uname="NO_USERNAME"; fullname=""
        if os.path.exists(USERS_FILE):
            for l in open(USERS_FILE):
                u,lun,lfn=l.strip().split("|")
                if u==uid:
                    uname=lun; fullname=lfn; break
        text+=f"👤 {fullname} (@{uname}) — ID: {uid}\n"
        kb.append([InlineKeyboardButton(f"❌ إلغاء {uname}", callback_data=f"cancel_subscribe|{uid}")])
    await msg.reply_text(text,reply_markup=InlineKeyboardMarkup(kb))

async def cancel_subscription_by_admin(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if q.from_user.id!=ADMIN_ID:
        return await q.answer("🚫 فقط للأدمن.",show_alert=True)
    uid=q.data.split("|")[1]; deactivate_subscription(uid)
    try: await q.edit_message_text(f"✅ أُلغي اشتراك {uid}.")
    except: pass
    await ctx.bot.send_message(int(uid),"❌ أُلغي اشتراكك من الأدمن.")

async def show_all_users(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID:
        return await update.message.reply_text("🚫 فقط للأدمن.")
    if not os.path.exists(USERS_FILE):
        return await update.message.reply_text("لا مستخدمين.")
    lines=open(USERS_FILE).read().splitlines()
    text=f"👥 عدد المستخدمين: {len(lines)}\n\n"
    for l in lines:
        u,un,fn=l.split("|")
        text+=f"👤 {fn} (@{un}) — ID: {u}\n"
    await update.message.reply_text(text)

async def admin_panel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID:
        return await update.message.reply_text("🚫 فقط للأدمن.")
    kb=[
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة مشترك", callback_data="admin_addpaid")],
        [InlineKeyboardButton("💳 المدفوعين", callback_data="admin_paid_users")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    await update.message.reply_text("لوحة الأدمن:",reply_markup=InlineKeyboardMarkup(kb))

async def admin_callback_handler(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data; await q.answer()
    if q.from_user.id!=ADMIN_ID:
        return await q.answer("🚫 ليس أدمن.",show_alert=True)
    # استدعاء الدوال بناءً على الزر:
    if data=="admin_users":
        await show_all_users(update,ctx)
    elif data=="admin_broadcast":
        ctx.user_data["waiting_for_announcement"]=True
        try: await q.edit_message_text("📝 أرسل لي الإعلان (نص/صورة/فيديو/صوت):")
        except: pass
    elif data=="admin_search":
        ctx.user_data["waiting_for_search"]=True
        try: await q.edit_message_text("🔍 أرسل اسم أو ID المستخدم للبحث:")
        except: pass
    elif data=="admin_stats":
        stats=load_stats()
        txt=(
            f"📊 إحصائيات:\n"
            f"- التنزيلات: {stats['total_downloads']}\n"
            f"- 720p: {stats['quality_counts']['720']}\n"
            f"- 480p: {stats['quality_counts']['480']}\n"
            f"- 360p: {stats['quality_counts']['360']}\n"
            f"- صوت: {stats['quality_counts']['audio']}\n"
            f"- الأكثر طلبًا: {stats['most_requested_quality']}"
        )
        try: await q.edit_message_text(txt)
        except: await q.message.reply_text(txt)
    elif data=="admin_addpaid":
        ctx.user_data["waiting_for_addpaid"]=True
        try: await q.edit_message_text("📥 أرسل ID لإضافته مشترك مدفوع:")
        except: pass
    elif data=="admin_paid_users":
        await show_paid_users(update,ctx)
    elif data=="admin_close":
        try: await q.edit_message_text("❌ أغلقت لوحة الأدمن.")
        except: pass
    elif data=="admin_back":
        await admin_panel(update,ctx)

async def media_handler(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    # إرسال إعلان:
    if ctx.user_data.get("waiting_for_announcement"):
        ctx.user_data["waiting_for_announcement"]=False
        msg=update.message; count=0
        lines=open(USERS_FILE).read().splitlines()
        for l in lines:
            uid=int(l.split("|")[0])
            if uid==ADMIN_ID: continue
            try:
                if msg.photo: await ctx.bot.send_photo(uid,msg.photo[-1].file_id,caption=msg.caption or "")
                elif msg.video: await ctx.bot.send_video(uid,msg.video.file_id,caption=msg.caption or "")
                elif msg.audio: await ctx.bot.send_audio(uid,msg.audio.file_id,caption=msg.caption or "")
                elif msg.text: await ctx.bot.send_message(uid,msg.text)
                count+=1
            except: pass
        await update.message.reply_text(f"📢 أرسل الإعلان إلى {count} مستخدم.")
        return
    # بحث مستخدم
    if ctx.user_data.get("waiting_for_search"):
        ctx.user_data["waiting_for_search"]=False
        q=update.message.text.strip()
        res=[]
        for l in open(USERS_FILE).read().splitlines():
            uid,un,fn=l.split("|")
            if q in uid or q.lower() in un.lower() or q in fn:
                res.append(f"👤 {fn} (@{un}) — ID: {uid}")
        await update.message.reply_text("\n".join(res) if res else "⚠️ لا مستخدم.")
        return
    # إضافة مدفوع
    if ctx.user_data.get("waiting_for_addpaid"):
        ctx.user_data["waiting_for_addpaid"]=False
        new=update.message.text.strip()
        if new.isdigit():
            activate_subscription(new)
            await update.message.reply_text(f"✅ أضفت {new} كمشترك مدفوع.")
        else:
            await update.message.reply_text("⚠️ ID غير صالح.")
        return

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    store_user(update.effective_user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو (YouTube/TikTok/Facebook/Instagram) أو أي نص لاستفسار AI.\n"
        "💡 مجاني: 3 تنزيلات فيديو و5 استفسارات AI يومياً.\n"
        "🔓 عند الوصول للحد، اضغط زر الاشتراك."
    )

async def download(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    txt=update.message.text.strip()
    user=update.effective_user
    store_user(user)
    # حد فيديو
    if is_valid_url(txt):
        if not check_limits(user.id,"video"):
            return await send_limit_message(update.message)
    else:
        if not check_limits(user.id,"ai"):
            return await send_limit_message(update.message)
        # AI
        try:
            r=openai.ChatCompletion.create(model="gpt-3.5-turbo",
                messages=[{"role":"user","content":txt}])
            await update.message.reply_text(r.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return

    # معالجة رابط
    key=str(update.message.message_id)
    url_store[key]=txt
    kb=[
        [InlineKeyboardButton("🎵 صوت فقط",callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p",callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p",callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p",callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء",callback_data=f"cancel|{key}")]
    ]
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("📥 اختر نوع التنزيل:",reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    act,qual,key=q.data.split("|")
    if act=="cancel":
        try: await q.edit_message_text("❌ تم الإلغاء.")
        except: pass
        url_store.pop(key,None)
        return
    url=url_store.get(key)
    if not url:
        try: await q.edit_message_text("⚠️ الرابط منتهي.")
        except: pass
        return
    lm=await q.edit_message_text(f"⏳ جار التحميل ({qual})...")
    fn=None
    if act=="audio":
        cmd=["yt-dlp","--cookies",COOKIES_FILE,"-x","--audio-format","mp3","-o","audio.%(ext)s",url]
        fn="audio.mp3"
    else:
        fmt=quality_map.get(qual,"best")
        cmd=["yt-dlp","--cookies",COOKIES_FILE,"-f",fmt,"-o","video.%(ext)s",url]
    res=subprocess.run(cmd,capture_output=True,text=True)
    if res.returncode!=0:
        fb=subprocess.run(
            ["yt-dlp","--cookies",COOKIES_FILE,"-f","best[ext=mp4]","-o","video.%(ext)s",url],
            capture_output=True,text=True
        )
        if fb.returncode!=0:
            try: await lm.edit_text("🚫 فشل التحميل.")
            except: pass
            url_store.pop(key,None)
            return
    if act=="video":
        for ext in ("mp4","mkv","webm"):
            if os.path.exists(f"video.{ext}"):
                fn=f"video.{ext}"; break
    if fn and os.path.exists(fn):
        with open(fn,"rb") as f:
            if act=="audio":
                await q.message.reply_audio(f)
            else:
                await q.message.reply_video(f)
        os.remove(fn)
        update_stats(act,qual)
    else:
        await q.message.reply_text("🚫 لم يُعثر على الملف.")
    url_store.pop(key,None)
    try: await lm.delete()
    except: pass

async def stats_command(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!=ADMIN_ID: return
    s=load_stats()
    txt=(
        f"📊 الاستخدام:\n"
        f"- التنزيلات: {s['total_downloads']}\n"
        f"- 720p: {s['quality_counts']['720']}\n"
        f"- 480p: {s['quality_counts']['480']}\n"
        f"- 360p: {s['quality_counts']['360']}\n"
        f"- صوت: {s['quality_counts']['audio']}\n"
        f"- الأكثر طلبًا: {s['most_requested_quality']}"
    )
    await update.message.reply_text(txt)

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats_command))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(CommandHandler("paid_users", show_paid_users))
app.add_handler(CommandHandler("all_users", show_all_users))

app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern="^cancel_subscribe\\|"))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))

app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), media_handler))

if __name__=="__main__":
    port=int(os.environ.get("PORT",8443))
    hostname=os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
