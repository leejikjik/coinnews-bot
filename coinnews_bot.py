import os
import asyncio
import logging
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from deep_translator import GoogleTranslator
import feedparser
import httpx

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 기본 설정
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
scheduler = AsyncIOScheduler()

# 뉴스 가져오기
async def fetch_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        news_items = feed.entries[:3]
        messages = []
        for entry in reversed(news_items):
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            messages.append(f"📰 <b>{translated_title}</b>\n{translated_summary}\n{entry.link}\n")
        return "\n".join(messages)
    except Exception as e:
        logging.error(f"뉴스 에러: {e}")
        return "❌ 뉴스 가져오기 실패"

# 코인 가격 추적
previous_prices = {}

async def fetch_price():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
        "vs_currencies": "usd"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            data = response.json()
    except Exception as e:
        logging.error(f"가격 API 에러: {e}")
        return "❌ 가격 정보 가져오기 실패"

    result = []
    for coin_id, label in {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "ripple": "XRP",
        "solana": "SOL",
        "dogecoin": "DOGE"
    }.items():
        now = data.get(coin_id, {}).get("usd")
        if now is None:
            continue
        prev = previous_prices.get(coin_id)
        diff = f"{now - prev:+.2f}" if prev else "N/A"
        previous_prices[coin_id] = now
        result.append(f"{label}: ${now:.2f} ({diff})")

    return "📈 실시간 코인 가격 (1분 단위 추적):\n" + "\n".join(result)

# 봇 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 봇 작동 중입니다!\n/news 또는 /price 입력해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_news()
    await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# 봇 실행
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logging.info("✅ Telegram 봇 작동 시작됨")

    # 스케줄링
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news()), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price()), "interval", minutes=1)
    scheduler.start()
    logging.info("⏱ 스케줄러 시작됨")

async def send_auto_news():
    msg = await fetch_news()
    await send_message(msg)

async def send_auto_price():
    msg = await fetch_price()
    await send_message(msg)

async def send_message(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"메시지 전송 오류: {e}")

# Flask 라우팅
@app.route('/')
def index():
    return "✅ Coin News Bot Running"

# Flask + Bot 병렬 실행
async def main():
    bot_task = asyncio.create_task(run_bot())
    flask_task = asyncio.to_thread(app.run, host="0.0.0.0", port=10000)
    await asyncio.gather(bot_task, flask_task)

# ✅ Render 환경에서는 조건문 없이 바로 실행
asyncio.run(main())
