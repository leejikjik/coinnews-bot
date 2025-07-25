import os
import asyncio
import logging
import pytz
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
import feedparser
import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 환경 변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Flask 앱
app = Flask(__name__)

# 가격 저장
last_prices = {}
last_sent_links = set()

# === 가격 추적 ===
async def fetch_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            return res.json().get(symbol, {}).get("usd")
    except Exception as e:
        logging.error(f"[fetch_price] {e}")
        return None

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")
    result = f"📈 <b>{now} 기준 1분간 가격 변화</b>\n\n"

    for symbol, name in coins.items():
        current = await fetch_price(symbol)
        if current is None:
            continue
        prev = last_prices.get(symbol, current)
        change = round(current - prev, 2)
        arrow = "🔺" if change > 0 else "🔻" if change < 0 else "➡️"
        result += f"{name}: ${prev} → ${current} {arrow} ({change})\n"
        last_prices[symbol] = current

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=result, parse_mode="HTML")

# === 뉴스 전송 ===
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)

    for entry in sorted_entries[-5:]:
        link = entry.link
        if link in last_sent_links:
            continue
        last_sent_links.add(link)
        title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        msg = f"📰 <b>{title}</b>\n{link}"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

# === 명령어 핸들러 ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 코인 뉴스 & 가격 추적 봇입니다!\n/news 또는 /price 명령어를 사용해보세요.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    msg = "<b>현재 코인 가격</b>\n\n"
    for symbol, name in coins.items():
        price = await fetch_price(symbol)
        msg += f"{name}: ${price}\n"
    await update.message.reply_text(msg.strip(), parse_mode="HTML")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)
    msg = ""
    for entry in sorted_entries[-5:]:
        title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        msg += f"📰 <b>{title}</b>\n{entry.link}\n\n"
    await update.message.reply_text(msg.strip(), parse_mode="HTML")

# === Flask Keep-Alive ===
@app.route("/")
def index():
    return "✅ Bot is running!"

# === Bot 메인 ===
async def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))
    application.job_queue.run_repeating(track_prices, interval=60, first=5)
    application.job_queue.run_repeating(fetch_and_send_news, interval=180, first=10)
    logging.info(">>> Telegram bot starting polling")
    await application.run_polling()

# === 실행 시작 ===
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(run_bot())  # 봇 실행
    app.run(host="0.0.0.0", port=10000)  # Flask 실행
