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
    JobQueue
)

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Flask
app = Flask(__name__)
@app.route("/")
def home():
    return "✅ 코인 뉴스 봇 작동 중!"

# 한국 시간대
KST = pytz.timezone("Asia/Seoul")
sent_links = set()
previous_prices = {}

# 뉴스 전송
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    for entry in feed.entries[:5]:
        if entry.link in sent_links:
            continue
        title_ko = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"📰 *{title_ko}*\n{entry.link}\n🕒 {now_kst} KST"
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        sent_links.add(entry.link)

# 가격 추적
async def fetch_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
        return res.json().get(symbol, {}).get("usd")
    except Exception as e:
        logger.error(f"가격 불러오기 실패: {e}")
        return None

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    symbols = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    names = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "ripple": "XRP",
        "solana": "SOL",
        "dogecoin": "DOGE"
    }
    now = datetime.now(KST).strftime("%H:%M:%S")
    updates = []

    for symbol in symbols:
        current = await fetch_price(symbol)
        prev = previous_prices.get(symbol)

        if current is None:
            continue

        if prev:
            diff = current - prev
            arrow = "🔻" if diff < 0 else "🔺" if diff > 0 else "➡️"
            percent = (diff / prev) * 100 if prev else 0
            updates.append(
                f"{names[symbol]}: ${prev:.2f} → ${current:.2f} {arrow} ({diff:+.2f}, {percent:+.2f}%)"
            )
        else:
            updates.append(f"{names[symbol]}: ${current:.2f} (처음 측정)")

        previous_prices[symbol] = current

    if updates:
        message = f"📉 *{now} 기준 1분간 가격 변화*\n\n" + "\n".join(updates)
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 코인 뉴스 & 가격 봇입니다!\n`/news`, `/price` 사용해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    class DummyContext:
        bot = context.bot
    await fetch_and_send_news(DummyContext())

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = [("bitcoin", "BTC"), ("ethereum", "ETH"), ("ripple", "XRP"), ("solana", "SOL"), ("dogecoin", "DOGE")]
    updates = []
    for sym, name in symbols:
        current = await fetch_price(sym)
        if current:
            updates.append(f"{name}: ${current:.2f}")
    await update.message.reply_text("\n".join(updates))

# 비동기 실행
async def main():
    app_ = ApplicationBuilder().token(TOKEN).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("news", news))
    app_.add_handler(CommandHandler("price", price))

    job_queue: JobQueue = app_.job_queue
    job_queue.run_repeating(fetch_and_send_news, interval=300, first=10)
    job_queue.run_repeating(track_prices, interval=60, first=15)

    await app_.initialize()
    await app_.start()
    await app_.updater.start_polling()
    await app_.updater.idle()

# Flask + 봇 동시 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
