import os
import json
import subprocess
import re
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
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

url_store = {}
user_pending_sub = set()
open_chats = set()

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_valid_url(text):
    pattern = r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    return re.match(pattern, text) is not None

def store_user(user):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f: pass
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = f.read().splitlines()
    entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}"
    if not any(str(user.id) in u for u in users):
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{entry}\n")

def is_subscribed(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    return str(user_id) in data and data[str(user_id)].get("active", False)

def activate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    data[str(user_id)] = {"active": True, "date": datetime.utcnow().isoformat()}
    save_json(SUBSCRIPTIONS_FILE, data)

def deactivate_subscription(user_id):
    data = load_json(SUBSCRIPTIONS_FILE, {})
    if str(user_id) in data:
        data.pop(str(user_id))
    save_json(SUBSCRIPTIONS_FILE, data)

def check_limits(user_id, action):
    if is_subscribed(user_id):
        return True
    today = datetime.utcnow().strftime("%Y-%m-%d")
    limits = load_json(LIMITS_FILE, {})
    user_limits = limits.get(str(user_id), {})
    if user_limits.get("date") != today:
        user_limits = {"date": today, "video": 0, "ai": 0}
    if action == "video" and user_limits["video"] >= DAILY_VIDEO_LIMIT:
        return False
    if action == "ai" and user_limits["ai"] >= DAILY_AI_LIMIT:
        return False
    user_limits[action] += 1
    limits[str(user_id)] = user_limits
    save_json(LIMITS_FILE, limits)
    return True

async def send_limit_message(update: Update):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        f"🚫 لقد وصلت للحد اليومي المجاني.\n"
        f"للاستخدام غير محدود، اشترك بـ 2 دينار شهريًا عبر أورنج ماني:\n"
        f"📲 الرقم: {ORANGE_NUMBER}\n"
        f"ثم اضغط زر اشترك الآن.",
        reply_markup=keyboard
    )

async def handle_subscription_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in user_pending_sub:
        await update.callback_query.answer("✅ تم إرسال طلبك بالفعل! انتظر مراجعة الأدمن.")
        return
    user_pending_sub.add(user.id)
    user_data = f"طلب اشتراك جديد:\n"
    user_data += f"الاسم: {user.first_name or ''} {user.last_name or ''}\n"
    user_data += f"المستخدم: @{user.username or 'NO_USERNAME'}\n"
    user_data += f"ID: {user.id}"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تفعيل الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    await context.bot.send_message(
        ADMIN_ID, user_data, reply_markup=keyboard
    )
    await update.callback_query.edit_message_text(
        "تم إرسال طلب الاشتراك للأدمن، سيتم تفعيله بعد المراجعة."
    )

async def confirm_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    activate_subscription(user_id)
    user_pending_sub.discard(int(user_id))
    await context.bot.send_message(chat_id=int(user_id),
        text="✅ تم تفعيل اشتراكك بنجاح!"
    )
    await query.edit_message_text("تم تفعيل الاشتراك للمستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    user_pending_sub.discard(int(user_id))
    await context.bot.send_message(chat_id=int(user_id),
        text="❌ تم رفض طلب الاشتراك."
    )
    await query.edit_message_text("تم رفض الاشتراك للمستخدم.")

def update_stats(action, quality):
    stats = load_json("stats.json", {
        "total_downloads": 0,
        "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
        "most_requested_quality": None
    })
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    stats["quality_counts"][key] = stats["quality_counts"].get(key, 0) + 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_json("stats.json", stats)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ابدأ الدعم", callback_data="support_start")],
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ])
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو من YouTube, TikTok, Facebook, Instagram لتحميله.\n"
        "الحد المجاني: 3 فيديو و 5 استفسارات AI يومياً.\n"
        f"للاشتراك المدفوع: إرسال 2 دينار عبر أورنج ماني {ORANGE_NUMBER} ثم أرسل صورة التحويل.",
        reply_markup=keyboard
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in open_chats:
        await update.message.reply_text("📩 أنت في دردشة الدعم، رجاءً انتظر رد الأدمن.")
        return

    msg = update.message.text.strip()
    store_user(update.effective_user)
    if not is_valid_url(msg):
        if not check_limits(user_id, "ai"):
            await send_limit_message(update)
            return
        try:
            res = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": msg}]
            )
            await update.message.reply_text(res.choices[0].message.content)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ AI: {e}")
        return

    if not check_limits(user_id, "video"):
        await send_limit_message(update)
        return

    key = str(update.message.message_id)
    url_store[key] = msg
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
    await update.message.reply_text("اختر الجودة أو صوت فقط:", reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        action, quality, key = query.data.split("|")
    except:
        await query.edit_message_text("خطأ في المعالجة.")
        return
    if action == "cancel":
        try: await query.edit_message_text("تم الإلغاء.")
        except: pass
        url_store.pop(key, None)
        return
    url = url_store.get(key)
    if not url:
        await query.edit_message_text("الرابط غير موجود أو منتهي.")
        return
    loading_msg = await query.edit_message_text(f"جاري التحميل بجودة {quality}...")
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
            await query.edit_message_text("فشل في تحميل الفيديو.")
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
        await query.message.reply_text("لم يتم العثور على الملف.")
    url_store.pop(key, None)
    try: await loading_msg.delete()
    except: pass

# دردشة الدعم المتكاملة (نصوص، صور، ملفات، إلخ)
def support_start_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("💬 ابدأ الدعم", callback_data="support_start")]])

def support_end_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ إنهاء الدعم", callback_data="support_end")]])

async def support_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data == "support_start":
        open_chats.add(user_id)
        await query.answer("تم فتح قناة الدعم")
        await query.edit_message_text(
            "💬 تم فتح قناة الدعم.\nيمكنك الآن إرسال رسائلك وسيتم الرد عليك من الأدمن.",
            reply_markup=support_end_keyboard()
        )
    elif data == "support_end":
        if user_id in open_chats:
            open_chats.remove(user_id)
            await query.answer("تم إغلاق قناة الدعم")
            await query.edit_message_text("❌ تم إغلاق قناة الدعم. لإعادة فتحها، اضغط على زر الدعم.")
        else:
            await query.answer("قناة الدعم غير مفتوحة", show_alert=True)

async def support_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in open_chats:
        await update.message.reply_text(
            "⛔ لم تبدأ قناة الدعم بعد. اضغط زر 'ابدأ الدعم' لفتحها.",
            reply_markup=support_start_keyboard()
        )
        return

    # إرسال أي نوع رسالة إلى الأدمن
    if update.message.text:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 رسالة نصية من المستخدم {user_id}:\n{update.message.text}"
        )
    elif update.message.photo:
        photo = update.message.photo[-1]
        caption = update.message.caption or ""
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo.file_id,
            caption=f"📩 صورة من المستخدم {user_id}:\n{caption}"
        )
    elif update.message.video:
        video = update.message.video
        caption = update.message.caption or ""
        await context.bot.send_video(
            chat_id=ADMIN_ID,
            video=video.file_id,
            caption=f"📩 فيديو من المستخدم {user_id}:\n{caption}"
        )
    elif update.message.audio:
        audio = update.message.audio
        caption = update.message.caption or ""
        await context.bot.send_audio(
            chat_id=ADMIN_ID,
            audio=audio.file_id,
            caption=f"📩 صوت من المستخدم {user_id}:\n{caption}"
        )
    elif update.message.document:
        doc = update.message.document
        caption = update.message.caption or ""
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=doc.file_id,
            caption=f"📩 ملف من المستخدم {user_id}:\n{caption}"
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 رسالة غير مدعومة من المستخدم {user_id}."
        )
    await update.message.reply_text("✅ تم إرسال رسالتك للأدمن، انتظر الرد.")

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        args = context.args
        target_id = int(args[0])
        reply_text = " ".join(args[1:])
        await context.bot.send_message(target_id, f"رد الأدمن:\n{reply_text}")
    except:
        await update.message.reply_text("استخدم الصيغة: /reply <user_id> <message>")

async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        user_id = int(context.args[0])
        if user_id in open_chats:
            open_chats.remove(user_id)
            await context.bot.send_message(user_id, "⚠️ تم إغلاق قناة الدعم من قبل الأدمن.")
            await update.message.reply_text(f"تم إغلاق قناة الدعم مع المستخدم {user_id}.")
        else:
            await update.message.reply_text("المستخدم ليس لديه دردشة مفتوحة.")
    except:
        await update.message.reply_text("استخدم الصيغة: /closechat <user_id>")

# لوحة تحكم الأدمن كاملة مع زر إغلاق ذكي
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("هذا الأمر خاص بالأدمن فقط.")
        elif update.callback_query:
            await update.callback_query.answer("هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton("عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("المشتركين المدفوعين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("قائمة دعم المستخدمين", callback_data="admin_support_list")],
        [InlineKeyboardButton("الإحصائيات", callback_data="admin_stats")],
        [InlineKeyboardButton("إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("إغلاق", callback_data="admin_close")]
    ]
    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    if data == "admin_close":
        try:
            await query.message.delete()
        except:
            await query.edit_message_text("تم إغلاق لوحة التحكم.", reply_markup=None)
        return

    if data == "admin_users":
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = f.read().splitlines()
        count = len(users)
        recent = "\n\nآخر 5 مستخدمين:\n"
        for u in users[-5:]:
            uid, username, name = u.split("|")
            recent += f"{name} | @{username} | ID: {uid}\n"
        await query.edit_message_text(f"عدد المستخدمين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_paidlist":
        data = load_json(SUBSCRIPTIONS_FILE, {})
        if not data:
            await query.edit_message_text("لا يوجد مشتركين مدفوعين حالياً.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("رجوع", callback_data="admin_back")]
            ]))
            return
        buttons = []
        text = "قائمة المشتركين المدفوعين:\n\n"
        for uid in data.keys():
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
            text += f"{fullname} (@{username}) — ID: {uid}\n"
            buttons.append([InlineKeyboardButton(f"❌ إلغاء {username}", callback_data=f"cancel_subscribe|{uid}")])
        buttons.append([InlineKeyboardButton("رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("cancel_subscribe|"):
        _, user_id = data.split("|")
        deactivate_subscription(user_id)
        await query.edit_message_text(f"تم إلغاء اشتراك المستخدم {user_id}.")
        try:
            await context.bot.send_message(chat_id=int(user_id), text="تم إلغاء اشتراكك من قبل الأدمن.")
        except:
            pass

    elif data == "admin_support_list":
        if not open_chats:
            await query.edit_message_text("لا يوجد مستخدمين لديهم دردشة دعم مفتوحة حالياً.")
            return
        buttons = []
        for uid in open_chats:
            buttons.append([
                InlineKeyboardButton(f"رد على {uid}", callback_data=f"support_reply|{uid}"),
                InlineKeyboardButton(f"إغلاق {uid}", callback_data=f"support_close|{uid}")
            ])
        buttons.append([InlineKeyboardButton("رجوع", callback_data="admin_back")])
        await query.edit_message_text("قائمة مستخدمي الدعم:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("support_reply|"):
        uid = int(data.split("|")[1])
        await query.edit_message_text(
            f"اكتب ردك للمستخدم {uid} بالصيغ: /reply {uid} <رسالتك>"
        )

    elif data.startswith("support_close|"):
        uid = int(data.split("|")[1])
        if uid in open_chats:
            open_chats.remove(uid)
            await context.bot.send_message(uid, "تم إغلاق دردشة الدعم من قبل الأدمن.")
            await query.edit_message_text(f"تم إغلاق دردشة الدعم مع المستخدم {uid}.")
        else:
            await query.edit_message_text("هذه الدردشة مغلقة أصلاً.")

    elif data == "admin_stats":
        stats = load_json("stats.json", {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        })
        text = (
            f"إحصائيات التحميل:\n"
            f"عدد الفيديوهات المنزلة: {stats['total_downloads']}\n"
            f"جودة 720p: {stats['quality_counts'].get('720',0)} مرات\n"
            f"جودة 480p: {stats['quality_counts'].get('480',0)} مرات\n"
            f"جودة 360p: {stats['quality_counts'].get('360',0)} مرات\n"
            f"تحميل الصوت فقط: {stats['quality_counts'].get('audio',0)} مرات\n"
            f"أكثر جودة مطلوبة: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_broadcast":
        await query.edit_message_text("أرسل لي الإعلان (نص أو صورة أو فيديو أو صوت):")
        context.user_data["waiting_for_announcement"] = True

    elif data == "admin_back":
        await admin_panel(update, context)

# استقبال إعلان من الأدمن قبل الإرسال
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        context.user_data["announcement"] = update.message
        await update.message.reply_text("هل تريد تأكيد الإرسال؟", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم", callback_data="confirm_broadcast"),
             InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]
        ]))

# تأكيد إرسال الإعلان
async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = context.user_data.get("announcement")
    if not message:
        await query.edit_message_text("لا يوجد إعلان محفوظ.")
        return
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = [line.strip() for line in f if line.strip()]
    sent = 0
    for l in users:
        uid = int(l.split("|")[0])
        try:
            if message.photo:
                await context.bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "")
            elif message.video:
                await context.bot.send_video(uid, message.video.file_id, caption=message.caption or "")
            elif message.audio:
                await context.bot.send_audio(uid, message.audio.file_id, caption=message.caption or "")
            elif message.text:
                await context.bot.send_message(uid, message.text)
            sent += 1
        except:
            pass
    await query.edit_message_text(f"تم إرسال الإعلان إلى {sent} مستخدم.")

# تسجيل الهاندلرز
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(admin_users|admin_paidlist|admin_support_list|admin_stats|admin_broadcast|admin_close|admin_back|support_reply\\|\\d+|support_close\\|\\d+)$"))
app.add_handler(CallbackQueryHandler(support_button_handler, pattern="^(support_start|support_end)$"))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, support_message_handler))
app.add_handler(CommandHandler("reply", admin_reply))
app.add_handler(CommandHandler("closechat", close_chat))
app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), media_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
