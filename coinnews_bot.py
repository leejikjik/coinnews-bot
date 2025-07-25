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

# .env 환경변수 불러오기
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수 로드
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Flask 앱 (Render용 keepalive)
app = Flask(__name__)

@app.route('/')
def home():
    return "코인 뉴스 봇 작동 중!"

# 뉴스 중복 방지
sent_news_links = set()

# 한국 시간
KST = pytz.timezone("Asia/Seoul")

# 1. 뉴스 전송 함수
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

# 2. 가격 추적 함수
async def fetch_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
        return res.json().get(symbol, {}).get("usd")
    except Exception as e:
        logger.error(f"{symbol} 가격 불러오기 실패: {e}")
        return None

previous_prices = {}

# 3. 1분 가격 추적
async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    symbols = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
    names = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "solana": "SOL",
        "ripple": "XRP",
        "dogecoin": "DOGE"
    }
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
            updates.append(
                f"{names[symbol]}: ${prev:.2f} → ${current:.2f} {arrow} ({diff:+.2f}, {percent:+.2f}%)"
            )
        else:
            updates.append(f"{names[symbol]}: ${current:.2f} (처음 측정)")

        previous_prices[symbol] = current

    if updates:
        message = f"📉 *{now_kst} 기준 1분간 가격 변화*\n\n" + "\n".join(updates)
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")

# 4. /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 코인 뉴스 & 가격 추적 봇입니다!\n/news 또는 /price 명령어를 입력해보세요.")

# 5. /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    class DummyContext:
        bot = context.bot
    await fetch_and_send_news(DummyContext())

# 6. /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "solana": "SOL",
        "ripple": "XRP",
        "dogecoin": "DOGE"
    }
    result = []
    for sym, name in symbols.items():
        price = await fetch_price(sym)
        if price:
            result.append(f"{name}: ${price}")
    await update.message.reply_text("\n".join(result))

# 7. Bot 실행 함수
def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    job_queue: JobQueue = application.job_queue
    job_queue.run_repeating(fetch_and_send_news, interval=300, first=5)
    job_queue.run_repeating(track_prices, interval=60, first=10)

    loop = asyncio.get_event_loop()
    loop.create_task(application.initialize())
    loop.create_task(application.start())
    loop.create_task(application.updater.start_polling())

# 8. 메인
if __name__ == "__main__":
    run_bot()
    app.run(host="0.0.0.0", port=10000)
