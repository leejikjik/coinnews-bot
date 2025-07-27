import os
import asyncio
import logging
import feedparser
import httpx
from datetime import datetime
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
import threading

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 상수
NEWS_URL = "https://cointelegraph.com/rss"
COINS = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
latest_prices = {}

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Telegram Coin Bot Running"

# 텔레그램 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇입니다.\n/news: 뉴스 확인\n/price: 현재 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse(NEWS_URL)
        entries = feed.entries[:5][::-1]
        msg = ""
        for entry in entries:
            title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            msg += f"<b>{title}</b>\n📝 {summary}\n🔗 {entry.link}\n\n"
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text("❌ 뉴스 로딩 실패")
        logger.warning(f"[뉴스 오류] {e}")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not latest_prices:
        await update.message.reply_text("⏳ 시세 로딩 중입니다.")
        return
    msg = "📊 현재 코인 시세 (1분 전 대비)\n"
    for coin in COINS:
        now = latest_prices[coin]["now"]
        before = latest_prices[coin]["before"]
        diff = now - before
        pct = (diff / before * 100) if before else 0
        msg += f"{coin.upper()} ➡️ ${now:.2f} ({'🔺' if diff > 0 else '🔻'} {abs(pct):.2f}%)\n"
    await update.message.reply_text(msg)

# 시세 수집
async def fetch_prices():
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(COINS)}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()
        for coin in COINS:
            price = data[coin]["usd"]
            if coin not in latest_prices:
                latest_prices[coin] = {"before": price, "now": price}
            else:
                latest_prices[coin]["before"] = latest_prices[coin]["now"]
                latest_prices[coin]["now"] = price
        logger.info("✅ 시세 갱신 완료")
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# 자동 뉴스 전송
async def send_auto_news(app: Application):
    try:
        feed = feedparser.parse(NEWS_URL)
        entries = feed.entries[:3][::-1]
        msg = ""
        for entry in entries:
            title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            msg += f"<b>{title}</b>\n📝 {summary}\n🔗 {entry.link}\n\n"
        await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[자동 뉴스 오류] {e}")

# 자동 시세 전송
async def send_auto_price(app: Application):
    if not latest_prices:
        return
    try:
        msg = "📈 자동 시세 알림\n"
        for coin in COINS:
            now = latest_prices[coin]["now"]
            before = latest_prices[coin]["before"]
            diff = now - before
            pct = (diff / before * 100) if before else 0
            msg += f"{coin.upper()} ➡️ ${now:.2f} ({'🔺' if diff > 0 else '🔻'} {abs(pct):.2f}%)\n"
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"[자동 시세 오류] {e}")

# 스케줄러
def start_scheduler(app: Application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(fetch_prices()), "interval", seconds=60)
    scheduler.add_job(lambda: asyncio.run(send_auto_news(app)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(app)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# 봇 실행
async def run_bot():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    await app_bot.initialize()
    await app_bot.start()
    start_scheduler(app_bot)
    logger.info("✅ 텔레그램 봇 작동 시작")
    await app_bot.updater.start_polling()
    await app_bot.updater.idle()

# 병렬 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    # Flask는 메인 쓰레드에서 실행
    threading.Thread(target=lambda: asyncio.run(run_bot())).start()
    run_flask()
