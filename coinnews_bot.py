import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from datetime import datetime, timezone, timedelta
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
)
from dotenv import load_dotenv

# Render 환경에서는 .env 생략
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

application = Application.builder().token(TOKEN).build()

# ⏱ 한국 시간
KST = timezone(timedelta(hours=9))

# ✅ 명령어: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 코인 뉴스봇 작동 중입니다!\n\n"
        "명령어:\n"
        "/news - 최신 코인 뉴스\n"
        "/price - 실시간 코인가격 추적"
    )

# ✅ 명령어: /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_translated_news()
    await update.message.reply_text(msg)

# ✅ 명령어: /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price_diff()
    await update.message.reply_text(msg)

# ✅ 뉴스 수집 + 번역
async def fetch_translated_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    entries = sorted(feed.entries, key=lambda x: x.published_parsed)
    messages = []

    for entry in entries[-5:]:
        title = GoogleTranslator(source='en', target='ko').translate(entry.title)
        link = entry.link
        published = datetime(*entry.published_parsed[:6]).astimezone(KST)
        time_str = published.strftime('%m/%d %H:%M')
        messages.append(f"📰 {title}\n🕒 {time_str}\n🔗 {link}")

    return "\n\n".join(messages)

# ✅ 가격 비교
price_cache = {}

async def fetch_price_diff():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,ripple,solana,dogecoin&vs_currencies=usd"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()

        msg = []
        now = datetime.now(KST).strftime("%H:%M:%S")
        for coin in ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]:
            name = {
                "bitcoin": "BTC",
                "ethereum": "ETH",
                "ripple": "XRP",
                "solana": "SOL",
                "dogecoin": "DOGE"
            }[coin]
            price = data.get(coin, {}).get("usd")
            if price is None:
                continue

            prev = price_cache.get(coin)
            diff = f"{price - prev:.2f}" if prev else "N/A"
            price_cache[coin] = price

            msg.append(f"{name}: ${price} (변동: {diff})")

        return f"📊 실시간 코인 시세 (KST {now})\n\n" + "\n".join(msg)

    except Exception as e:
        logging.error(f"가격 조회 실패: {e}")
        return "❌ 코인 가격 조회 실패"

# ✅ 자동 작업
async def send_auto_news():
    try:
        msg = await fetch_translated_news()
        await application.bot.send_message(chat_id=CHAT_ID, text=f"📢 [자동 뉴스]\n\n{msg}")
    except Exception as e:
        logging.error(f"자동 뉴스 전송 실패: {e}")

async def send_auto_price():
    try:
        msg = await fetch_price_diff()
        await application.bot.send_message(chat_id=CHAT_ID, text=f"📢 [자동 시세]\n\n{msg}")
    except Exception as e:
        logging.error(f"자동 시세 전송 실패: {e}")

# ✅ Flask 서버 (keepalive 용도)
@app.route("/")
def index():
    return "Coin News Bot is running."

# ✅ Bot 실행
async def run_bot():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logging.info("✅ Telegram 봇이 시작되었습니다.")

# ✅ 스케줄러
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news()), IntervalTrigger(minutes=60))
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price()), IntervalTrigger(minutes=1))
    scheduler.start()
    logging.info("⏱ 스케줄러 작동 시작됨")

# ✅ main
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    start_scheduler()
    app.run(host="0.0.0.0", port=10000)
