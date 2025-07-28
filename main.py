import os
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from datetime import datetime

# الإعدادات
BOT_TOKEN = os.getenv("BOT_TOKEN") or "ضع_توكن_البوت_هنا"
ADMIN_ID = 337597459  # عدّل إلى آيدي الأدمن

logging.basicConfig(level=logging.INFO)

# حفظ آخر رسالة مرسلة من كل مستخدم (للمطابقة عند الرد)
last_message_from_user = {}

# == استقبال رسالة من المستخدمين وإرسالها للأدمن ==
async def user_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    # حفظ آخر رسالة للمستخدم
    last_message_from_user[user.id] = msg.message_id
    # نص الرسالة
    text = msg.text or ""
    media = None

    # تجهيز نص للمشرف
    info = (
        f"📩 رسالة من مستخدم:\n"
        f"👤 الاسم: {user.first_name} {user.last_name or ''}\n"
        f"🔗 المعرف: @{user.username or 'بدون'}\n"
        f"🆔 ID: {user.id}\n"
        f"⏱️ في: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"\n"
    )
    if msg.text:
        info += f"💬 الرسالة:\n{text}"
        await context.bot.send_message(ADMIN_ID, info, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("رد عليه", callback_data=f"replyto|{user.id}")]
        ]))
    elif msg.photo:
        photo_file = msg.photo[-1].file_id
        info += f"🖼️ [صورة]\n"
        await context.bot.send_photo(ADMIN_ID, photo=photo_file, caption=info, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("رد عليه", callback_data=f"replyto|{user.id}")]
        ]))
    elif msg.video:
        video_file = msg.video.file_id
        info += f"🎬 [فيديو]\n"
        await context.bot.send_video(ADMIN_ID, video=video_file, caption=info, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("رد عليه", callback_data=f"replyto|{user.id}")]
        ]))
    elif msg.voice:
        voice_file = msg.voice.file_id
        info += f"🔊 [رسالة صوتية]\n"
        await context.bot.send_voice(ADMIN_ID, voice=voice_file, caption=info, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("رد عليه", callback_data=f"replyto|{user.id}")]
        ]))
    else:
        await context.bot.send_message(ADMIN_ID, info + "[رسالة غير معروفة]")

    await msg.reply_text("✅ تم إرسال رسالتك إلى الأدمن. سنرد عليك بأقرب وقت.")

# == الأدمن يضغط زر "رد عليه" أو يكتب أمر الرد ==
reply_to_id = {}

async def replyto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ هذا الزر للمشرف فقط.", show_alert=True)
        return
    _, uid = data.split("|")
    reply_to_id[update.effective_user.id] = int(uid)
    await query.answer()
    await query.message.reply_text(f"✏️ اكتب رسالتك الآن، وسيتم إرسالها للمستخدم ID:{uid}")

# == استقبال رسالة من الأدمن وإعادة توجيهها ==
async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user
    if admin.id != ADMIN_ID: return

    uid = reply_to_id.get(admin.id)
    if not uid:
        # دعم الرد عبر أمر: /رد 123456789 مرحباً!
        if update.message.text and update.message.text.startswith("/رد "):
            parts = update.message.text.split(" ", 2)
            if len(parts) >= 3 and parts[1].isdigit():
                uid = int(parts[1])
                msg_txt = parts[2]
                await context.bot.send_message(uid, f"📩 رد الأدمن:\n{msg_txt}")
                await update.message.reply_text("✅ تم إرسال الرد للمستخدم.")
            else:
                await update.message.reply_text("❗ الصيغة: /رد آيدي الرسالة")
            return
        await update.message.reply_text("❗ اضغط زر (رد عليه) أسفل رسالة المستخدم أولاً أو استخدم: /رد ID النص")
        return

    # إرسال نفس نوع الرسالة للمستخدم
    if update.message.text:
        await context.bot.send_message(uid, f"📩 رد الأدمن:\n{update.message.text}")
    elif update.message.photo:
        await context.bot.send_photo(uid, photo=update.message.photo[-1].file_id, caption="📩 رد الأدمن: صورة")
    elif update.message.video:
        await context.bot.send_video(uid, video=update.message.video.file_id, caption="📩 رد الأدمن: فيديو")
    elif update.message.voice:
        await context.bot.send_voice(uid, voice=update.message.voice.file_id, caption="📩 رد الأدمن: صوت")
    await update.message.reply_text("✅ تم إرسال الرد للمستخدم.")
    reply_to_id.pop(admin.id, None)

# == تشغيل البوت ==
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL & ~filters.User(user_id=ADMIN_ID), user_message_handler))
    app.add_handler(CallbackQueryHandler(replyto_callback, pattern=r"^replyto\|"))
    app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), admin_message_handler))
    app.add_handler(CommandHandler("رد", admin_message_handler))
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
