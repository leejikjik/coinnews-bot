import os
import logging
import feedparser
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import httpx

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

logging.basicConfig(level=logging.INFO)

# Flask keep-alive
app = Flask(__name__)
@app.route("/")
def index():
    return "Bot is alive."

# Telegram 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 및 시세 알리미 봇입니다.\n/news : 최신 뉴스\n/price : 실시간 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await get_translated_news())

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await get_price_message())

# 뉴스 번역 함수
async def get_translated_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    sorted_entries = sorted(feed.entries, key=lambda x: x.published_parsed)
    translator = GoogleTranslator(source='auto', target='ko')
    messages = []

    for entry in sorted_entries[:5]:
        title = translator.translate(entry.title)
        link = entry.link
        pub_time = datetime(*entry.published_parsed[:6]) + timedelta(hours=9)
        messages.append(f"📰 {title}\n🕒 {pub_time.strftime('%Y-%m-%d %H:%M')}\n🔗 {link}")

    return "\n\n".join(messages)

# 시세 추적 함수
price_cache = {}

async def get_price_message():
    url = "https://api.coingecko.com/api/v3/simple/price"
    coins = ["bitcoin", "ethereum", "solana", "dogecoin", "ripple"]
    params = {
        "ids": ",".join(coins),
        "vs_currencies": "usd"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params)
            result = resp.json()
        except Exception as e:
            return "❌ 시세 정보를 가져오지 못했습니다."

    now = datetime.now(timezone(timedelta(hours=9))).strftime("%H:%M:%S")
    messages = [f"📊 코인 시세 ({now}) 기준:"]

    for coin in coins:
        name = coin.capitalize()
        current = result.get(coin, {}).get("usd", 0)
        prev = price_cache.get(coin, current)
        diff = current - prev
        arrow = "🔼" if diff > 0 else "🔽" if diff < 0 else "⏺"
        percent = f"{(diff / prev * 100):.2f}%" if prev else "0%"
        messages.append(f"{name}: ${current:.2f} {arrow} ({percent})")
        price_cache[coin] = current

    return "\n".join(messages)

# 자동 전송
async def send_auto(application):
    await application.bot.send_message(chat_id=CHAT_ID, text=await get_translated_news())
    await application.bot.send_message(chat_id=CHAT_ID, text=await get_price_message())

# 봇 실행
async def main():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: app_bot.create_task(send_auto(app_bot)), 'interval', minutes=1)
    scheduler.start()

    await app_bot.run_polling()

# Render-friendly 방식
import asyncio
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
