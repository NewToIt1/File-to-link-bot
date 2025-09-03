import os
import time
import secrets
from flask import Flask, request, redirect
from telegram.ext import Application, MessageHandler, filters, CommandHandler
from telegram import Update
from telegram.ext import ContextTypes

# =========================
# Configuration
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # keep token hidden (set in Render/GitHub secrets)
BASE_URL = os.getenv("BASE_URL", "https://your-app.onrender.com")

# Store signed links temporarily (in memory)
temp_links = {}

# Flask app for file serving
app = Flask(__name__)

# =========================
# Telegram Bot Handlers
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a file and I’ll give you a 48-hour streaming link!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("Please send a valid file.")
        return

    file_id = update.message.document.file_id

    try:
        # Get file info from Telegram (this never downloads the file)
        tg_file = await context.bot.get_file(file_id)
        file_path = tg_file.file_path

        # Generate signed link valid for 48 hours
        expiry_time = int(time.time()) + 48 * 3600
        token = secrets.token_urlsafe(16)
        signed_link = f"{BASE_URL}/file/{file_id}?token={token}&expiry={expiry_time}"

        # Store mapping
        temp_links[token] = {
            "file_path": file_path,
            "expiry": expiry_time
        }

        await update.message.reply_text(
            f"✅ Your 48-hour streaming link:\n{signed_link}"
        )

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")

# =========================
# Flask Routes
# =========================

@app.route("/file/<file_id>")
def serve_file(file_id):
    token = request.args.get("token")
    expiry = request.args.get("expiry")

    if not token or token not in temp_links:
        return "❌ Invalid or expired link", 403

    entry = temp_links[token]
    if int(time.time()) > entry["expiry"]:
        return "⏰ Link expired", 403

    file_path = entry["file_path"]

    # Telegram file download URL
    tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    # Redirect user to actual file (token stays hidden)
    return redirect(tg_url, code=302)

# =========================
# Main Runner
# =========================
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_message))

    # Run bot in background
    application.run_polling()

if __name__ == "__main__":
    main()
