import os
import logging
import httpx
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
import feedparser
from datetime import datetime, timedelta
import threading

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 주요 코인 ID 매핑
COIN_MAP = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

# 개인 채팅에서만 허용
def is_private_chat(update: Update) -> bool:
    return update.effective_chat.type == "private"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private_chat(update):
        await update.message.reply_text(
            "🟢 코인 뉴스 및 시세 알림 봇 작동 중입니다.\n\n"
            "/news : 최신 뉴스 요약\n"
            "/price : 주요 코인 시세 확인"
        )

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[:5]):
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        messages.append(f"📰 {translated}\n{entry.link}")
    await update.message.reply_text("\n\n".join(messages))

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = response.json()
            result = []
            for coin_id in COIN_MAP:
                coin = next((c for c in data if c["id"] == coin_id), None)
                if coin:
                    name = COIN_MAP[coin_id]
                    symbol = coin["symbol"]
                    price = float(coin["quotes"]["USD"]["price"])
                    change = float(coin["quotes"]["USD"]["percent_change_1h"])
                    result.append(
                        f"{symbol} ({name})\n💰 ${price:.2f} | ⏱ 1시간변동: {change:+.2f}%"
                    )
            await update.message.reply_text("📊 주요 코인 시세\n\n" + "\n\n".join(result))
    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("시세를 불러오는 중 오류가 발생했습니다.")

# 주요 기능 전송 (자동 전송용)
async def send_auto_price(application):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = response.json()

            # 주요 시세
            prices = []
            for coin_id in COIN_MAP:
                coin = next((c for c in data if c["id"] == coin_id), None)
                if coin:
                    name = COIN_MAP[coin_id]
                    symbol = coin["symbol"]
                    price = float(coin["quotes"]["USD"]["price"])
                    change = float(coin["quotes"]["USD"]["percent_change_1h"])
                    prices.append(f"{symbol} ({name})\n💰 ${price:.2f} | ⏱ 1시간변동: {change:+.2f}%")

            # 랭킹
            sorted_up = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)
            top_10 = sorted_up[:10]
            up_msg = "\n".join(
                [f"{i+1}. {coin['symbol']} ({coin['name']}) {coin['quotes']['USD']['percent_change_1h']:+.2f}%"
                 for i, coin in enumerate(top_10)]
            )

            # 급등 코인
            now = datetime.utcnow()
            one_hour_ago = now - timedelta(hours=1)
            surged = [
                f"{coin['symbol']} ({coin['name']}) {coin['quotes']['USD']['percent_change_1h']:+.2f}%"
                for coin in data if coin["quotes"]["USD"]["percent_change_1h"] >= 5
            ]
            surge_msg = "\n".join(surged) if surged else "📉 급등 코인 없음"

            await application.bot.send_message(chat_id=CHAT_ID, text="📊 주요 코인 시세\n\n" + "\n\n".join(prices))
            await application.bot.send_message(chat_id=CHAT_ID, text="🚀 상승률 상위 10종\n\n" + up_msg)
            await application.bot.send_message(chat_id=CHAT_ID, text="📈 1시간 내 급등 코인\n\n" + surge_msg)
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# APScheduler 설정
def start_scheduler(application):
    def wrap_async(func):
        return lambda: asyncio.run(func(application))
    scheduler.add_job(wrap_async(send_auto_price), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# Flask 서버
@app.route("/")
def home():
    return "Coin bot running."

# main 실행
if __name__ == "__main__":
    # Telegram 봇 설정
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 실행
    start_scheduler(application)

    # Flask 서버 백그라운드 실행
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # Telegram run_polling 메인 스레드 실행
    application.run_polling()
