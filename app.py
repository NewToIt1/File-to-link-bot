import os
from fastapi import FastAPI
from telegram.ext import Application, MessageHandler, filters, CommandHandler
from telegram import Update
from telegram.ext import ContextTypes
import uvicorn

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://example.com")  # Render public base URL

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing. Set it in Render environment variables.")

# FastAPI app
app = FastAPI()

@app.get("/")
async def home():
    return {"status": "ok", "message": "Bot is running!"}

# Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Send me a file and I’ll generate a temporary link.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        file = update.message.document
    elif update.message.video:
        file = update.message.video
    elif update.message.audio:
        file = update.message.audio
    else:
        return

    file_id = file.file_id
    link = f"{BASE_URL}/download/{file_id}"
    await update.message.reply_text(f"Here’s your temporary link:\n{link}")

# Build Telegram Application
telegram_app = Application.builder().token(BOT_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))

# Run both FastAPI + Telegram bot
def run():
    import asyncio

    async def main():
        # Start Telegram bot in background
        asyncio.create_task(telegram_app.run_polling())
        # Start FastAPI (Uvicorn)
        config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(main())

if __name__ == "__main__":
    run()
