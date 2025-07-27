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

# 환경변수 로드
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로그 설정
logging.basicConfig(level=logging.INFO)

# Flask 앱
app = Flask(__name__)

# 비동기 HTTP 클라이언트
http = AsyncClient()

# 텔레그램 번역기
translator = GoogleTranslator(source="en", target="ko")

# 스케줄러
scheduler = AsyncIOScheduler()

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스봇 작동 중입니다.\n/news 또는 /price 명령어를 입력해보세요.")

# 뉴스 전송 함수
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

# 가격 전송 함수
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

# 스케줄러 등록
def setup_scheduler(bot_app):
    scheduler.add_job(lambda: asyncio.create_task(send_news(context=bot_app)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.create_task(send_price(context=bot_app)), "interval", minutes=3)
    scheduler.start()
    logging.info("⏱ 스케줄러 시작됨")

# Telegram 봇 실행
async def run_bot():
    app_telegram = Application.builder().token(BOT_TOKEN).build()

    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("news", send_news))
    app_telegram.add_handler(CommandHandler("price", send_price))

    await app_telegram.initialize()
    await app_telegram.start()
    await app_telegram.bot.delete_webhook(drop_pending_updates=True)
    app_telegram.create_task(app_telegram.updater.start_polling())

    setup_scheduler(app_telegram)
    logging.info("✅ Telegram 봇 작동 시작됨")

# Flask 기본 라우팅
@app.route("/")
def home():
    return "✅ Coin News Bot 서버 정상 작동 중!"

# 실행 진입점 (Render에서 반드시 실행됨)
async def main():
    asyncio.create_task(run_bot())
    app.run(host="0.0.0.0", port=10000)

# Render에서는 이 방식이 강제됨
if __name__ == "__main__":
    asyncio.run(main())
