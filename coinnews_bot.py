import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 한국시간
KST = timezone("Asia/Seoul")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "✅ Coin News Bot is running!"

# 뉴스 가져오기 + 번역
def fetch_translated_news(limit=3):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    items = feed.entries[:limit]
    messages = []

    for item in reversed(items):
        title = item.title
        link = item.link
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        published = datetime(*item.published_parsed[:6]).astimezone(KST)
        messages.append(f"📰 {translated}\n{published.strftime('%Y-%m-%d %H:%M')} KST\n{link}")
    return "\n\n".join(messages)

# 시세 가져오기
async def get_price_change():
    url = "https://api.coingecko.com/api/v3/simple/price"
    coins = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
    params = {
        "ids": ",".join(coins),
        "vs_currencies": "usd",
        "include_last_updated_at": "true"
    }
    try:
        async with httpx.AsyncClient() as client:
            res1 = await client.get(url, params=params)
            await asyncio.sleep(60)
            res2 = await client.get(url, params=params)
        data1 = res1.json()
        data2 = res2.json()
        msg = ["💹 코인 시세 1분 변화:\n"]
        for coin in coins:
            price1 = data1[coin]["usd"]
            price2 = data2[coin]["usd"]
            diff = price2 - price1
            sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "⏸"
            msg.append(f"{coin.upper()}: ${price2:.2f} ({sign} {diff:.2f})")
        return "\n".join(msg)
    except Exception as e:
        logger.error(f"❌ 가격 가져오기 오류: {e}")
        return "❌ 가격 데이터를 가져오지 못했습니다."

# /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 봇입니다!\n/news 최신 뉴스\n/price 실시간 시세")

# /news
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news = fetch_translated_news()
    await update.message.reply_text(news)

# /price
async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_price_change()
    await update.message.reply_text(msg)

# 봇 실행 함수
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("price", price_command))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # 스케줄러
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_auto_news(application), application.loop),
                      IntervalTrigger(minutes=10))
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_auto_price(application), application.loop),
                      IntervalTrigger(minutes=1))
    scheduler.start()

    logger.info("✅ Telegram 봇 시작됨")
    await application.updater.wait_until_disconnected()

# 자동 뉴스
async def send_auto_news(app: Application):
    try:
        news = fetch_translated_news()
        await app.bot.send_message(chat_id=CHAT_ID, text=news)
    except Exception as e:
        logger.error(f"❌ 자동 뉴스 전송 실패: {e}")

# 자동 시세
async def send_auto_price(app: Application):
    try:
        msg = await get_price_change()
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"❌ 자동 시세 전송 실패: {e}")

# main
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    flask_app.run(host="0.0.0.0", port=10000)
