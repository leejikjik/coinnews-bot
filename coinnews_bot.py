import os
import logging
import asyncio
import feedparser
import requests
from datetime import datetime
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

# 환경변수
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Bot is running!"

# Telegram 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 알림 봇 작동 중입니다!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = fetch_translated_news()
    for msg in messages:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = fetch_price()
    if msg:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

# 뉴스 수집 및 번역
def fetch_translated_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    news_items = feed.entries[:5][::-1]  # 최신순이 아니라 오래된 순
    translated = []
    for item in news_items:
        title = item.title
        link = item.link
        translated_title = GoogleTranslator(source="auto", target="ko").translate(title)
        translated.append(f"📰 {translated_title}\n🔗 {link}")
    return translated

# 가격 정보
def fetch_price():
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        coin_symbols = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        response = requests.get(url)
        data = response.json()

        now = datetime.now().strftime("%H:%M:%S")
        message = f"💹 [코인 시세 - {now} 기준]\n"
        for coin in coins:
            price = data.get(coin, {}).get("usd")
            if price is not None:
                message += f"{coin_symbols[coin]}: ${price:,.2f}\n"
        return message
    except Exception as e:
        logger.error(f"가격 정보 가져오기 실패: {e}")
        return None

# 스케줄러 함수
def start_scheduler(application):
    scheduler = BackgroundScheduler()

    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_news(application), application.bot.loop), 'interval', minutes=10)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_price(application), application.bot.loop), 'interval', minutes=1)

    scheduler.start()
    logger.info("✅ Scheduler Started")

# 자동 전송 함수
async def send_news(application):
    messages = fetch_translated_news()
    for msg in messages:
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)

async def send_price(application):
    msg = fetch_price()
    if msg:
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)

# 앱 시작
if __name__ == "__main__":
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 시작
    start_scheduler(application)

    # Telegram 봇 비동기 실행
    loop = asyncio.get_event_loop()
    loop.create_task(application.start())

    # Flask 서버 실행 (Render용 keepalive)
    flask_app.run(host="0.0.0.0", port=10000)
