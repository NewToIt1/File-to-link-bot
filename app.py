import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import boto3
from datetime import datetime, timedelta

# Environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# S3 client
s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
)

# Handle incoming files
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = None
    if update.message.document:
        file = update.message.document
    elif update.message.video:
        file = update.message.video
    elif update.message.audio:
        file = update.message.audio

    if not file:
        return

    file_id = file.file_id
    file_name = file.file_name or f"{file_id}"
    new_file = await context.bot.get_file(file_id)

    # Save locally
    await new_file.download_to_drive(file_name)

    # Upload to S3
    s3.upload_file(file_name, BUCKET_NAME, file_name)

    # Generate expiring link (48 hours)
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": file_name},
        ExpiresIn=48 * 3600,  # 48 hours
    )

    # Send back proxy-style Telegram link (privacy safe)
    await update.message.reply_text(f"Here’s your temporary download link:\n{url}")

    # Clean up local
    os.remove(file_name)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Correct filter usage ✅
    app.add_handler(
        MessageHandler(
            filters.Document | filters.Video | filters.Audio,
            handle_file
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
