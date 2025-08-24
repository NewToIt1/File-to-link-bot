import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Get bot token from environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Store file links with expiry
file_links = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! Send me any file/video/audio and I will give you a temporary streaming link (valid for 48 hours)."
    )

# Handle incoming files
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = update.message.document or update.message.video or update.message.audio
    if not file:
        await update.message.reply_text("No file detected.")
        return

    # Get Telegram CDN link
    new_file = await context.bot.get_file(file.file_id)
    link = new_file.file_path

    # Set expiry 48 hours from now
    expiry = datetime.utcnow() + timedelta(hours=48)
    file_links[file.file_id] = {"link": link, "expiry": expiry}

    await update.message.reply_text(f"Your 48-hour streaming link:\n{link}")

# Periodic cleanup of expired links
async def clean_expired_links(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow()
    expired = [fid for fid, info in file_links.items() if info["expiry"] < now]
    for fid in expired:
        del file_links[fid]

# Main bot function
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    # Correct filter usage for v20.3
    app.add_handler(
        MessageHandler(
            filters.DOCUMENT | filters.VIDEO | filters.AUDIO,
            handle_file
        )
    )

    # Run periodic cleanup every hour
    app.job_queue.run_repeating(clean_expired_links, interval=3600, first=10)

    # Start polling
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
