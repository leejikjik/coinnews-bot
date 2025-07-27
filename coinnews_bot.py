import os
import asyncio
import threading
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, Defaults, JobQueue
)
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경변수 로드
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 서버
flask_app = Flask(__name__)
@flask_app.route("/")
def index():
    return "Bot is running"

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📢 코인 뉴스 및 시세 알림 봇입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price()

# 뉴스 전송
async def send_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[-5:]):
        title = entry.title
        link = entry.link
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        messages.append(f"📰 {translated}\n{link}")
    text = "\n\n".join(messages)
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"[뉴스전송오류] {e}")

# 시세 전송
price_cache = {}
async def send_price():
    url = "https://api.coingecko.com/api/v3/simple/price"
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    params = {
        "ids": ",".join(coins),
        "vs_currencies": "usd"
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, timeout=10)
            result = r.json()
        msg_lines = []
        for coin in coins:
            now = result.get(coin, {}).get("usd")
            before = price_cache.get(coin, now)
            change = now - before
            emoji = "🔺" if change > 0 else "🔻" if change < 0 else "⏸️"
            msg_lines.append(f"{coin.upper()}: ${now} ({emoji}{change:.2f})")
            price_cache[coin] = now
        text = "📊 실시간 코인 시세\n" + "\n".join(msg_lines)
        await app.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"[시세전송오류] {e}")

# 텔레그램 봇 실행 함수
async def main_bot():
    global app
    defaults = Defaults(parse_mode="HTML")
    app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))

    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(lambda _: asyncio.create_task(send_news()), interval=60*15, first=5)
    job_queue.run_repeating(lambda _: asyncio.create_task(send_price()), interval=60, first=10)

    logger.info("✅ Telegram 봇 시작됨")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.wait_until_closed()

# Flask를 스레드로 실행
def run_flask():
    flask_app.run(host="0.0.0.0", port=10000)

# 최종 실행
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    asyncio.run(main_bot())
