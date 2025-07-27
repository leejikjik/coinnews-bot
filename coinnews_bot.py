import os
import logging
import asyncio
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
from deep_translator import GoogleTranslator
import requests
from datetime import datetime, timedelta

# 기본 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Flask 서버
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Coin News Bot is running!"

# 텔레그램 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇입니다.\n명령어: /news, /price")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    articles = fetch_news()
    if not articles:
        await update.message.reply_text("❌ 뉴스 불러오기 실패")
        return

    for article in articles:
        message = f"📰 <b>{article['title']}</b>\n{article['summary']}\n{article['link']}"
        await update.message.reply_text(message, parse_mode="HTML")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = fetch_price_change()
    await update.message.reply_text(message, parse_mode="HTML")

# Cointelegraph 뉴스 가져오기
def fetch_news():
    try:
        rss_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(rss_url)
        articles = []
        for entry in feed.entries[:3]:  # 최근 뉴스 3개
            title = entry.title
            summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            link = entry.link
            articles.append({"title": title, "summary": summary, "link": link})
        return articles
    except Exception as e:
        logging.error(f"뉴스 가져오기 실패: {e}")
        return []

# 실시간 가격 추적
price_cache = {}

def fetch_price_change():
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    symbol_map = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "ripple": "XRP",
        "solana": "SOL",
        "dogecoin": "DOGE"
    }

    try:
        ids = ",".join(coins)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        response = requests.get(url, timeout=10)
        data = response.json()

        now = datetime.now() + timedelta(hours=9)  # KST
        timestamp = now.strftime("%H:%M:%S")

        result = f"💰 <b>{timestamp} 기준 코인 시세 (USD)</b>\n"

        for coin in coins:
            symbol = symbol_map[coin]
            current_price = data[coin]["usd"]
            previous_price = price_cache.get(coin)

            if previous_price is None:
                change = "🔄 최초 조회"
            else:
                diff = current_price - previous_price
                pct = (diff / previous_price) * 100
                arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                change = f"{arrow} {diff:.2f} ({pct:.2f}%)"

            result += f"{symbol}: ${current_price:.2f} | {change}\n"
            price_cache[coin] = current_price

        return result
    except Exception as e:
        logging.error(f"가격 정보 오류: {e}")
        return "❌ 코인 시세 가져오기 실패"

# 가격 자동 전송
async def send_price(app):
    try:
        message = fetch_price_change()
        await app.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML")
    except Exception as e:
        logging.error(f"자동 시세 전송 오류: {e}")

def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_price(app)), "interval", minutes=1)
    scheduler.start()
    logging.info("✅ Scheduler Started")

# 봇 실행 함수
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    start_scheduler(application)
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

def run_flask():
    flask_app.run(host="0.0.0.0", port=10000)

def start():
    # Flask는 스레드로 실행
    Thread(target=run_flask).start()
    # Telegram Bot은 asyncio로 실행
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_bot())

if __name__ == "__main__":
    start()
