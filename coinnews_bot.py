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
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 가 필요합니다.")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 서버
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Coin Bot is running."

# 이전 가격 저장
previous_prices = {}

# Cointelegraph 뉴스 전송
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

# CoinGecko 시세 전송 (403 해결 버전)
async def send_auto_price(bot: Bot):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
            "vs_currencies": "usd"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; CoinNewsBot/1.0; +https://cointelegraph.com)"
        }
        names = {
            "bitcoin": "비트코인",
            "ethereum": "이더리움",
            "ripple": "리플",
            "solana": "솔라나",
            "dogecoin": "도지코인"
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"📊 {now} 기준 시세:\n"]

        for key, name in names.items():
            price = float(data[key]["usd"])
            diff = price - previous_prices.get(key, price)
            emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            lines.append(f"{name}: {price:.2f} USD {emoji} ({diff:+.2f})")
            previous_prices[key] = price

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

# 스케줄러 시작
def start_scheduler(bot: Bot):
    loop = asyncio.get_event_loop()
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: loop.create_task(send_auto_news(bot)), "interval", hours=1)
    scheduler.add_job(lambda: loop.create_task(send_auto_price(bot)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 시작됨")

# Flask 실행
def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# 메인 실행
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    start_scheduler(application.bot)

    application.run_polling()
