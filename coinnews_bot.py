import os
import logging
import asyncio
import httpx
import feedparser
from flask import Flask
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱 생성
app = Flask(__name__)

# 한국 시간대
KST = timezone("Asia/Seoul")

# 시세 조회 대상 코인
coins = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

# 이전 시세 저장용 딕셔너리
previous_prices = {}

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 코인 뉴스 및 시세 봇이 작동 중입니다.\n"
        "/news : 최신 뉴스\n"
        "/price : 현재 시세"
    )

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        messages = []
        for entry in reversed(entries):
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            messages.append(f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}")
        await update.message.reply_text("\n\n".join(messages))
    except Exception as e:
        logger.error(f"뉴스 오류: {e}")
        await update.message.reply_text("뉴스를 가져오는 중 오류가 발생했습니다.")

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.coincap.io/v2/assets")
            data = response.json().get("data", [])
            result = [f"📊 코인 시세 ({now} 기준):"]
            for coin_id, name in coins.items():
                coin_data = next((c for c in data if c["id"] == coin_id), None)
                if coin_data:
                    price = float(coin_data["priceUsd"])
                    price_str = f"{price:,.2f} USD"
                    prev = previous_prices.get(coin_id)
                    if prev:
                        diff = price - prev
                        sign = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➖")
                        change = f"{sign} {abs(diff):,.4f}"
                    else:
                        change = "➖ 변화 없음"
                    result.append(f"{name}: {price_str} ({change})")
                    previous_prices[coin_id] = price
            await update.message.reply_text("\n".join(result))
    except Exception as e:
        logger.error(f"시세 오류: {e}")
        await update.message.reply_text("시세를 가져오는 중 오류가 발생했습니다.")

# 자동 뉴스 전송
async def send_auto_news(application):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entry = feed.entries[0]
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        text = f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}"
        await application.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"자동 뉴스 오류: {e}")

# 자동 시세 전송
async def send_auto_price(application):
    try:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.coincap.io/v2/assets")
            data = response.json().get("data", [])
            result = [f"📊 코인 시세 ({now} 기준):"]
            for coin_id, name in coins.items():
                coin_data = next((c for c in data if c["id"] == coin_id), None)
                if coin_data:
                    price = float(coin_data["priceUsd"])
                    price_str = f"{price:,.2f} USD"
                    prev = previous_prices.get(coin_id)
                    if prev:
                        diff = price - prev
                        sign = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➖")
                        change = f"{sign} {abs(diff):,.4f}"
                    else:
                        change = "➖ 변화 없음"
                    result.append(f"{name}: {price_str} ({change})")
                    previous_prices[coin_id] = price
            await application.bot.send_message(chat_id=CHAT_ID, text="\n".join(result))
    except Exception as e:
        logger.error(f"자동 시세 오류: {e}")

# Flask 라우터
@app.route("/")
def index():
    return "✅ CoinNews Bot 작동 중"

# 스케줄러 시작
def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(application)), "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(application)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# Telegram Bot 실행
async def main():
    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    start_scheduler(app_bot)

    await app_bot.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
