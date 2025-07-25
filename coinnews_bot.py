import os
import asyncio
import logging
from datetime import datetime
import pytz

import feedparser
import httpx
from deep_translator import GoogleTranslator
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
)
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱 (Render용 keep-alive)
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ 코인 뉴스 & 가격 추적 봇 실행 중"

# 한국 시간
KST = pytz.timezone("Asia/Seoul")

# 전송한 뉴스 링크 저장
sent_links = set()

# 이전 가격 저장
previous_prices = {}

# 추적할 코인
coin_map = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "dogecoin": "DOGE"
}

# 1. 뉴스 가져오기
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    for entry in reversed(feed.entries[:5]):  # 오래된 순
        if entry.link in sent_links:
            continue

        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        message = f"\ud83d\udcf0 *{translated}*\n{entry.link}\n\ud83d\udd52 {now_kst} KST"

        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        sent_links.add(entry.link)

# 2. 가격 정보 가져오기
async def fetch_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
        return res.json().get(symbol, {}).get("usd")
    except Exception as e:
        logger.error(f"가격 가져오기 실패: {symbol} - {e}")
        return None

# 3. 가격 추적
async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KST).strftime("%H:%M:%S")
    updates = []

    for symbol, name in coin_map.items():
        current = await fetch_price(symbol)
        prev = previous_prices.get(symbol)

        if current is None:
            continue

        if prev is not None:
            diff = current - prev
            arrow = "🔻" if diff < 0 else "🔺" if diff > 0 else "➡️"
            percent = (diff / prev) * 100 if prev != 0 else 0
            updates.append(
                f"{name}: ${prev:.2f} → ${current:.2f} {arrow} ({diff:+.2f}, {percent:+.2f}%)"
            )
        else:
            updates.append(f"{name}: ${current:.2f} (처음 측정)")

        previous_prices[symbol] = current

    if updates:
        msg = f"\ud83d\udcc9 *{now} 기준 1분 가격 변화*\n\n" + "\n".join(updates)
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")

# 4. /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\ud83e\udde0 코인 뉴스 & 실시간 가격 추적 봇입니다!\n/news 또는 /price 명령어를 사용해보세요.")

# 5. /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    class DummyContext: bot = context.bot
    await fetch_and_send_news(DummyContext())

# 6. /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = []
    for symbol, name in coin_map.items():
        current = await fetch_price(symbol)
        if current:
            messages.append(f"{name}: ${current:.2f}")
    await update.message.reply_text("\n".join(messages))

# 7. Bot 실행 함수
def run():
    app_builder = ApplicationBuilder().token(TOKEN)
    app = app_builder.build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))

    # Job 등록
    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(fetch_and_send_news, interval=300, first=5)
    job_queue.run_repeating(track_prices, interval=60, first=10)

    loop = asyncio.get_event_loop()
    loop.create_task(app.initialize())
    loop.create_task(app.start())
    loop.create_task(app.updater.start_polling())

# 8. 메인
if __name__ == "__main__":
    run()
    app.run(host="0.0.0.0", port=10000)
