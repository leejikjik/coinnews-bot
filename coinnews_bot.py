import os
import asyncio
import logging
import feedparser
import requests
from flask import Flask
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, AIORateLimiter
)

# 환경변수
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 기본 설정
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
scheduler = BackgroundScheduler()
KST = timezone(timedelta(hours=9))

# 코인 리스트
COINS = ['bitcoin', 'ethereum', 'ripple', 'solana', 'dogecoin']
COIN_SYMBOLS = {'bitcoin': 'BTC', 'ethereum': 'ETH', 'ripple': 'XRP', 'solana': 'SOL', 'dogecoin': 'DOGE'}
COIN_PREV_PRICES = {}

# 뉴스 파싱
def fetch_and_translate_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    translated_news = []

    for entry in reversed(feed.entries[-3:]):
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime('%Y-%m-%d %H:%M')
        title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        link = entry.link
        translated_news.append(f"📰 {published}\n{title}\n🔗 {link}\n")

    return "\n".join(translated_news)

# 가격 정보
def fetch_prices():
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(COINS)}&vs_currencies=usd"
    try:
        res = requests.get(url, timeout=10)
        result = res.json()
        return result
    except Exception as e:
        logging.error(f"가격 호출 오류: {e}")
        return {}

# 가격 메시지 생성
def build_price_message():
    prices = fetch_prices()
    if not prices:
        return "가격 정보를 불러올 수 없습니다."

    msg = f"📊 실시간 코인 시세 (1분 전 대비)\n"
    for coin in COINS:
        symbol = COIN_SYMBOLS[coin]
        current_price = prices.get(coin, {}).get("usd")
        prev_price = COIN_PREV_PRICES.get(coin)

        if current_price is None:
            msg += f"{symbol}: 가격 불러오기 실패\n"
            continue

        change = ""
        if prev_price:
            diff = current_price - prev_price
            pct = (diff / prev_price) * 100
            arrow = "🔼" if diff > 0 else "🔽" if diff < 0 else "⏺️"
            change = f"{arrow} {diff:.2f}$ ({pct:+.2f}%)"

        msg += f"{symbol}: {current_price:.2f}$ {change}\n"
        COIN_PREV_PRICES[coin] = current_price

    return msg

# 봇 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 및 시세봇 작동 중입니다!\n/news: 최신 뉴스\n/price: 실시간 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = fetch_and_translate_news()
    await update.message.reply_text(message)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = build_price_message()
    await update.message.reply_text(message)

# Flask Keepalive
@app.route('/')
def index():
    return "CoinNews Bot is alive!"

# 텔레그램 앱 실행
async def telegram_main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .rate_limiter(AIORateLimiter())
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logging.info("🤖 텔레그램 봇 시작됨")

# 스케줄러 작업
def scheduled_tasks():
    from telegram import Bot
    bot = Bot(BOT_TOKEN)

    try:
        news = fetch_and_translate_news()
        price = build_price_message()
        bot.send_message(chat_id=CHAT_ID, text=f"🕒 {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} 기준\n\n{price}\n\n{news}")
    except Exception as e:
        logging.error(f"자동 전송 오류: {e}")

# 메인 실행
def start_all():
    loop = asyncio.get_event_loop()
    loop.create_task(telegram_main())
    scheduler.add_job(scheduled_tasks, 'interval', minutes=1)
    scheduler.start()
    app.run(host='0.0.0.0', port=10000)

if __name__ == '__main__':
    start_all()
