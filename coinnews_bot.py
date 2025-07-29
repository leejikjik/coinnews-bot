import os
import logging
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ CoinNews Bot is running"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in reversed(feed.entries[:5]):
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n{entry.link}")
        await update.message.reply_text("\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"[뉴스 오류] {e}")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get("https://api.binance.com/api/v3/ticker/price")
            data = res.json()
            symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
            result = ""
            for symbol in symbols:
                coin = next((item for item in data if item["symbol"] == symbol), None)
                if coin:
                    name = symbol.replace("USDT", "")
                    price = float(coin["price"])
                    result += f"• {name}: ${price:,.2f}\n"
            await update.message.reply_text(f"💰 현재 시세:\n{result}")
    except Exception as e:
        await update.message.reply_text(f"[시세 오류] {e}")

# 자동 뉴스 전송
async def send_auto_news(app):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in reversed(feed.entries[:3]):
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n{entry.link}")
        if messages:
            await app.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        logger.error(f"[자동 뉴스 오류] {e}")

# 자동 시세 전송
async def send_auto_price(app):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get("https://api.binance.com/api/v3/ticker/price")
            data = res.json()
            symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
            result = ""
            for symbol in symbols:
                coin = next((item for item in data if item["symbol"] == symbol), None)
                if coin:
                    name = symbol.replace("USDT", "")
                    price = float(coin["price"])
                    result += f"• {name}: ${price:,.2f}\n"
            if result:
                await app.bot.send_message(chat_id=CHAT_ID, text=f"💰 실시간 시세:\n{result}")
    except Exception as e:
        logger.error(f"[자동 시세 오류] {e}")

# APScheduler
def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: app.create_task(send_auto_news(app)), "interval", minutes=30)
    scheduler.add_job(lambda: app.create_task(send_auto_price(app)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# Flask 실행 (백그라운드)
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# 메인 실행
if __name__ == "__main__":
    telegram_app = ApplicationBuilder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("news", news))
    telegram_app.add_handler(CommandHandler("price", price))

    # Flask 백그라운드로 실행
    Thread(target=run_flask).start()

    # 스케줄러 실행
    start_scheduler(telegram_app)

    # Telegram run_polling 메인 스레드에서 실행
    telegram_app.run_polling()
