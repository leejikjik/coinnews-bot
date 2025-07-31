import os
import logging
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 주요 코인 리스트
COINS = {
    "bitcoin": "BTC (비트코인)",
    "ethereum": "ETH (이더리움)",
    "xrp": "XRP (리플)",
    "solana": "SOL (솔라나)",
    "dogecoin": "DOGE (도지코인)",
}

# 1. /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🟢 코인 뉴스 및 시세 알림 봇입니다.\n\n명령어 목록:\n/news - 최신 뉴스\n/price - 주요 코인 시세"
    )

# 2. /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[:5]):
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        messages.append(f"📰 <b>{translated}</b>\n{entry.link}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n\n".join(messages),
        parse_mode="HTML"
    )

# 3. /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    async with httpx.AsyncClient() as client:
        prices = []
        for coin_id, label in COINS.items():
            try:
                res = await client.get(f"https://api.coinpaprika.com/v1/tickers/{coin_id}")
                data = res.json()
                krw = round(data["quotes"]["KRW"]["price"])
                change = data["quotes"]["KRW"]["percent_change_1h"]
                prices.append(f"{label} : {krw:,}원 ({change:+.2f}%)")
            except:
                prices.append(f"{label} : ⚠️ 데이터 오류")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="💰 주요 코인 시세\n\n" + "\n".join(prices)
        )

# 자동 시세 전송 (그룹방)
async def auto_price(context: ContextTypes.DEFAULT_TYPE):
    async with httpx.AsyncClient() as client:
        prices = []
        for coin_id, label in COINS.items():
            try:
                res = await client.get(f"https://api.coinpaprika.com/v1/tickers/{coin_id}")
                data = res.json()
                krw = round(data["quotes"]["KRW"]["price"])
                change = data["quotes"]["KRW"]["percent_change_1h"]
                prices.append(f"{label} : {krw:,}원 ({change:+.2f}%)")
            except:
                prices.append(f"{label} : ⚠️ 데이터 오류")
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="💸 1분 주기 실시간 코인 시세\n\n" + "\n".join(prices)
        )

# 최초 실행용 함수 (배포 후 1회 전송)
async def send_once(application):
    await application.bot.send_message(
        chat_id=CHAT_ID, text="✅ 코인 뉴스/시세 봇이 시작되었습니다."
    )
    await auto_price(ContextTypes.DEFAULT_TYPE(bot=application.bot))

# Flask 엔드포인트
@app.route("/")
def index():
    return "✅ CoinNewsBot is running."

# run_polling 실행 함수 (메인 스레드에서)
def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 시작
    scheduler.add_job(lambda: asyncio.run(auto_price(application.bot)), "interval", minutes=1)
    scheduler.start()

    # 배포 직후 최초 메시지 전송
    asyncio.run(send_once(application))

    # 봇 시작
    application.run_polling()

# Flask는 백그라운드로 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
