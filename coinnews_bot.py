import os
import feedparser
import logging
import asyncio
import httpx
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue
)

# 환경변수 로딩
load_dotenv()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱 (Render Keepalive용)
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ 코인 봇 작동 중입니다!"

# 시간 설정
KST = pytz.timezone("Asia/Seoul")
sent_news_links = set()
previous_prices = {}

# 주요 코인 목록
coin_list = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "dogecoin": "DOGE"
}

# 뉴스 자동 전송
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    for entry in feed.entries[:5]:
        if entry.link in sent_news_links:
            continue
        sent_news_links.add(entry.link)

        translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        kst_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        message = f"📰 *{translated_title}*\n{entry.link}\n🕒 {kst_time} KST"
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')

# 가격 정보 가져오기
async def fetch_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            return res.json()[symbol]["usd"]
    except Exception as e:
        logger.warning(f"{symbol} 가격 요청 실패: {e}")
        return None

# 1분 가격 추적
async def track_price(context: ContextTypes.DEFAULT_TYPE):
    messages = []
    now = datetime.now(KST).strftime("%H:%M:%S")

    for symbol, name in coin_list.items():
        current = await fetch_price(symbol)
        if current is None:
            continue

        previous = previous_prices.get(symbol)
        previous_prices[symbol] = current

        if previous:
            diff = current - previous
            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
            percent = (diff / previous) * 100 if previous != 0 else 0
            messages.append(f"{name}: ${previous:.2f} → ${current:.2f} {arrow} ({diff:+.2f}, {percent:+.2f}%)")
        else:
            messages.append(f"{name}: ${current:.2f} (처음 측정)")

    if messages:
        final_msg = f"📊 *1분 가격 추적 ({now} KST)*\n\n" + "\n".join(messages)
        await context.bot.send_message(chat_id=CHAT_ID, text=final_msg, parse_mode='Markdown')

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 + 가격 추적 봇입니다.\n/news, /price 명령어를 사용해보세요!")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    messages = []
    for entry in feed.entries[:3]:
        translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        kst_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        messages.append(f"📰 *{translated_title}*\n{entry.link}\n🕒 {kst_time} KST")

    for msg in messages:
        await update.message.reply_text(msg, parse_mode='Markdown')

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = []
    for symbol, name in coin_list.items():
        price = await fetch_price(symbol)
        if price:
            messages.append(f"{name}: ${price:.2f}")
    final_msg = "\n".join(messages) if messages else "가격 정보를 불러올 수 없습니다."
    await update.message.reply_text(final_msg)

# 비동기 실행
async def main():
    app_ = ApplicationBuilder().token(TOKEN).build()
    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("news", news))
    app_.add_handler(CommandHandler("price", price))

    # 주기적 작업 등록
    app_.job_queue.run_repeating(fetch_and_send_news, interval=300, first=5)
    app_.job_queue.run_repeating(track_price, interval=60, first=10)

    await app_.initialize()
    await app_.start()
    await app_.updater.start_polling()

# 시작
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
