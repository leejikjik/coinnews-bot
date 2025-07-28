import os
import threading
import logging
import asyncio
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
import httpx
from dotenv import load_dotenv

load_dotenv()

# 환경변수
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 텔레그램 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스봇 작동 중입니다!")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.binance.com/api/v3/ticker/price")
            data = response.json()
            coins = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'DOGEUSDT']
            result = []
            for coin in coins:
                price = next((item['price'] for item in data if item['symbol'] == coin), None)
                if price:
                    result.append(f"{coin.replace('USDT', '')}: ${float(price):,.2f}")
            message = "📈 현재 코인 시세:\n" + "\n".join(result)
            await update.message.reply_text(message)
    except Exception as e:
        logging.error(f"가격 조회 실패: {e}")
        await update.message.reply_text("❌ 시세 조회 실패")

# 텔레그램 봇 초기화
application = ApplicationBuilder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("price", price))

# Flask 서버
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is alive!"

# 가격 자동 전송 함수
def send_auto_price():
    asyncio.run(_send_price_message())

async def _send_price_message():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.binance.com/api/v3/ticker/price")
            data = response.json()
            coins = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'DOGEUSDT']
            result = []
            for coin in coins:
                price = next((item['price'] for item in data if item['symbol'] == coin), None)
                if price:
                    result.append(f"{coin.replace('USDT', '')}: ${float(price):,.2f}")
            message = "📢 자동 시세 알림\n" + "\n".join(result)
            await application.bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# APScheduler 실행
def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(send_auto_price, 'interval', minutes=1)
    scheduler.start()
    logging.info("🔁 Scheduler started")

# Flask를 서브 스레드로 실행
def run_flask():
    flask_app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=run_flask).start()
    start_scheduler()
    application.run_polling()  # 반드시 메인스레드에서 실행
