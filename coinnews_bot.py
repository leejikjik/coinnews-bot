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

# 로그 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 1. /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세",
        )

# 2. /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        if not feed.entries:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 뉴스 로드 실패")
            return
        messages = []
        for entry in feed.entries[:5][::-1]:  # 오래된 뉴스부터 출력
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n<a href=\"{entry.link}\">원문 보기</a>")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="\n\n".join(messages), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"[뉴스 오류] {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 뉴스 수신 오류")

# 3. /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price(context)

# 4. 코인 시세 전송 함수
previous_prices = {}

async def send_price(context: ContextTypes.DEFAULT_TYPE):
    global previous_prices
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
            "vs_currencies": "usd",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            if response.status_code == 403:
                raise Exception("CoinGecko 차단됨 (403)")
            data = response.json()

        message = "<b>📈 실시간 코인 시세 (USD)</b>\n"
        for coin, info in data.items():
            current = info["usd"]
            prev = previous_prices.get(coin, current)
            diff = current - prev
            emoji = "🔺" if diff > 0 else ("🔻" if diff < 0 else "⏺")
            message += f"{coin.upper():<8} : ${current:.2f} {emoji} ({diff:+.2f})\n"
            previous_prices[coin] = current

        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML")
    except Exception as e:
        logging.error(f"[시세 오류] {e}")
        await context.bot.send_message(chat_id=CHAT_ID, text="❌ 시세 데이터를 가져올 수 없습니다.")

# 5. 스케줄러 시작
def start_scheduler(application):
    scheduler.add_job(lambda: asyncio.run(send_price(application)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(news_job(application)), "interval", hours=1)
    scheduler.start()
    logging.info("✅ 스케줄러 실행됨")

async def news_job(application):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:3][::-1]:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n<a href=\"{entry.link}\">원문 보기</a>")
        await application.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"[뉴스 스케줄러 오류] {e}")

# 6. Flask 엔드포인트
@app.route("/")
def index():
    return "✅ Flask 서버 작동 중"

# 7. Telegram Bot 실행
async def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    start_scheduler(application)

    logging.info("✅ 텔레그램 봇 작동 시작")
    await application.run_polling()

if __name__ == "__main__":
    import threading

    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(run_bot())
    
