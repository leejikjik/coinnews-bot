# coinnews_bot.py
import os
import asyncio
import logging
import feedparser
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from dotenv import load_dotenv

# 환경변수 로드 (.env는 로컬에서만 필요 / Render는 설정 패널에 입력)
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# 뉴스 크롤링 및 번역 함수
def fetch_translated_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        return "❌ 뉴스 데이터를 불러올 수 없습니다."

    messages = []
    for entry in reversed(feed.entries[:3]):
        title = entry.title
        link = entry.link
        translated_title = GoogleTranslator(source="auto", target="ko").translate(title)
        messages.append(f"📰 {translated_title}\n{link}")
    return "\n\n".join(messages)

# 가격 추적 함수
import httpx
previous_prices = {}

async def fetch_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,dogecoin,ripple&vs_currencies=usd"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()
    except Exception:
        return "❌ 가격 데이터를 가져올 수 없습니다."

    result = []
    for coin, label in {
        "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
        "dogecoin": "DOGE", "ripple": "XRP"
    }.items():
        current = data.get(coin, {}).get("usd")
        prev = previous_prices.get(coin)
        previous_prices[coin] = current
        if prev:
            diff = round(current - prev, 4)
            sign = "🔼" if diff > 0 else "🔽" if diff < 0 else "⏸️"
            result.append(f"{label}: ${current} ({sign}{abs(diff)})")
        else:
            result.append(f"{label}: ${current}")
    return "\n".join(result)

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스봇이 정상 작동 중입니다.\n/news - 최신 뉴스\n/price - 실시간 가격")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = fetch_translated_news()
    await update.message.reply_text(msg)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# 텔레그램 봇 실행 함수
async def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 매 60초마다 가격 자동 전송
    async def job_send_price(context: ContextTypes.DEFAULT_TYPE):
        msg = await fetch_price()
        if msg:
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)

    application.job_queue.run_repeating(job_send_price, interval=60, first=5)

    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

# Flask 서버
@app.route("/")
def home():
    return "✅ Flask 서버 작동 중"

# 병렬 실행
if __name__ == "__main__":
    # Flask는 스레드로 실행
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # Telegram 봇은 메인 asyncio 루프에서 실행
    asyncio.run(main())
