import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import feedparser
from deep_translator import GoogleTranslator
import httpx
from threading import Thread

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 한국 시간
KST = pytz.timezone("Asia/Seoul")

# 로깅
logging.basicConfig(level=logging.INFO)

# Flask 서버
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "Coin Bot is running"

# 가격 저장소
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
            except:
                prices[coin] = f"{coin.capitalize()}: 오류 발생"
    return "\n".join(prices.values())

def get_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    items = feed.entries[:3][::-1]
    result = []
    for item in items:
        try:
            title = GoogleTranslator(source='auto', target='ko').translate(item.title)
        except:
            title = item.title
        result.append(f"📰 {title}\n🔗 {item.link}")
    return "\n\n".join(result)

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 코인봇입니다\n/start: 안내\n/news: 뉴스\n/price: 시세")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = await get_prices()
    await update.message.reply_text(f"💸 현재 코인 시세:\n\n{data}")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_news()
    await update.message.reply_text(f"🗞️ 최신 뉴스:\n\n{data}")

# 스케줄러 작업
def run_scheduler(application: Application):
    async def task():
        prices = await get_prices()
        news = get_news()
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        message = f"⏰ {now} 기준\n\n{prices}\n\n{news}"
        await application.bot.send_message(chat_id=CHAT_ID, text=message)

    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(task()), "interval", minutes=1)
    scheduler.start()

# Telegram 봇 쓰레드
def run_bot():
    async def main():
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("price", price))
        application.add_handler(CommandHandler("news", news))
        run_scheduler(application)
        await application.run_polling()

    asyncio.run(main())

if __name__ == "__main__":
    Thread(target=run_bot).start()
    flask_app.run(host="0.0.0.0", port=10000)
