import os
import logging
import asyncio
import httpx
from flask import Flask
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from deep_translator import GoogleTranslator
import feedparser

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 주요 코인 ID 및 이름
MAIN_COINS = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
    "cardano": "에이다",
    "ton": "톤코인",
    "tron": "트론",
    "aptos": "앱토스",
    "avalanche": "아발란체",
}

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 주요 코인 로고 URL
def get_logo_url(coin_id):
    return f"https://static.coinpaprika.com/coin/{coin_id}/logo.png"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세 확인"
        )

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        result = []
        for item in data:
            if item["id"] in MAIN_COINS:
                name_kr = MAIN_COINS[item["id"]]
                logo = get_logo_url(item["id"])
                price = float(item["quotes"]["USD"]["price"])
                result.append(f"🪙 <b>{item['symbol']} ({name_kr})</b>\n💰 ${price:,.2f}\n🖼 {logo}")

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n\n".join(result),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 시세 정보를 불러오지 못했습니다.")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:5]:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n{entry.link}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        logger.error(f"뉴스 오류: {e}")

# 자동 전송 함수
async def auto_send_all(application):
    await send_price(application)
    await send_top_rank(application)
    await send_pump_alert(application)

# 자동 시세 전송
async def send_price(app):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        msg = "<b>📊 주요 코인 시세 (1분 간격)</b>\n\n"
        for item in data:
            if item["id"] in MAIN_COINS:
                name_kr = MAIN_COINS[item["id"]]
                price = float(item["quotes"]["USD"]["price"])
                msg += f"🪙 <b>{item['symbol']} ({name_kr})</b> - ${price:,.2f}\n"

        await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 급등 알림
async def send_pump_alert(app):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        pumps = []
        for item in data:
            change = item["quotes"]["USD"].get("percent_change_1h", 0)
            if change and change > 10:
                pumps.append(f"🚀 {item['symbol']} +{change:.2f}%")

        if pumps:
            await app.bot.send_message(chat_id=CHAT_ID, text="🔥 <b>급등 코인 알림</b>\n\n" + "\n".join(pumps), parse_mode="HTML")
    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

# 상승률/하락률 랭킹
async def send_top_rank(app):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        sorted_up = sorted(data, key=lambda x: x["quotes"]["USD"].get("percent_change_24h", 0), reverse=True)[:10]
        sorted_down = sorted(data, key=lambda x: x["quotes"]["USD"].get("percent_change_24h", 0))[:10]

        msg = "<b>📈 24시간 상승률 TOP 10</b>\n"
        for item in sorted_up:
            change = item["quotes"]["USD"].get("percent_change_24h", 0)
            msg += f"🔺 {item['symbol']} +{change:.2f}%\n"

        msg += "\n<b>📉 24시간 하락률 TOP 10</b>\n"
        for item in sorted_down:
            change = item["quotes"]["USD"].get("percent_change_24h", 0)
            msg += f"🔻 {item['symbol']} {change:.2f}%\n"

        await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# Flask keepalive
@app.route("/")
def index():
    return "CoinNews Bot Running"

# 명령어 등록
def add_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("news", news))

# 스케줄러 시작
def start_scheduler(app):
    scheduler.add_job(lambda: asyncio.run(send_price(app)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_top_rank(app)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_pump_alert(app)), "interval", minutes=10)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# 메인 실행
async def main():
    application = ApplicationBuilder().token(TOKEN).build()
    add_handlers(application)
    start_scheduler(application)
    await auto_send_all(application)
    await application.run_polling()

if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(main())
