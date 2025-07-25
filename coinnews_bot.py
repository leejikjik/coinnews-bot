import os
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import feedparser
import pytz
import httpx
from flask import Flask
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# .env 환경변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")

# Flask 앱 (Render KeepAlive용)
app = Flask(__name__)
@app.route("/")
def index():
    return "Bot is running"

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# 이전 가격 저장
last_prices = {}
last_sent_links = set()

# 코인 가격 가져오기
async def fetch_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        return r.json().get(symbol, {}).get("usd")

# 가격 추적 작업
async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    now = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")
    result = f"📈 <b>{now} 기준 1분간 가격 변화</b>\n\n"
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

# 뉴스 가져오기 및 전송
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    sorted_entries = sorted(feed.entries, key=lambda e: e.published_parsed)

    for entry in sorted_entries[-5:]:
        if entry.link in last_sent_links:
            continue
        last_sent_links.add(entry.link)
        title_ko = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 <b>{title_ko}</b>\n{entry.link}"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 코인 뉴스 & 가격 추적 봇입니다!\n/news 또는 /price 명령어를 사용해보세요.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = {"bitcoin": "BTC", "ethereum": "ETH"}
    msg = "<b>현재 코인 가격</b>\n\n"
    for symbol, name in coins.items():
        p = await fetch_price(symbol)
        msg += f"{name}: ${p}\n"
    await update.message.reply_text(msg, parse_mode="HTML")

# 봇 실행
async def main():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.job_queue.run_repeating(track_prices, interval=60, first=5)
    application.job_queue.run_repeating(fetch_and_send_news, interval=180, first=10)
    await application.run_polling()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
