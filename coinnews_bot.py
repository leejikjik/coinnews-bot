import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pytz
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 한국 시간대
KST = pytz.timezone("Asia/Seoul")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Coin News Bot is running!"

# 가격 가져오기
previous_prices = {}

async def get_prices():
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    prices = {}
    async with httpx.AsyncClient() as client:
        for coin in coins:
            try:
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
                r = await client.get(url, timeout=10)
                r.raise_for_status()
                result = r.json()
                price = result[coin]["usd"]
                prev = previous_prices.get(coin)
                change = f"(변화 없음)" if prev is None else f"(변동: {price - prev:+.2f}$)"
                previous_prices[coin] = price
                prices[coin] = f"{coin.capitalize()}: ${price:.2f} {change}"
            except Exception as e:
                prices[coin] = f"{coin.capitalize()}: 오류 발생"
    return "\n".join(prices.values())

# 뉴스 가져오기
def get_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    items = feed.entries[:3][::-1]  # 오래된 순 → 최신 순
    translated_news = []
    for item in items:
        try:
            translated_title = GoogleTranslator(source='auto', target='ko').translate(item.title)
            translated_news.append(f"📰 {translated_title}\n🔗 {item.link}")
        except:
            translated_news.append(f"📰 {item.title}\n🔗 {item.link}")
    return "\n\n".join(translated_news)

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 봇에 오신 것을 환영합니다!\n\n/start: 봇 안내\n/news: 최신 뉴스\n/price: 실시간 가격")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await get_prices()
    await update.message.reply_text(f"💸 현재 코인 시세:\n\n{result}")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = get_news()
    await update.message.reply_text(f"🗞️ 최신 코인 뉴스:\n\n{result}")

# 스케줄 작업
async def send_scheduled(application):
    prices = await get_prices()
    news = get_news()
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    message = f"⏰ {now} 기준\n\n{prices}\n\n{news}"
    await application.bot.send_message(chat_id=CHAT_ID, text=message)

def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_scheduled(application)), 'interval', minutes=1)
    scheduler.start()

# main
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))

    start_scheduler(application)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    flask_app.run(host="0.0.0.0", port=10000)
