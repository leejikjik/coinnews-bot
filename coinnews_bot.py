import os
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 한국시간
KST = timezone(timedelta(hours=9))

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 코인 ID (CoinCap 기준 정확하게)
coins = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

# 가격 캐시
price_cache = {}

# Flask 앱
app = Flask(__name__)

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 시세 가져오기
async def fetch_price():
    result = []
    async with httpx.AsyncClient() as client:
        for coin_id, name in coins.items():
            try:
                url = f"https://api.coincap.io/v2/assets/{coin_id}"
                r = await client.get(url)
                data = r.json()["data"]
                current_price = float(data["priceUsd"])
                previous_price = price_cache.get(coin_id, current_price)
                diff = current_price - previous_price
                emoji = "🔺" if diff > 0 else ("🔻" if diff < 0 else "⏸️")
                price_cache[coin_id] = current_price
                result.append(f"{name}: ${current_price:,.2f} {emoji} ({diff:+.2f})")
            except Exception as e:
                logger.error(f"[시세 오류] {e}")
    return "\n".join(result)

# 뉴스 가져오기
async def fetch_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    items = sorted(feed.entries[:5], key=lambda x: x.published_parsed)
    messages = []
    for item in items:
        try:
            translated = GoogleTranslator(source="auto", target="ko").translate(item.title)
            pub_time = datetime(*item.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            messages.append(f"🗞️ {translated}\n🕒 {pub_time}\n🔗 {item.link}")
        except Exception as e:
            logger.error(f"[뉴스 오류] {e}")
    return "\n\n".join(messages)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("✅ 봇 작동 중\n/news : 뉴스\n/price : 코인시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await fetch_news()
    await update.message.reply_text(text or "뉴스를 불러올 수 없습니다.")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await fetch_price()
    await update.message.reply_text(text or "시세를 불러올 수 없습니다.")

# 자동 시세 전송
async def send_auto_price():
    from telegram import Bot
    bot = Bot(token=TOKEN)
    try:
        text = await fetch_price()
        if text:
            await bot.send_message(chat_id=CHAT_ID, text=f"📊 1분 간격 자동 시세\n\n{text}")
    except Exception as e:
        logger.error(f"[자동 시세 오류] {e}")

# 스케줄러
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price()), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# Flask 라우팅
@app.route("/")
def index():
    return "Bot is running!"

# 앱 실행
if __name__ == "__main__":
    import asyncio
    from threading import Thread

    async def run_bot():
        app_builder = ApplicationBuilder().token(TOKEN)
        application = app_builder.build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("news", news))
        application.add_handler(CommandHandler("price", price))
        start_scheduler()
        await application.run_polling()

    def run_flask():
        app.run(host="0.0.0.0", port=10000)

    Thread(target=run_flask).start()
    asyncio.run(run_bot())
