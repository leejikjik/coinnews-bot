import os
import logging
import httpx
import feedparser
from flask import Flask
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
import threading
import asyncio

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 시간대
KST = timezone("Asia/Seoul")

# Flask
app = Flask(__name__)

# 코인 목록
coins = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}
previous_prices = {}

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 코인 뉴스 및 시세 봇 작동 중\n/news : 뉴스\n/price : 시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        messages = []
        for entry in reversed(entries):
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            messages.append(f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}")
        await update.message.reply_text("\n\n".join(messages))
    except Exception as e:
        logger.error(f"/news 오류: {e}")
        await update.message.reply_text("❌ 뉴스 가져오기 실패")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coincap.io/v2/assets")
            data = r.json().get("data", [])
            result = [f"📊 코인 시세 ({now})"]
            for coin_id, name in coins.items():
                coin_data = next((c for c in data if c["id"] == coin_id), None)
                if coin_data:
                    price = float(coin_data["priceUsd"])
                    prev = previous_prices.get(coin_id)
                    diff = price - prev if prev else 0
                    sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                    change = f"{sign} {abs(diff):,.4f}" if prev else "➖ 변화 없음"
                    result.append(f"{name}: {price:,.2f} USD ({change})")
                    previous_prices[coin_id] = price
            await update.message.reply_text("\n".join(result))
    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("❌ 시세 가져오기 실패")

# 자동 뉴스
async def send_auto_news(application):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entry = feed.entries[0]
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        msg = f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"자동 뉴스 오류: {e}")

# 자동 시세
async def send_auto_price(application):
    try:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coincap.io/v2/assets")
            data = r.json().get("data", [])
            result = [f"📊 자동 코인 시세 ({now})"]
            for coin_id, name in coins.items():
                coin_data = next((c for c in data if c["id"] == coin_id), None)
                if coin_data:
                    price = float(coin_data["priceUsd"])
                    prev = previous_prices.get(coin_id)
                    diff = price - prev if prev else 0
                    sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                    change = f"{sign} {abs(diff):,.4f}" if prev else "➖ 변화 없음"
                    result.append(f"{name}: {price:,.2f} USD ({change})")
                    previous_prices[coin_id] = price
            await application.bot.send_message(chat_id=CHAT_ID, text="\n".join(result))
    except Exception as e:
        logger.error(f"자동 시세 오류: {e}")

# Flask 루트
@app.route("/")
def home():
    return "✅ CoinNewsBot 작동 중"

# 스케줄러 시작
def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news(application)), "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price(application)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# Telegram 봇 실행 함수
async def start_bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    start_scheduler(app_bot)
    await app_bot.run_polling()

# 병렬 실행: Telegram Bot + Flask
def run_all():
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())

    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    loop.run_forever()

if __name__ == "__main__":
    run_all()
