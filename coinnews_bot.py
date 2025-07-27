import os
import logging
import feedparser
import httpx
import asyncio
from flask import Flask
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Coin News Bot is running"

# 한국 시간대
KST = timezone("Asia/Seoul")

# 뉴스 가져오기 및 번역
def fetch_translated_news(limit=3):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    items = feed.entries[:limit]
    messages = []
    for item in reversed(items):
        title = item.title
        link = item.link
        published = datetime(*item.published_parsed[:6]).astimezone(KST)
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        messages.append(f"📰 {translated}\n{published.strftime('%Y-%m-%d %H:%M')} KST\n{link}")
    return "\n\n".join(messages)

# 시세 비교
async def get_price_change():
    url = "https://api.coingecko.com/api/v3/simple/price"
    coins = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
    params = {
        "ids": ",".join(coins),
        "vs_currencies": "usd"
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
            price1 = data1.get(coin, {}).get("usd", 0)
            price2 = data2.get(coin, {}).get("usd", 0)
            diff = price2 - price1
            sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "⏸"
            msg.append(f"{coin.upper()}: ${price2:.2f} ({sign} {diff:.2f})")
        return "\n".join(msg)
    except Exception as e:
        logger.error(f"❌ 시세 오류: {e}")
        return "❌ 시세 데이터를 가져올 수 없습니다."

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 및 실시간 시세 봇입니다.\n/news 최신 뉴스\n/price 실시간 가격")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    news = fetch_translated_news()
    await update.message.reply_text(news)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_price_change()
    await update.message.reply_text(msg)

# 자동 전송
async def send_auto_news(app: Application):
    try:
        news = fetch_translated_news()
        await app.bot.send_message(chat_id=CHAT_ID, text=news)
    except Exception as e:
        logger.error(f"[뉴스 자동 전송 실패] {e}")

async def send_auto_price(app: Application):
    try:
        msg = await get_price_change()
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"[시세 자동 전송 실패] {e}")

# 메인 실행
async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # 스케줄러
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news(application)), IntervalTrigger(minutes=10))
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price(application)), IntervalTrigger(minutes=1))
    scheduler.start()

    logger.info("✅ Telegram Bot 시작됨")
    await application.updater.wait_until_disconnected()

# 진입점
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    flask_app.run(host="0.0.0.0", port=10000)
