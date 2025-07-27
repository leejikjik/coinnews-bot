# coinnews_bot.py

import os
import logging
import feedparser
import httpx
import threading
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Flask 앱
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ 코인 뉴스봇이 실행 중입니다!"

# 번역기
translator = GoogleTranslator(source="auto", target="ko")

# 뉴스 전송 함수
async def send_news(application):
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        if not feed.entries:
            return

        messages = []
        for entry in reversed(feed.entries[-5:]):
            title = translator.translate(entry.title)
            link = entry.link
            messages.append(f"📰 {title}\n{link}\n")

        text = "\n".join(messages)
        await application.bot.send_message(chat_id=CHAT_ID, text=text)

    except Exception as e:
        logger.error(f"자동 뉴스 전송 오류: {e}")

# 명령어 핸들러
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스봇이 시작되었습니다!\n/news, /price 를 입력해보세요.")

async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    if not feed.entries:
        await update.message.reply_text("❌ 현재 뉴스가 없습니다.")
        return

    messages = []
    for entry in reversed(feed.entries[-5:]):
        title = translator.translate(entry.title)
        link = entry.link
        messages.append(f"📰 {title}\n{link}\n")

    await update.message.reply_text("\n".join(messages))

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coins = ["bitcoin", "ethereum", "solana", "dogecoin", "ripple"]
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()

        msg = "💰 주요 코인 시세 (USD 기준):\n"
        for coin in coins:
            price = data.get(coin, {}).get("usd", "N/A")
            msg += f"{coin.capitalize()}: ${price}\n"

        await update.message.reply_text(msg)

    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("❌ 시세를 불러오는 중 오류가 발생했습니다.")

# 봇 실행 함수
def run_bot():
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()

    async def main():
        app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

        # 명령어 등록
        app_bot.add_handler(CommandHandler("start", start_cmd))
        app_bot.add_handler(CommandHandler("news", news_cmd))
        app_bot.add_handler(CommandHandler("price", price_cmd))

        # 자동 뉴스 스케줄
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda: asyncio.create_task(send_news(app_bot)), "interval", minutes=60)
        scheduler.start()

        await app_bot.initialize()
        await app_bot.start()
        await app_bot.updater.start_polling()  # ❌ 제거해야 함 (v20.3에서 제거됨)
        # 정답은 아래 run_polling() 사용!
        await app_bot.run_polling()

    loop.run_until_complete(main())

# Flask + 봇 병렬 실행
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
