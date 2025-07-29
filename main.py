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

url_store = {}
user_pending_sub = set()
open_chats = set()
admin_waiting_reply = {}

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
        open(USERS_FILE, "w", encoding="utf-8").close()
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

async def safe_edit_message_text(query, text, reply_markup=None):
    try:
        if query.message.text == text and (reply_markup is None or query.message.reply_markup == reply_markup):
            return
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"edit_message_text error: {e}")

def user_fullname(user):
    return f"{user.first_name or ''} {user.last_name or ''}".strip()

# ----------- واجهة البداية والدعم -----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    keyboard = [
        [InlineKeyboardButton("💬 ابدأ الدعم", callback_data="support_start")],
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو من YouTube, TikTok, Facebook, Instagram لتحميله.\n"
        "الحد المجاني: 3 فيديو و 5 استفسارات AI يومياً.\n"
        f"للاشتراك المدفوع: إرسال 2 دينار عبر أورنج ماني {ORANGE_NUMBER} ثم أرسل صورة التحويل.",
        reply_markup=markup
    )

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
    user_data = (
        f"طلب اشتراك جديد:\n"
        f"الاسم: {user_fullname(user)}\n"
        f"المستخدم: @{user.username or 'NO_USERNAME'}\n"
        f"ID: {user.id}"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ فتح محادثة", callback_data=f"support_reply|{user.id}"),
            InlineKeyboardButton("✅ تفعيل الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ],
        [InlineKeyboardButton("❌ إنهاء الدعم", callback_data=f"support_close|{user.id}")]
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
    await safe_edit_message_text(query, "تم تفعيل الاشتراك للمستخدم.")

async def reject_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, user_id = query.data.split("|")
    user_pending_sub.discard(int(user_id))
    await context.bot.send_message(chat_id=int(user_id),
        text="❌ تم رفض طلب الاشتراك."
    )
    await safe_edit_message_text(query, "تم رفض الاشتراك للمستخدم.")

# ----------- الدعم (مستخدم/أدمن) -----------

async def support_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "support_start":
        if user_id in open_chats:
            await query.answer("قناة الدعم مفتوحة بالفعل.")
            return
        open_chats.add(user_id)
        await query.answer("تم فتح قناة الدعم")
        await query.edit_message_text(
            "💬 تم فتح قناة الدعم. يمكنك الآن إرسال رسائلك.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إنهاء الدعم", callback_data="support_end")]
            ])
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ فتح دعم جديد من المستخدم: {user_id}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📝 رد", callback_data=f"support_reply|{user_id}"),
                    InlineKeyboardButton("❌ إغلاق", callback_data=f"support_close|{user_id}")
                ]
            ])
        )

    elif data == "support_end":
        if user_id in open_chats:
            open_chats.remove(user_id)
            await query.answer("تم إغلاق قناة الدعم")
            await query.edit_message_text("❌ تم إغلاق قناة الدعم.")
            await context.bot.send_message(user_id, "❌ تم إغلاق قناة الدعم من قبلك.")
        else:
            await query.answer("قناة الدعم غير مفتوحة", show_alert=True)

async def support_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in open_chats:
        await update.message.reply_text(
            "⛔ لم تبدأ قناة الدعم بعد. اضغط زر 'ابدأ الدعم' لفتحها.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 ابدأ الدعم", callback_data="support_start")]
            ])
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 رد", callback_data=f"support_reply|{user_id}"),
            InlineKeyboardButton("❌ إنهاء", callback_data=f"support_close|{user_id}")
        ]
    ])

    if update.message.text:
        await context.bot.send_message(ADMIN_ID, f"من المستخدم {user_id}:\n{update.message.text}", reply_markup=keyboard)
    elif update.message.photo:
        await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id,
                                     caption=f"من المستخدم {user_id}:\n{update.message.caption or ''}", reply_markup=keyboard)
    elif update.message.video:
        await context.bot.send_video(ADMIN_ID, update.message.video.file_id,
                                     caption=f"من المستخدم {user_id}:\n{update.message.caption or ''}", reply_markup=keyboard)
    elif update.message.audio:
        await context.bot.send_audio(ADMIN_ID, update.message.audio.file_id,
                                     caption=f"من المستخدم {user_id}:\n{update.message.caption or ''}", reply_markup=keyboard)
    elif update.message.document:
        await context.bot.send_document(ADMIN_ID, update.message.document.file_id,
                                        caption=f"من المستخدم {user_id}:\n{update.message.caption or ''}", reply_markup=keyboard)
    else:
        await context.bot.send_message(ADMIN_ID, f"رسالة جديدة من المستخدم {user_id}.", reply_markup=keyboard)

    await update.message.reply_text("✅ تم إرسال رسالتك للأدمن، انتظر الرد.")

# ----------- الرد من الأدمن على المستخدم (ميزة مهمة) -----------
async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    reply_to = None
    # دعم الرد السريع من زر في الدعم
    if "reply_to_user" in context.user_data:
        reply_to = context.user_data["reply_to_user"]
        del context.user_data["reply_to_user"]
    # دعم الرد العادي (لو كتب الأدمن "/reply 123456")
    elif update.message.text and update.message.text.startswith("/reply "):
        try:
            reply_to = int(update.message.text.split()[1])
        except: pass

    if reply_to:
        await context.bot.send_message(chat_id=reply_to, text=f"📩 رد الأدمن:\n{update.message.text}")
        await update.message.reply_text("✅ تم إرسال ردك للمستخدم.")
    else:
        await update.message.reply_text("❗ استخدم زر الرد ضمن الدعم أو أرسل الأمر: /reply [ID] متبوع برسالتك.")

# ----------- تحميل الفيديو والذكاء الصناعي -----------

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in open_chats:
        await update.message.reply_text("📩 أنت في دردشة الدعم، رجاءً انتظر رد الأدمن.")
        return

    msg = update.message.text.strip()
    store_user(update.effective_user)

    if not is_valid_url(msg):
        if user_id == ADMIN_ID:
            return
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
    try:
        await update.message.delete()
    except:
        pass
    await update.message.reply_text("اختر الجودة أو صوت فقط:", reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if "|" not in data:
        await query.answer("طلب غير صالح.")
        return

    action, quality, key = data.split("|")
    if action == "cancel":
        try:
            await query.message.delete()
        except:
            pass
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.answer("انتهت صلاحية الرابط.")
        try:
            await query.message.delete()
        except:
            pass
        return

    await query.edit_message_text("⏳ جاري التحميل...")

    output = "video.mp4"
    download_cmd = []
    caption = ""

    if action == "audio":
        download_cmd = [
            "yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio/best", "--extract-audio",
            "--audio-format", "mp3", "-o", output, "--cookies", COOKIES_FILE, url
        ]
        caption = "🎵 تم التحميل (صوت فقط)"
    elif action == "video":
        quality_code = quality_map.get(quality, "best[ext=mp4]")
        download_cmd = [
            "yt-dlp", "-f", quality_code, "-o", output, "--cookies", COOKIES_FILE, url
        ]
        caption = f"🎬 تم التحميل بجودة {quality}p"

    try:
        subprocess.run(download_cmd, check=True)
        with open(output, "rb") as video_file:
            if action == "audio":
                await context.bot.send_audio(chat_id=user_id, audio=video_file, caption=caption)
            else:
                await context.bot.send_video(chat_id=user_id, video=video_file, caption=caption)
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ حدث خطأ أثناء التحميل: {e}")
    finally:
        if os.path.exists(output):
            os.remove(output)
        url_store.pop(key, None)
    try:
        await query.message.delete()
    except:
        pass

# ----------------- الهاندلرز -----------------
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^(video|audio|cancel)\\|"))
app.add_handler(CallbackQueryHandler(handle_subscription_request, pattern="^subscribe_request$"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\\|"))
app.add_handler(CallbackQueryHandler(support_button_handler, pattern="^support_(start|end)$"))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, support_message_handler))
app.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=ADMIN_ID), admin_reply_handler))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
