import os
import subprocess
import logging
import re
import json
import openai
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
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
ORANGE_NUMBER = "0781200500"

openai.api_key = OPENAI_API_KEY
url_store = {}

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def is_valid_url(text):
    return re.match(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+",
        text
    ) is not None

def store_user(user):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f: pass
    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()
    entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{user.first_name or ''} {user.last_name or ''}".strip()
    if not any(str(user.id) in u for u in users):
        with open(USERS_FILE, "a") as f:
            f.write(f"{entry}\n")

def load_json(file_path, default=None):
    if not os.path.exists(file_path):
        return default if default is not None else {}
    with open(file_path, "r") as f:
        try: return json.load(f)
        except: return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w") as f:
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
    if is_subscribed(user_id) or user_id == ADMIN_ID:
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    keyboard = [
        [InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")],
        [InlineKeyboardButton("💬 دردشة مع الأدمن", callback_data="start_chat")]
    ]
    await update.message.reply_text(
        "👋 أهلاً! أرسل رابط فيديو من يوتيوب/تيك توك/إنستا/فيسبوك لتحميله.\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        f"🔔 للاشتراك المدفوع، أرسل 2 دينار إلى رقم أورنج ماني: {ORANGE_NUMBER} ثم أرسل صورة التحويل.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)
    if not is_subscribed(user.id):
        allowed = check_limits(user.id, "video")
        if not allowed:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
            await update.message.reply_text(
                f"🚫 تجاوزت الحد اليومي المجاني للتحميل.\n"
                f"📲 اشترك الآن عبر أورنج ماني: {ORANGE_NUMBER}",
                reply_markup=keyboard
            )
            return
    text = update.message.text.strip()
    if not is_valid_url(text):
        if not is_subscribed(user.id):
            allowed = check_limits(user.id, "ai")
            if not allowed:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 اشترك الآن", callback_data="subscribe_request")]])
                await update.message.reply_text(
                    f"🚫 تجاوزت الحد اليومي المجاني لاستفسارات AI.\n"
                    f"📲 اشترك الآن عبر أورنج ماني: {ORANGE_NUMBER}",
                    reply_markup=keyboard
                )
                return
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": text}]
            )
            reply = response['choices'][0]['message']['content']
            await update.message.reply_text(reply)
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ في OpenAI: {e}")
        return

    key = str(update.message.message_id)
    url_store[key] = text
    keyboard = [
        [InlineKeyboardButton("🎵 صوت فقط", callback_data=f"audio|best|{key}")],
        [
            InlineKeyboardButton("🎥 720p", callback_data=f"video|720|{key}"),
            InlineKeyboardButton("🎥 480p", callback_data=f"video|480|{key}"),
            InlineKeyboardButton("🎥 360p", callback_data=f"video|360|{key}")
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel|{key}")]
    ]
    try: await update.message.delete()
    except: pass
    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    action = data[0]

    if action == "subscribe_request":
        user = query.from_user
        with open(REQUESTS_FILE, "a") as f:
            f.write(f"{user.id}|{user.username or 'NO_USERNAME'}|{datetime.utcnow()}\n")
        await query.edit_message_text(
            f"💳 للاشتراك:\n"
            f"أرسل 2 دينار عبر أورنج ماني إلى الرقم:\n📱 {ORANGE_NUMBER}\n"
            f"ثم أرسل لقطة شاشة (صورة) من التحويل هنا ليتم تفعيل اشتراكك."
        )
        return

    if action == "cancel":
        key = data[1]
        url_store.pop(key, None)
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    if action in ("video", "audio"):
        quality = data[1]
        key = data[2]
        url = url_store.get(key)
        if not url:
            await query.edit_message_text("⚠️ الرابط غير موجود أو منتهي.")
            return

        loading_msg = await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")
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
                await query.edit_message_text("🚫 فشل في تحميل الفيديو.")
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
        else:
            await query.message.reply_text("🚫 لم يتم العثور على الملف.")

        url_store.pop(key, None)
        try: await loading_msg.delete()
        except: pass
        return

# إضافة هندلر لدردشة الأدمن والمستخدم
user_chatting = {}

async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🔙 إنهاء المحادثة", callback_data="end_chat")]
    ]
    user_chatting[user.id] = True
    await update.message.reply_text(
        "💬 يمكنك الآن التحدث مع الأدمن. اكتب رسالتك أو اضغط إنهاء للمغادرة.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user_chatting.get(user.id):
        # إعادة توجيه الرسالة إلى الأدمن
        try:
            if update.message.text:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"💬 رسالة من @{user.username or 'NoUsername'} (ID: {user.id}):\n\n{update.message.text}"
                )
            elif update.message.photo:
                file = await update.message.photo[-1].get_file()
                await file.download_to_drive(f"temp/{user.id}_userphoto.jpg")
                await context.bot.send_photo(
                    ADMIN_ID,
                    photo=open(f"temp/{user.id}_userphoto.jpg", "rb"),
                    caption=f"💬 صورة من @{user.username or 'NoUsername'} (ID: {user.id})"
                )
            # يمكن إضافة المزيد من أنواع الوسائط حسب الحاجة
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ أثناء إرسال الرسالة للأدمن: {e}")
        return
    else:
        # لا في دردشة مفتوحة للمستخدم
        await update.message.reply_text("❌ ليس لديك محادثة مفتوحة مع الأدمن. اكتب /start للبدء.")

async def admin_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    data = query.data
    if data == "end_chat":
        user = query.from_user
        user_chatting.pop(user.id, None)
        await query.edit_message_text("🛑 انتهت المحادثة. شكراً لك!")
    else:
        await query.answer()

async def end_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_chatting.pop(query.from_user.id, None)
    await query.edit_message_text("🛑 تم إنهاء المحادثة. شكراً لاستخدامك البوت.")

# لوحة تحكم الأدمن (يمكنك إضافة أو تعديل حسب حاجتك)
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return
    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 إضافة مشترك مدفوع", callback_data="admin_addpaid")],
        [InlineKeyboardButton("🟢 قائمة المشتركين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

# إضافة باقي هندلرات الأدمن (يوجد عدة CallbackQueryHandlers لإدارة الأزرار)
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return
    # هنا ضع باقي أوامر الأدمن حسب البيانات في query.data
    # مثال:
    if data == "admin_users":
        if not os.path.exists(USERS_FILE):
            await query.edit_message_text("لا يوجد مستخدمين.")
            return
        lines = open(USERS_FILE, encoding="utf-8").read().splitlines()
        text = f"👥 عدد المستخدمين: {len(lines)}\n\nآخر 5 مستخدمين:\n"
        for l in lines[-5:]:
            parts = l.split("|")
            text += f"👤 {parts[2]} | @{parts[1]} | ID: {parts[0]}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))
    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل نص أو صورة أو فيديو للإعلان:")
        context.user_data["waiting_for_announcement"] = True
    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل اسم المستخدم أو رقم المستخدم للبحث:")
        context.user_data["waiting_for_search"] = True
    elif data == "admin_stats":
        stats = load_json(STATS_FILE, {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        })
        text = (
            f"📊 إحصائيات التحميل:\n"
            f"عدد الفيديوهات المنزلة: {stats['total_downloads']}\n"
            f"جودة 720p: {stats['quality_counts'].get('720', 0)} مرات\n"
            f"جودة 480p: {stats['quality_counts'].get('480', 0)} مرات\n"
            f"جودة 360p: {stats['quality_counts'].get('360', 0)} مرات\n"
            f"تحميل الصوت فقط: {stats['quality_counts'].get('audio', 0)} مرات\n"
            f"أكثر جودة مطلوبة: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))
    elif data == "admin_addpaid":
        await query.edit_message_text("📥 أرسل آيدي المستخدم الذي تريد إضافته كمشترك مدفوع.\nمثال: 123456789")
        context.user_data["waiting_for_addpaid"] = True
    elif data == "admin_paidlist":
        data = load_json(SUBSCRIPTIONS_FILE, {})
        if not data:
            await query.edit_message_text("لا يوجد مشتركين مدفوعين حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]))
            return
        buttons = []
        text = "👥 قائمة المشتركين المدفوعين:\n\n"
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
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=None)
    elif data == "admin_back":
        await admin_panel(update, context)
    elif data.startswith("cancel_subscribe|"):
        uid = data.split("|")[1]
        deactivate_subscription(uid)
        await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {uid}.")
        try:
            await context.bot.send_message(chat_id=int(uid), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
        except: pass

# التعامل مع رسائل الأدمن لإرسال الإعلانات أو البحث أو إضافة مشترك
async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        msg = update.message
        context.user_data["announcement"] = msg
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد الإرسال", callback_data="confirm_broadcast")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")]
        ])
        await msg.reply_text("✅ هل تريد تأكيد إرسال الإعلان؟", reply_markup=kb)
        return

    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        term = update.message.text.strip().lower()
        results = []
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if term in line.lower():
                        results.append(line.strip())
        await update.message.reply_text("\n".join(results) if results else "⚠️ لم يتم العثور على نتائج.")
        return

    if context.user_data.get("waiting_for_addpaid"):
        context.user_data["waiting_for_addpaid"] = False
        new_id = update.message.text.strip()
        if not new_id.isdigit():
            await update.message.reply_text("⚠️ آيدي غير صالح.")
            return
        activate_subscription(new_id)
        await update.message.reply_text(f"✅ تم إضافة المستخدم {new_id} كمشترك مدفوع.")
        return

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message = context.user_data.get("announcement")
    if not message:
        await query.edit_message_text("🚫 لا يوجد إعلان محفوظ.")
        return
    try:
        sent = 0
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    uid = int(line.split("|")[0])
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
                        continue
        await query.edit_message_text(f"📢 تم إرسال الإعلان إلى {sent} مستخدم.")
    except Exception as e:
        await query.edit_message_text(f"🚫 حدث خطأ أثناء الإرسال: {e}")

# ============== تشغيل البوت ================

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_subscription_proof))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(subscribe_request|cancel|video|audio)$"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(admin_users|admin_broadcast|admin_search|admin_stats|admin_addpaid|admin_paidlist|admin_close|admin_back|cancel_subscribe\|.+)$"))
    app.add_handler(CallbackQueryHandler(confirm_subscription, pattern="^confirm_sub\|"))
    app.add_handler(CallbackQueryHandler(reject_subscription, pattern="^reject_sub\|"))
    app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern="^cancel_subscribe\|"))
    app.add_handler(CallbackQueryHandler(confirm_broadcast, pattern="^confirm_broadcast$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), admin_message_handler))
    app.add_handler(MessageHandler(filters.ALL & filters.User(ADMIN_ID), media_handler))
    
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
