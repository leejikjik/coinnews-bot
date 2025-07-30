import os
import logging
import threading
import httpx
import feedparser
from datetime import datetime, timedelta
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    filters,
)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # 그룹방 ID

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask 서버
app = Flask(__name__)

@app.route("/")
def index():
    return "Coin News Bot is Running"

# Telegram 앱 생성
application = ApplicationBuilder().token(TOKEN).build()

# 한글명 매핑
KOREAN_NAMES = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "ripple": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
    "binance-coin": "바이낸스코인",
    "cardano": "카르다노",
    "toncoin": "톤코인",
    "shiba-inu": "시바이누",
    "tron": "트론",
}

TOP_COINS = list(KOREAN_NAMES.keys())

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "🟢 코인 뉴스봇 작동 중입니다.\n"
                "/news - 최신 뉴스 확인\n"
                "/price - 주요 코인 시세 확인"
            ),
        )

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_news(update.effective_chat.id, context)

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_price(update.effective_chat.id, context)

# CoinPaprika 시세 조회
async def get_prices():
    url = "https://api.coinpaprika.com/v1/tickers"
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        if res.status_code != 200:
            return []
        return res.json()

# 시세 전송
async def send_price(chat_id, context):
    try:
        data = await get_prices()
        result = ""
        for coin in data:
            if coin["id"] in TOP_COINS:
                name = coin["symbol"]
                kor = KOREAN_NAMES[coin["id"]]
                price = float(coin["quotes"]["USD"]["price"])
                change = float(coin["quotes"]["USD"]["percent_change_24h"])
                result += f"{name} ({kor})\n💰 ${price:,.4f} | 24h {change:+.2f}%\n\n"
        if result:
            await context.bot.send_message(chat_id=chat_id, text="📊 주요 코인 시세:\n\n" + result.strip())
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 급등 코인 감지
async def send_spike_coins(context):
    try:
        data = await get_prices()
        spikes = []
        for coin in data:
            change = float(coin["quotes"]["USD"]["percent_change_24h"])
            if change >= 10:
                name = coin["symbol"]
                price = float(coin["quotes"]["USD"]["price"])
                spikes.append(f"{name} 🚀 ${price:,.4f} ({change:+.2f}%)")
        if spikes:
            msg = "📈 급등 코인 감지:\n\n" + "\n".join(spikes)
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"급등 코인 감지 오류: {e}")

# 상승률/하락률 랭킹
async def send_rankings(context):
    try:
        data = await get_prices()
        sorted_data = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_24h"])
        top = sorted_data[-10:]
        bottom = sorted_data[:10]

        top_msg = "🔼 상승률 TOP 10:\n" + "\n".join(
            f"{c['symbol']} {c['quotes']['USD']['percent_change_24h']:+.2f}%" for c in reversed(top)
        )
        bottom_msg = "🔽 하락률 TOP 10:\n" + "\n".join(
            f"{c['symbol']} {c['quotes']['USD']['percent_change_24h']:+.2f}%" for c in bottom
        )

        await context.bot.send_message(chat_id=CHAT_ID, text=top_msg + "\n\n" + bottom_msg)
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# 뉴스 전송
async def send_news(chat_id, context):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5][::-1]
        msg = "📰 최근 코인 뉴스:\n\n"
        for entry in entries:
            title = GoogleTranslator(source="en", target="ko").translate(entry.title)
            msg += f"• {title}\n{entry.link}\n\n"
        await context.bot.send_message(chat_id=chat_id, text=msg.strip())
    except Exception as e:
        logger.error(f"뉴스 전송 오류: {e}")

# 스케줄러 시작
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: application.create_task(send_price(CHAT_ID, application.bot)), 'interval', minutes=1)
    scheduler.add_job(lambda: application.create_task(send_spike_coins(application.bot)), 'interval', minutes=1)
    scheduler.add_job(lambda: application.create_task(send_rankings(application.bot)), 'interval', minutes=10)
    scheduler.add_job(lambda: application.create_task(send_news(CHAT_ID, application.bot)), 'interval', hours=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# main 실행
def main():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 배포 즉시 전송
    application.create_task(send_price(CHAT_ID, application.bot))
    application.create_task(send_spike_coins(application.bot))
    application.create_task(send_rankings(application.bot))
    application.create_task(send_news(CHAT_ID, application.bot))

    start_scheduler()
    application.run_polling()

# Flask + Bot 병렬 실행
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    main()
