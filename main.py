// الكود السابق موجود بالفعل هنا ...

# ⬇️ إضافة الدوال الناقصة من البوت الكامل

async def receive_subscription_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message.photo:
        await update.message.reply_text("❌ الرجاء إرسال صورة إثبات الدفع فقط.")
        return
    photo_file = await update.message.photo[-1].get_file()
    photo_path = f"proofs/{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    os.makedirs("proofs", exist_ok=True)
    await photo_file.download_to_drive(photo_path)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data=f"confirm_sub|{user.id}"),
            InlineKeyboardButton("❌ رفض الاشتراك", callback_data=f"reject_sub|{user.id}")
        ]
    ])
    caption = f"📩 طلب اشتراك جديد:\nالمستخدم: @{user.username or 'NO_USERNAME'}\nID: {user.id}"
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=open(photo_path, "rb"),
        caption=caption,
        reply_markup=keyboard
    )
    await update.message.reply_text("✅ تم استلام إثبات الدفع، جاري المراجعة من قبل الأدمن.")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    store_user(user)
    if not is_subscribed(user.id):
        allowed = check_limits(user.id, "video")
        if not allowed:
            await update.message.reply_text("🚫 لقد وصلت للحد المجاني اليومي. اشترك للمتابعة.")
            return
    text = update.message.text.strip()
    if not is_valid_url(text):
        await update.message.reply_text("❌ الرابط غير صالح أو غير مدعوم.")
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

async def cancel_subscription_by_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.data.split("|")[1]
    deactivate_subscription(user_id)
    await query.edit_message_text(f"✅ تم إلغاء اشتراك المستخدم {user_id} من قبل الأدمن.")
    try:
        await context.bot.send_message(chat_id=int(user_id), text="❌ تم إلغاء اشتراكك من قبل الأدمن.")
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    store_user(user)
    welcome_text = (
        f"👋 مرحباً {user.first_name or ''}، سعيدون بانضمامك!

"
        "📥 أرسل رابط فيديو من YouTube أو TikTok أو Instagram أو Facebook لتحميله مباشرة.
"
        "🎯 يمكنك أيضاً إرسال سؤال وسنستخدم الذكاء الاصطناعي للإجابة عليه.

"
        f"💡 الحد المجاني اليومي: {DAILY_VIDEO_LIMIT} فيديو و{DAILY_AI_LIMIT} استفسار AI.
"
        f"🔓 اشترك مقابل 2 دينار عبر أورنج ماني: {ORANGE_NUMBER} وارسِل إثبات الدفع هنا لتفعيل الاشتراك."
    )
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆘 مساعدة", callback_data="help_menu")]
        ])
    )

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    help_text = (
        "🆘 *مساعدة*:
"
        "• أرسل رابط فيديو من TikTok أو YouTube أو Instagram أو Facebook.
"
        "• اختر الجودة أو حمّل الصوت فقط.
"
        "• يمكنك أيضاً إرسال سؤال وسيتم الرد عليه باستخدام الذكاء الاصطناعي.
"
        "• اشترك لتفعيل الاستخدام غير المحدود.
"
        "📩 لأي استفسار، تواصل مع الأدمن."
    )
    await query.edit_message_text(help_text, parse_mode="Markdown")

# ⬇️ ربط الهاندلرز والبدء بالبروجيكت
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_menu))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, receive_subscription_proof))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download))
app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(video|audio|cancel)\|"))
app.add_handler(CallbackQueryHandler(confirm_subscription, pattern=r"^confirm_sub\|"))
app.add_handler(CallbackQueryHandler(reject_subscription, pattern=r"^reject_sub\|"))
app.add_handler(CallbackQueryHandler(cancel_subscription_by_admin, pattern=r"^cancel_subscribe\|"))
app.add_handler(CallbackQueryHandler(admin_panel, pattern=r"^admin_back$"))
app.add_handler(CallbackQueryHandler(help_menu, pattern=r"^help_menu$"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{hostname}/{BOT_TOKEN}"
    )
