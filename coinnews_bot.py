import os
import logging
import threading
import asyncio
import feedparser
import httpx
from flask import Flask
from pytz import timezone
from datetime import datetime
from deep_translator import GoogleTranslator
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)
@app.route("/")
def index():
    return "✅ Coin Bot is running."

# 이전 가격 저장용
previous_prices = {}

# CoinCap 기반 실시간 시세
async def send_auto_price(bot: Bot):
    try:
        coins = {
            "bitcoin": "비트코인",
            "ethereum": "이더리움",
            "ripple": "리플",
            "solana": "솔라나",
            "dogecoin": "도지코인"
        }
        lines = []
        now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"📊 {now} 기준 시세:\n")

        async with httpx.AsyncClient() as client:
            for symbol, name in coins.items():
                url = f"https://api.coincap.io/v2/assets/{symbol}"
                resp = await client.get(url)
                data = resp.json()

                if "data" not in data:
                    raise ValueError("시세 데이터 없음")

                price = float(data["data"]["priceUsd"])
                old_price = previous_prices.get(symbol, price)
                diff = price - old_price
                emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                lines.append(f"{name}: {price:,.2f} USD {emoji} ({diff:+.2f})")
                previous_prices[symbol] = price

        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")
        await bot.send_message(chat_id=CHAT_ID, text="❌ 시세 조회 중 오류가 발생했습니다.")

# 뉴스 번역 + 전송
async def send_auto_news(bot: Bot):
    try:
        rss_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(rss_url)
        entries = sorted(feed.entries, key=lambda x: x.published_parsed)[-5:]

        messages = []
        for entry in entries:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source="auto", target="ko").translate(title)
            messages.append(f"📰 <b>{translated}</b>\n<a href='{link}'>원문 보기</a>")

        await bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")
        await bot.send_message(chat_id=CHAT_ID, text="❌ 뉴스 수집 중 오류가 발생했습니다.")

# 봇 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 알림 봇입니다!\n/news : 최신 뉴스\n/price : 현재 시세")

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

# Flask 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# 메인
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    start_scheduler(app_bot.bot)
    app_bot.run_polling()
