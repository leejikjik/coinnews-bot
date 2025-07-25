import os
import logging
import asyncio
from datetime import datetime
import pytz
import httpx
import feedparser
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ========== 초기 설정 ==========
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
last_prices = {}
last_sent_links = set()

# ========== 가격 추적 ==========
async def fetch_price(symbol):
    url_map = {
        "bitcoin": "BTCUSDT",
        "ethereum": "ETHUSDT"
    }
    binance_symbol = url_map[symbol]
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}"

    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()
        return float(data['price'])

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")
    result = f"📉 <b>{now} 기준 1분간 가격 변화</b>\n\n"

    for symbol, name in coins.items():
        current = await fetch_price(symbol)
        prev = last_prices.get(symbol, current)
        diff = round(current - prev, 2)
        arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
        result += f"{name}: ${prev} → ${current} {arrow} ({diff})\n"
        last_prices[symbol] = current

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=result, parse_mode="HTML")

# ========== 뉴스 ==========
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)

    for entry in sorted_entries[-5:]:
        if entry.link in last_sent_links:
            continue
        last_sent_links.add(entry.link)
        title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 <b>{title}</b>\n{entry.link}"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

# ========== 명령어 ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 코인 뉴스 & 가격 추적 봇입니다!\n/news 또는 /price 명령어를 사용해보세요.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    result = "<b>📊 현재 가격</b>\n\n"

    for symbol, name in coins.items():
        current = await fetch_price(symbol)
        result += f"{name}: ${current}\n"

    await update.message.reply_text(result, parse_mode="HTML")

# ========== Flask KeepAlive ==========
@app.route("/")
def home():
    return "Bot is alive!"

# ========== 메인 ==========
async def setup_bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("price", price))
    app_bot.job_queue.run_repeating(track_prices, interval=60, first=5)
    app_bot.job_queue.run_repeating(fetch_and_send_news, interval=180, first=10)

    await app_bot.initialize()
    await app_bot.start()
    logging.info("✅ Telegram 봇 시작됨")
    asyncio.create_task(app_bot.updater.start_polling())

async def main():
    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    await setup_bot()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
