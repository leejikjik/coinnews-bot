import os
import feedparser
import logging
import httpx
import asyncio
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)
from dotenv import load_dotenv

# 환경 변수 로딩
load_dotenv()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Flask 앱 (Render keep-alive용)
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ 코인 뉴스 봇 작동 중!"

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 시간 설정
KST = pytz.timezone("Asia/Seoul")
sent_news_links = set()
previous_prices = {}

# 1. 뉴스 자동 전송
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    for entry in feed.entries[:5]:
        if entry.link in sent_news_links:
            continue

        translated_title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        message = f"📰 *{translated_title}*\n{entry.link}\n🕒 {now_kst} KST"

        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        sent_news_links.add(entry.link)

# 2. 가격 가져오기
async def fetch_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        return response.json().get(symbol, {}).get("usd")
    except Exception as e:
        logger.error(f"가격 불러오기 실패: {e}")
        return None

# 3. 가격 추적
async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    symbols = ["bitcoin", "ethereum"]
    names = {"bitcoin": "BTC", "ethereum": "ETH"}
    updates = []
    now_kst = datetime.now(KST).strftime("%H:%M:%S")

    for symbol in symbols:
        current = await fetch_price(symbol)
        prev = previous_prices.get(symbol)

        if current is None:
            continue

        if prev is not None:
            diff = current - prev
            arrow = "🔻" if diff < 0 else "🔺" if diff > 0 else "➡️"
            percent = (diff / prev) * 100 if prev != 0 else 0
            updates.append(f"{names[symbol]}: ${prev:.2f} → ${current:.2f} {arrow} ({diff:+.2f}, {percent:+.2f}%)")
        else:
            updates.append(f"{names[symbol]}: ${current:.2f} (처음 측정)")

        previous_prices[symbol] = current

    if updates:
        message = f"📉 *{now_kst} 기준 1분간 가격 변화*\n\n" + "\n".join(updates)
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")

# 4. /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 코인 뉴스 및 실시간 가격 추적 봇입니다!\n/news 또는 /price 명령어를 사용해보세요!")

# 5. /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    messages = []

    for entry in feed.entries[:3]:
        translated_title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        messages.append(f"📰 *{translated_title}*\n{entry.link}\n🕒 {now_kst} KST")

    for msg in messages:
        await update.message.reply_text(msg, parse_mode="Markdown")

# 6. /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = []
    for symbol, name in [("bitcoin", "BTC"), ("ethereum", "ETH")]:
        price = await fetch_price(symbol)
        if price:
            result.append(f"{name}: ${price}")
    message = "\n".join(result) if result else "가격 정보를 불러올 수 없습니다."
    await update.message.reply_text(message)

# 7. 봇 실행
async def main():
    app_ = ApplicationBuilder().token(TOKEN).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("news", news))
    app_.add_handler(CommandHandler("price", price))

    job_queue = app_.job_queue
    job_queue.run_repeating(fetch_and_send_news, interval=300, first=10)
    job_queue.run_repeating(track_prices, interval=60, first=15)

    await app_.initialize()
    await app_.start()
    await app_.updater.start_polling()

# 8. 메인 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
