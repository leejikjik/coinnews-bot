import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Flask 앱 생성
app = Flask(__name__)

# 스케줄러 생성
scheduler = BackgroundScheduler()

# 한국 시간대 기준
KST = datetime.now().astimezone().tzinfo

# 텔레그램 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news()

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price()

# Cointelegraph 뉴스 크롤링 및 전송
async def send_auto_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        if not feed.entries:
            raise Exception("피드 항목이 없습니다.")

        sorted_entries = sorted(feed.entries, key=lambda x: x.published_parsed)
        messages = []

        for entry in sorted_entries[-5:]:
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime('%Y-%m-%d %H:%M')
            msg = f"📰 <b>{translated_title}</b>\n🕒 {published}\n\n{translated_summary}\n<a href='{entry.link}'>[원문 보기]</a>"
            messages.append(msg)

        async with httpx.AsyncClient() as client:
            for msg in messages:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
                )

    except Exception as e:
        logging.error(f"[뉴스 오류] {e}")

# 실시간 시세 전송
async def send_auto_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        coins = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT",
            "XRP": "XRPUSDT",
            "SOL": "SOLUSDT",
            "DOGE": "DOGEUSDT",
        }

        async with httpx.AsyncClient(timeout=5) as client:
            responses = await asyncio.gather(
                *[client.get(f"{url}?symbol={symbol}") for symbol in coins.values()],
                return_exceptions=True
            )

        now = datetime.now(KST).strftime('%H:%M:%S')
        lines = [f"📈 <b>{now} 기준 실시간 코인 시세</b>"]

        for coin, response in zip(coins.keys(), responses):
            if isinstance(response, Exception) or response.status_code != 200:
                lines.append(f"{coin}: ❌ 시세 조회 실패")
                continue
            data = response.json()
            price = float(data['price'])
            lines.append(f"{coin}: ${price:,.2f}")

        msg = '\n'.join(lines)
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            )

    except Exception as e:
        logging.error(f"[시세 오류] {e}")

# 스케줄러 작업
def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), 'interval', minutes=30, id='news_job', replace_existing=True)
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), 'interval', minutes=1, id='price_job', replace_existing=True)
    scheduler.start()
    logging.info("✅ 스케줄러 시작됨")

# Flask용 기본 라우팅
@app.route("/", methods=["GET"])
def index():
    return "✅ Coin Bot is Running!"

# 텔레그램 봇 실행
async def run_telegram():
    app_builder = ApplicationBuilder().token(BOT_TOKEN)
    application = app_builder.build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    await application.initialize()
    await application.start()
    logging.info("🤖 텔레그램 봇 시작됨")
    await application.updater.start_polling()
    await application.updater.idle()

# 메인 실행
if __name__ == "__main__":
    start_scheduler()
    loop = asyncio.get_event_loop()
    loop.create_task(run_telegram())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
