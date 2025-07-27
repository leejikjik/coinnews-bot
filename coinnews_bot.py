import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from pytz import timezone
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# 환경변수 로드
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Flask 앱 생성
flask_app = Flask(__name__)

# 번역기
translator = GoogleTranslator(source="auto", target="ko")

# 뉴스 파싱
async def send_auto_news(app):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    news_items = feed.entries[:5][::-1]  # 오래된 순
    messages = []

    for entry in news_items:
        title = translator.translate(entry.title)
        link = entry.link
        published = datetime(*entry.published_parsed[:6])
        published_kst = published.astimezone(timezone("Asia/Seoul"))
        messages.append(f"📰 {title}\n{link}\n🕒 {published_kst.strftime('%Y-%m-%d %H:%M')}\n")

    message = "\n".join(messages)
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        logging.error(f"뉴스 전송 오류: {e}")

# 가격 추적
previous_prices = {}

async def send_auto_price(app):
    url = "https://api.coingecko.com/api/v3/simple/price"
    coins = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
    params = {
        "ids": ",".join(coins),
        "vs_currencies": "usd",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            data = response.json()
    except Exception as e:
        logging.error(f"가격 가져오기 오류: {e}")
        return

    messages = []
    for coin in coins:
        now = data.get(coin, {}).get("usd")
        before = previous_prices.get(coin)
        if now is not None:
            change = f"{(now - before):+.2f}" if before else "N/A"
            messages.append(f"💰 {coin.upper()}: ${now:.2f} ({change})")
            previous_prices[coin] = now

    if messages:
        try:
            await app.bot.send_message(chat_id=CHAT_ID, text="\n".join(messages))
        except Exception as e:
            logging.error(f"가격 전송 오류: {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 & 시세 봇 작동 중입니다.\n/news: 뉴스\n/price: 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    news_items = feed.entries[:5][::-1]
    messages = []

    for entry in news_items:
        title = translator.translate(entry.title)
        link = entry.link
        published = datetime(*entry.published_parsed[:6])
        published_kst = published.astimezone(timezone("Asia/Seoul"))
        messages.append(f"📰 {title}\n{link}\n🕒 {published_kst.strftime('%Y-%m-%d %H:%M')}\n")

    await update.message.reply_text("\n".join(messages))

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.coingecko.com/api/v3/simple/price"
    coins = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
    params = {
        "ids": ",".join(coins),
        "vs_currencies": "usd",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            data = response.json()
    except Exception as e:
        await update.message.reply_text("❌ 가격 정보를 가져오지 못했습니다.")
        logging.error(f"/price 오류: {e}")
        return

    messages = []
    for coin in coins:
        price = data.get(coin, {}).get("usd")
        if price is not None:
            messages.append(f"💰 {coin.upper()}: ${price:.2f}")

    await update.message.reply_text("\n".join(messages))

# 봇 실행 및 Flask 서버 병렬 실행
async def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))

    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: app.create_task(send_auto_news(app)), IntervalTrigger(minutes=30))
    scheduler.add_job(lambda: app.create_task(send_auto_price(app)), IntervalTrigger(minutes=1))
    scheduler.start()

    logging.info("✅ Telegram 봇 시작됨")
    await app.start()
    await app.updater.start_polling()
    await app.updater.wait()

# Flask 루트 페이지
@flask_app.route("/")
def index():
    return "✅ Telegram Coin Bot is running!"

# 메인 시작
if __name__ == "__main__":
    import threading

    # Telegram 봇 스레드 실행
    threading.Thread(target=lambda: asyncio.run(run_bot())).start()

    # Flask 실행
    flask_app.run(host="0.0.0.0", port=10000)
