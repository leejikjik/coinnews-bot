import os
import logging
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
import asyncio
import threading
import json
import urllib.parse

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 시간대
KST = timezone("Asia/Seoul")
app = Flask(__name__)
previous_prices = {}

# CoinGecko 코인 ID
coins = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "ripple": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 코인 뉴스 및 시세 봇 작동 중\n/news : 뉴스\n/price : 시세")

# /news
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
        logger.error(f"/news 오류: {e}")
        await update.message.reply_text("❌ 뉴스 가져오기 실패")

# 프록시를 통한 CoinGecko 시세 호출
async def get_coin_data():
    try:
        ids = ",".join(coins.keys())
        original_url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(original_url)}"
        async with httpx.AsyncClient() as client:
            r = await client.get(proxy_url)
            r.raise_for_status()
            raw_json = json.loads(r.json()["contents"])
            return raw_json
    except Exception as e:
        logger.error(f"CoinGecko 우회 요청 실패: {e}")
        return None

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await get_coin_data()
        if not data:
            await update.message.reply_text("❌ 시세 가져오기 실패")
            return

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        result = [f"📊 실시간 코인 시세 ({now})"]
        for coin_id, name in coins.items():
            if coin_id in data:
                price = float(data[coin_id]["usd"])
                prev = previous_prices.get(coin_id)
                diff = price - prev if prev else 0
                sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                change = f"{sign} {abs(diff):,.4f}" if prev else "➖ 변화 없음"
                result.append(f"{name}: {price:,.2f} USD ({change})")
                previous_prices[coin_id] = price
            else:
                result.append(f"{name}: ❌ 데이터 없음")
        await update.message.reply_text("\n".join(result))

    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("❌ 시세 처리 중 오류 발생")

# 자동 뉴스
async def send_auto_news(bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entry = feed.entries[0]
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        msg = f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}"
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"자동 뉴스 오류: {e}")

# 자동 시세
async def send_auto_price(bot):
    try:
        data = await get_coin_data()
        if not data:
            return

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        result = [f"📊 자동 코인 시세 ({now})"]
        for coin_id, name in coins.items():
            if coin_id in data:
                price = float(data[coin_id]["usd"])
                prev = previous_prices.get(coin_id)
                diff = price - prev if prev else 0
                sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                change = f"{sign} {abs(diff):,.4f}" if prev else "➖ 변화 없음"
                result.append(f"{name}: {price:,.2f} USD ({change})")
                previous_prices[coin_id] = price
            else:
                result.append(f"{name}: ❌ 데이터 없음")
        await bot.send_message(chat_id=CHAT_ID, text="\n".join(result))
    except Exception as e:
        logger.error(f"자동 시세 오류: {e}")

# Flask 루트
@app.route("/")
def home():
    return "✅ CoinNewsBot 작동 중"

# 스케줄러
def start_scheduler(bot):
    scheduler = BackgroundScheduler()

    def run_news():
        asyncio.run(send_auto_news(bot))

    def run_price():
        asyncio.run(send_auto_price(bot))

    scheduler.add_job(run_news, "interval", minutes=30)
    scheduler.add_job(run_price, "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# Telegram 봇 실행
def start_bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    start_scheduler(app_bot.bot)
    app_bot.run_polling()

# 병렬 실행
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    start_bot()
