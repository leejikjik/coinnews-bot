# coinnews_bot.py

import os
import asyncio
import logging
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
import feedparser
import httpx
from datetime import datetime

# 환경 변수 로딩
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Flask 앱 생성
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ 코인 뉴스봇 작동 중!"

# 텔레그램 명령어 핸들러
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 코인 뉴스 & 시세 봇 작동 중입니다.")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = await fetch_news()
    for msg in messages:
        await update.message.reply_text(msg)

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# Cointelegraph 뉴스 파싱 및 번역
async def fetch_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    entries = feed.entries[:5][::-1]  # 오래된 순
    result = []
    for entry in entries:
        title = GoogleTranslator(source="en", target="ko").translate(entry.title)
        link = entry.link
        pub_date = entry.published
        result.append(f"📰 {title}\n📆 {pub_date}\n🔗 {link}")
    return result

# 코인 시세 조회
previous_prices = {}

async def fetch_price():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
        "vs_currencies": "usd",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10)
            data = resp.json()
    except Exception as e:
        return f"[시세 오류] {e}"

    now = datetime.now().strftime("%H:%M:%S")
    lines = [f"💹 코인 시세 (USD 기준)\n🕒 {now}"]
    for coin in data:
        price = data[coin]["usd"]
        prev = previous_prices.get(coin, price)
        change = price - prev
        emoji = "📈" if change > 0 else ("📉" if change < 0 else "⏸️")
        lines.append(f"{emoji} {coin.upper()}: ${price:.2f} ({change:+.2f})")
        previous_prices[coin] = price
    return "\n".join(lines)

# 자동 뉴스 전송
async def send_auto_news(app):
    try:
        messages = await fetch_news()
        for msg in messages:
            await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"[뉴스전송오류] {e}")

# 자동 시세 전송
async def send_auto_price(app):
    try:
        msg = await fetch_price()
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"[시세전송오류] {e}")

# 메인 비동기 실행 함수
async def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("price", price_command))

    # 스케줄러: asyncio 기반
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_auto_news, IntervalTrigger(minutes=15), args=[application])
    scheduler.add_job(send_auto_price, IntervalTrigger(minutes=1), args=[application])
    scheduler.start()

    logging.info("✅ Telegram 봇 시작됨")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

# 병렬 실행
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
