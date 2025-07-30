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
from datetime import datetime
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 기본 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
KST = datetime.utcnow().astimezone().tzinfo
app = Flask(__name__)
scheduler = BackgroundScheduler()
logging.basicConfig(level=logging.INFO)

# 전역 client
client = httpx.AsyncClient(timeout=10.0)

# 코인 이름 매핑
COIN_NAMES = {
    "bitcoin": "BTC (비트코인)",
    "ethereum": "ETH (이더리움)",
    "xrp": "XRP (리플)",
    "solana": "SOL (솔라나)",
    "dogecoin": "DOGE (도지코인)"
}

# 개인 채팅에서만 작동
def is_private_chat(update: Update) -> bool:
    return update.effective_chat.type == "private"

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private_chat(update):
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        items = feed.entries[:5]
        msg = "📰 [최신 뉴스]\n\n"
        for entry in reversed(items):
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            msg += f"🔹 <b>{translated}</b>\n<a href='{entry.link}'>원문 보기</a>\n\n"
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"뉴스 전송 오류: {e}")

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        res = await client.get(url)
        tickers = res.json()
        targets = ["bitcoin", "ethereum", "xrp", "solana", "dogecoin"]
        msg = "💹 [주요 코인 시세]\n\n"
        for coin in targets:
            data = next((c for c in tickers if c["id"] == coin), None)
            if data:
                name = COIN_NAMES.get(coin, coin.upper())
                price = float(data["quotes"]["USD"]["price"])
                change = float(data["quotes"]["USD"]["percent_change_1h"])
                arrow = "🔺" if change >= 0 else "🔻"
                msg += f"{name}: ${price:,.2f} ({arrow}{change:.2f}%)\n"
        await update.message.reply_text(msg)
    except Exception as e:
        logging.error(f"시세 명령어 오류: {e}")

# 자동 시세 전송
async def send_auto_price():
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        res = await client.get(url)
        tickers = res.json()
        targets = ["bitcoin", "ethereum", "xrp", "solana", "dogecoin"]
        msg = "💹 [주요 코인 시세]\n\n"
        for coin in targets:
            data = next((c for c in tickers if c["id"] == coin), None)
            if data:
                name = COIN_NAMES.get(coin, coin.upper())
                price = float(data["quotes"]["USD"]["price"])
                change = float(data["quotes"]["USD"]["percent_change_1h"])
                arrow = "🔺" if change >= 0 else "🔻"
                msg += f"{name}: ${price:,.2f} ({arrow}{change:.2f}%)\n"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 상승률 TOP10 전송
async def send_top_rank():
    try:
        res = await client.get("https://api.coinpaprika.com/v1/tickers")
        data = res.json()
        ranked = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)
        msg = "🚀 [1시간 상승률 TOP10]\n\n"
        for coin in ranked[:10]:
            name = f'{coin["symbol"]} ({coin["name"]})'
            change = coin["quotes"]["USD"]["percent_change_1h"]
            msg += f"{name}: 🔺 {change:.2f}%\n"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# 급등 코인 탐지
async def send_pump_alert():
    try:
        res = await client.get("https://api.coinpaprika.com/v1/tickers")
        data = res.json()
        pumps = [c for c in data if c["quotes"]["USD"]["percent_change_1h"] > 5]
        if not pumps:
            return
        msg = "📈 [급등 코인 알림 - 1시간 기준 +5% 이상]\n\n"
        for coin in pumps:
            msg += f'{coin["symbol"]} ({coin["name"]}): +{coin["quotes"]["USD"]["percent_change_1h"]:.2f}%\n'
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"급등 감지 오류: {e}")

# 스케줄러 등록
def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_top_rank()), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_pump_alert()), "interval", minutes=5)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

    # 시작 시 1회 실행
    asyncio.run(send_auto_price())
    asyncio.run(send_top_rank())
    asyncio.run(send_pump_alert())

# Flask 기본 응답
@app.route("/", methods=["GET"])
def index():
    return "✅ Coin Bot is running"

# 실행
if __name__ == "__main__":
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    start_scheduler()

    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 10000}).start()

    application.run_polling()
