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
from datetime import datetime, timedelta
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 기본 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # 개인 DM용
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID")  # 그룹방용

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 1. /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 코인 시세\n/test : 응답 확인"
        )

# 2. /test
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await update.message.reply_text("✅ 정상 작동 중입니다.")

# 3. /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in reversed(feed.entries[:5]):
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            published = entry.published
            messages.append(f"📰 <b>{translated}</b>\n🕒 {published}\n🔗 {entry.link}\n")
        await update.message.reply_text("\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        logging.error(f"뉴스 오류: {e}")
        await update.message.reply_text("❌ 뉴스 가져오기 실패")

# 4. /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        coins = {
            "bitcoin": "BTC (비트코인)",
            "ethereum": "ETH (이더리움)",
            "xrp": "XRP (리플)",
            "solana": "SOL (솔라나)",
            "dogecoin": "DOGE (도지코인)",
        }

        msg = "💹 <b>주요 코인 시세</b>\n"
        for coin_id, label in coins.items():
            coin = next((c for c in data if c["id"] == coin_id), None)
            if coin:
                price = round(coin["quotes"]["USD"]["price"], 4)
                change = coin["quotes"]["USD"]["percent_change_1h"]
                arrow = "📈" if change > 0 else "📉"
                msg += f"{arrow} <b>{label}</b>: ${price} ({change:+.2f}%)\n"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"시세 오류: {e}")
        await update.message.reply_text("❌ 시세 불러오기 실패")

# 자동 시세 전송
async def send_auto_price():
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        coins = {
            "bitcoin": "BTC (비트코인)",
            "ethereum": "ETH (이더리움)",
            "xrp": "XRP (리플)",
            "solana": "SOL (솔라나)",
            "dogecoin": "DOGE (도지코인)",
        }

        msg = "📊 <b>1분 시세 알림</b>\n"
        for coin_id, label in coins.items():
            coin = next((c for c in data if c["id"] == coin_id), None)
            if coin:
                price = round(coin["quotes"]["USD"]["price"], 4)
                change = coin["quotes"]["USD"]["percent_change_1h"]
                arrow = "📈" if change > 0 else "📉"
                msg += f"{arrow} <b>{label}</b>: ${price} ({change:+.2f}%)\n"

        await application.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 자동 뉴스 전송
async def send_auto_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in reversed(feed.entries[:3]):
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            published = entry.published
            messages.append(f"📰 <b>{translated}</b>\n🕒 {published}\n🔗 {entry.link}\n")
        await application.bot.send_message(chat_id=GROUP_ID, text="\n\n".join(messages), parse_mode="HTML")
    except Exception as e:
        logging.error(f"자동 뉴스 오류: {e}")

# 스케줄러 설정
def start_scheduler():
    loop = asyncio.get_event_loop()

    def wrap_async(func):
        return lambda: asyncio.run_coroutine_threadsafe(func(), loop)

    scheduler.add_job(wrap_async(send_auto_price), "interval", minutes=1)
    scheduler.add_job(wrap_async(send_auto_news), "interval", minutes=10)

    # 최초 1회 전송
    loop.create_task(send_auto_price())
    loop.create_task(send_auto_news())

    scheduler.start()

# Flask keepalive
@app.route("/")
def index():
    return "✅ Bot is running"

# 실행
if __name__ == "__main__":
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 시작
    start_scheduler()

    # Flask 병렬 실행
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # 봇 실행 (main thread)
    application.run_polling()
