import os
import logging
import httpx
import feedparser
from flask import Flask
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import asyncio

# ───── 환경 변수 ─────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ───── Flask ─────
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Coin News Bot Running"

# ───── Logger ─────
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ───── CoinGecko 시세 저장 ─────
latest_prices = {}

# ───── /start ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇 작동 중입니다.\n/news : 뉴스\n/price : 시세 확인")

# ───── /news ─────
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in feed.entries[:5][::-1]:  # 오래된 순으로
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        time_str = datetime(*entry.published_parsed[:6]).strftime('%m/%d %H:%M')
        messages.append(f"🗞 [{time_str}] {translated}\n{entry.link}")
    await update.message.reply_text("\n\n".join(messages))

# ───── /price ─────
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global latest_prices
    try:
        message = await get_price_change_message()
        await update.message.reply_text(message)
    except Exception as e:
        logging.error(f"/price error: {e}")
        await update.message.reply_text("⚠️ 시세 정보를 불러오지 못했습니다.")

# ───── 가격 추적 함수 ─────
async def get_price_change_message():
    global latest_prices
    url = "https://api.coingecko.com/api/v3/simple/price"
    symbols = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    params = {
        "ids": ",".join(symbols),
        "vs_currencies": "usd"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            raise Exception("CoinGecko API 호출 실패")

        data = response.json()

    now = datetime.now().strftime('%H:%M:%S')
    lines = [f"💰 [코인 시세] {now} 기준\n"]
    for key in symbols:
        symbol = key.capitalize()
        price = data.get(key, {}).get("usd", None)
        if price is None:
            continue

        prev = latest_prices.get(key)
        change = f" (변동 없음)"
        if prev:
            diff = price - prev
            rate = (diff / prev) * 100 if prev != 0 else 0
            arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            change = f" {arrow} {abs(diff):.2f} USD ({rate:.2f}%)"
        lines.append(f"{symbol}: ${price:.2f}{change}")

        latest_prices[key] = price

    return "\n".join(lines)

# ───── 뉴스/시세 자동 전송 ─────
async def send_auto_news(app):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:3][::-1]:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            time_str = datetime(*entry.published_parsed[:6]).strftime('%m/%d %H:%M')
            messages.append(f"🗞 [{time_str}] {translated}\n{entry.link}")
        await app.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages))
    except Exception as e:
        logging.error(f"자동 뉴스 에러: {e}")

async def send_auto_price(app):
    try:
        message = await get_price_change_message()
        await app.bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        logging.error(f"자동 시세 에러: {e}")

# ───── 스케줄러 설정 ─────
def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(app)), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(app)), 'interval', minutes=1)
    scheduler.start()
    logging.info("✅ 스케줄러 실행됨")

# ───── 텔레그램 봇 실행 ─────
def run_bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    # 스케줄러 실행
    start_scheduler(app_bot)

    app_bot.run_polling()

# ───── 병렬 실행 ─────
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    run_bot()
