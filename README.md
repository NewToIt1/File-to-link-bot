# Telegram R2 Temp Link Bot

This bot allows you to upload Telegram files to **Cloudflare R2** and get a temporary **24-hour download/streaming link**.

## 🚀 Features
- Uploads any Telegram file to R2 bucket
- Generates signed URL valid for 24h
- Links work in VLC, MX Player, browsers
- Files auto-expire after 24h (R2 lifecycle rule)

## 🛠️ Setup
1. Clone repo & install dependencies
   ```bash
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```bash
   export BOT_TOKEN="your-telegram-bot-token"
   export R2_ACCESS_KEY="your-access-key"
   export R2_SECRET_KEY="your-secret-key"
   export R2_BUCKET_NAME="your-bucket"
   export R2_ENDPOINT="https://<account_id>.r2.cloudflarestorage.com"
   ```

3. Run locally:
   ```bash
   python app.py
   ```

4. Deploy on Heroku/Railway (uses `Procfile`).

## ⚡ Notes
- Files & links expire automatically after 24h.
- You must configure **R2 bucket lifecycle rule** to delete files after 24h.
