# coinnews_bot.py

import os
import logging
import asyncio
import feedparser
import httpx
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running!"

# 번역기
translator = GoogleTranslator(source='auto', target='ko')

# 뉴스 전송 함수
async def send_news(application):
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)

    if not feed.entries:
        logger.warning("❌ 뉴스 없음")
        return

    messages = []
    for entry in reversed(feed.entries[-5:]):
        title = translator.translate(entry.title)
        link = entry.link
        messages.append(f"📰 {title}\n{link}\n")

    text = "\n".join(messages)
    await application.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)

# 명령어 핸들러
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인봇 시작되었습니다. /news 또는 /price 를 입력해보세요!")

async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    if not feed.entries:
        await update.message.reply_text("❌ 최신 뉴스 없음")
        return

    messages = []
    for entry in reversed(feed.entries[-5:]):
        title = translator.translate(entry.title)
        link = entry.link
        messages.append(f"📰 {title}\n{link}\n")

    text = "\n".join(messages)
    await update.message.reply_text(text)

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coins = ['bitcoin', 'ethereum', 'solana', 'dogecoin', 'ripple']
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()

        msg = "💰 현재 시세 (USD):\n"
        for coin in coins:
            name = coin.capitalize()
            price = data.get(coin, {}).get("usd", "N/A")
            msg += f"{name}: ${price}\n"
        await update.message.reply_text(msg)

    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("❌ 시세 정보를 가져오는 중 오류 발생")

# 봇 실행 함수
async def run_bot():
    app_bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start_cmd))
    app_bot.add_handler(CommandHandler("news", news_cmd))
    app_bot.add_handler(CommandHandler("price", price_cmd))

    # 스케줄러 등록
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_news(app_bot)), 'interval', minutes=60)
    scheduler.start()
    logger.info("✅ Scheduler Started")

    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await app_bot.updater.idle()

# Flask + Bot 병렬 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    app.run(host="0.0.0.0", port=10000)
