import os
import asyncio
import logging
import threading
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import httpx
import feedparser
from deep_translator import GoogleTranslator

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)

@app.route('/')
def index():
    return '✅ CoinNewsBot is running.'

# 번역 함수
def translate(text):
    try:
        return GoogleTranslator(source='auto', target='ko').translate(text)
    except:
        return text

# 뉴스 전송 함수
async def send_auto_news(app: Application):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in feed.entries[-5:]:
        translated = translate(entry.title)
        messages.append(f"📰 {translated}\n{entry.link}")
    text = "\n\n".join(messages)
    await app.bot.send_message(chat_id=CHAT_ID, text=text)

# 가격 추적 함수
previous_prices = {}

async def send_auto_price(app: Application):
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        ids = ",".join(coins)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            data = response.json()

        messages = []
        for coin in coins:
            now = data.get(coin, {}).get("usd")
            if not now:
                continue
            before = previous_prices.get(coin, now)
            change = now - before
            change_pct = (change / before) * 100 if before != 0 else 0
            messages.append(f"{coin.upper()}: ${now:.2f} ({change:+.2f}, {change_pct:+.2f}%)")
            previous_prices[coin] = now

        msg = "📉 실시간 코인가격 (1분 주기)\n\n" + "\n".join(messages)
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)

    except Exception as e:
        logger.error(f"Price fetch error: {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 및 실시간 시세 봇입니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.application)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.application)

# 봇 실행 함수
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    await application.initialize()
    await application.start()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.updater.start_polling()
    logger.info("✅ Telegram 봇이 시작되었습니다.")

    # Scheduler 실행
    scheduler = BackgroundScheduler()
    loop = asyncio.get_event_loop()

    scheduler.add_job(
        lambda: loop.call_soon_threadsafe(asyncio.create_task, send_auto_news(application)),
        trigger=IntervalTrigger(minutes=15)
    )
    scheduler.add_job(
        lambda: loop.call_soon_threadsafe(asyncio.create_task, send_auto_price(application)),
        trigger=IntervalTrigger(minutes=1)
    )

    scheduler.start()

# 스레드에서 비동기 봇 실행
def start_async_loop():
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_bot())

if __name__ == "__main__":
    threading.Thread(target=start_async_loop).start()
    app.run(host="0.0.0.0", port=10000)
