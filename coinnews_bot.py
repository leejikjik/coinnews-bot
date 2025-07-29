import os
import logging
import asyncio
import feedparser
import httpx
from flask import Flask
from datetime import datetime
from pytz import timezone
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Coin Bot is running."

COIN_NAMES = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "ripple": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인"
}

previous_prices = {}

async def send_auto_news(bot: Bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = sorted(feed.entries, key=lambda x: x.published_parsed)[-5:]

        messages = []
        for entry in entries:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 <b>{translated}</b>\n<a href='{link}'>원문 보기</a>")

        await bot.send_message(
            chat_id=CHAT_ID,
            text="\n\n".join(messages),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")

async def send_auto_price(bot: Bot):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        coins = list(COIN_NAMES.keys())
        params = {"ids": ",".join(coins), "vs_currencies": "usd"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                raise Exception("CoinGecko API 429 Too Many Requests")
            data = resp.json()

        now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"📊 {now} 기준 시세:\n"]

        for coin in coins:
            price = float(data.get(coin, {}).get("usd", 0))
            prev = previous_prices.get(coin, price)
            diff = price - prev
            emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            lines.append(f"{COIN_NAMES[coin]}: {price:.2f} USD {emoji} ({diff:+.2f})")
            previous_prices[coin] = price

        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 알림 봇입니다!\n/news 또는 /price 입력해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.bot)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.bot)

# 스케줄러
def start_scheduler(bot: Bot):
    loop = asyncio.get_event_loop()
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        lambda: loop.create_task(send_auto_news(bot)),
        trigger="interval",
        hours=1
    )
    scheduler.add_job(
        lambda: loop.create_task(send_auto_price(bot)),
        trigger="interval",
        minutes=3
    )

    scheduler.start()
    logger.info("✅ 스케줄러 시작됨")

# 메인
if __name__ == "__main__":
    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    async def main():
        application = ApplicationBuilder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("news", news))
        application.add_handler(CommandHandler("price", price))

        start_scheduler(application.bot)

        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        await application.updater.idle()

    asyncio.run(main())
