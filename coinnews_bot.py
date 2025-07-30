import os
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경변수 불러오기
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 기본 설정
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
scheduler = BackgroundScheduler()
KST = datetime.utcnow() + timedelta(hours=9)

# 주요 코인 ID 및 한글명
COINS = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인"
}

# DM 전용 필터
async def is_private_chat(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.type == "private"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_private_chat(update):
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_private_chat(update): return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:5]:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"📰 <b>{translated}</b>\n<a href='{entry.link}'>원문 보기</a>")
        await update.message.reply_text("\n\n".join(reversed(messages)), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"뉴스 오류: {e}")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_private_chat(update): return
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            tickers = {coin['id']: coin for coin in res.json() if coin['id'] in COINS}

        messages = []
        for coin_id, name in COINS.items():
            data = tickers.get(coin_id)
            if data:
                price = data['quotes']['USD']['price']
                change = data['quotes']['USD']['percent_change_1h']
                arrow = "🔺" if change > 0 else "🔻"
                messages.append(f"{data['symbol']} ({name})\n💰 ${price:,.2f} ({arrow}{change:.2f}%)")

        await update.message.reply_text("\n\n".join(messages))
    except Exception as e:
        logging.error(f"시세 오류: {e}")

# 자동 전송 함수들
def start_scheduler(application):
    def wrap_async(func):
        return lambda: asyncio.run(func(application))

    scheduler.add_job(wrap_async(send_price), 'interval', minutes=1)
    scheduler.add_job(wrap_async(send_top_rank), 'interval', minutes=10)
    scheduler.add_job(wrap_async(send_pump_alert), 'interval', minutes=1)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# 주요 코인 시세 전송
async def send_price(app):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            tickers = {coin['id']: coin for coin in res.json() if coin['id'] in COINS}

        messages = []
        for coin_id, name in COINS.items():
            data = tickers.get(coin_id)
            if data:
                price = data['quotes']['USD']['price']
                change = data['quotes']['USD']['percent_change_1h']
                arrow = "🔺" if change > 0 else "🔻"
                messages.append(f"{data['symbol']} ({name})\n💰 ${price:,.2f} ({arrow}{change:.2f}%)")

        await app.bot.send_message(chat_id=CHAT_ID, text="[1분 시세]\n\n" + "\n\n".join(messages))
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 상승/하락률 랭킹 전송
async def send_top_rank(app):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            coins = res.json()

        top = sorted(coins, key=lambda x: x['quotes']['USD']['percent_change_1h'], reverse=True)[:10]
        bottom = sorted(coins, key=lambda x: x['quotes']['USD']['percent_change_1h'])[:10]

        msg = "[📈 상승률 상위 10]\n" + "\n".join([
            f"{c['name']} ({c['symbol']}) : 🔺{c['quotes']['USD']['percent_change_1h']:.2f}%"
            for c in top
        ]) + "\n\n[📉 하락률 상위 10]\n" + "\n".join([
            f"{c['name']} ({c['symbol']}) : 🔻{c['quotes']['USD']['percent_change_1h']:.2f}%"
            for c in bottom
        ])
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# 급등 코인 감지
async def send_pump_alert(app):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            coins = res.json()

        pumps = [c for c in coins if c['quotes']['USD']['percent_change_1h'] > 5]
        if pumps:
            msg = "[🚨 급등 감지]\n" + "\n".join([
                f"{c['name']} ({c['symbol']}) : +{c['quotes']['USD']['percent_change_1h']:.2f}%"
                for c in pumps
            ])
            await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"급등 감지 오류: {e}")

# Flask 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# 핸들러 등록
def add_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))

# 실행 시작
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    async def main():
        application = ApplicationBuilder().token(TOKEN).build()
        add_handlers(application)
        start_scheduler(application)

        await send_price(application)
        await send_top_rank(application)
        await send_pump_alert(application)

        await application.run_polling()

    asyncio.run(main())
