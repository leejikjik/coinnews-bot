import os
import logging
import threading
import asyncio
from datetime import datetime, timezone, timedelta

import feedparser
import httpx
from deep_translator import GoogleTranslator
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    defaults,
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")       # 개인 DM 용
GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")     # 그룹방 자동 전송용

# 타임존
KST = timezone(timedelta(hours=9))

# Flask 앱
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Coin Bot is running."

# Telegram 기본 설정
defaults = defaults.Defaults(parse_mode="HTML", tzinfo=KST)
application = ApplicationBuilder().token(TOKEN).defaults(defaults).build()

# 명령어 핸들러들
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text("✅ 봇이 작동 중입니다.\n/news : 뉴스\n/price : 시세\n/test : 테스트")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text("✅ 테스트 성공!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[:5]):
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%m/%d %H:%M")
        messages.append(f"🗞 <b>{translated}</b>\n🕒 {published}")
    await update.message.reply_text("\n\n".join(messages))

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_price(update.effective_chat.id)

# 시세 전송 함수
async def send_price(target_id: str):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url)
            data = res.json()

        symbols = {
            "bitcoin": "BTC (비트코인)",
            "ethereum": "ETH (이더리움)",
            "ripple": "XRP (리플)",
            "solana": "SOL (솔라나)",
            "dogecoin": "DOGE (도지코인)",
        }

        message = "<b>📊 주요 코인 시세</b>\n"
        now = datetime.now(KST).strftime("%H:%M:%S")
        message += f"🕒 기준 시각: {now}\n\n"

        for coin in data:
            if coin["id"] in symbols:
                name = symbols[coin["id"]]
                price = round(coin["quotes"]["USD"]["price"], 4)
                change = coin["quotes"]["USD"]["percent_change_1h"]
                emoji = "🔼" if change > 0 else "🔽"
                message += f"{emoji} {name} - ${price} ({change:+.2f}%)\n"

        await application.bot.send_message(chat_id=target_id, text=message)

    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 랭킹 전송
async def send_ranking():
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url)
            data = res.json()

        sorted_data = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)

        top = sorted_data[:10]
        message = "<b>🚀 1시간 상승률 TOP10</b>\n\n"
        for coin in top:
            symbol = coin["symbol"]
            name = coin["name"]
            change = coin["quotes"]["USD"]["percent_change_1h"]
            message += f"🔼 {symbol} ({name}): {change:.2f}%\n"

        await application.bot.send_message(chat_id=GROUP_ID, text=message)

    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# 급등 감지
async def detect_surge():
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url)
            data = res.json()

        surged = [coin for coin in data if coin["quotes"]["USD"]["percent_change_1h"] >= 5]

        if surged:
            message = "<b>📈 급등 감지 코인 (1시간 기준 +5%)</b>\n\n"
            for coin in surged:
                name = coin["name"]
                symbol = coin["symbol"]
                change = coin["quotes"]["USD"]["percent_change_1h"]
                message += f"🚀 {symbol} ({name}) +{change:.2f}%\n"
            await application.bot.send_message(chat_id=GROUP_ID, text=message)

    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

# 스케줄러 시작
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_price(GROUP_ID)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_ranking()), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(detect_surge()), "interval", minutes=5)
    scheduler.start()

    # 부팅 직후 1회 전송
    asyncio.run(send_price(GROUP_ID))
    asyncio.run(send_ranking())
    asyncio.run(detect_surge())

# Flask 백그라운드 실행
def run_flask():
    flask_app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    # 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("test", test))

    # Flask 백그라운드 시작
    threading.Thread(target=run_flask, daemon=True).start()

    # 스케줄러 시작
    start_scheduler()

    # run_polling을 메인 쓰레드에서 실행
    application.run_polling()
