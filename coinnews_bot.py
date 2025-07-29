import os
import logging
import httpx
import feedparser
from datetime import datetime
from deep_translator import GoogleTranslator
from flask import Flask
from threading import Thread
from pytz import timezone
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from apscheduler.schedulers.background import BackgroundScheduler

# 환경설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
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

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇 작동 중\n/news : 뉴스\n/price : 시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        articles = feed.entries[:5][::-1]
        result = []
        for entry in articles:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            result.append(f"🗞 {translated}\n🕒 {published}\n🔗 {entry.link}")
        await update.message.reply_text("\n\n".join(result))
    except Exception:
        await update.message.reply_text("❌ 뉴스 로딩 실패")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await fetch_price_message()
    await update.message.reply_text(message)

# 시세 메시지 생성
async def fetch_price_message():
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coincap.io/v2/assets", timeout=10)
        data = res.json().get("data", [])
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        msg = [f"📊 코인 시세 ({now})"]
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
                msg.append(f"{name}: ${price}{change}")
        return "\n".join(msg)
    except:
        return "❌ 시세 정보를 가져올 수 없습니다."

# 자동 뉴스 전송
async def send_auto_news(app):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entry = feed.entries[0]
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        msg = f"🗞 {translated}\n🕒 {published}\n🔗 {entry.link}"
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except:
        pass

# 자동 시세 전송
async def send_auto_price(app):
    try:
        message = await fetch_price_message()
        await app.bot.send_message(chat_id=CHAT_ID, text=message)
    except:
        pass

# 스케줄러
def start_scheduler(app, loop):
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_auto_news(app), loop), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_auto_price(app), loop), 'interval', minutes=1)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# Flask
@app.route("/")
def home():
    return "Bot is running."

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# 메인 실행
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def main():
        app_bot = ApplicationBuilder().token(TOKEN).build()
        app_bot.add_handler(CommandHandler("start", start))
        app_bot.add_handler(CommandHandler("news", news))
        app_bot.add_handler(CommandHandler("price", price))
        start_scheduler(app_bot, loop)
        await app_bot.run_polling()

    Thread(target=run_flask).start()
    loop.run_until_complete(main())
