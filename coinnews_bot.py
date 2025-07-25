# coinnews_bot.py
import os
import logging
import asyncio
import feedparser
import httpx
from datetime import datetime
from deep_translator import GoogleTranslator
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue
)
import pytz

# 환경 변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__)
@app.route("/")
def home():
    return "✅ 코인 뉴스봇 작동 중!"

# 한국 시간대
KST = pytz.timezone("Asia/Seoul")

# 뉴스 중복 방지
sent_news_links = set()

# 뉴스 보내기
async def fetch_and_send_news(context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    for entry in feed.entries[:5]:
        if entry.link in sent_news_links:
            continue
        title_ko = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"📰 *{title_ko}*\n{entry.link}\n🕒 {now} KST"
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        sent_news_links.add(entry.link)

# 가격 정보
previous_prices = {}
async def fetch_price(symbol):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
        return r.json().get(symbol, {}).get("usd")
    except Exception as e:
        logger.error(f"{symbol} 가격 오류: {e}")
        return None

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    symbols = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    names = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}
    updates = []
    now = datetime.now(KST).strftime("%H:%M:%S")

    for s in symbols:
        cur = await fetch_price(s)
        prev = previous_prices.get(s)
        if cur is None:
            continue
        if prev:
            diff = cur - prev
            pct = (diff / prev) * 100 if prev else 0
            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
            updates.append(f"{names[s]}: ${prev:.2f} → ${cur:.2f} {arrow} ({diff:+.2f}, {pct:+.2f}%)")
        else:
            updates.append(f"{names[s]}: ${cur:.2f} (처음 측정)")
        previous_prices[s] = cur

    if updates:
        msg = f"📈 *{now} 기준 1분간 가격 변화*\n\n" + "\n".join(updates)
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 코인 뉴스 & 가격 추적 봇입니다.\n/news 또는 /price 입력해보세요!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    class DummyContext:
        bot = context.bot
    await fetch_and_send_news(DummyContext())

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    for symbol, name in [("bitcoin", "BTC"), ("ethereum", "ETH")]:
        p = await fetch_price(symbol)
        if p:
            text += f"{name}: ${p}\n"
    await update.message.reply_text(text or "❌ 가격 정보를 가져올 수 없습니다.")

# 봇 실행 함수
def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    job_queue = application.job_queue
    job_queue.run_repeating(fetch_and_send_news, interval=300, first=5)
    job_queue.run_repeating(track_prices, interval=60, first=10)

    application.run_polling()

# Flask + 봇 병렬 실행
if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
