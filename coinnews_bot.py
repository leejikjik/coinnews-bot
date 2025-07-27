# coinnews_bot.py

import os
import logging
import asyncio
import feedparser
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 환경변수 불러오기
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로그 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Coin News Bot is Running!"

# 텔레그램 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 및 시세 알림 봇이 작동 중입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news(context.application)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price(context.application)

# 뉴스 전송
async def send_news(application):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    messages = []
    for entry in feed.entries[:3]:
        title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        summary = GoogleTranslator(source="auto", target="ko").translate(entry.summary)
        published = entry.published
        msg = f"📰 <b>{title}</b>\n🕒 {published}\n{summary}\n🔗 {entry.link}"
        messages.append(msg)

    for msg in reversed(messages):
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

# 시세 전송
prev_prices = {}
async def send_price(application):
    try:
        coins = ['bitcoin', 'ethereum', 'ripple', 'solana', 'dogecoin']
        names = {'bitcoin': 'BTC', 'ethereum': 'ETH', 'ripple': 'XRP', 'solana': 'SOL', 'dogecoin': 'DOGE'}
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        response = requests.get(url)
        result = response.json()

        msg = "💹 <b>코인 시세 (1분 전 대비)</b>\n"
        for coin in coins:
            price = result[coin]['usd']
            prev = prev_prices.get(coin)
            diff = ""
            if prev:
                delta = price - prev
                diff = f"{'📈 +' if delta > 0 else '📉 '}{round(delta, 2)}"
            prev_prices[coin] = price
            msg += f"\n{names[coin]}: ${price} {diff}"

        msg += f"\n⏱️ {datetime.now().strftime('%H:%M:%S')}"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"가격 전송 오류: {e}")

# 스케줄러
def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_price(application), application.loop),
                      trigger='interval', minutes=1)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_news(application), application.loop),
                      trigger='interval', minutes=10)
    scheduler.start()
    logger.info("✅ Scheduler started")

# Telegram 봇 실행
async def start_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    start_scheduler(application)

# 병렬 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())  # Telegram 봇 비동기 실행
    flask_app.run(host="0.0.0.0", port=10000)
