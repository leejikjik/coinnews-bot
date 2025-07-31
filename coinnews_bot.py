import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID")

# Flask 앱 생성
flask_app = Flask(__name__)

# Application 생성
app = ApplicationBuilder().token(TOKEN).build()

# 한국 시간
KST = datetime.utcnow().astimezone().tzinfo

# -------------------- 명령어 핸들러 --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await update.message.reply_text("✅ 작동 중입니다.\n/news : 뉴스\n/price : 시세\n/test : 테스트")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await update.message.reply_text("✅ 테스트 완료")

async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(f"🆔 Chat ID: `{cid}`", parse_mode="Markdown")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        articles = feed.entries[:5]
        result = []
        for entry in articles:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            result.append(f"📰 {translated}\n{entry.link}")
        if result:
            await update.message.reply_text("\n\n".join(result))
        else:
            await update.message.reply_text("뉴스를 불러오지 못했습니다.")
    except Exception as e:
        logger.error(f"뉴스 오류: {e}")
        await update.message.reply_text("❌ 뉴스 불러오기 실패")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    await send_price(update.effective_chat.id)

# -------------------- 시세 함수 --------------------

symbol_map = {
    "bitcoin": "BTC (비트코인)",
    "ethereum": "ETH (이더리움)",
    "xrp": "XRP (리플)",
    "solana": "SOL (솔라나)",
    "dogecoin": "DOGE (도지코인)",
}

async def fetch_prices():
    try:
        ids = ",".join(symbol_map.keys())
        url = f"https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            data = r.json()
            result = {}
            for coin in data:
                if coin["id"] in symbol_map:
                    result[coin["id"]] = coin["quotes"]["USD"]["price"]
            return result
    except Exception as e:
        logger.error(f"가격 가져오기 오류: {e}")
        return {}

async def send_price(chat_id):
    prices = await fetch_prices()
    if not prices:
        return
    msg = f"\n\n".join([
        f"{symbol_map[k]}: ${prices[k]:,.2f}" for k in symbol_map if k in prices
    ])
    try:
        await app.bot.send_message(chat_id=chat_id, text=f"📊 현재 시세:\n{msg}")
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# -------------------- 스케줄러 --------------------

scheduler = BackgroundScheduler()
scheduler.add_job(lambda: asyncio.run(send_price(GROUP_ID)), 'interval', minutes=1)

# -------------------- Flask --------------------

@flask_app.route("/")
def index():
    return "Bot is running"

# -------------------- main --------------------

def main():
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("getid", getid))

    scheduler.start()

    loop = asyncio.get_event_loop()
    loop.create_task(app.initialize())
    loop.create_task(app.start())

    from threading import Thread
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000)).start()
    loop.run_forever()

if __name__ == '__main__':
    main()
