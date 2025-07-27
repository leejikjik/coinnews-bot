import os
import logging
import asyncio
import httpx
import feedparser
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 환경변수
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로그 설정
logging.basicConfig(level=logging.INFO)

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return '✅ Telegram Coin News Bot Running'

# 가격 저장소
previous_prices = {}

# 뉴스 가져오기
async def fetch_news():
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        news_items = feed.entries[:3]
        messages = []
        for entry in reversed(news_items):
            title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            messages.append(f"📰 <b>{title}</b>\n{summary}\n{entry.link}\n")
        return "\n".join(messages)
    except Exception as e:
        logging.error(f"뉴스 에러: {e}")
        return "❌ 뉴스 가져오기 실패"

# 가격 가져오기
async def fetch_price():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
        "vs_currencies": "usd"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            data = response.json()
    except Exception as e:
        logging.error(f"가격 API 에러: {e}")
        return "❌ 가격 가져오기 실패"

    result = []
    for coin_id, symbol in {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "ripple": "XRP",
        "solana": "SOL",
        "dogecoin": "DOGE"
    }.items():
        now = data.get(coin_id, {}).get("usd")
        if now is None:
            continue
        prev = previous_prices.get(coin_id)
        diff = f"{now - prev:+.2f}" if prev else "N/A"
        previous_prices[coin_id] = now
        result.append(f"{symbol}: ${now:.2f} ({diff})")

    return "📊 주요 코인 시세 (1분 단위 추적):\n" + "\n".join(result)

# 메시지 전송
async def send_message(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"메시지 전송 오류: {e}")

# 봇 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 봇 작동 중입니다!\n/news 또는 /price 명령어를 사용하세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_news()
    await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# 자동 뉴스
async def send_auto_news():
    msg = await fetch_news()
    await send_message(msg)

# 자동 시세
async def send_auto_price():
    msg = await fetch_price()
    await send_message(msg)

# 봇 + 스케줄러 실행
def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def main():
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("news", news))
        app.add_handler(CommandHandler("price", price))
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logging.info("✅ Telegram 봇 시작됨")

        # 스케줄러 등록
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda: asyncio.run(send_auto_news()), 'interval', minutes=10)
        scheduler.add_job(lambda: asyncio.run(send_auto_price()), 'interval', minutes=1)
        scheduler.start()

        await asyncio.Event().wait()

    loop.run_until_complete(main())

# Flask 서버 + 봇 동시에 실행
if __name__ == "__main__":
    import threading
    threading.Thread(target=start_bot).start()
    flask_app.run(host="0.0.0.0", port=10000)
