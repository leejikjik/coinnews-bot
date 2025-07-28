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
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 기본 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# 전역 변수
latest_titles = set()
price_cache = {}

# 번역기
translator = GoogleTranslator(source='auto', target='ko')

# ---------------------------- 기능 핸들러 ----------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 코인 뉴스 및 시세 알림 봇이 작동 중입니다.\n/start, /news, /price 명령어를 사용하세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price()

# ---------------------------- 자동 뉴스 전송 ----------------------------

async def send_auto_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        messages = []
        for entry in reversed(feed.entries[-3:]):
            if entry.title not in latest_titles:
                translated_title = translator.translate(entry.title)
                translated_summary = translator.translate(entry.summary)
                messages.append(f"📰 <b>{translated_title}</b>\n{translated_summary}\n<a href='{entry.link}'>[원문 보기]</a>")
                latest_titles.add(entry.title)
        if messages:
            for msg in messages:
                await bot_send(msg)
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")

# ---------------------------- 가격 전송 ----------------------------

async def send_auto_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise Exception(f"상태코드 {response.status_code}")
            data = response.json()
        coins = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'DOGEUSDT']
        msg = "<b>📊 실시간 코인 시세 (Binance 기준)</b>\n"
        for coin in coins:
            price = next((item for item in data if item['symbol'] == coin), None)
            if not price:
                continue
            now = float(price['price'])
            name = coin.replace("USDT", "")
            old = price_cache.get(coin, now)
            diff = now - old
            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            msg += f"{name}: ${now:.2f} {arrow} ({diff:+.2f})\n"
            price_cache[coin] = now
        await bot_send(msg)
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# ---------------------------- 메시지 전송 ----------------------------

async def bot_send(text):
    try:
        await application.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML", disable_web_page_preview=False)
    except Exception as e:
        logger.error(f"[메시지 전송 오류] {e}")

# ---------------------------- 스케줄러 ----------------------------

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), 'interval', minutes=5)
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# ---------------------------- Flask (Render Keepalive 용) ----------------------------

@app.route("/")
def index():
    return "코인 뉴스 텔레그램 봇 실행 중."

# ---------------------------- 봇 실행 ----------------------------

async def run_bot():
    global application
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    logger.info("✅ 텔레그램 봇 작동 시작")
    await application.run_polling()

# ---------------------------- 메인 ----------------------------

if __name__ == "__main__":
    start_scheduler()
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    app.run(host="0.0.0.0", port=10000)
