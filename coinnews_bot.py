import os
import logging
import asyncio
import pytz
import feedparser
import httpx

from datetime import datetime
from deep_translator import GoogleTranslator
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수 불러오기
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 시간대
KST = pytz.timezone("Asia/Seoul")
sent_news_links = set()
previous_prices = {}

# 코인 목록
coin_list = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "dogecoin": "DOGE"
}

# Flask (Render용 Keepalive)
app = Flask(__name__)
@app.route('/')
def home():
    return "✅ 코인 뉴스 봇 정상 작동 중!"

# 뉴스 크롤링 및 전송
async def fetch_and_send_news(application):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)

    for entry in feed.entries[:5]:
        if entry.link in sent_news_links:
            continue
        sent_news_links.add(entry.link)
        translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        kst_time = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        message = f"📰 *{translated_title}*\n{entry.link}\n🕒 {kst_time} KST"
        try:
            await application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"뉴스 전송 오류: {e}")

# 가격 조회
async def fetch_price(symbol):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            return res.json()[symbol]["usd"]
    except Exception as e:
        logger.warning(f"{symbol} 가격 불러오기 실패: {e}")
        return None

# 가격 추적
async def track_price(application):
    now = datetime.now(KST).strftime('%H:%M:%S')
    messages = []
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
        try:
            await application.bot.send_message(chat_id=CHAT_ID, text=final_msg, parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"가격 전송 오류: {e}")

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/가격 추적 봇입니다.\n/news, /price 명령어 사용 가능!")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    for entry in feed.entries[:3]:
        translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        kst_time = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        msg = f"📰 *{translated_title}*\n{entry.link}\n🕒 {kst_time} KST"
        await update.message.reply_text(msg, parse_mode='Markdown')

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = []
    for symbol, name in coin_list.items():
        price = await fetch_price(symbol)
        if price:
            messages.append(f"{name}: ${price:.2f}")
    if messages:
        await update.message.reply_text("\n".join(messages))
    else:
        await update.message.reply_text("가격 정보를 불러올 수 없습니다.")

# 메인 봇 실행
async def start_bot():
    app_ = ApplicationBuilder().token(TOKEN).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("news", news))
    app_.add_handler(CommandHandler("price", price))

    job = app_.job_queue
    job.run_repeating(lambda ctx: fetch_and_send_news(app_), interval=300, first=5)
    job.run_repeating(lambda ctx: track_price(app_), interval=60, first=10)

    await app_.initialize()
    await app_.start()
    await app_.updater.start_polling()

# 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())
    app.run(host="0.0.0.0", port=10000)
