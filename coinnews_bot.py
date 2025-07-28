import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
import threading

# 환경변수
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)

# Flask 앱
flask_app = Flask(__name__)

# 봇 초기화
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

# 번역기
translator = GoogleTranslator(source='auto', target='ko')

# 뉴스 전송
async def fetch_and_send_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)

    messages = []
    for entry in reversed(feed.entries[:3]):
        title = translator.translate(entry.title)
        link = entry.link
        messages.append(f"📰 <b>{title}</b>\n{link}")

    if messages:
        message_text = "\n\n".join(messages)
        await application.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message_text,
            parse_mode='HTML'
        )

# 시세 전송
coin_list = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
price_cache = {}

async def fetch_and_send_price():
    url = "https://api.binance.com/api/v3/ticker/price"
    message_lines = ["💰 <b>실시간 코인 시세 (1분 변동)</b>\n"]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            data = response.json()

        prices = {}
        for coin in coin_list:
            symbol = f"{coin.upper()}USDT"
            item = next((x for x in data if x["symbol"] == symbol), None)
            if item:
                current_price = float(item["price"])
                old_price = price_cache.get(coin)
                diff = ""
                if old_price:
                    change = current_price - old_price
                    percent = (change / old_price) * 100
                    sign = "🔼" if change > 0 else "🔽" if change < 0 else "➡️"
                    diff = f"{sign} {abs(change):.2f} USDT ({percent:.2f}%)"
                else:
                    diff = "⏳ 최초 측정 중"
                prices[coin] = current_price
                message_lines.append(f"• {coin.upper()}: {current_price:.2f} USDT {diff}")
        price_cache.update(prices)

        await application.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="\n".join(message_lines),
            parse_mode='HTML'
        )

    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 봇이 작동 중입니다.\n/news = 코인 뉴스\n/price = 실시간 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[:3]):
        title = translator.translate(entry.title)
        link = entry.link
        messages.append(f"📰 <b>{title}</b>\n{link}")

    await update.message.reply_text("\n\n".join(messages), parse_mode='HTML')

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_and_send_price()

# 명령어 등록
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("news", news))
application.add_handler(CommandHandler("price", price))

# APScheduler 시작
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_news()), "interval", minutes=15)
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_price()), "interval", minutes=1)
    scheduler.start()

# Flask Keepalive
@flask_app.route("/")
def home():
    return "Coin Bot Running"

# Telegram 쓰레드
def run_telegram():
    application.run_polling()

# 전체 실행
if __name__ == "__main__":
    start_scheduler()
    threading.Thread(target=run_telegram).start()
    flask_app.run(host="0.0.0.0", port=10000)
