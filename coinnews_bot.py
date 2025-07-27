import os
import logging
import asyncio
import feedparser
import requests
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, JobQueue, Job
)

# 환경변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 서버 (Render keep-alive용)
app = Flask(__name__)
@app.route('/')
def home():
    return 'Bot is running!'

# 뉴스 가져오기 함수
async def get_translated_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    entries = sorted(feed.entries, key=lambda x: x.published_parsed)

    result = []
    for entry in entries[:5]:  # 최신 뉴스 5개
        title = entry.title
        link = entry.link
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        result.append(f"📰 <b>{translated}</b>\n🔗 {link}\n")

    return "\n".join(result)

# 가격 비교용 저장소
price_cache = {}

# 실시간 가격 가져오기 함수
async def get_price_diff():
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    symbols = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
    
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
    except Exception as e:
        logger.error(f"가격 정보 오류: {e}")
        return "❌ 코인 가격 정보를 가져오지 못했습니다."

    output = []
    now = datetime.now().strftime("%H:%M:%S")

    for coin in coins:
        current = data[coin]["usd"]
        previous = price_cache.get(coin)
        price_cache[coin] = current

        symbol = symbols[coin]
        if previous:
            diff = current - previous
            percent = (diff / previous) * 100
            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "⏺"
            output.append(f"{symbol}: ${current:.2f} ({arrow} {diff:.2f}, {percent:.2f}%)")
        else:
            output.append(f"{symbol}: ${current:.2f} (📊 기준값 저장됨)")

    return f"🕒 {now} 기준 가격 변동:\n" + "\n".join(output)

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇이 작동 중입니다!")

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_translated_news()
    await update.message.reply_html(text)

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_price_diff()
    await update.message.reply_text(text)

# 주기적 작업 실행 함수
async def send_news_job(context: ContextTypes.DEFAULT_TYPE):
    text = await get_translated_news()
    await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")

async def send_price_job(context: ContextTypes.DEFAULT_TYPE):
    text = await get_price_diff()
    await context.bot.send_message(chat_id=CHAT_ID, text=text)

# 봇 실행 함수
async def run_bot():
    app_telegram = ApplicationBuilder().token(TOKEN).build()

    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("news", news))
    app_telegram.add_handler(CommandHandler("price", price))

    # JobQueue로 자동 전송 등록 (1분마다 가격, 10분마다 뉴스)
    job_queue: JobQueue = app_telegram.job_queue
    job_queue.run_repeating(send_price_job, interval=60, first=5)
    job_queue.run_repeating(send_news_job, interval=600, first=10)

    await app_telegram.initialize()
    await app_telegram.start()
    await app_telegram.updater.start_polling()
    logger.info("텔레그램 봇 실행 중...")
    await app_telegram.updater.idle()

# 비동기 루프 실행 (Render용)
def start_all():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(run_bot())
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    start_all()
