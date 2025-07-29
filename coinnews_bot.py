import os
import logging
import asyncio
import threading
from flask import Flask
from datetime import datetime
from pytz import timezone
import httpx
import feedparser
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

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
    return "✅ Coin Bot is running."

# CoinCap 시세 ID 매핑
coins = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인"
}
previous_prices = {}

# 자동 뉴스 전송
async def send_auto_news(bot: Bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = sorted(feed.entries, key=lambda x: x.published_parsed)[-5:]

        messages = []
        for entry in entries:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source="auto", target="ko").translate(title)
            messages.append(f"📰 <b>{translated}</b>\n<a href='{link}'>원문 보기</a>")

        await bot.send_message(
            chat_id=CHAT_ID,
            text="\n\n".join(messages),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")

# 자동 시세 전송
async def send_auto_price(bot: Bot):
    try:
        async with httpx.AsyncClient() as client:
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

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 봇입니다!\n/news : 최신 뉴스\n/price : 실시간 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.bot)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.bot)

# 스케줄러
def start_scheduler(bot: Bot):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(bot)), "interval", hours=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(bot)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# Flask 병렬 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# 메인 실행
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    start_scheduler(application.bot)
    application.run_polling()
