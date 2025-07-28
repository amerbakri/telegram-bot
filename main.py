import os
import subprocess
import logging
import re
import json
import datetime
import openai
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
PAYMENT_PROOFS_DIR = "payment_proofs"

ADMIN_ID = 337597459
USERS_FILE = "users.txt"
STATS_FILE = "stats.json"
USAGE_FILE = "usage.json"
PAID_USERS_FILE = "paid_users.txt"

MAX_VIDEO_DOWNLOADS_FREE = 3
MAX_AI_REQUESTS_FREE = 5

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
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                pass
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{(user.first_name or '')} {(user.last_name or '')}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

def load_json(file_path):
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_paid_users():
    if not os.path.exists(PAID_USERS_FILE):
        return set()
    with open(PAID_USERS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_paid_user(user_id):
    paid_users = load_paid_users()
    if str(user_id) not in paid_users:
        with open(PAID_USERS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{user_id}\n")

def remove_paid_user(user_id):
    paid_users = load_paid_users()
    if str(user_id) in paid_users:
        paid_users.remove(str(user_id))
        with open(PAID_USERS_FILE, "w", encoding="utf-8") as f:
            for uid in paid_users:
                f.write(f"{uid}\n")
        return True
    return False

def is_paid_user(user_id):
    paid_users = load_paid_users()
    return str(user_id) in paid_users

def reset_daily_usage_if_needed(usage_data):
    today_str = datetime.date.today().isoformat()
    if usage_data.get("date") != today_str:
        usage_data["date"] = today_str
        usage_data["video_downloads"] = {}
        usage_data["ai_requests"] = {}
    return usage_data

def increment_usage(user_id, usage_type):
    usage_data = load_json(USAGE_FILE)
    usage_data = reset_daily_usage_if_needed(usage_data)

    user_id_str = str(user_id)
    if usage_type == "video":
        count = usage_data.get("video_downloads", {}).get(user_id_str, 0)
        if count >= MAX_VIDEO_DOWNLOADS_FREE:
            return False
        usage_data.setdefault("video_downloads", {})[user_id_str] = count + 1

    elif usage_type == "ai":
        count = usage_data.get("ai_requests", {}).get(user_id_str, 0)
        if count >= MAX_AI_REQUESTS_FREE:
            return False
        usage_data.setdefault("ai_requests", {})[user_id_str] = count + 1

    save_json(USAGE_FILE, usage_data)
    return True

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "total_downloads": 0,
            "quality_counts": {"720": 0, "480": 0, "360": 0, "audio": 0},
            "most_requested_quality": None
        }
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_stats(stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def update_stats(action, quality):
    stats = load_stats()
    stats["total_downloads"] += 1
    key = quality if action != "audio" else "audio"
    if key in stats["quality_counts"]:
        stats["quality_counts"][key] += 1
    else:
        stats["quality_counts"][key] = 1
    stats["most_requested_quality"] = max(stats["quality_counts"], key=stats["quality_counts"].get)
    save_stats(stats)

def ensure_payment_proofs_dir():
    if not os.path.exists(PAYMENT_PROOFS_DIR):
        os.makedirs(PAYMENT_PROOFS_DIR)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥\n"
        "💡 الحد المجاني: 3 فيديوهات و5 استفسارات AI يومياً.\n"
        "🔔 للاشتراك المدفوع، راسل الأدمن."
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)

    # تحقق الاشتراك أو الحد اليومي
    if not is_paid_user(user.id):
        allowed = increment_usage(user.id, "video")
        if not allowed:
            await update.message.reply_text(
                "🚫 وصلت إلى الحد المجاني اليومي (3 فيديوهات).\n"
                "للمتابعة، اشترك عبر رقم 0781200500 (أورنج)."
            )
            return

    text = update.message.text.strip()

    if not is_valid_url(text):
        # AI usage limit check
        if not is_paid_user(user.id):
            allowed = increment_usage(user.id, "ai")
            if not allowed:
                await update.message.reply_text(
                    "🚫 وصلت إلى الحد المجاني اليومي لاستفسارات AI (5 مرات).\n"
                    "للمتابعة، اشترك عبر رقم 0781200500 (أورنج)."
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
            await update.message.reply_text(f"⚠️ خطأ OpenAI: {e}")
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

    try:
        await update.message.delete()
    except:
        pass

    await update.message.reply_text("📥 اختر نوع التنزيل:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        await query.edit_message_text("❌ تم الإلغاء.")
        url_store.pop(key, None)
        return

    url = url_store.get(key)
    if not url:
        await query.message.reply_text("⚠️ الرابط غير صالح أو منتهي.")
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
        update_stats(action, quality)
    else:
        await query.message.reply_text("🚫 لم يتم العثور على الملف.")

    url_store.pop(key, None)
    try:
        await loading_msg.delete()
    except:
        pass

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        elif update.callback_query:
            await update.callback_query.answer("⚠️ هذا الأمر خاص بالأدمن فقط.", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton("👥 عدد المستخدمين", callback_data="admin_users")],
        [InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search")],
        [InlineKeyboardButton("📊 إحصائيات التحميل", callback_data="admin_stats")],
        [InlineKeyboardButton("💎 قائمة المشتركين المدفوعين", callback_data="admin_paidlist")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]

    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    if data == "admin_users":
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = f.read().splitlines()
            count = len(users)
            recent = "\n\n📌 آخر 5 مستخدمين:\n"
            for u in users[-5:]:
                uid, username, name = u.split("|")
                recent += f"👤 {name} | @{username} | ID: {uid}\n"
        except:
            count = 0
            recent = ""
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{recent}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل لي الإعلان (نص أو صورة أو فيديو مع نص):")
        context.user_data["waiting_for_announcement"] = True

    elif data == "admin_search":
        await query.edit_message_text("🔍 أرسل لي اسم المستخدم أو رقم المستخدم للبحث:")
        context.user_data["waiting_for_search"] = True

    elif data == "admin_stats":
        stats = load_stats()
        text = (
            f"📊 إحصائيات التحميل:\n"
            f"عدد الفيديوهات المنزلة: {stats['total_downloads']}\n"
            f"جودة 720p: {stats['quality_counts'].get('720',0)} مرات\n"
            f"جودة 480p: {stats['quality_counts'].get('480',0)} مرات\n"
            f"جودة 360p: {stats['quality_counts'].get('360',0)} مرات\n"
            f"تحميل الصوت فقط: {stats['quality_counts'].get('audio',0)} مرات\n"
            f"أكثر جودة مطلوبة: {stats['most_requested_quality']}"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
        ]))

    elif data == "admin_paidlist":
        paid_users = list(load_paid_users())
        if not paid_users:
            text = "⚠️ لا يوجد مشتركين مدفوعين حالياً."
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
            ]))
            return
        
        # نعرض قائمة مع زر إلغاء بجانب كل مستخدم
        buttons = []
        for uid in paid_users:
            display_text = f"ID: {uid}"
            buttons.append([InlineKeyboardButton(f"❌ {display_text}", callback_data=f"remove_paid|{uid}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
        await query.edit_message_text("💎 قائمة المشتركين المدفوعين:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("remove_paid|"):
        uid_to_remove = data.split("|")[1]
        removed = remove_paid_user(uid_to_remove)
        if removed:
            await query.answer(f"✅ تم حذف المستخدم {uid_to_remove} من المشتركين المدفوعين.", show_alert=True)
            # بعد الحذف نعيد عرض القائمة المحدثة
            paid_users = list(load_paid_users())
            if not paid_users:
                text = "⚠️ لا يوجد مشتركين مدفوعين حالياً."
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
                ]))
                return
            buttons = []
            for uid in paid_users:
                display_text = f"ID: {uid}"
                buttons.append([InlineKeyboardButton(f"❌ {display_text}", callback_data=f"remove_paid|{uid}")])
            buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
            await query.edit_message_text("💎 قائمة المشتركين المدفوعين:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await query.answer("⚠️ حدث خطأ أو المستخدم غير موجود.", show_alert=True)

    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=ReplyKeyboardRemove())

    elif data == "admin_back":
        await admin_panel(update, context)

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        context.user_data["announcement"] = update.message
        await update.message.reply_text("✅ هل تريد تأكيد الإرسال؟", reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ نعم", callback_data="confirm_broadcast"),
                InlineKeyboardButton("❌ إلغاء", callback_data="admin_back")
            ]
        ]))
        return

    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query_text = update.message.text.strip()
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = f.read().splitlines()
            results = []
            for u in users:
                uid, username, name = u.split("|")
                if query_text.lower() in username.lower() or query_text == uid or query_text in name.lower():
                    results.append(f"👤 {name} | @{username} | ID: {uid}")
            if results:
                reply = "نتائج البحث:\n" + "\n".join(results)
            else:
                reply = "⚠️ لم يتم العثور على مستخدم."
        except Exception as e:
            reply = f"⚠️ خطأ في البحث: {e}"

        await update.message.reply_text(reply)
        return

    # استقبال إثبات الدفع
    if context.user_data.get("waiting_for_payment_proof"):
        context.user_data["waiting_for_payment_proof"] = False
        ensure_payment_proofs_dir()

        user_id = None
        if update.message.caption:
            match = re.search(r'\b(\d{5,})\b', update.message.caption)
            if match:
                user_id = match.group(1)
        elif update.message.text:
            match = re.search(r'\b(\d{5,})\b', update.message.text)
            if match:
                user_id = match.group(1)

        if not user_id:
            await update.message.reply_text("⚠️ لم أتمكن من العثور على آيدي المستخدم في الرسالة. أرسل الصورة مع كتابة آيدي المستخدم في الوصف.")
            return

        photo = update.message.photo[-1] if update.message.photo else None
        if not photo:
            await update.message.reply_text("⚠️ الرجاء إرسال صورة إثبات الدفع.")
            return

        file = await photo.get_file()
        filename = os.path.join(PAYMENT_PROOFS_DIR, f"{user_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
        await file.download_to_drive(filename)

        save_paid_user(user_id)
        await update.message.reply_text(f"✅ تم تفعيل الاشتراك المدفوع للمستخدم: {user_id} وشكرًا لإرسال إثبات الدفع.")

async def confirm_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    if query.data == "confirm_broadcast":
        announcement_msg = context.user_data.get("announcement")
        if not announcement_msg:
            await query.edit_message_text("⚠️ لم يتم العثور على رسالة للإرسال.")
            return

        await query.edit_message_text("⏳ جاري إرسال الإعلان...")

        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users = f.read().splitlines()
        except:
            users = []

        sent_count = 0
        fail_count = 0
        for u in users:
            uid = u.split("|")[0]
            try:
                if announcement_msg.text:
                    await context.bot.send_message(int(uid), announcement_msg.text)
                elif announcement_msg.photo:
                    photo_file = announcement_msg.photo[-1]
                    caption = announcement_msg.caption or ""
                    await context.bot.send_photo(int(uid), photo_file.file_id, caption=caption)
                elif announcement_msg.video:
                    video_file = announcement_msg.video
                    caption = announcement_msg.caption or ""
                    await context.bot.send_video(int(uid), video_file.file_id, caption=caption)
            except Exception as e:
                fail_count += 1
                logging.error(f"خطأ بالإرسال للمستخدم {uid}: {e}")
            else:
                sent_count += 1

        await query.edit_message_text(f"✅ تم إرسال الإعلان إلى {sent_count} مستخدمين.\nفشل الإرسال لـ {fail_count} مستخدمين.")

        context.user_data["announcement"] = None

async def remove_paid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ هذا الأمر خاص بالأدمن فقط.")
        return

    if len(context.args) == 0:
        await update.message.reply_text("⚠️ استخدم: /removepaid <user_id>")
        return

    user_id = context.args[0].strip()
    if remove_paid_user(user_id):
        await update.message.reply_text(f"✅ تم حذف الاشتراك المدفوع للمستخدم: {user_id}")
    else:
        await update.message.reply_text("⚠️ لم أجد هذا المستخدم في المشتركين المدفوعين.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # أوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("removepaid", remove_paid_command))

    # رسائل نصية
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download))

    # أزرار Inline
    application.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(video|audio|cancel)\|"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(confirm_broadcast_handler, pattern="^confirm_broadcast$"))

    # استقبال وسائط (صور، فيديو، نص)
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.TEXT, media_handler))

    # Webhook support (مثال)
    # application.run_webhook(listen="0.0.0.0", port=8443, url_path=BOT_TOKEN,
    #                         webhook_url=f"https://yourdomain.com/{BOT_TOKEN}")

    # للتشغيل العادي poll
   import os
port = int(os.environ.get("PORT", 8443))
hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
application.run_webhook(
    listen="0.0.0.0",
    port=port,
    url_path=BOT_TOKEN,
    webhook_url=f"https://{hostname}/{BOT_TOKEN}"
)

if __name__ == "__main__":
    main()
