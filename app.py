import os
import time
import uuid
import threading
import requests
from flask import Flask, Response, abort
from telegram.ext import Updater, MessageHandler, Filters

# =======================
# CONFIG
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_TELEGRAM_BOT_TOKEN"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_BASE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
LINK_EXPIRY = 48 * 3600  # 48 hours in seconds

# Temporary storage for links {id: {file_path, expiry}}
temp_links = {}

app = Flask(__name__)

# =======================
# Flask Routes
# =======================

@app.route("/download/<link_id>")
def download(link_id):
    if link_id not in temp_links:
        return abort(404, "Link expired or invalid")

    entry = temp_links[link_id]
    if time.time() > entry["expiry"]:
        del temp_links[link_id]
        return abort(410, "Link expired")

    file_url = f"{FILE_BASE_URL}/{entry['file_path']}"

    def generate():
        with requests.get(file_url, stream=True) as r:
            for chunk in r.iter_content(chunk_size=8192):
                yield chunk

    return Response(generate(), content_type="application/octet-stream")


# =======================
# Telegram Handlers
# =======================

def handle_file(update, context):
    file = None
    if update.message.document:
        file = update.message.document
    elif update.message.video:
        file = update.message.video
    elif update.message.audio:
        file = update.message.audio
    elif update.message.voice:
        file = update.message.voice

    if not file:
        update.message.reply_text("Send me a document, video, or audio file.")
        return

    file_id = file.file_id
    file_info = requests.get(f"{BASE_URL}/getFile?file_id={file_id}").json()

    if "result" not in file_info:
        update.message.reply_text("Error retrieving file info.")
        return

    file_path = file_info["result"]["file_path"]

    # Generate unique temp link
    link_id = str(uuid.uuid4())
    temp_links[link_id] = {
        "file_path": file_path,
        "expiry": time.time() + LINK_EXPIRY
    }

    # Full streaming URL
    stream_link = f"https://YOUR_SERVER_URL/download/{link_id}"

    update.message.reply_text(
        f"✅ Here is your 48-hour link:\n{stream_link}\n\n"
        "You can open this in VLC, MX Player, or browser. "
        "Link will expire automatically after 48 hours."
    )

# =======================
# Cleanup Thread
# =======================
def cleanup_links():
    while True:
        now = time.time()
        expired = [lid for lid, entry in temp_links.items() if now > entry["expiry"]]
        for lid in expired:
            del temp_links[lid]
        time.sleep(600)  # cleanup every 10 mins

threading.Thread(target=cleanup_links, daemon=True).start()

# =======================
# Main Bot Runner
# =======================
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(Filters.document | Filters.video | Filters.audio | Filters.voice, handle_file))

    updater.start_polling()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

if __name__ == "__main__":
    main()
