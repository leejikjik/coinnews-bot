import os
import logging
import asyncio
import feedparser
import requests
from flask import Flask
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
)
from apscheduler.schedulers.background import BackgroundScheduler

# 환경변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask 설정
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Telegram Coin Bot Running"

# 뉴스 중복 방지용 캐시
latest_news_links = set()

# 뉴스 전송
async def send_news(context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[-5:]):
        if entry.link not in latest_news_links:
            latest_news_links.add(entry.link)
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            messages.append(f"📰 {translated}\n{entry.link}")
    for msg in messages:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)

# 시세 전송
async def send_price(context: ContextTypes.DEFAULT_TYPE):
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price", params={
            "ids": ",".join(coins),
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        })
        data = response.json()
    except Exception as e:
        await context.bot.send_message(chat_id=CHAT_ID, text=f"❌ 시세 오류: {e}")
        return

    msg = "💰 실시간 코인 시세:\n"
    for coin in coins:
        price = data.get(coin, {}).get("usd")
        change = data.get(coin, {}).get("usd_24h_change")
        if price is not None and change is not None:
            msg += f"{coin.capitalize()}: ${price:.2f} ({change:+.2f}%)\n"
    await context.bot.send_message(chat_id=CHAT_ID, text=msg)

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 및 시세 봇입니다!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news(context)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price(context)

# 봇 실행 함수
async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))

    job: JobQueue = app.job_queue
    job.run_repeating(send_news, interval=600, first=10)
    job.run_repeating(send_price, interval=60, first=15)

    await app.initialize()
    await app.start()
    logger.info("✅ Telegram Bot Started")
    await app.updater.start_polling()
    await app.updater.idle()

# 시작점
if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    finally:
        loop.close()

    # Flask는 별도 스레드에서 keep-alive
    from threading import Thread
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000)).start()
