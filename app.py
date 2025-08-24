import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import boto3
from botocore.config import Config

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

# S3 client for R2
s3 = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version="s3v4")
)

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return

    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    file_path = f"uploads/{file_name}"

    # Download file locally
    await file.download_to_drive(file_name)

    # Upload to R2
    s3.upload_file(file_name, R2_BUCKET_NAME, file_path)

    # Generate 24h signed URL
    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': R2_BUCKET_NAME, 'Key': file_path},
        ExpiresIn=86400
    )

    # Reply with link
    await update.message.reply_text(
        f"✅ File uploaded successfully!\n\n"
        f"🔗 Download/Stream Link (valid 24h):\n{url}\n\n"
        f"👉 You can play it in VLC/MX Player by pasting the link."
    )

    # Cleanup local file
    os.remove(file_name)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
