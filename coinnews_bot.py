import asyncio
import logging
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
import os

# 환경 변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Flask 앱 설정
app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

# 텔레그램 봇 명령어 처리
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start command received.")  # 명령어 수신 확인
    await update.message.reply_text("Hello, I'm your Coin news bot!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("News command received.")  # 명령어 수신 확인
    await update.message.reply_text("Fetching news...")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Price command received.")  # 명령어 수신 확인
    await update.message.reply_text("Fetching prices...")

# 텔레그램 봇 초기화 및 실행
async def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 봇 시작
    await application.initialize()
    await application.start_polling()

# Flask 서버 및 텔레그램 봇 동시에 실행
if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    # 텔레그램 봇을 비동기적으로 실행
    loop.create_task(run_bot())

    # Flask 서버 실행
    app.run(host="0.0.0.0", port=10000, use_reloader=False)
