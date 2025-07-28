import os
import asyncio
import logging
import feedparser
from flask import Flask
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from httpx import AsyncClient
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 한국 시간대
KST = timezone("Asia/Seoul")

# Flask 앱 (Render용 keepalive)
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ CoinNewsBot is running!"

# 전역 변수
tg_app = None  # application 객체 저장용

# 뉴스 가져오기 및 번역
async def fetch_and_translate_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        if not feed.entries:
            return "❗ 뉴스 로딩 실패"

        sorted_entries = sorted(feed.entries, key=lambda x: x.published_parsed)
        messages = []

        for entry in sorted_entries[:5]:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 <b>{translated}</b>\n🔗 {link}")

        return "\n\n".join(messages)
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")
        return "❗ 뉴스 가져오기 중 오류 발생"

# 시세 가져오기
async def fetch_price_summary():
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        async with AsyncClient() as client:
            resp = await client.get(url)
            data = resp.json()

        watchlist = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        result = []

        for item in data:
            if item["symbol"] in watchlist:
                coin = item["symbol"].replace("USDT", "")
                price = float(item["price"])
                result.append(f"{coin}: ${price:,.2f}")

        if not result:
            return "❗ 시세 정보를 찾을 수 없습니다."

        return f"📊 {now} 기준 시세:\n" + "\n".join(result)
    except Exception as e:
        logger.error(f"[시세 오류] {e}")
        return "❗ 시세 가져오기 오류 발생"

# 자동 뉴스 전송
async def send_auto_news():
    if tg_app:
        try:
            message = await fetch_and_translate_news()
            await tg_app.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"[뉴스 전송 오류] {e}")

# 자동 시세 전송
async def send_auto_price():
    if tg_app:
        try:
            message = await fetch_price_summary()
            await tg_app.bot.send_message(chat_id=CHAT_ID, text=message)
        except Exception as e:
            logger.error(f"[시세 전송 오류] {e}")

# 명령어 핸들러들
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 봇입니다!\n/start\n/news\n/price 사용 가능!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_and_translate_news()
    await update.message.reply_text(msg, parse_mode="HTML")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price_summary()
    await update.message.reply_text(msg)

# 스케줄러
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# 실행 함수
def main():
    global tg_app
    tg_app = ApplicationBuilder().token(TOKEN).build()

    # 명령어 등록
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("news", news))
    tg_app.add_handler(CommandHandler("price", price))

    # 스케줄러 시작
    start_scheduler()

    # 비동기 실행
    loop = asyncio.get_event_loop()
    loop.create_task(tg_app.run_polling())

    # Flask 서버 실행
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    main()
