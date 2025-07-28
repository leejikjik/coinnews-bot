import os
import asyncio
import logging
import feedparser
import httpx
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    Defaults,
)

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 시간대
KST = timezone(timedelta(hours=9))

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_news()
    await update.message.reply_text(msg, disable_web_page_preview=True)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# 뉴스 파싱 및 번역
async def fetch_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        items = sorted(feed.entries[:5], key=lambda x: x.published_parsed)
        messages = []

        for entry in items:
            title = GoogleTranslator(source='en', target='ko').translate(entry.title)
            link = entry.link
            messages.append(f"📰 {title}\n{link}")

        return "\n\n".join(messages)

    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")
        return "❌ 뉴스 불러오기 실패"

# 시세 파싱 (403 우회 헤더 적용)
async def fetch_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
            "vs_currencies": "usd",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Referer": "https://www.google.com",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.error(f"[시세 오류] HTTP {resp.status_code}")
                return "❌ 시세 불러오기 실패"

            data = resp.json()

        result = []
        for name in ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]:
            price = data.get(name, {}).get("usd")
            if price is not None:
                result.append(f"{name.upper()}: ${price:,.2f}")
            else:
                result.append(f"{name.upper()}: ❌ 정보 없음")

        now = datetime.now(KST).strftime('%H:%M:%S')
        return f"📊 {now} 기준 시세:\n" + "\n.join(result)

    except Exception as e:
        logger.error(f"[시세 오류] {e}")
        return "❌ 시세 불러오기 실패"

# 자동 전송
async def send_auto_news(app: Application):
    msg = await fetch_news()
    await app.bot.send_message(chat_id=CHAT_ID, text=f"🗞️ 코인 뉴스 업데이트\n\n{msg}")

async def send_auto_price(app: Application):
    msg = await fetch_price()
    await app.bot.send_message(chat_id=CHAT_ID, text=f"💰 실시간 코인 시세\n\n{msg}")

# 스케줄러
def start_scheduler(app: Application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(app)), 'interval', hours=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(app)), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# 텔레그램 봇 실행
async def run_bot():
    defaults = Defaults(parse_mode='HTML')
    application = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    logger.info("✅ 텔레그램 봇 작동 시작")
    start_scheduler(application)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

# 병렬 실행
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(run_bot())
    Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 10000}).start()
    loop.run_forever()

if __name__ == "__main__":
    main()
