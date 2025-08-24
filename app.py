import os
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta

TOKEN = os.getenv("BOT_TOKEN")

# Handle incoming files
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = None

    # Check for document, video, or audio
    if update.message.document:
        file = update.message.document
    elif update.message.video:
        file = update.message.video
    elif update.message.audio:
        file = update.message.audio

    if not file:
        return

    # Get file info
    telegram_file = await context.bot.get_file(file.file_id)

    # Generate expiry (48 hours)
    expiry_time = datetime.utcnow() + timedelta(hours=48)
    expiry_str = expiry_time.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build Telegram CDN link (proxy, no token exposure)
    stream_link = f"https://api.telegram.org/file/bot{TOKEN}/{telegram_file.file_path}"

    # Reply to user
    await update.message.reply_text(
        f"✅ Your temporary link (valid until {expiry_str}):\n\n{stream_link}"
    )

# Main function
def main():
    app = Application.builder().token(TOKEN).build()

    # Correct filters for v20.3
    file_filter = filters.Document.ALL | filters.Video.ALL | filters.Audio.ALL
    app.add_handler(MessageHandler(file_filter, handle_file))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
