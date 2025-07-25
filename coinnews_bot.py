import os
import threading
import asyncio
from datetime import datetime
import pytz
import logging
import httpx
import feedparser
from deep_translator import GoogleTranslator
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 시간대
KST = pytz.timezone("Asia/Seoul")

# Flask (Render용)
app = Flask(__name__)
@app.route('/')
def index():
    return "✅ 코인 뉴스봇 작동 중입니다!"

# 전송된 뉴스 링크 추적
sent_news_links = set()

# 이전 가격 저장
previous_prices = {}

# 코인 가격 가져오기
async def fetch_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        return response.json().get(symbol, {}).get("usd")
    except Exception as e:
        logger.error(f"{symbol} 가격 불러오기 실패: {e}")
        return None

# 뉴스 전송
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    for entry in reversed(feed.entries[:5]):
        if entry.link in sent_news_links:
            continue
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        message = f"📰 *{translated}*\n{entry.link}\n🕒 {now} KST"
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        sent_news_links.add(entry.link)

# 가격 추적
async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    symbols = ["bitcoin", "ethereum"]
    names = {"bitcoin": "BTC", "ethereum": "ETH"}
    now = datetime.now(KST).strftime("%H:%M:%S")
    updates = []

    for symbol in symbols:
        current = await fetch_price(symbol)
        prev = previous_prices.get(symbol)
        if current is None:
            continue
        if prev:
            diff = current - prev
            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
            pct = (diff / prev) * 100 if prev != 0 else 0
            updates.append(f"{names[symbol]}: ${prev:.2f} → ${current:.2f} {arrow} ({diff:+.2f}, {pct:+.2f}%)")
        else:
            updates.append(f"{names[symbol]}: ${current:.2f} (처음 측정)")
        previous_prices[symbol] = current

    if updates:
        msg = f"📉 *{now} 기준 1분 가격 변화*\n\n" + "\n".join(updates)
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 코인 뉴스 및 실시간 가격 추적 봇입니다.\n/news 또는 /price 사용해보세요!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    class DummyContext:
        bot = context.bot
    await fetch_and_send_news(DummyContext())

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = []
    for symbol, name in [("bitcoin", "BTC"), ("ethereum", "ETH")]:
        price = await fetch_price(symbol)
        if price:
            result.append(f"{name}: ${price:.2f}")
    await update.message.reply_text("\n".join(result))

# 봇 실행
def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 잡 큐 등록
    job_queue: JobQueue = application.job_queue
    job_queue.run_repeating(fetch_and_send_news, interval=300, first=5)
    job_queue.run_repeating(track_prices, interval=60, first=10)

    # 비동기 루프 시작
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())
    loop.run_until_complete(application.updater.start_polling())
    loop.run_forever()

# 메인
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
