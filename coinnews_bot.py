import os
import asyncio
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    Defaults, JobQueue
)
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 1. 환경설정
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 2. 기본 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 3. Flask 설정
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Bot is running"

# 4. 봇 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("코인 뉴스 및 시세 봇입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price()

# 5. 뉴스 전송 함수
async def send_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[-5:]):
        title = entry.title
        link = entry.link
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        messages.append(f"📰 {translated}\n{link}")
    if messages:
        async with Application.builder().token(BOT_TOKEN).build() as app:
            for msg in messages:
                await app.bot.send_message(chat_id=CHAT_ID, text=msg)

# 6. 시세 전송 함수
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

        text = "📊 코인 실시간 시세\n" + "\n".join(msg_lines)
        async with Application.builder().token(BOT_TOKEN).build() as app:
            await app.bot.send_message(chat_id=CHAT_ID, text=text)

    except Exception as e:
        logger.error(f"Price fetch error: {e}")

# 7. 텔레그램 봇 실행 함수
async def run_bot():
    defaults = Defaults(parse_mode="HTML")
    application = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 자동 전송 잡
    job_queue: JobQueue = application.job_queue
    job_queue.run_repeating(lambda _: asyncio.create_task(send_news()), interval=60*15, first=10)
    job_queue.run_repeating(lambda _: asyncio.create_task(send_price()), interval=60, first=15)

    logger.info("▶️ 봇 루프 시작됨")
    await application.start()
    await application.updater.start_polling()
    await application.updater.wait_until_closed()

# 8. 메인 실행 (Flask + 봇 동시에)
def main():
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    flask_app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    main()
