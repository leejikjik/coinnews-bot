import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

import feedparser
from deep_translator import GoogleTranslator
import httpx

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "✅ Coin News Telegram Bot is running!"

# 한국 시간
KST = timezone(timedelta(hours=9))

# 텔레그램 봇 Application
application = ApplicationBuilder().token(BOT_TOKEN).build()

# 뉴스 함수
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

# 가격 함수
coin_ids = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
coin_symbols = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ripple": "XRP",
    "solana": "SOL",
    "dogecoin": "DOGE",
}
previous_prices = {}

async def fetch_and_send_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            data = response.json()

        messages = []
        for coin in coin_ids:
            price = data.get(coin, {}).get("usd")
            if price is None:
                continue

            prev = previous_prices.get(coin)
            change = f" ({price - prev:+.2f})" if prev else ""
            messages.append(f"{coin_symbols[coin]}: ${price:.2f}{change}")
            previous_prices[coin] = price

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"📈 <b>코인 시세</b>\n{now}\n\n" + "\n".join(messages)
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
        logger.info("✅ 시세 전송 완료")
    except Exception as e:
        logger.error(f"❌ 시세 오류: {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ /news 또는 /price로 뉴스와 시세를 확인할 수 있습니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_and_send_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_and_send_prices()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("news", news))
application.add_handler(CommandHandler("price", price))

# 스케줄러
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.get_event_loop().create_task(fetch_and_send_news()), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.get_event_loop().create_task(fetch_and_send_prices()), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ APScheduler 시작됨")

# 봇 실행
async def run_bot():
    start_scheduler()
    await application.initialize()
    await application.start()
    logger.info("✅ 봇 실행됨")
    await application.updater.stop()  # 제거되어도 무방하나 안전하게 중단처리

# 메인
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    flask_app.run(host="0.0.0.0", port=10000)
