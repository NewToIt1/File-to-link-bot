import os
import asyncio
import logging
from datetime import datetime, timedelta
from flask import Flask, request, redirect
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# -------------------------
# Logging setup
# -------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("tg-stream-bot")

# -------------------------
# Config
# -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")  # e.g., https://your-app.onrender.com

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing. Set it in environment variables.")

if not PUBLIC_BASE_URL:
    raise ValueError("PUBLIC_BASE_URL is missing. Set it in environment variables.")

# -------------------------
# Telegram Bot
# -------------------------
telegram_app = Application.builder().token(BOT_TOKEN).build()

# Store temporary links
temp_links = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a file and I’ll give you a streamable link valid for 48 hours.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        await update.message.reply_text("Please send a valid file.")
        return

    file = update.message.document
    file_id = file.file_id

    try:
        tg_file = await context.bot.get_file(file_id)
    except Exception as e:
        logger.error(f"Failed to get file: {e}")
        await update.message.reply_text("❌ Error: File is too big or cannot be accessed.")
        return

    expiry_time = datetime.utcnow() + timedelta(hours=48)
    temp_links[file_id] = {"file_url": tg_file.file_path, "expiry": expiry_time}

    link = f"{PUBLIC_BASE_URL}/stream/{file_id}"
    await update.message.reply_text(f"✅ Your file link (valid 48 hrs):\n{link}")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.Document.ALL, handle_message))

# -------------------------
# Flask Web App for Render
# -------------------------
app = Flask(__name__)

# -------------------------
# Event loop fix
# -------------------------
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    async def process():
        await telegram_app.initialize()
        await telegram_app.process_update(update)
    loop.run_until_complete(process())
    return "ok", 200

@app.route("/stream/<file_id>")
def stream(file_id):
    if file_id not in temp_links:
        return "❌ Link expired or invalid", 404

    file_info = temp_links[file_id]
    if datetime.utcnow() > file_info["expiry"]:
        del temp_links[file_id]
        return "❌ Link expired", 410

    # Redirect browser directly to Telegram file URL for better streaming
    return redirect(file_info["file_url"])

# -------------------------
# Main
# -------------------------
async def set_webhook():
    url = f"{PUBLIC_BASE_URL}/webhook/{BOT_TOKEN}"
    await telegram_app.bot.set_webhook(url=url)
    logger.info(f"Webhook set to {url}")

def run():
    port = int(os.environ.get("PORT", 5000))
    loop.run_until_complete(set_webhook())
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    run()
