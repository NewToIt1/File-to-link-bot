import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta

# Get bot token from environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Dictionary to store file links with expiry
file_links = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! Send me any file/video and I will give you a temporary streaming link (valid for 48 hours)."
    )

# Handle files
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.effective_attachment or update.message.document or update.message.video
    if not file:
        await update.message.reply_text("No file detected.")
        return

    # Get Telegram file URL
    file_id = file.file_id
    new_file = await context.bot.get_file(file_id)
    link = new_file.file_path  # Direct Telegram CDN link

    # Set expiry (48 hours from now)
    expiry = datetime.utcnow() + timedelta(hours=48)
    file_links[file_id] = {"link": link, "expiry": expiry}

    await update.message.reply_text(f"Your 48-hour streaming link:\n{link}")

# Optional: Clean expired links every hour
async def clean_expired_links(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow()
    expired = [fid for fid, info in file_links.items() if info["expiry"] < now]
    for fid in expired:
        del file_links[fid]

# Main function to start bot
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.Video.ALL | filters.Audio.ALL, handle_file))

    # Periodic job to clean expired links
    app.job_queue.run_repeating(clean_expired_links, interval=3600, first=10)

    # Run bot
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
