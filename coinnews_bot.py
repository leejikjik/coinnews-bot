import os
import logging
import threading
import asyncio
import feedparser
import httpx
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from datetime import datetime
from pytz import timezone
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# 환경 변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로거
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 앱
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Coin Bot is running."

# 이전 가격 저장
previous_prices = {}

# 코인 시세 전송
async def send_auto_price(bot: Bot):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "bitcoin,ethereum,ripple,solana,dogecoin", "vs_currencies": "usd"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise Exception(f"CoinGecko API 응답 코드: {resp.status_code}")
            data = resp.json()

        names = {
            "bitcoin": "비트코인",
            "ethereum": "이더리움",
            "ripple": "리플",
            "solana": "솔라나",
            "dogecoin": "도지코인"
        }

        now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"📊 {now} 기준 시세:\n"]

        for coin_id, coin_name in names.items():
            price = data.get(coin_id, {}).get("usd", 0)
            prev = previous_prices.get(coin_id, price)
            diff = price - prev
            emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            lines.append(f"{coin_name}: {price:.2f} USD {emoji} ({diff:+.2f})")
            previous_prices[coin_id] = price

        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# 뉴스 전송
async def send_auto_news(bot: Bot):
    try:
        rss_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(rss_url)
        entries = sorted(feed.entries, key=lambda x: x.published_parsed)[-5:]

        messages = []
        for entry in entries:
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 <b>{translated}</b>\n<a href='{link}'>원문 보기</a>")

        await bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 & 시세 알림 봇입니다!\n/news 또는 /price 입력해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.bot)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.bot)

# 스케줄러 시작
def start_scheduler(bot: Bot):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(bot)), "interval", hours=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(bot)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 시작됨")

# Flask 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# Telegram Bot 실행
async def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    start_scheduler(application.bot)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

# 메인 실행
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    asyncio.run(run_bot())
