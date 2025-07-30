import os
import logging
import httpx
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from datetime import datetime
import feedparser
import asyncio
import threading

# ───────────────────── 설정 ─────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# ───────────────────── Flask ─────────────────────
app = Flask(__name__)
@app.route("/")
def home():
    return "CoinNews Bot Running"

# ───────────────────── Telegram 핸들러 ─────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세 확인"
        )

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
                price = float(item["quotes"]["USD"]["price"])
                result.append(f"🪙 <b>{item['symbol']} ({name_kr})</b>\n💰 ${price:,.2f}")

        await update.message.reply_text("\n\n".join(result), parse_mode="HTML")

    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("❌ 시세 정보를 불러오지 못했습니다.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:5]:
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n{entry.link}")
        await update.message.reply_text("\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        logger.error(f"/news 오류: {e}")
        await update.message.reply_text("❌ 뉴스 정보를 불러오지 못했습니다.")

# ───────────────────── 자동 기능 ─────────────────────
async def send_price(bot):
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

        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

async def send_top_rank(bot):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        up = sorted(data, key=lambda x: x["quotes"]["USD"].get("percent_change_24h", 0), reverse=True)[:10]
        down = sorted(data, key=lambda x: x["quotes"]["USD"].get("percent_change_24h", 0))[:10]

        msg = "<b>📈 24시간 상승률 TOP 10</b>\n"
        for item in up:
            change = item["quotes"]["USD"].get("percent_change_24h", 0)
            msg += f"🔺 {item['symbol']} +{change:.2f}%\n"

        msg += "\n<b>📉 24시간 하락률 TOP 10</b>\n"
        for item in down:
            change = item["quotes"]["USD"].get("percent_change_24h", 0)
            msg += f"🔻 {item['symbol']} {change:.2f}%\n"

        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

async def send_pump_alert(bot):
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
            msg = "🔥 <b>급등 코인 알림</b>\n\n" + "\n".join(pumps)
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

# ───────────────────── APScheduler 실행 ─────────────────────
def start_scheduler(bot):
    scheduler = BackgroundScheduler()

    def wrap_async(func):
        return lambda: asyncio.run(func(bot))

    scheduler.add_job(wrap_async(send_price), "interval", minutes=1)
    scheduler.add_job(wrap_async(send_top_rank), "interval", minutes=10)
    scheduler.add_job(wrap_async(send_pump_alert), "interval", minutes=10)

    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# ───────────────────── Main 실행 ─────────────────────
def run():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))

    # Flask 백그라운드 실행
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # APScheduler 시작 (run_polling 이후 실행되면 안됨!)
    threading.Thread(target=start_scheduler, args=(application.bot,)).start()

    application.run_polling()

if __name__ == "__main__":
    run()
