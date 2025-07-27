import os
import subprocess
import logging
import re
import openai
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

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ تأكد من تعيين BOT_TOKEN و OPENAI_API_KEY في .env")

openai.api_key = OPENAI_API_KEY
url_store = {}

def is_valid_url(text):
    pattern = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch)/.+"
    )
    return bool(pattern.match(text))

quality_map = {
    "720": "best[height<=720][ext=mp4]",
    "480": "best[height<=480][ext=mp4]",
    "360": "best[height<=360][ext=mp4]",
}

def store_user(user):
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                pass
        with open(USERS_FILE, "r") as f:
            users = f.read().splitlines()
        entry = f"{user.id}|{user.username or 'NO_USERNAME'}|{(user.first_name or '')} {(user.last_name or '')}".strip()
        if not any(str(user.id) in u for u in users):
            with open(USERS_FILE, "a") as f:
                f.write(f"{entry}\n")
    except Exception as e:
        logging.error(f"خطأ بتخزين المستخدم: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    await update.message.reply_text(
        "👋 أهلاً! أرسل لي رابط فيديو من يوتيوب أو تيك توك أو إنستا أو فيسبوك لتحميله 🎥"
    )

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_announcement"):
        return  # تجاهل أثناء انتظار الإعلان

    if not update.message or not update.message.text:
        return

    user = update.effective_user
    store_user(user)

    text = update.message.text.strip()

    if not is_valid_url(text):
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
        await query.edit_message_text("❌ تم الإلغاء.", reply_markup=None)
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
            await query.edit_message_text("🚫 فشل في تحميل الفيديو.", reply_markup=None)
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
    try:
        await loading_msg.delete()
    except:
        pass


# لوحة تحكم الأدمن
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
        [InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search_start")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]

    if update.message:
        await update.message.reply_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text("لوحة تحكم الأدمن:", reply_markup=InlineKeyboardMarkup(keyboard))


# إدارة نقرات لوحة الأدمن
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if query.from_user.id != ADMIN_ID:
        await query.answer("🚫 هذا الزر مخصص للأدمن فقط.", show_alert=True)
        return

    if data == "admin_users":
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            count = len(users)
            recent = "\n\n📌 آخر 5 مستخدمين:\n"
            for u in users[-5:]:
                uid, username, name = u.split("|")
                recent += f"👤 {name} | @{username} | ID: {uid}\n"
        except:
            count = 0
            recent = ""
        await query.edit_message_text(f"عدد المستخدمين المسجلين: {count}{recent}",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
                                      ]))

    elif data == "admin_broadcast":
        await query.edit_message_text("📝 أرسل لي الإعلان (نص فقط حالياً):")
        context.user_data["waiting_for_announcement"] = True

    elif data == "admin_close":
        await query.edit_message_text("❌ تم إغلاق لوحة التحكم.", reply_markup=None)

    elif data == "admin_back":
        await admin_panel(update, context)

    elif data == "admin_search_start":
        await query.edit_message_text("🔎 اكتب اسم المستخدم أو المعرف للبحث عنه:")
        context.user_data["waiting_for_search"] = True

    elif data.startswith("admin_search_result_"):
        selected_uid = data.split("_")[-1]
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            user_info = next((u for u in users if u.startswith(selected_uid + "|")), None)
            if user_info:
                uid, username, name = user_info.split("|")
                text = f"👤 المستخدم:\nالاسم: {name}\nالمعرف: @{username}\nالـ ID: {uid}"
            else:
                text = "❌ لم يتم العثور على المستخدم."
        except Exception as e:
            text = f"❌ خطأ: {e}"

        await query.edit_message_text(text,
                                     reply_markup=InlineKeyboardMarkup([
                                         [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]
                                     ]))


# استقبال نص الإعلان أو البحث
async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    text = update.message.text.strip()

    if context.user_data.get("waiting_for_announcement"):
        context.user_data["waiting_for_announcement"] = False
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            sent = 0
            for u in users:
                uid = u.split("|")[0]
                try:
                    await context.bot.send_message(chat_id=int(uid), text=text)
                    sent += 1
                except:
                    pass
            await update.message.reply_text(f"✅ تم إرسال الإعلان إلى {sent} مستخدمًا.")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في الإرسال: {e}")
        return

    if context.user_data.get("waiting_for_search"):
        context.user_data["waiting_for_search"] = False
        query = text.lower()
        try:
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            results = []
            for u in users:
                uid, username, name = u.split("|")
                # لا تطبق lower على uid لأنه أرقام
                if query in uid or query in username.lower() or query in name.lower():
                    results.append((uid, username, name))
            if not results:
                await update.message.reply_text("❌ لم يتم العثور على أي مستخدم.")
                return
            buttons = []
            for uid, username, name in results[:10]:
                buttons.append([InlineKeyboardButton(f"{name} | @{username}", callback_data=f"admin_search_result_{uid}")])
            buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")])
            await update.message.reply_text("📋 نتائج البحث:", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في البحث: {e}")
        return


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8443"))
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_handler))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(audio|video|cancel)\|"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
