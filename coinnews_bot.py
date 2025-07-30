import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
from deep_translator import GoogleTranslator
import httpx

# ===================== ⚙️ 설정 =====================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
KST = timezone(timedelta(hours=9))
app = Flask(__name__)
scheduler = BackgroundScheduler()
logging.basicConfig(level=logging.INFO)

# ===================== 🗺️ 코인 이름 변환 =====================
coin_name_map = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "ripple": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
    "cardano": "에이다",
    "binance-coin": "바이낸스코인",
    "tron": "트론",
    "polkadot": "폴카닷",
    "litecoin": "라이트코인",
}

symbol_name_map = {
    "BTC": "비트코인",
    "ETH": "이더리움",
    "XRP": "리플",
    "SOL": "솔라나",
    "DOGE": "도지코인",
    "ADA": "에이다",
    "BNB": "바이낸스코인",
    "TRX": "트론",
    "DOT": "폴카닷",
    "LTC": "라이트코인",
}

major_symbols = list(symbol_name_map.keys())

# ===================== 🔎 뉴스 =====================
import feedparser

def get_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    news_items = feed.entries[:5]
    translated = []
    for entry in news_items:
        title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        link = entry.link
        translated.append(f"📰 {title}\n🔗 {link}")
    return "\n\n".join(translated)

async def send_news(chat_id, context):
    try:
        news = get_news()
        await context.bot.send_message(chat_id=chat_id, text=f"<b>📢 최신 코인 뉴스</b>\n\n{news}", parse_mode="HTML")
    except Exception as e:
        logging.error(f"뉴스 전송 오류: {e}")

# ===================== 💸 시세 =====================
async def fetch_prices():
    url = "https://api.coinpaprika.com/v1/tickers"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        data = resp.json()
        return [coin for coin in data if coin["symbol"] in major_symbols]

async def send_price(chat_id, context):
    try:
        coins = await fetch_prices()
        msg = f"<b>💰 주요 코인 시세</b> ({datetime.now(KST).strftime('%H:%M:%S')})\n\n"
        for c in coins:
            symbol = c["symbol"]
            name = symbol_name_map.get(symbol, "")
            price = float(c["quotes"]["USD"]["price"])
            change = float(c["quotes"]["USD"]["percent_change_24h"])
            msg += f"{symbol} ({name}): ${price:,.2f} ({change:+.2f}%)\n"
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# ===================== 📈 상승/하락 랭킹 =====================
async def send_rankings(context):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            coins = resp.json()
        ranked = sorted(coins, key=lambda x: x["quotes"]["USD"]["percent_change_24h"], reverse=True)
        top_gainers = ranked[:10]
        top_losers = ranked[-10:][::-1]

        gain_msg = "<b>🚀 24시간 상승률 TOP 10</b>\n\n"
        for c in top_gainers:
            gain_msg += f"{c['symbol']} ({c['name']}): {c['quotes']['USD']['percent_change_24h']:+.2f}%\n"

        lose_msg = "\n<b>📉 하락률 TOP 10</b>\n\n"
        for c in top_losers:
            lose_msg += f"{c['symbol']} ({c['name']}): {c['quotes']['USD']['percent_change_24h']:+.2f}%\n"

        await context.bot.send_message(chat_id=CHAT_ID, text=gain_msg + lose_msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# ===================== 🚨 급등 감지 =====================
async def send_spike_coins(context):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            coins = resp.json()
        spiked = [
            c for c in coins if c["quotes"]["USD"]["percent_change_24h"] >= 10 and c["symbol"] in major_symbols
        ]
        if spiked:
            msg = "<b>📈 급등 코인 알림 (24H 10%↑)</b>\n\n"
            for c in spiked:
                msg += f"{c['symbol']} ({c['name']}): {c['quotes']['USD']['percent_change_24h']:+.2f}%\n"
            await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"급등 코인 전송 오류: {e}")

# ===================== 🧠 명령어 =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🟢 코인 뉴스봇이 작동 중입니다!\n\n/price : 주요 코인 시세\n/news : 코인 뉴스",
        )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await send_price(update.effective_chat.id, context)

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await send_news(update.effective_chat.id, context)

# ===================== ⏱ 스케줄러 =====================
def start_scheduler(application):
    scheduler.add_job(lambda: asyncio.run(send_price(CHAT_ID, application.bot)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_rankings(application.bot)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_spike_coins(application.bot)), "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_news(CHAT_ID, application.bot)), "interval", minutes=30)
    scheduler.start()
    logging.info("✅ JobQueue 스케줄러 시작됨")

# ===================== 🚀 실행 =====================
if __name__ == "__main__":
    from telegram.ext import Application

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))

    async def initial_tasks():
        await send_price(CHAT_ID, application.bot)
        await send_spike_coins(application.bot)
        await send_rankings(application.bot)
        await send_news(CHAT_ID, application.bot)

    loop = asyncio.get_event_loop()
    loop.create_task(initial_tasks())
    start_scheduler(application)

    from threading import Thread
    def run_flask():
        app.run(host="0.0.0.0", port=10000)

    Thread(target=run_flask).start()
    application.run_polling()
