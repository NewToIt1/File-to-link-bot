import os
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")  # You must set BOT_TOKEN in Render Environment

# Handle incoming files
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = None
    if update.message.document:
        file = update.message.document
    elif update.message.video:
        file = update.message.video
    elif update.message.audio:
        file = update.message.audio

    if file:
        telegram_file = await context.bot.get_file(file.file_id)
        file_url = telegram_file.file_path  # Temporary link (valid ~1h on Telegram CDN)
        await update.message.reply_text(f"Here is your temporary link:\n{file_url}\n\n⚠️ Note: Expires soon!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a file and I will give you a temporary download link.")

def main():
    app = Application.builder().token(TOKEN).build()

    # Start command
    app.add_handler(MessageHandler(filters.COMMAND, start))

    # File handler (documents, videos, audios)
    app.add_handler(MessageHandler(filters.DOCUMENT | filters.VIDEO | filters.AUDIO, handle_file))

    app.run_polling()

if __name__ == "__main__":
    main()
