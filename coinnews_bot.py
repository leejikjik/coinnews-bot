# coinnews_bot.py

import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 환경변수 (Render 환경변수 UI에 설정)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Telegram Application 전역 선언
application: Application = Application.builder().token(BOT_TOKEN).build()

# 한국 시간대
KST = timezone(timedelta(hours=9))

# 명령어 핸들러 함수
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 및 실시간 시세 봇입니다.\n/start - 안내\n/news - 뉴스 보기\n/price - 실시간 시세 보기")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = await fetch_news()
    for msg in messages:
        await update.message.reply_text(msg)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = await fetch_prices()
    for msg in messages:
        await update.message.reply_text(msg)

# 뉴스 크롤링 및 번역
async def fetch_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    messages = []
    for entry in feed.entries[:5][::-1]:  # 오래된 순으로 출력
        published_kst = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 {translated}\n{entry.link}\n🕒 {published_kst.strftime('%Y-%m-%d %H:%M')}"
        messages.append(msg)
    return messages

# 실시간 시세 조회
async def fetch_prices():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,dogecoin,ripple&vs_currencies=krw"
    now = datetime.now(KST)
    result = []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data_now = response.json()

        # 저장된 이전 가격이 없으면 초기화
        if not hasattr(fetch_prices, "prev_data"):
            fetch_prices.prev_data = data_now
            return ["⏳ 1분 후 시세 변화량을 알려드립니다."]

        prev_data = fetch_prices.prev_data
        fetch_prices.prev_data = data_now

        for coin in data_now:
            price_now = data_now[coin]["krw"]
            price_prev = prev_data[coin]["krw"]
            diff = price_now - price_prev
            percent = (diff / price_prev) * 100
            sign = "📈" if diff > 0 else "📉" if diff < 0 else "⏸️"
            result.append(
                f"{sign} {coin.upper()} 현재가: {price_now:,.0f}원\n1분 전 대비: {diff:+,.0f}원 ({percent:+.2f}%)"
            )

        result.insert(0, f"🕒 {now.strftime('%Y-%m-%d %H:%M:%S')} 기준 코인 시세 📊")
        return result

    except Exception as e:
        return [f"⚠️ 가격 조회 오류: {e}"]

# 자동 뉴스 전송
async def send_auto_news():
    messages = await fetch_news()
    for msg in messages:
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)

# 자동 시세 전송
async def send_auto_price():
    messages = await fetch_prices()
    for msg in messages:
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)

# Flask 엔드포인트 (keepalive 용)
@app.route('/')
def home():
    return '✅ Coin Bot Running'

# 스케줄러 실행 함수
def start_scheduler():
    scheduler = BackgroundScheduler(timezone=KST)
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), IntervalTrigger(minutes=15))
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), IntervalTrigger(minutes=1))
    scheduler.start()

# Telegram 봇 실행 함수
async def run_bot():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    await application.initialize()
    await application.start()
    logging.info("✅ Telegram 봇이 시작되었습니다.")

if __name__ == '__main__':
    start_scheduler()
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    app.run(host="0.0.0.0", port=10000)
