import os
import logging
import asyncio
import httpx
import feedparser
from flask import Flask
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
from datetime import datetime
import pytz

# ✅ 환경변수 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ✅ 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Flask 앱 (Render Keepalive 용)
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Coin News Bot is running!"

# ✅ 뉴스 전송 함수
async def send_auto_news():
    try:
        feed_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(feed_url)

        if not feed.entries:
            return

        sorted_entries = sorted(feed.entries, key=lambda x: x.published_parsed)

        messages = []
        for entry in sorted_entries[-3:]:  # 최근 3개 뉴스
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 {translated}\n🔗 {link}")

        news_message = "\n\n".join(messages)
        await bot_app.bot.send_message(chat_id=CHAT_ID, text=f"📡 코인 뉴스 업데이트\n\n{news_message}")
    except Exception as e:
        logger.error(f"뉴스 전송 오류: {e}")

# ✅ 가격 전송 함수
previous_prices = {}

async def send_auto_price():
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            data = response.json()

        if not data:
            return

        now_prices = {coin: data[coin]["usd"] for coin in coins}
        msg = "📈 코인 시세 (1분 전 대비)\n"

        for coin in coins:
            now = now_prices[coin]
            prev = previous_prices.get(coin, now)
            diff = now - prev
            emoji = "🔺" if diff > 0 else ("🔻" if diff < 0 else "⏸")
            msg += f"{coin.upper():<10}: ${now:.2f} {emoji} ({diff:+.2f})\n"
            previous_prices[coin] = now

        await bot_app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"가격 전송 오류: {e}")

# ✅ 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 & 시세 봇 작동 중입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price()

# ✅ 봇 앱 설정
bot_app = ApplicationBuilder().token(TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("news", news))
bot_app.add_handler(CommandHandler("price", price))

# ✅ 스케줄러 실행
scheduler = AsyncIOScheduler()

def start_scheduler():
    scheduler.add_job(send_auto_news, IntervalTrigger(minutes=10))
    scheduler.add_job(send_auto_price, IntervalTrigger(minutes=1))
    scheduler.start()
    logger.info("⏱ 스케줄러 작동 시작됨")

# ✅ 메인 비동기 실행
async def main():
    start_scheduler()
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    await bot_app.updater.wait_for_stop()

# ✅ Flask + Bot 병렬 실행
if __name__ == "__main__":
    import threading

    # Flask 따로 실행
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000)).start()

    # 봇 이벤트 루프 실행
    asyncio.run(main())
