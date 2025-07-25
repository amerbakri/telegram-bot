async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, quality, key = query.data.split("|")
    except ValueError:
        await query.message.reply_text("⚠️ خطأ في المعالجة.")
        return

    if action == "cancel":
        url_store.pop(key, None)
        await query.edit_message_text("❌ تم الإلغاء.")
        return

    url = url_store.get(key)
    if not url:
        await query.edit_message_text("⚠️ الرابط غير صالح.")
        return

    await query.edit_message_text(f"⏳ جاري التحميل بجودة {quality}...")

    # التحميل الأساسي
    if action == "audio":
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-x", "--audio-format", "mp3",
            "-o", "audio.%(ext)s", url
        ]
        filename = "audio.mp3"
    else:
        format_code = quality_map.get(quality, "best")
        cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", format_code,
            "-o", "video.%(ext)s", url
        ]
        filename = None

    result = subprocess.run(cmd, capture_output=True, text=True)

    # إذا فشل التنزيل، جرب الجودة الافتراضية
    if result.returncode != 0:
        fallback_cmd = [
            "yt-dlp", "--cookies", COOKIES_FILE,
            "-f", "best[ext=mp4]",
            "-o", "video.%(ext)s", url
        ]
        fallback = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if fallback.returncode != 0:
            await query.message.reply_text("🚫 لم أتمكن من تحميل الفيديو. جرب رابط آخر.")
            return

    # تحديد اسم الملف النهائي
    if action == "video":
        for ext in ["mp4", "mkv", "webm"]:
            f = f"video.{ext}"
            if os.path.exists(f):
                filename = f
                break

    if filename and os.path.exists(filename):
        with open(filename, "rb") as f:
            if action == "audio":
                await query.message.reply_audio(f)
            else:
                await query.message.reply_video(f)
        os.remove(filename)
    else:
        await query.message.reply_text("🚫 الملف غير موجود بعد التحميل.")
        return

    # حذف الرابط و رسالة التحميل
    url_store.pop(key, None)
    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=int(key))
    except:
        pass
    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
    except:
        pass
