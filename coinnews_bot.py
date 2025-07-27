import os
import asyncio
import logging
import feedparser
import requests
from flask import Flask
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────────────────────
# 뉴스 크롤링 및 번역
def get_translated_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    news_items = feed.entries[:5][::-1]  # 오래된 순
    messages = []
    for entry in news_items:
        translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
        message = f"📰 <b>{translated_title}</b>\n{translated_summary}\n{entry.link}"
        messages.append(message)
    return messages

# ──────────────────────────────────────────────────────────────
# 가격 추적
price_cache = {}

def fetch_price_data():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
        "vs_currencies": "usd",
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        return {
            "BTC": data["bitcoin"]["usd"],
            "ETH": data["ethereum"]["usd"],
            "XRP": data["ripple"]["usd"],
            "SOL": data["solana"]["usd"],
            "DOGE": data["dogecoin"]["usd"],
        }
    except Exception as e:
        logging.error(f"가격 정보 오류: {e}")
        return {}

def get_price_change_message():
    global price_cache
    current = fetch_price_data()
    if not current:
        return "⚠️ 코인 시세를 가져오지 못했습니다."
    
    msg = f"💰 <b>코인 시세 (1분 추적)</b>\n{datetime.now().strftime('%H:%M:%S')}\n\n"
    for coin, now_price in current.items():
        before = price_cache.get(coin)
        if before:
            diff = now_price - before
            arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "⏸️")
            msg += f"{coin}: ${before} → ${now_price} {arrow} ({diff:.2f})\n"
        else:
            msg += f"{coin}: ${now_price} (처음 측정)\n"
    price_cache = current
    return msg

# ──────────────────────────────────────────────────────────────
# Telegram 봇 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇이 작동 중입니다.\n/news: 최신 뉴스\n/price: 실시간 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for msg in get_translated_news():
        await update.message.reply_html(msg)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(get_price_change_message())

# ──────────────────────────────────────────────────────────────
# 스케줄러로 뉴스/시세 자동 전송
def start_scheduler(bot_app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: bot_app.bot.send_message(chat_id=CHAT_ID, text=get_price_change_message(), parse_mode="HTML"), "interval", minutes=1)
    scheduler.add_job(lambda: [bot_app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML") for msg in get_translated_news()], "interval", minutes=10)
    scheduler.start()
    logging.info("뉴스 스케줄러 시작됨.")

# ──────────────────────────────────────────────────────────────
# Flask 서버 루트
@app.route("/")
def index():
    return "✅ Telegram Coin Bot is Running!"

# ──────────────────────────────────────────────────────────────
# 비동기로 Telegram 앱 실행
async def run_telegram_bot():
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    start_scheduler(app_bot)
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    logging.info("텔레그램 봇 작동 시작됨.")

# ──────────────────────────────────────────────────────────────
# 실제 실행: Flask + Telegram 봇
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_telegram_bot())
    app.run(host="0.0.0.0", port=10000)
