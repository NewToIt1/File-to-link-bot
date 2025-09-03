# app.py
import os
import time
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, Generator

import requests
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# -------------------------
# Configuration (env vars)
# -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # REQUIRED
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")  # optional, e.g. https://your-app.onrender.com
EXPIRY_HOURS = int(os.getenv("EXPIRY_HOURS", "48"))
DB_PATH = os.getenv("DB_PATH", "links.db")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", str(256 * 1024)))  # 256 KB
PORT = int(os.getenv("PORT", os.getenv("UVICORN_PORT", "8000")))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

TG_API_BASE = "https://api.telegram.org"

# -------------------------
# SQLite DB (simple)
# -------------------------
def connect_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = connect_db()
with db:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            token TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            mime TEXT,
            file_name TEXT,
            file_size INTEGER,
            created_at INTEGER NOT NULL
        )
        """
    )

def create_link(file_id: str, file_path: str, mime: Optional[str], file_name: Optional[str], file_size: Optional[int]) -> str:
    token = secrets.token_urlsafe(16)
    created_at = int(time.time())
    with db:
        db.execute(
            "INSERT INTO links (token, file_id, file_path, mime, file_name, file_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, file_id, file_path, mime, file_name, file_size, created_at),
        )
    return token

def fetch_link(token: str):
    cur = db.execute("SELECT * FROM links WHERE token = ?", (token,))
    return cur.fetchone()

def delete_link(token: str):
    with db:
        db.execute("DELETE FROM links WHERE token = ?", (token,))

def cleanup_expired_loop():
    while True:
        try:
            cutoff = int(time.time()) - EXPIRY_HOURS * 3600
            with db:
                db.execute("DELETE FROM links WHERE created_at < ?", (cutoff,))
        except Exception:
            pass
        time.sleep(1800)  # every 30 minutes

# -------------------------
# FastAPI app (proxy endpoint)
# -------------------------
app = FastAPI(title="Telegram Streaming Proxy")

def telegram_file_url(file_path: str) -> str:
    # server-side URL, BOT_TOKEN kept secret
    return f"{TG_API_BASE}/file/bot{BOT_TOKEN}/{file_path}"

def parse_range_header(range_header: str, total: int) -> Tuple[int, int]:
    """
    Parse Range header "bytes=start-end" -> (start, end) inclusive.
    Raises ValueError on invalid ranges.
    """
    if not range_header:
        raise ValueError("Empty Range")
    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range unit")
    rng = range_header.split("=", 1)[1]
    if "-" not in rng:
        raise ValueError("Invalid Range format")
    start_str, end_str = rng.split("-", 1)
    if start_str == "":
        start = 0
    else:
        start = int(start_str)
    if end_str == "":
        end = total - 1
    else:
        end = int(end_str)
    if start < 0 or end < start or (total is not None and end >= total):
        raise ValueError("Range out of bounds")
    return start, end

@app.get("/s/{token}")
def stream(token: str, request: Request):
    """
    Streams proxied file for the given token.
    Supports Range requests for seeking.
    """
    row = fetch_link(token)
    if not row:
        raise HTTPException(404, detail="Link not found")

    created_at = int(row["created_at"])
    if time.time() - created_at > EXPIRY_HOURS * 3600:
        delete_link(token)
        raise HTTPException(410, detail="Link expired")

    file_path = row["file_path"]
    mime = row["mime"] or "application/octet-stream"
    file_name = row["file_name"] or "file"
    reported_size = row["file_size"]  # might be None

    upstream_url = telegram_file_url(file_path)

    total_size = reported_size
    if total_size is None:
        # try HEAD to get size
        try:
            head = requests.head(upstream_url, timeout=15)
            if head.ok:
                cl = head.headers.get("Content-Length")
                if cl:
                    total_size = int(cl)
        except Exception:
            total_size = None

    range_header = request.headers.get("range") or request.headers.get("Range")
    headers = {"Accept": "*/*"}
    status_code = 200
    response_headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{file_name}"',
        "Cache-Control": "no-store",
    }

    if range_header and total_size is not None:
        try:
            start, end = parse_range_header(range_header, total_size)
        except ValueError:
            raise HTTPException(416, detail="Invalid Range")
        headers["Range"] = f"bytes={start}-{end}"
        status_code = 206
        response_headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
        response_headers["Content-Length"] = str(end - start + 1)
    else:
        if total_size is not None:
            response_headers["Content-Length"] = str(total_size)

    upstream = requests.get(upstream_url, headers=headers, stream=True, timeout=30)
    if upstream.status_code not in (200, 206):
        # propagate reasonable upstream errors
        raise HTTPException(status_code=upstream.status_code if 400 <= upstream.status_code < 600 else 502, detail="Upstream error")

    def stream_generator():
        try:
            for chunk in upstream.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(stream_generator(), status_code=status_code, headers=response_headers)

@app.get("/")
def health():
    return JSONResponse({"ok": True, "expiry_hours": EXPIRY_HOURS})

# -------------------------
# Telegram bot (PTB v20.x)
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a file (document/video/audio) and I will reply with a streaming link valid for "
        f"{EXPIRY_HOURS} hours. Links work in VLC/MX Player and do not expose tokens."
    )

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # prioritize attachments
    file_obj = update.message.document or update.message.video or update.message.audio
    if not file_obj:
        # ignore non-file messages
        return

    file_id = file_obj.file_id
    file_name = getattr(file_obj, "file_name", None)
    mime = getattr(file_obj, "mime_type", None)
    size = getattr(file_obj, "file_size", None)

    # get file_path server-side (safe)
    tg_file = await context.bot.get_file(file_id)
    file_path = tg_file.file_path  # e.g. "documents/file_12345.mp4"

    token = create_link(file_id, file_path, mime, file_name, size)
    expires_at = (datetime.utcnow() + timedelta(hours=EXPIRY_HOURS)).strftime("%Y-%m-%d %H:%M UTC")

    if PUBLIC_BASE_URL:
        link = f"{PUBLIC_BASE_URL}/s/{token}"
    else:
        link = f"/s/{token}"

    text = (
        "✅ Streaming link created.\n\n"
        f"Link (valid until {expires_at}):\n{link}\n\n"
        "Open in VLC/MX Player (Open Network Stream) or in a browser."
    )
    await update.message.reply_text(text)

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    # capture all non-command messages and inspect attachments inside handler
    application.add_handler(MessageHandler(~filters.COMMAND, handle_all_messages))
    # blocking
    application.run_polling()

# -------------------------
# Runner
# -------------------------
def main():
    # start cleanup background thread
    t = threading.Thread(target=cleanup_expired_loop, daemon=True)
    t.start()

    # start bot in background thread
    bt = threading.Thread(target=run_bot, daemon=True)
    bt.start()

    # run FastAPI (uvicorn) in main thread so host/port are exposed to Render
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, log_level="info")

if __name__ == "__main__":
    main()
