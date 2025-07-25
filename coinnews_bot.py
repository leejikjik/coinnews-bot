import logging
import feedparser
import asyncio
import httpx
import pytz
from datetime import datetime, timedelta
from flask import Flask
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, defaults
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID"))

app = Flask(__name__)

# 가격 저장소
last_prices = {}

# 번역기
def translate(text):
    try:
        return GoogleTranslator(source='auto', target='ko').translate(text)
    except:
        return text

# Cointelegraph RSS 파싱 및 번역
async def fetch_and_send_news(app):
    while True:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)

        async with httpx.AsyncClient() as client:
            for entry in sorted_entries[-5:]:
                title_ko = translate(entry.title)
                summary_ko = translate(entry.summary)
                pub_time = datetime(*entry.published_parsed[:6]).astimezone(pytz.timezone("Asia/Seoul"))
                pub_str = pub_time.strftime("%Y-%m-%d %H:%M:%S (KST)")
                message = f"✨ {title_ko}\n{pub_str}\n{entry.link}\n\n📰 {summary_ko}"
                await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=message)
                await asyncio.sleep(10)
        await asyncio.sleep(600)

# 가격 가져오기
async def get_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        data = r.json()
        return data[symbol]["usd"]

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📰 실시간 코인 뉴스봇\n\n- 최신 뉴스 자동 번역 전송\n- /price : BTC/ETH 가격 1분 전 대비 확인"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = ["bitcoin", "ethereum"]
    msg = "📊 실시간 코인가격 (1분 전 대비)\n"

    for symbol in symbols:
        now_price = await get_price(symbol)
        old_price = last_prices.get(symbol)
        diff = now_price - old_price if old_price else 0
        emoji = "🔼" if diff > 0 else "🔽" if diff < 0 else "⏸"
        msg += f"{symbol.upper()} : ${now_price:.2f} ({emoji} {diff:.2f})\n"
        last_prices[symbol] = now_price

    await update.message.reply_text(msg)

# 백그라운드 1분 간격으로 가격 저장
async def track_price():
    while True:
        for symbol in ["bitcoin", "ethereum"]:
            last_prices[symbol] = await get_price(symbol)
        await asyncio.sleep(60)

# Flask용 keepalive
@app.route('/')
def home():
    return 'Coin News Bot is Running'

# 실행
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app_telegram = ApplicationBuilder().token(TOKEN).defaults(defaults).build()

    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("price", price))

    loop = asyncio.get_event_loop()
    loop.create_task(fetch_and_send_news(app_telegram))
    loop.create_task(track_price())
    loop.create_task(app_telegram.run_polling())

    app.run(host='0.0.0.0', port=10000)
