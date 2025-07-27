import os
import asyncio
import logging
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
import feedparser
from deep_translator import GoogleTranslator
import httpx
from datetime import datetime, timedelta, timezone

# 환경변수 불러오기 (Render에서 설정)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Flask 앱
app = Flask(__name__)

# 한국시간
KST = timezone(timedelta(hours=9))

# 뉴스 전송 함수
async def send_auto_news(app: Application):
    try:
        url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(url)
        if not feed.entries:
            return

        sorted_news = sorted(feed.entries, key=lambda x: x.published_parsed)
        messages = []
        for entry in sorted_news[:3]:
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published_at = datetime(*entry.published_parsed[:6]).astimezone(KST)
            msg = f"📰 <b>{translated}</b>\n{entry.link}\n🕒 {published_at.strftime('%Y-%m-%d %H:%M')}\n"
            messages.append(msg)

        text = "\n\n".join(messages)
        await app.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"뉴스 전송 실패: {e}")

# 시세 전송 함수
coin_list = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
prev_prices = {}

async def send_auto_price(app: Application):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": ",".join(coin_list),
            "vs_currencies": "usd"
        }

        async with httpx.AsyncClient() as client:
            res = await client.get(url, params=params)
            data = res.json()

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        msg = f"📊 코인 시세 알림 ({now})\n\n"
        for coin in coin_list:
            price = data.get(coin, {}).get("usd")
            if price is None:
                continue

            diff = ""
            if coin in prev_prices:
                delta = price - prev_prices[coin]
                emoji = "🔼" if delta > 0 else "🔽" if delta < 0 else "⏸"
                diff = f" ({emoji} {delta:+.2f})"

            prev_prices[coin] = price
            msg += f"• {coin.capitalize()}: ${price:.2f}{diff}\n"

        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"가격 전송 실패: {e}")

# 봇 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 코인 뉴스 및 시세 알림 봇입니다!\n/news 또는 /price로 사용해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.application)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.application)

# Flask 루트
@app.route("/")
def index():
    return "CoinNews Bot Running!"

# 메인 실행
async def main():
    app_telegram = Application.builder().token(BOT_TOKEN).build()

    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("news", news))
    app_telegram.add_handler(CommandHandler("price", price))

    await app_telegram.initialize()
    asyncio.create_task(app_telegram.start())

    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news(app_telegram)), trigger=IntervalTrigger(minutes=30))
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price(app_telegram)), trigger=IntervalTrigger(minutes=1))
    scheduler.start()

    logging.info("✅ Telegram 봇 시작됨")

    # Flask 실행 (비동기 아님)
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        # Render 환경에서 루프가 이미 돌아가는 경우
        loop = asyncio.get_event_loop()
        loop.create_task(main())
        loop.run_forever()
