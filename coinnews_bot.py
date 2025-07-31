import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID")
app = Flask(__name__)
scheduler = BackgroundScheduler()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KST = timedelta(hours=9)
client = httpx.AsyncClient(timeout=10)

# 코인 ID 및 한글 이름 매핑
COINS = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

# 개인채팅에서만 동작하는 명령어 제한
def private_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            await func(update, context)
    return wrapper

# 명령어 핸들러
@private_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ 봇이 정상 작동 중입니다.\n/news : 뉴스 보기\n/price : 주요 코인 시세 보기")

@private_only
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ TEST 명령어 응답 성공")

@private_only
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        msgs = []
        for entry in reversed(feed.entries[:5]):
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            pub_time = datetime(*entry.published_parsed[:6]) + KST
            time_str = pub_time.strftime("%m/%d %H:%M")
            msgs.append(f"📰 {translated}\n🕒 {time_str}\n🔗 {entry.link}")
        for msg in msgs:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
    except Exception as e:
        logger.error(f"뉴스 오류: {e}")

@private_only
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price_to_chat(update.effective_chat.id)

# 시세 전송
async def send_price_to_chat(chat_id):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        response = await client.get(url)
        data = response.json()

        result = []
        for coin_id, name in COINS.items():
            coin = next((c for c in data if c["id"] == coin_id), None)
            if coin:
                symbol = coin["symbol"]
                price = float(coin["quotes"]["USD"]["price"])
                change = coin["quotes"]["USD"]["percent_change_1h"]
                result.append(f"{symbol} ({name})\n💰 ${price:,.2f}\n📈 1시간: {change:+.2f}%")

        message = "💹 주요 코인 시세\n\n" + "\n\n".join(result)
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 급등 코인 감지
async def detect_gainers():
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        response = await client.get(url)
        data = response.json()

        gainers = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)[:5]
        lines = []
        for coin in gainers:
            symbol = coin["symbol"]
            name = coin["name"]
            price = float(coin["quotes"]["USD"]["price"])
            change = coin["quotes"]["USD"]["percent_change_1h"]
            if change >= 5:
                lines.append(f"{symbol} ({name})\n💰 ${price:,.2f} | 📈 +{change:.2f}%")

        if lines:
            msg = "🚀 급등 코인 TOP 5 (1시간 기준)\n\n" + "\n\n".join(lines)
            await bot.send_message(chat_id=GROUP_ID, text=msg)
    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

# 랭킹 전송
async def send_rankings():
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        response = await client.get(url)
        data = response.json()

        top_gainers = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_24h"], reverse=True)[:10]
        lines = []
        for coin in top_gainers:
            symbol = coin["symbol"]
            name = coin["name"]
            change = coin["quotes"]["USD"]["percent_change_24h"]
            lines.append(f"{symbol} ({name}) 📈 {change:+.2f}%")

        msg = "📊 24시간 상승률 TOP 10\n\n" + "\n".join(lines)
        await bot.send_message(chat_id=GROUP_ID, text=msg)
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# 봇 실행
async def main():
    global bot
    app_builder = ApplicationBuilder().token(TOKEN)
    application = app_builder.build()
    bot = application.bot

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("test", test))

    # 스케줄링
    scheduler.add_job(lambda: asyncio.run(send_price_to_chat(GROUP_ID)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(detect_gainers()), "interval", minutes=3)
    scheduler.add_job(lambda: asyncio.run(send_rankings()), "interval", minutes=10)

    scheduler.start()

    # 부팅 직후 한 번 전송
    await send_price_to_chat(GROUP_ID)
    await send_rankings()
    await detect_gainers()

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

# Flask (keepalive용)
@app.route("/")
def index():
    return "Coin bot is running!"

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
