import os
import logging
import asyncio
import httpx
import feedparser
from datetime import datetime
from deep_translator import GoogleTranslator
from flask import Flask
from threading import Thread
from pytz import timezone

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from apscheduler.schedulers.background import BackgroundScheduler

# 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

KST = timezone("Asia/Seoul")
app = Flask(__name__)
scheduler = BackgroundScheduler()

coins = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

previous_prices = {}

# 🟢 /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("🟢 봇 작동 중\n/news : 최신 뉴스\n/price : 실시간 시세")

# 📰 /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        articles = feed.entries[:5][::-1]
        messages = []
        for entry in articles:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            messages.append(f"🗞 {translated}\n🕒 {published}\n🔗 {entry.link}")
        await update.message.reply_text("\n\n".join(messages))
    except Exception as e:
        await update.message.reply_text("❌ 뉴스 로딩 실패")

# 📈 /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await fetch_price_message()
    await update.message.reply_text(message)

# 시세 조회 메시지 생성
async def fetch_price_message():
    url = "https://api.coincap.io/v2/assets"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
        data = response.json().get("data", [])
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        result = [f"📊 코인 시세 ({now})"]
        for coin_id, name in coins.items():
            coin = next((c for c in data if c["id"] == coin_id), None)
            if coin:
                price = round(float(coin["priceUsd"]), 2)
                change = ""
                if coin_id in previous_prices:
                    diff = round(price - previous_prices[coin_id], 2)
                    emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "⏺"
                    change = f" ({emoji}{abs(diff)})"
                previous_prices[coin_id] = price
                result.append(f"{name}: ${price}{change}")
        return "\n".join(result)
    except Exception:
        return "❌ 시세 정보를 불러오지 못했습니다."

# 자동 뉴스 전송
async def send_auto_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        article = feed.entries[0]
        translated = GoogleTranslator(source='auto', target='ko').translate(article.title)
        published = datetime(*article.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        message = f"🗞 {translated}\n🕒 {published}\n🔗 {article.link}"
        await app_bot.bot.send_message(chat_id=CHAT_ID, text=message)
    except:
        pass

# 자동 시세 전송
async def send_auto_price():
    try:
        message = await fetch_price_message()
        await app_bot.bot.send_message(chat_id=CHAT_ID, text=message)
    except:
        pass

# APScheduler 시작
def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), 'interval', minutes=1)
    scheduler.start()
    logging.info("✅ 스케줄러 실행됨")

# Flask 서버
@app.route("/")
def home():
    return "Bot is running."

# Flask + Scheduler 쓰레드로 실행
def run_flask():
    start_scheduler()
    app.run(host="0.0.0.0", port=PORT)

# Bot 실행
async def main():
    global app_bot
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    await app_bot.run_polling()

if __name__ == "__main__":
    Thread(target=run_flask).start()
    asyncio.run(main())
