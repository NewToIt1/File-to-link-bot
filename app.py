#!/usr/bin/env python3
import os
import time
import secrets
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple, Generator

import requests
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# -----------------------------
# Configuration (env variables)
# -----------------------------
# REQUIRED: set this in Render environment variables (do NOT commit token to repo)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN environment variable in Render (BotFather token)")

# PUBLIC_BASE_URL: e.g. https://your-app.onrender.com  (recommended)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# EXPIRY_HOURS: how long the generated links should remain valid (default 48)
EXPIRY_HOURS = int(os.getenv("EXPIRY_HOURS", "48"))

# SQLite DB path (file stored in app directory on Render)
DB_PATH = os.getenv("DB_PATH", "links.db")

# Chunk size for streaming (256 KB)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", str(256 * 1024)))

# FastAPI port (Render will provide PORT env; fallback 8000)
PORT = int(os.getenv("PORT", os.getenv("UVICORN_PORT", "8000")))

# Telegram API base
TG_API_BASE = "https://api.telegram.org"

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-stream-bot")

# -----------------------------
# Database (SQLite)
# -----------------------------
def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = db_connect()
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
    db.commit()

def create_link(file_id: str, file_path: str, mime: Optional[str], file_name: Optional[str], file_size: Optional[int]) -> str:
    token = secrets.token_urlsafe(16)
    created_at = int(time.time())
    with db:
        db.execute(
            "INSERT INTO links (token, file_id, file_path, mime, file_name, file_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, file_id, file_path, mime, file_name, file_size, created_at),
        )
    logger.info("Created token %s for file_id=%s", token, file_id)
    return token

def fetch_link(token: str):
    cur = db.execute("SELECT * FROM links WHERE token = ?", (token,))
    return cur.fetchone()

def delete_link(token: str):
    with db:
        db.execute("DELETE FROM links WHERE token = ?", (token,))
    logger.info("Deleted token %s", token)

def cleanup_expired_links():
    cutoff = int(time.time()) - EXPIRY_HOURS * 3600
    with db:
        db.execute("DELETE FROM links WHERE created_at < ?", (cutoff,))
    logger.debug("Cleanup run: deleted links older than %s", cutoff)

def cleanup_loop():
    while True:
        try:
            cleanup_expired_links()
        except Exception as e:
            logger.exception("Cleanup error: %s", e)
        time.sleep(1800)  # every 30 minutes

# -----------------------------
# FastAPI app (proxy)
# -----------------------------
app = FastAPI(title="Telegram Streaming Proxy")

def telegram_file_url(file_path: str) -> str:
    # Server-side URL; bot token is used only on server
    return f"{TG_API_BASE}/file/bot{BOT_TOKEN}/{file_path}"

def parse_range_header(range_header: str, total_size: int) -> Tuple[int, int]:
    # "bytes=start-end" -> (start, end)
    if not range_header:
        raise ValueError("No Range header")
    if not range_header.startswith("bytes="):
        raise ValueError("Invalid range unit")
    rng = range_header.split("=", 1)[1]
    if "-" not in rng:
        raise ValueError("Invalid range format")
    start_str, end_str = rng.split("-", 1)
    start = int(start_str) if start_str != "" else 0
    end = int(end_str) if end_str != "" else (total_size - 1)
    if start < 0 or end < start or end >= total_size:
        raise ValueError("Range out of bounds")
    return start, end

@app.get("/f/{token}")
def stream(token: str, request: Request):
    """
    Stream proxied file for given token. Supports Range headers.
    """
    row = fetch_link(token)
    if not row:
        raise HTTPException(status_code=404, detail="Link not found")

    created_at = int(row["created_at"])
    if time.time() - created_at > EXPIRY_HOURS * 3600:
        # expired
        delete_link(token)
        raise HTTPException(status_code=410, detail="Link expired")

    file_path = row["file_path"]
    mime = row["mime"] or "application/octet-stream"
    file_name = row["file_name"] or "file"
    reported_size = row["file_size"]  # may be None

    upstream_url = telegram_file_url(file_path)

    total_size = reported_size
    if total_size is None:
        # try HEAD to obtain size
        try:
            head = requests.head(upstream_url, timeout=15)
            if head.ok:
                cl = head.headers.get("Content-Length")
                if cl:
                    total_size = int(cl)
        except Exception as e:
            logger.debug("HEAD failed: %s", e)
            total_size = None

    range_header = request.headers.get("range") or request.headers.get("Range")
    headers = {"Accept": "*/*"}
    status_code = 200
    resp_headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{file_name}"',
        "Cache-Control": "no-store",
    }

    if range_header and total_size is not None:
        try:
            start, end = parse_range_header(range_header, total_size)
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid Range")
        headers["Range"] = f"bytes={start}-{end}"
        status_code = 206
        resp_headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
        resp_headers["Content-Length"] = str(end - start + 1)
    else:
        if total_size is not None:
            resp_headers["Content-Length"] = str(total_size)

    upstream = requests.get(upstream_url, headers=headers, stream=True, timeout=30)
    if upstream.status_code not in (200, 206):
        logger.warning("Upstream status %s for url %s", upstream.status_code, upstream_url)
        raise HTTPException(status_code=upstream.status_code if 400 <= upstream.status_code < 600 else 502, detail="Upstream error")

    def generate() -> Generator[bytes, None, None]:
        try:
            for chunk in upstream.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(generate(), status_code=status_code, headers=resp_headers)

@app.get("/")
def health():
    return JSONResponse({"ok": True, "expiry_hours": EXPIRY_HOURS})

# -----------------------------
# Telegram bot handlers
# -----------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a file (document/video/audio). I will give a streamable link valid for "
        f"{EXPIRY_HOURS} hours."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only proceed if message contains a file-like object
    if not update.message:
        return

    # prefer explicit file types
    file_obj = update.message.document or update.message.video or update.message.audio
    if not file_obj:
        # ignore other messages silently (or you can reply)
        return

    file_id = file_obj.file_id
    file_name = getattr(file_obj, "file_name", None)
    mime = getattr(file_obj, "mime_type", None)
    size = getattr(file_obj, "file_size", None)

    # fetch file_path from Telegram (server-side)
    try:
        tg_file = await context.bot.get_file(file_id)
        file_path = tg_file.file_path  # e.g. "documents/file_12345.mp4"
    except Exception as e:
        logger.exception("Failed to get_file for file_id=%s: %s", file_id, e)
        await update.message.reply_text("Error: could not retrieve file info from Telegram.")
        return

    token = create_link(file_id, file_path, mime, file_name, size)
    expires_at = (datetime.utcfromtimestamp(int(time.time()) + EXPIRY_HOURS * 3600)).strftime("%Y-%m-%d %H:%M UTC")

    if PUBLIC_BASE_URL:
        link = f"{PUBLIC_BASE_URL}/f/{token}"
    else:
        # relative link (useful for local testing)
        link = f"/f/{token}"

    text = (
        "✅ Stream link created.\n\n"
        f"Link (valid until {expires_at}):\n{link}\n\n"
        "Open it in VLC / MX Player (Open Network Stream) or in your browser."
    )
    await update.message.reply_text(text)

# -----------------------------
# Run bot + server in same loop
# -----------------------------
async def start_bot_and_server():
    # Start cleanup background thread (non-async; cheap)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, cleanup_loop)

    # Build application (PTB v20)
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    # Use a broad message handler and inspect inside it to avoid filter mismatch across PTB versions
    application.add_handler(MessageHandler(~filters.COMMAND, handle_message))

    # Initialize and start application inside THIS asyncio loop (do not use run_polling())
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # Start uvicorn server programmatically in the same loop
    config = uvicorn.Config("app:app", host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    # server.serve() is an async function that runs until stopped; await it so process stays alive
    try:
        await server.serve()
    finally:
        # Shutdown telegram app gracefully if server exits
        try:
            await application.updater.stop_polling()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass

def main():
    # run the combined startup
    asyncio.run(start_bot_and_server())

if __name__ == "__main__":
    main()
