import os
import asyncio
import logging
import feedparser
from flask import Flask
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
)
from apscheduler.schedulers.background import BackgroundScheduler
import httpx
from datetime import datetime, timedelta

# 환경 변수 로드
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱 설정 (Render keep-alive 용도)
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "CoinNews Bot is running!"

# Cointelegraph 뉴스 가져오기 및 번역
async def fetch_and_send_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        entries = feed.entries[::-1]  # 오래된 순으로 정렬
        async with httpx.AsyncClient() as client:
            for entry in entries[-3:]:
                translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
                translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
                message = f"📰 <b>{translated_title}</b>\n{translated_summary}\n<a href='{entry.link}'>🔗 원문 보기</a>"
                await send_message(message)
    except Exception as e:
        logger.error(f"뉴스 전송 중 오류 발생: {e}")

# 시세 정보
price_cache = {}

async def fetch_price(coin_id):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get(coin_id, {}).get("usd", None)
    except Exception as e:
        logger.warning(f"{coin_id} 가격 가져오기 실패: {e}")
        return None

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    global price_cache
    coins = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "ripple": "XRP",
        "solana": "SOL",
        "dogecoin": "DOGE"
    }
    messages = ["📊 <b>실시간 코인 시세 (1분 간격)</b>"]
    for cid, name in coins.items():
        now = await fetch_price(cid)
        old = price_cache.get(cid)
        price_cache[cid] = now
        if now is None:
            messages.append(f"{name}: ❌ 불러오기 실패")
        elif old is None:
            messages.append(f"{name}: ${now} (이전값 없음)")
        else:
            diff = now - old
            percent = (diff / old) * 100 if old != 0 else 0
            arrow = "📈" if diff > 0 else "📉" if diff < 0 else "➖"
            messages.append(f"{name}: ${now:.2f} ({diff:+.2f}, {percent:+.2f}%) {arrow}")
    await send_message("\n".join(messages))

# 메시지 전송 함수
async def send_message(text: str):
    try:
        await app_bot.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML", disable_web_page_preview=False)
    except Exception as e:
        logger.error(f"메시지 전송 오류: {e}")

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 & 시세 알림 봇이 작동 중입니다!")

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await fetch_and_send_news()

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await track_prices(context)

# 봇 실행 함수
async def telegram_main():
    global app_bot
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    # 1분마다 시세 전송 작업 등록
    job_queue = app_bot.job_queue
    job_queue.run_repeating(track_prices, interval=60, first=10)

    await app_bot.initialize()
    await app_bot.start()
    logger.info("텔레그램 봇 시작됨.")
    await app_bot.updater.start_polling()
    await app_bot.updater.wait_until_closed()

# 스케줄러 시작
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_news()), 'interval', minutes=5)
    scheduler.start()
    logger.info("뉴스 스케줄러 시작됨.")

# 서버 시작
if __name__ == "__main__":
    start_scheduler()
    loop = asyncio.get_event_loop()
    loop.create_task(telegram_main())
    flask_app.run(host="0.0.0.0", port=10000)
