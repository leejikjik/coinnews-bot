import os
import logging
import httpx
import asyncio
import feedparser
from flask import Flask
from pytz import timezone
from datetime import datetime
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 코인 목록 (CoinCap ID)
coins = {
    "btc-bitcoin": "비트코인",
    "eth-ethereum": "이더리움",
    "xrp-xrp": "리플",
    "sol-solana": "솔라나",
    "doge-dogecoin": "도지코인",
}
previous_prices = {}

# Flask 앱
app = Flask(__name__)

# Telegram 봇 Application
application = ApplicationBuilder().token(TOKEN).build()

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:5][::-1]:  # 오래된 뉴스부터
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source="auto", target="ko").translate(title)
            messages.append(f"📰 <b>{translated}</b>\n{link}")
        await update.message.reply_text("\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")
        await update.message.reply_text("❌ 뉴스 불러오기 실패")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(headers=headers) as client:
            lines = []
            now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"📊 {now} 기준 주요 코인 시세\n")

            for coin_id, name in coins.items():
                url = f"https://api.coincap.io/v2/assets/{coin_id}"
                r = await client.get(url)
                result = r.json()
                price = float(result["data"]["priceUsd"])
                prev = previous_prices.get(coin_id, price)
                diff = price - prev
                emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                lines.append(f"{name}: ${price:,.2f} {emoji} ({diff:+.2f})")
                previous_prices[coin_id] = price

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")
        await update.message.reply_text("❌ 시세 불러오기 실패")

# 핸들러 등록
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("news", news))
application.add_handler(CommandHandler("price", price))

# 자동 뉴스 전송
async def send_auto_news(bot: Bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:3][::-1]:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source="auto", target="ko").translate(title)
            messages.append(f"📰 <b>{translated}</b>\n{link}")
        await bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML")
        logger.info("✅ 뉴스 전송 완료")
    except Exception as e:
        logger.error(f"[뉴스 전송 오류] {e}")

# 자동 시세 전송
async def send_auto_price(bot: Bot):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(headers=headers) as client:
            lines = []
            now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"📊 {now} 기준 주요 코인 시세\n")

            for coin_id, name in coins.items():
                url = f"https://api.coincap.io/v2/assets/{coin_id}"
                r = await client.get(url)
                result = r.json()
                price = float(result["data"]["priceUsd"])
                prev = previous_prices.get(coin_id, price)
                diff = price - prev
                emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                lines.append(f"{name}: ${price:,.2f} {emoji} ({diff:+.2f})")
                previous_prices[coin_id] = price

        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# 스케줄러
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(application.bot)), 'interval', hours=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(application.bot)), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# Flask 루트 페이지
@app.route("/")
def home():
    return "코인 뉴스봇 작동 중"

# 실행
if __name__ == "__main__":
    import threading

    # Flask 백그라운드 실행
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # 스케줄러 시작
    start_scheduler()

    # Telegram 봇 실행
    application.run_polling()
