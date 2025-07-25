import asyncio
import logging
import os
from datetime import datetime

import feedparser
import httpx
import pytz
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, Defaults, JobQueue
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

last_prices = {}
last_sent_links = set()

# ================= 코인 가격 추적 =================

async def fetch_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        return res.json().get(symbol, {}).get("usd")

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")

    msg = f"📉 <b>{now} 기준 1분 가격 변화</b>\n\n"
    for symbol, name in coins.items():
        curr = await fetch_price(symbol)
        prev = last_prices.get(symbol, curr)
        diff = round(curr - prev, 2)
        arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
        msg += f"{name}: ${prev} → ${curr} {arrow} ({diff})\n"
        last_prices[symbol] = curr

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

# ================= 뉴스 =================

async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)

    for entry in sorted_entries[-5:]:
        link = entry.link
        if link in last_sent_links:
            continue
        last_sent_links.add(link)
        title_ko = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        msg = f"📰 <b>{title_ko}</b>\n{link}"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

# ================= 명령어 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 코인 뉴스 & 가격 추적 봇입니다.\n/price 또는 /news 명령어를 사용하세요.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    msg = "<b>📊 현재 코인 가격</b>\n\n"
    for symbol, name in coins.items():
        price = await fetch_price(symbol)
        msg += f"{name}: ${price}\n"
    await update.message.reply_text(msg, parse_mode="HTML")

# ================= Flask keepalive =================

@app.route("/")
def home():
    return "Bot is Alive"

# ================= 실행 =================

async def main():
    defaults = Defaults(parse_mode="HTML")
    app_bot = ApplicationBuilder().token(TOKEN).defaults(defaults).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("price", price))

    job_queue: JobQueue = app_bot.job_queue
    job_queue.run_repeating(track_prices, interval=60, first=5)
    job_queue.run_repeating(fetch_and_send_news, interval=180, first=10)

    task1 = asyncio.create_task(app_bot.run_polling())
    task2 = asyncio.create_task(app.run_task("0.0.0.0", port=10000))
    await asyncio.gather(task1, task2)

if __name__ == "__main__":
    asyncio.run(main())
