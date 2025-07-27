import os
import asyncio
import logging
import feedparser
from flask import Flask
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from deep_translator import GoogleTranslator
from httpx import AsyncClient
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 기본설정
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
scheduler = AsyncIOScheduler()
http = AsyncClient()

# 번역기
translator = GoogleTranslator(source="en", target="ko")

# 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 봇이 작동 중입니다. /news 또는 /price를 입력해보세요.")

async def send_news(update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in reversed(feed.entries[-5:]):
            translated = translator.translate(entry.title)
            pub_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
            msg = f"📰 {translated}\n📅 {pub_time}\n🔗 {entry.link}"
            messages.append(msg)

        full_msg = "\n\n".join(messages)
        if update:
            await update.message.reply_text(full_msg)
        else:
            await context.bot.send_message(chat_id=CHAT_ID, text=full_msg)
    except Exception as e:
        logging.error(f"뉴스 전송 오류: {e}")

async def send_price(update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,ripple,solana,dogecoin&vs_currencies=usd"
        response = await http.get(url)
        data = response.json()

        msg = "💰 실시간 코인 시세 (USD)\n\n"
        for coin in ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]:
            price = data[coin]["usd"]
            msg += f"• {coin.upper()}: ${price}\n"

        if update:
            await update.message.reply_text(msg)
        else:
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"가격 전송 오류: {e}")

# 스케줄 등록
def setup_scheduler(bot_app):
    scheduler.add_job(lambda: asyncio.create_task(send_news(context=bot_app)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.create_task(send_price(context=bot_app)), "interval", minutes=3)
    scheduler.start()
    logging.info("⏱ 스케줄러 시작됨")

# Telegram 봇 실행
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", send_news))
    application.add_handler(CommandHandler("price", send_price))

    await application.initialize()
    await application.start()
    await application.bot.delete_webhook(drop_pending_updates=True)
    application.create_task(application.updater.start_polling())

    setup_scheduler(application)
    logging.info("✅ Telegram 봇 작동 시작됨")

# Flask 기본 라우팅
@app.route("/")
def index():
    return "✅ CoinNews Bot Flask 서버 실행 중!"

# 메인 실행부
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())  # 👈 이 줄이 누락되어 있으면 봇이 작동안함
    app.run(host="0.0.0.0", port=10000)
