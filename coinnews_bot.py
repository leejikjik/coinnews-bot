import os
import logging
import asyncio
import threading
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from httpx import AsyncClient, HTTPError
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
)

import feedparser
from datetime import datetime

# ✅ 환경 변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ✅ 로깅
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ✅ Flask 서버
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ CoinNews Telegram Bot is running."

# ✅ Telegram 봇 Application
application = ApplicationBuilder().token(TOKEN).build()

# ✅ 뉴스 수집 및 전송
async def send_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        sorted_entries = sorted(feed.entries, key=lambda x: x.published_parsed)

        messages = []
        for entry in sorted_entries[-3:]:  # 최근 3개만
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 {translated}\n🔗 {link}")

        msg = "\n\n".join(messages)
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
        logger.info("✅ 뉴스 전송 완료")
    except Exception as e:
        logger.error(f"[뉴스전송오류] {e}")

# ✅ 실시간 코인 시세 전송
price_cache = {}

async def send_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
            "vs_currencies": "usd"
        }

        async with AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            result = response.json()

        msg_lines = ["📊 코인 시세 (1분 전 대비)\n"]
        for coin in ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]:
            now_price = result.get(coin, {}).get("usd")
            if now_price is None:
                continue

            before = price_cache.get(coin)
            diff = f"{(now_price - before):+.2f}" if before else "N/A"
            msg_lines.append(f"{coin.upper()}: ${now_price} ({diff})")
            price_cache[coin] = now_price

        msg = "\n".join(msg_lines)
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
        logger.info("✅ 시세 전송 완료")
    except HTTPError as e:
        logger.error(f"[시세전송오류] {e}")
    except Exception as e:
        logger.error(f"[시세전송오류] {e}")

# ✅ 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 알리미 봇입니다.\n/news - 뉴스 보기\n/price - 코인 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("news", news))
application.add_handler(CommandHandler("price", price))

# ✅ 스케줄러 설정
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_news(), application.loop), "interval", minutes=15)
scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_price(), application.loop), "interval", minutes=1)
scheduler.start()

# ✅ Telegram Bot 실행 (비동기 루프)
async def run_bot():
    await application.initialize()
    await application.start()
    logger.info("✅ Telegram 봇 시작됨")
    await application.updater.start_polling()
    await application.updater.idle()

def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

# ✅ 서버 & 봇 병렬 실행
if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
    flask_app.run(host="0.0.0.0", port=10000)
