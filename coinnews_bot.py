# coinnews_bot.py

import os
import logging
import asyncio
import feedparser
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Load environment
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask 서버
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Coin News Bot is running!"

# 텔레그램 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 코인 뉴스 및 실시간 시세 봇이 작동 중입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news(context.application)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price(context.application)

# 뉴스 전송 함수
async def send_news(application: Application):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    messages = []
    for entry in feed.entries[:3]:  # 최근 3개
        translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
        published = entry.published
        msg = f"📰 <b>{translated_title}</b>\n🕒 {published}\n{translated_summary}\n🔗 {entry.link}"
        messages.append(msg)

    for msg in reversed(messages):  # 오래된 뉴스부터 순서대로
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

# 시세 전송 함수
prev_prices = {}

async def send_price(application: Application):
    coins = ['bitcoin', 'ethereum', 'ripple', 'solana', 'dogecoin']
    names = {'bitcoin': 'BTC', 'ethereum': 'ETH', 'ripple': 'XRP', 'solana': 'SOL', 'dogecoin': 'DOGE'}
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"

    try:
        response = requests.get(url)
        result = response.json()
        if not result:
            logger.warning("가격 데이터가 비어 있음")
            return

        msg = "💹 <b>실시간 코인 시세 (1분 전 대비)</b>\n"
        now = datetime.now().strftime("%H:%M:%S")

        for coin in coins:
            price = result[coin]['usd']
            prev = prev_prices.get(coin)
            change = ""
            if prev:
                diff = price - prev
                change = f"{'📈 +' if diff > 0 else '📉 '}{round(diff, 2)} USD"
            prev_prices[coin] = price
            msg += f"\n{names[coin]}: ${price} {change}"

        msg += f"\n⏱️ {now}"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"가격 요청 오류: {e}")

# 스케줄러
def start_scheduler(application: Application):
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(send_price(application), application.loop),
        'interval', minutes=1
    )
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(send_news(application), application.loop),
        'interval', minutes=10
    )

    scheduler.start()
    logger.info("✅ Scheduler Started")

# main 진입
if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 텔레그램 봇 비동기 실행
    async def main():
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        start_scheduler(application)

    loop = asyncio.get_event_loop()
    loop.create_task(main())

    # Flask는 keepalive용
    flask_app.run(host="0.0.0.0", port=10000)
