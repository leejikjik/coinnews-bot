# 파일명: coinnews_bot.py
import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ CoinNews Bot is running"

KST = timezone("Asia/Seoul")

# 뉴스 번역 및 메시지 생성
def fetch_translated_news(limit=3):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[:limit]):
        title = entry.title
        link = entry.link
        published = datetime(*entry.published_parsed[:6]).astimezone(KST)
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        messages.append(f"📰 {translated}\n{published.strftime('%Y-%m-%d %H:%M')} KST\n{link}")
    return "\n\n".join(messages)

# 시세 추적
async def get_price_change():
    coins = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(coins), "vs_currencies": "usd"}
    try:
        async with httpx.AsyncClient() as client:
            res1 = await client.get(url, params=params)
            await asyncio.sleep(60)
            res2 = await client.get(url, params=params)
        d1, d2 = res1.json(), res2.json()
        result = ["💹 코인 시세 변화 (1분)\n"]
        for coin in coins:
            p1, p2 = d1.get(coin, {}).get("usd", 0), d2.get(coin, {}).get("usd", 0)
            diff = p2 - p1
            sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "⏸"
            result.append(f"{coin.upper()}: ${p2:.2f} ({sign} {diff:.2f})")
        return "\n".join(result)
    except Exception as e:
        logger.error(f"시세 오류: {e}")
        return "❌ 시세 데이터를 불러올 수 없습니다."

# 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 및 시세 봇입니다.\n/news : 뉴스\n/price : 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = fetch_translated_news()
    await update.message.reply_text(msg)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_price_change()
    await update.message.reply_text(msg)

# 자동 전송
async def send_auto_news(app: Application):
    try:
        news = fetch_translated_news()
        await app.bot.send_message(chat_id=CHAT_ID, text=news)
    except Exception as e:
        logger.error(f"[뉴스 전송 실패] {e}")

async def send_auto_price(app: Application):
    try:
        msg = await get_price_change()
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"[시세 전송 실패] {e}")

# 메인 봇 실행
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # APScheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news(application)), IntervalTrigger(minutes=10))
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price(application)), IntervalTrigger(minutes=1))
    scheduler.start()

    logger.info("✅ Telegram 봇이 시작되었습니다.")
    await application.updater.wait_until_disconnected()

# 진입점
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    flask_app.run(host="0.0.0.0", port=10000)
