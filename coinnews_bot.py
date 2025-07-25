import os
import asyncio
import logging
from datetime import datetime, timedelta

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import feedparser
from deep_translator import GoogleTranslator
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("GROUP_CHAT_ID")

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Translation function
def translate(text):
    try:
        return GoogleTranslator(source='auto', target='ko').translate(text)
    except:
        return text

# News fetch and send
async def fetch_and_send_news(app):
    logger.info("뉴스 수집 시작")
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        logger.warning("뉴스 항목 없음")
        return

    now = datetime.utcnow()
    latest_time = now - timedelta(minutes=10)

    for entry in reversed(feed.entries):  # 오래된 것부터
        published = datetime(*entry.published_parsed[:6])
        if published < latest_time:
            continue

        title = translate(entry.title)
        summary = translate(entry.summary)
        url = entry.link

        message = f"\ud83d\udcf0 <b>{title}</b>\n\n{summary}\n\n<a href=\"{url}\">\ub354 \ubcf4\uae30</a>"
        try:
            await app.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='HTML')
            logger.info("뉴스 전송 완료")
        except Exception as e:
            logger.error(f"뉴스 전송 실패: {e}")

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\ud83d\udd04 코인 뉴스봇 작동 중입니다. /price 입력시 현재 가격 확인 가능합니다.")

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coins = ['bitcoin', 'ethereum']
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()

        now = datetime.now().strftime('%H:%M:%S')
        message = f"[{now}] 현재 코인가격:\n"
        for coin in coins:
            price = data[coin]['usd']
            message += f"- {coin.capitalize()}: ${price:,}\n"

        await update.message.reply_text(message)
    except Exception as e:
        await update.message.reply_text("가격 정보를 불러오는 데 실패했습니다.")
        logger.error(f"가격 오류: {e}")

# Flask keep-alive
flask_app = Flask(__name__)
@flask_app.route("/")
def index():
    return "Bot is alive"

def start_scheduler(app):
    scheduler = BackgroundScheduler(timezone='Asia/Seoul')
    scheduler.add_job(lambda: asyncio.get_event_loop().create_task(fetch_and_send_news(app)), 'interval', minutes=3)
    scheduler.start()

if __name__ == '__main__':
    async def main():
        app = ApplicationBuilder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("price", price))

        start_scheduler(app)

        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await app.updater.idle()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

    # Flask 유지
    flask_app.run(host='0.0.0.0', port=10000)
