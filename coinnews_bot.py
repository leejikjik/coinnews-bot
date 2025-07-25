import os
import asyncio
import feedparser
import logging
from dotenv import load_dotenv
from flask import Flask
from pytz import timezone
from datetime import datetime
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# 환경변수 불러오기
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("GROUP_CHAT_ID"))

# 한국 시간대 설정
KST = timezone('Asia/Seoul')

# 텔레그램 Application 초기화
app_bot = ApplicationBuilder().token(TOKEN).build()

# 뉴스 캐시
latest_titles = []

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 코인봇입니다.\n\n- 실시간 코인 시세 (/price)\n- Cointelegraph 최신 뉴스 자동 번역 제공\n- 매 3분마다 뉴스 업데이트")

# /price 명령어
last_prices = {}

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()
    
    messages = []
    for coin in ['bitcoin', 'ethereum']:
        now_price = data[coin]['usd']
        prev_price = last_prices.get(coin, now_price)
        diff = now_price - prev_price
        change = f"+${diff:.2f}" if diff >= 0 else f"-${abs(diff):.2f}"
        messages.append(f"{coin.upper()}: ${now_price} ({change})")
        last_prices[coin] = now_price

    msg = f"📊 실시간 시세\n\n" + "\n".join(messages)
    await update.message.reply_text(msg)

# 뉴스 수집 및 번역
async def fetch_and_send_news():
    global latest_titles
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    new_items = []
    for entry in feed.entries:
        if entry.title not in latest_titles:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            published = datetime(*entry.published_parsed[:6])
            pub_time = datetime.astimezone(published.replace(tzinfo=timezone('UTC')), KST).strftime('%m월 %d일 %H:%M')
            new_items.append(f"📰 {translated}\n🕒 {pub_time}\n🔗 {entry.link}")
            latest_titles.append(entry.title)

    # 캐시 크기 제한
    latest_titles = latest_titles[-20:]

    if new_items:
        await app_bot.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(new_items))

# Flask keepalive
flask_app = Flask(__name__)
@flask_app.route("/")
def index():
    return "Bot is running"

# 스케줄러 시작 함수
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_news()), 'interval', minutes=3)
    scheduler.start()

# 메인 실행
async def main():
    # 핸들러 등록
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("price", price))

    # 봇 실행
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()

    # 뉴스 스케줄러 실행
    start_scheduler()

    # keepalive 서버 시작
    flask_app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
