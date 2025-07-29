import os
import logging
import asyncio
from datetime import datetime
from pytz import timezone
import httpx
import feedparser
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 서버
app = Flask(__name__)
@app.route("/")
def index():
    return "✅ Bot is running."

# 가격 추적용 캐시
previous_prices = {}

# 시세 전송
async def send_auto_price(bot: Bot):
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        coins = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
        names = {
            "BTCUSDT": "비트코인",
            "ETHUSDT": "이더리움",
            "XRPUSDT": "리플",
            "SOLUSDT": "솔라나",
            "DOGEUSDT": "도지코인",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()

        now = datetime.now(timezone("Asia/Seoul")).strftime("%p %I:%M:%S").replace("AM", "오전").replace("PM", "오후")
        lines = [f"📉 {now} 기준 실시간 코인 시세\n"]

        for coin in coins:
            price = float(next((i["price"] for i in data if i["symbol"] == coin), 0))
            before = previous_prices.get(coin, price)
            diff = price - before
            rate = (diff / before) * 100 if before else 0
            emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "⏸️"
            lines.append(f"{names[coin]}: ${price:.2f} {emoji} ({diff:+.2f}, {rate:+.2f}%)")
            previous_prices[coin] = price

        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# 뉴스 전송
async def send_auto_news(bot: Bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = sorted(feed.entries, key=lambda x: x.published_parsed)[-5:]
        messages = []

        for entry in entries:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source="auto", target="ko").translate(title)
            messages.append(f"🗞 <b>{translated}</b>\n<a href='{link}'>원문 보기</a>")

        await bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")

# 봇 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 봇입니다.\n/news : 최신 뉴스\n/price : 실시간 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.bot)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.bot)

# 스케줄러
def start_scheduler(bot: Bot):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(bot)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(bot)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# 메인
if __name__ == "__main__":
    from threading import Thread
    from telegram.ext import Application

    # Flask 서버 실행
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()

    # Telegram Bot 실행
    async def run():
        app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
        app_bot.add_handler(CommandHandler("start", start))
        app_bot.add_handler(CommandHandler("news", news))
        app_bot.add_handler(CommandHandler("price", price))
        start_scheduler(app_bot.bot)
        await app_bot.initialize()
        await app_bot.start()
        await app_bot.updater.start_polling()
        await app_bot.updater.idle()

    asyncio.run(run())
