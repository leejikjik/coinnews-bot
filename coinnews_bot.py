import asyncio
import logging
import os
from datetime import datetime
import pytz
import feedparser
import httpx
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

last_prices = {}
last_sent_links = set()

# 가격 조회 함수
async def fetch_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        return r.json().get(symbol, {}).get("usd")

# 가격 추적 작업
async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")
    result = f"📊 <b>{now} 기준 1분간 가격 변화</b>\n\n"
    for symbol, name in coins.items():
        current = await fetch_price(symbol)
        if not current:
            continue
        prev = last_prices.get(symbol, current)
        change = round(current - prev, 2)
        arrow = "🔺" if change > 0 else "🔻" if change < 0 else "➡️"
        result += f"{name}: ${prev} → ${current} {arrow} ({change})\n"
        last_prices[symbol] = current

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=result, parse_mode="HTML")

# 뉴스 전송 작업
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)
    for entry in sorted_entries[-5:]:
        link = entry.link
        if link in last_sent_links:
            continue
        last_sent_links.add(link)
        title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 <b>{title}</b>\n{link}"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

# 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 코인 뉴스 & 가격 추적 봇입니다!\n/news 또는 /price 명령어를 사용해보세요.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    msg = "<b>📈 현재 코인 가격</b>\n\n"
    for symbol, name in coins.items():
        price = await fetch_price(symbol)
        msg += f"{name}: ${price}\n"
    await update.message.reply_text(msg, parse_mode="HTML")

# Flask KeepAlive
@app.route("/")
def keep_alive():
    return "✅ Bot is running!"

# 실행부
async def run_bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("price", price))

    app_bot.job_queue.run_repeating(track_prices, interval=60, first=5)
    app_bot.job_queue.run_repeating(fetch_and_send_news, interval=180, first=10)

    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await app_bot.updater.wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    app.run(host="0.0.0.0", port=10000)
