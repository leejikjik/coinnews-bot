import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "✅ Flask 서버 실행 중입니다."

# 한국 시간
KST = timezone(timedelta(hours=9))

# 봇 초기화
application = ApplicationBuilder().token(BOT_TOKEN).build()

# 이전 가격 저장
coin_ids = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
coin_symbols = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ripple": "XRP",
    "solana": "SOL",
    "dogecoin": "DOGE",
}
previous_prices = {}

# 뉴스 전송
async def fetch_and_send_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        if not feed.entries:
            return
        messages = []
        for entry in reversed(feed.entries[-3:]):
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"🗞 <b>{translated}</b>\n{published}\n<a href='{entry.link}'>원문보기</a>\n")
        await application.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML", disable_web_page_preview=True)
        logger.info("✅ 뉴스 전송 완료")
    except Exception as e:
        logger.error(f"❌ 뉴스 오류: {e}")

# 시세 전송
async def fetch_and_send_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}

        async with httpx.AsyncClient() as client:
            res = await client.get(url, params=params, timeout=10)
            data = res.json()

        messages = []
        for coin in coin_ids:
            price = data.get(coin, {}).get("usd")
            if price is None:
                continue
            prev = previous_prices.get(coin)
            diff = f" ({price - prev:+.2f})" if prev else ""
            previous_prices[coin] = price
            messages.append(f"{coin_symbols[coin]}: ${price:.2f}{diff}")

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"📈 <b>코인 시세</b>\n{now}\n\n" + "\n".join(messages)
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
        logger.info("✅ 시세 전송 완료")
    except Exception as e:
        logger.error(f"❌ 시세 오류: {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ /news 또는 /price 명령어로 확인 가능합니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_and_send_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_and_send_prices()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("news", news))
application.add_handler(CommandHandler("price", price))

# 스케줄러 설정
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_news()), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_prices()), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ APScheduler 시작됨")

# 봇 실행 함수
async def run_bot():
    await application.initialize()
    await application.start()
    logger.info("✅ 봇 실행됨")
    await application.updater.stop()  # updater 사용 안 하지만 안전하게 정리

# 메인 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    start_scheduler()
    flask_app.run(host="0.0.0.0", port=10000)
