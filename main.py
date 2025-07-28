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

# ========= الإعدادات =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COOKIES_FILE = "cookies.txt"
ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
LIMITS_FILE = "limits.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
REQUESTS_FILE = "subscription_requests.txt"
FREE_VIDEO_LIMIT = 3
FREE_AI_LIMIT = 5
ORANGE_NUMBER = "0781200500"

logging.basicConfig(level=logging.INFO)
openai.api_key = OPENAI_API_KEY
url_store = {}

# جودة الفيديو
quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

# ========= دوال المساعدة =========
def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w", encoding="utf-8") as f: pass
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def is_subscribed(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, data)

def deactivate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    if str(user_id) in data: data.pop(str(user_id))
    save_json(SUBSCRIPTIONS_FILE, data)

def check_limits(user_id, action):
    if is_subscribed(user_id) or user_id == ADMIN_ID: return True
    today = date.today().isoformat()
    limits = load_json(LIMITS_FILE, {})
    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}
    if action == "video" and user_limits["video"] >= FREE_VIDEO_LIMIT: return False
    if action == "ai" and user_limits["ai"] >= FREE_AI_LIMIT: return False
    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    save_json(LIMITS_FILE, limits)
    return True

def update_stats(action, quality):
    stats = load_json(STATS_FILE, {
        "total_downloads": 0,
        "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
        "most_requested_quality": None
    })
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    stats["quality_counts"][key] = stats["quality_counts"].get(key, 0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_json(STATS_FILE, stats)

# ========= أوامر البوت =========
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    store_user(u)
    await update.message.reply_text(
        "👋 <b>مرحبًا بك في البوت الذكي!</b>\n\n"
        "<b>مميزات البوت:</b>\n"
        "✅ تحميل فيديوهات من YouTube, Facebook, TikTok, Instagram.\n"
        "✅ ذكاء صناعي مباشر (بدون أوامر).\n"
        "✅ كل مستخدم له 3 فيديوهات و5 استفسارات AI يوميًا مجانًا.\n"
        "🔓 للاشتراك المدفوع: أرسل 2 دينار لـ <b>أورنج ماني</b> (<b>0781200500</b>) ثم اضغط /subscribe",
        parse_mode="HTML"
    )

async def download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    u = update.effective_user
    store_user(u)
    # ذكاء صناعي مباشر
    if not is_valid_url(msg):
        if not check_limits(u.id, "ai"):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
            ])
            await update.message.reply_text(
                "<b>🚫 انتهت محاولاتك المجانية للذكاء الاصطناعي اليوم.</b>\n\n"
                "اشترك للتمتع بعدد غير محدود! 👇\n"
                f"رقم أورنج ماني: <b>{ORANGE_NUMBER}</b>\n"
                "ثم أرسل /subscribe",
                reply_markup=kb, parse_mode="HTML"
            )
            return
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": msg}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
        return

    # تحميل فيديو
    if not check_limits(u.id, "video"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
        ])
        await update.message.reply_text(
            "<b>🚫 انتهت تحميلاتك المجانية لليوم.</b>\n\n"
            "اشترك للتمتع بعدد غير محدود! 👇\n"
            f"رقم أورنج ماني: <b>{ORANGE_NUMBER}</b>\n"
            "ثم أرسل /subscribe",
            reply_markup=kb, parse_mode="HTML"
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
    await update.message.reply_text(
        "<b>اختر الجودة أو التحميل الصوتي:</b>", reply_markup=kb, parse_mode="HTML"
    )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split("|")
    action = data[0]
    if action == "cancel":
        try: await q.message.delete()
        except: pass
        url_store.pop(data[1], None)
        return
    if action in ("video", "audio"):
        if action == "audio":
            _, key = data
            url = url_store.pop(key, "")
            cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-x", "--audio-format", "mp3", "-o", "audio.%(ext)s", url]
            fname = "audio.mp3"
        else:
            _, qual, key = data
            url = url_store.pop(key, "")
            fmt = quality_map.get(qual)
            cmd = ["yt-dlp", "--cookies", COOKIES_FILE, "-f", fmt, "-o", "video.%(ext)s", url]
            fname = None
        loading = await q.edit_message_text("⏳ <b>جاري التحميل...</b>", parse_mode="HTML")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            subprocess.run(["yt-dlp", "--cookies", COOKIES_FILE, "-f", "best[ext=mp4]", "-o", "video.%(ext)s", url])
        if not fname:
            for ext in ("mp4", "mkv", "webm"):
                if os.path.exists(f"video.{ext}"):
                    fname = f"video.{ext}"
                    break
        if fname and os.path.exists(fname):
            with open(fname, "rb") as f:
                if action == "audio":
                    await q.message.reply_audio(f)
                else:
                    await q.message.reply_video(f)
            os.remove(fname)
            update_stats(action, qual if action == "video" else "audio")
        else:
            await q.message.reply_text("❌ فشل التحميل.")
        try: await loading.delete()
        except: pass
        return

# == اشتراك مدفوع ==
async def handle_subscription_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.callback_query.edit_message_text(
        f"💳 <b>للاشتراك المدفوع:</b>\n\n"
        f"1️⃣ أرسل <b>2 دينار</b> عبر أورنج ماني إلى الرقم: <b>{ORANGE_NUMBER}</b>\n"
        f"2️⃣ ثم أرسل اسمك الكامل أو اسم المستخدم أو رقمك (اختياري) هنا ليتم تفعيل اشتراكك.",
        parse_mode="HTML"
    )
    # إشعار الأدمن بوجود طلب اشتراك
    await ctx.bot.send_message(
        ADMIN_ID,
        f"📬 مستخدم طلب الاشتراك:\n"
        f"الاسم: {user.first_name or ''} {user.last_name or ''}\n"
        f"المعرف: @{user.username or 'NO_USERNAME'}\n"
        f"ID: {user.id}"
    )

# == استقبال بيانات الاشتراك (اسم، أو رقم...الخ) ==
async def receive_subscription_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("أرسل اسمك الكامل أو رقمك لتأكيد الاشتراك.")
        return
    # إرسال للأدمن مع أزرار التفعيل/الرفض
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    caption = f"📝 بيانات طلب اشتراك:\nالاسم: {text}\nالمعرف: @{user.username or 'NO_USERNAME'}\nID: {user.id}"
    await ctx.bot.send_message(ADMIN_ID, caption, reply_markup=keyboard)
    await update.message.reply_text("✅ تم إرسال بياناتك. سيتم مراجعتها من الأدمن وتفعيل الاشتراك قريبًا.")

# == تفعيل/رفض الاشتراك من الأدمن ==
async def confirm_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    await ctx.bot.send_message(int(user_id), "✅ تم تفعيل اشتراكك بنجاح! يمكنك الآن استخدام البوت بلا حدود.")
    await query.edit_message_text("✅ تم تفعيل الاشتراك.")

async def reject_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    await ctx.bot.send_message(int(user_id), "❌ تم رفض طلب الاشتراك.")
    await query.edit_message_text("❌ تم رفض الاشتراك.")

# == لوحة الأدمن وإدارتها ==
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر للأدمن فقط.")
        return
    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("🟢 قائمة المشتركين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 الأدمن فقط.", show_alert=True)
        return
    if data == "admin_users":
        if not os.path.exists(USERS_FILE):
            await query.edit_message_text("لا يوجد مستخدمين.")
            return
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = f.read().splitlines()
        count = len(users)
        recent = "\n\n📌 آخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.split("|")
            recent += f"👤 {name} | @{username} | ID: {uid}\n"
        await query.edit_message_text(f"عدد المستخدمين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")]
        ]))
    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل الآن نص أو صورة أو فيديو ليتم إرساله لجميع المستخدمين.")
        ctx.user_data["waiting_for_announcement"] = True
    elif data == "admin_stats":
        stats = load_json(STATS_FILE, {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        })
        text = (
            f"📊 إحصائيات التحميل:\n"
            f"إجمالي التحميل: {stats['total_downloads']}\n"
            f"720p: {stats['quality_counts'].get('720',0)}\n"
            f"480p: {stats['quality_counts'].get('480',0)}\n"
            f"360p: {stats['quality_counts'].get('360',0)}\n"
            f"صوت فقط: {stats['quality_counts'].get('audio',0)}\n"
            f"الأكثر طلباً: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")]
        ]))
    elif data == "admin_paidlist":
        data = load_json(SUBSCRIPTIONS_FILE, {})
        if not data:
            await query.edit_message_text("لا يوجد مشتركين مدفوعين حالياً.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")]
            ]))
            return
        buttons = []
        text = "👥 قائمة المشتركين:\n\n"
        for uid, info in data.items():
            username = "NO_USERNAME"
            fullname = ""
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, "r", encoding="utf-8") as uf:
                    for line in uf:
                        if line.startswith(uid + "|"):
                            parts = line.strip().split("|")
                            username = parts[1]
                            fullname = parts[2]
                            break
            text += f"👤 {fullname} (@{username}) — ID: {uid}\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء {username}", callback_data=f"cancel_subscribe|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())

# == حذف الاشتراك من الأدمن ==
async def cancel_subscription_by_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الأمر للأدمن فقط.", show_alert=True)
        return
    _, user_id = query.data.split("|")
    deactivate_subscription(user_id)
    await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id}.")
    try:
        await ctx.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    except:
        pass

# == استقبال رسائل نصية من الأدمن (إعلانات نص/صورة/فيديو) ==
async def admin_media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("waiting_for_announcement"):
        return
    ctx.user_data["waiting_for_announcement"] = False
    ctx.user_data["announcement"] = update.message
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد الإرسال", callback_data="confirm_broadcast"),
         InlineKeyboardButton("❌ إلغاء", callback_data="admin_close")]
    ])
    await update.message.reply_text("هل تريد تأكيد إرسال الإعلان لجميع المستخدمين؟", reply_markup=kb)

async def confirm_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    msg = ctx.user_data.get("announcement")
    sent = 0
    if not msg:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    # ارسال للمستخدمين
    if not os.path.exists(USERS_FILE):
        await query.edit_message_text("🚫 لا يوجد مستخدمين مسجلين.")
        return
    with open(USERS_FILE, "r", encoding="utf-8") as ff:
        for l in ff:
            l = l.strip()
            if not l or l.startswith("{"):
                continue
            try:
                uid = int(l.split("|")[0])
            except:
                continue
            try:
                if msg.photo:
                    await ctx.bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption or "")
                elif msg.video:
                    await ctx.bot.send_video(uid, msg.video.file_id, caption=msg.caption or "")
                elif msg.text:
                    await ctx.bot.send_message(uid, msg.text)
                sent += 1
            except Exception:
                continue
    await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_close")]
    ]))

# == ربط كل شيء ==
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("subscribe", handle_subscription_request))
app.add_handler(CommandHandler("admin", admin_panel))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), admin_media_handler))

app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern="^cancel_subscribe\\|"))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))

# == استقبال نص الاشتراك من المستخدم بدلاً من صورة (اسم أو رقم أو أي ملاحظة للاشتراك) ==
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_subscription_proof))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
