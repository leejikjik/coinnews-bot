import os
import logging
import asyncio
import feedparser
import httpx
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from datetime import datetime
from pytz import timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ✅ 환경변수 설정
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ✅ 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Flask 서버
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Telegram Coin Bot is running!"

# ✅ 뉴스 파싱 및 번역
async def send_auto_news(bot):
    try:
        rss_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(rss_url)
        sorted_entries = sorted(feed.entries, key=lambda x: x.published_parsed)

        messages = []
        for entry in sorted_entries[:5]:
            title = entry.title
            link = entry.link
            translated_title = GoogleTranslator(source='auto', target='ko').translate(title)
            messages.append(f"📰 <b>{translated_title}</b>\n<a href='{link}'>원문 보기</a>\n")

        message = "\n".join(messages)
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[뉴스 전송 오류] {e}")

# ✅ 시세 자동 전송 함수
previous_prices = {}

async def send_auto_price(bot):
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        coins = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
        coin_names = {
            "BTCUSDT": "비트코인",
            "ETHUSDT": "이더리움",
            "XRPUSDT": "리플",
            "SOLUSDT": "솔라나",
            "DOGEUSDT": "도지코인"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()

        now = datetime.now(timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        result = [f"📊 {now} 기준 시세:\n"]

        for coin in coins:
            price = float(next((item for item in data if item["symbol"] == coin), {"price": 0})["price"])
            old_price = previous_prices.get(coin)
            diff = price - old_price if old_price else 0
            emoji = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➖")
            result.append(f"{coin_names[coin]}: {price:.2f} USD {emoji} ({diff:+.2f})")
            previous_prices[coin] = price

        message = "\n".join(result)
        await bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        logger.error(f"[시세 전송 오류] {e}")

# ✅ 명령어 핸들러
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 및 시세 알림 봇입니다!\n/news 또는 /price 명령어를 사용해보세요.")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_news(context.bot)

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_auto_price(context.bot)

# ✅ 스케줄러 실행
def start_scheduler(bot):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(bot)), 'interval', hours=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(bot)), 'interval', minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 실행됨")

# ✅ 봇 실행 함수
async def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("price", price_command))

    # 스케줄러 시작 시 application.bot 전달
    start_scheduler(application.bot)

    await application.run_polling()

# ✅ main
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    app.run(host="0.0.0.0", port=10000)
