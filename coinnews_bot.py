import os
import asyncio
import logging
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
import feedparser
from deep_translator import GoogleTranslator
import httpx
from datetime import datetime

# 환경변수 불러오기
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Flask 앱 설정
app = Flask(__name__)

@app.route("/")
def home():
    return "Coin News Bot is running!"

# 뉴스 가져오기
def fetch_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    articles = feed.entries[::-1]  # 오래된 순 정렬
    messages = []

    for entry in articles[:5]:
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        published_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
        messages.append(f"📰 {translated}\n{entry.link}\n⏰ {published_time}\n")

    return "\n".join(messages)

# 시세 가져오기
async def fetch_price():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,solana,dogecoin,ripple",
        "vs_currencies": "usd"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            data = response.json()

        prices = {
            "BTC": data["bitcoin"]["usd"],
            "ETH": data["ethereum"]["usd"],
            "SOL": data["solana"]["usd"],
            "DOGE": data["dogecoin"]["usd"],
            "XRP": data["ripple"]["usd"]
        }

        now = datetime.now().strftime("%H:%M:%S")
        price_text = f"📊 코인 시세 ({now})\n"
        for coin, price in prices.items():
            price_text += f"{coin}: ${price:,.2f}\n"

        return price_text

    except Exception as e:
        logging.error(f"가격 가져오기 실패: {e}")
        return "❌ 코인 시세를 불러올 수 없습니다."

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 및 시세 알림 봇입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = fetch_news()
    await update.message.reply_text(msg or "뉴스를 불러올 수 없습니다.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# 스케줄링 함수
async def send_auto_news(application):
    try:
        msg = fetch_news()
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"자동 뉴스 전송 실패: {e}")

async def send_auto_price(application):
    try:
        msg = await fetch_price()
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"자동 시세 전송 실패: {e}")

# 메인 함수
async def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # 명령어 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 시작
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news(application)), "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price(application)), "interval", minutes=1)
    scheduler.start()

    logging.info("✅ Telegram 봇 시작됨")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

# 스레드로 Telegram 봇 실행
def start_bot():
    asyncio.run(main())

if __name__ == "__main__":
    from threading import Thread
    Thread(target=start_bot).start()
    app.run(host="0.0.0.0", port=10000)
