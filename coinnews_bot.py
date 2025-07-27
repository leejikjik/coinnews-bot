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

# 텔레그램 봇 설정
application = ApplicationBuilder().token(BOT_TOKEN).build()

# 뉴스 가져오기 함수
async def fetch_and_send_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        if not feed.entries:
            logger.warning("뉴스 피드가 비어 있습니다.")
            return

        messages = []
        for entry in reversed(feed.entries[-3:]):
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"🗞 <b>{translated}</b>\n{published}\n<a href='{entry.link}'>원문보기</a>\n")

        full_message = "\n\n".join(messages)
        await application.bot.send_message(chat_id=CHAT_ID, text=full_message, parse_mode="HTML", disable_web_page_preview=True)
        logger.info("✅ 뉴스 전송 완료")
    except Exception as e:
        logger.error(f"❌ 뉴스 전송 오류: {e}")

# 가격 추적 함수
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
        params = {
            "ids": ",".join(coin_ids),
            "vs_currencies": "usd",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

        messages = []
        for coin in coin_ids:
            now_price = data.get(coin, {}).get("usd")
            if now_price is None:
                continue

            prev_price = previous_prices.get(coin)
            change = ""
            if prev_price:
                diff = now_price - prev_price
                change = f" ({'+' if diff >= 0 else ''}{diff:.2f})"

            messages.append(f"{coin_symbols[coin]}: ${now_price:.2f}{change}")
            previous_prices[coin] = now_price

        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        message = f"📈 <b>코인 실시간 시세</b>\n{timestamp}\n\n" + "\n".join(messages)
        await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML")
        logger.info("✅ 시세 전송 완료")
    except httpx.HTTPStatusError as e:
        logger.warning(f"⏳ API 호출 오류 (Rate Limit?): {e}")
    except Exception as e:
        logger.error(f"❌ 시세 전송 실패: {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇입니다. /news 또는 /price 명령어를 사용하세요.")

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
    logger.info("✅ 스케줄러 실행됨")

# 메인 실행
async def run():
    logger.info("✅ 텔레그램 봇 작동 시작")
    start_scheduler()
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.wait()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run())
    flask_app.run(host="0.0.0.0", port=10000)
