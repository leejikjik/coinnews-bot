# coinnews_bot.py

import os
import logging
import feedparser
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# 환경변수
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Flask 서버
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "Bot is running!"

# 텔레그램 핸들러 함수
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 코인 뉴스 & 시세 봇 작동 중입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price()

# 뉴스 전송
async def send_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        messages = []

        for entry in feed.entries[:5][::-1]:  # 오래된 → 최신순
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 <b>{translated}</b>\n🔗 {link}")

        if messages:
            text = "\n\n".join(messages)
            await telegram_app.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")

    except Exception as e:
        logging.error(f"뉴스 전송 오류: {e}")

# 시세 전송
async def send_price():
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        ids = ",".join(coins)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        response = requests.get(url, timeout=10)
        result = response.json()

        if not result:
            await telegram_app.bot.send_message(chat_id=CHAT_ID, text="⚠️ 시세 데이터를 불러오지 못했습니다.")
            return

        lines = [f"📈 실시간 코인 시세 (USD 기준):"]
        for coin in coins:
            name = coin.capitalize()
            price = result.get(coin, {}).get("usd", "N/A")
            lines.append(f"{name}: ${price:,}")

        text = "\n".join(lines)
        await telegram_app.bot.send_message(chat_id=CHAT_ID, text=text)

    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 텔레그램 봇 실행 함수
async def run_telegram():
    global telegram_app
    telegram_app = ApplicationBuilder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("news", news))
    telegram_app.add_handler(CommandHandler("price", price))

    await telegram_app.initialize()
    await telegram_app.start()
    logging.info("✅ Telegram Bot Started")
    await telegram_app.updater.start_polling()
    await telegram_app.updater.idle()

# 스케줄러 설정
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: telegram_app.create_task(send_news()), "interval", minutes=10)
    scheduler.add_job(lambda: telegram_app.create_task(send_price()), "interval", minutes=1)
    scheduler.start()
    logging.info("✅ Scheduler Started")

# 병렬 실행
if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()

    try:
        loop.create_task(run_telegram())
        start_scheduler()
        app_flask.run(host="0.0.0.0", port=10000)
    except Exception as e:
        logging.error(f"실행 오류: {e}")
