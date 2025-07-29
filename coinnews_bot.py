import os
import logging
import httpx
import feedparser
from flask import Flask
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from pytz import timezone

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Flask 서버
app = Flask(__name__)

# 로깅
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# 한국 시간
KST = timezone("Asia/Seoul")

# 이전 가격 저장용
last_prices = {}

# 텔레그램 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ 봇 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세"
    )

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    entries = feed.entries[:5][::-1]  # 최신순 정렬

    for entry in entries:
        title = entry.title
        link = entry.link
        translated = GoogleTranslator(source="auto", target="ko").translate(title)
        msg = f"📰 <b>{translated}</b>\n🔗 {link}"
        await update.message.reply_html(msg)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_price(context.bot)

# 가격 가져오기
async def fetch_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            if res.status_code == 200:
                return float(res.json()["price"])
    except Exception as e:
        logging.error(f"{symbol} fetch error: {e}")
    return None

# 가격 출력
async def send_price(bot):
    symbols = {
        "BTCUSDT": "비트코인",
        "ETHUSDT": "이더리움",
        "XRPUSDT": "리플",
        "SOLUSDT": "솔라나",
        "DOGEUSDT": "도지코인",
    }
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    msg = f"📊 코인 시세 (KST 기준 {now})\n\n"

    for symbol, name in symbols.items():
        current = await fetch_price(symbol)
        if current is None:
            msg += f"{name}: 🚫 오류\n"
            continue

        previous = last_prices.get(symbol)
        change = ""
        if previous:
            diff = current - previous
            percent = (diff / previous) * 100
            change = f" ({diff:+.2f} / {percent:+.2f}%)"
        last_prices[symbol] = current
        msg += f"{name}: ${current:,.2f}{change}\n"

    await bot.send_message(chat_id=CHAT_ID, text=msg)

# 스케줄러 실행 함수
def start_scheduler(bot):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: bot.loop.create_task(send_price(bot)), "interval", minutes=1)
    scheduler.add_job(lambda: bot.loop.create_task(send_news(bot)), "interval", hours=1)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# 뉴스 전송 스케줄러용
async def send_news(bot):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    entries = feed.entries[:3][::-1]
    for entry in entries:
        title = entry.title
        link = entry.link
        translated = GoogleTranslator(source="auto", target="ko").translate(title)
        msg = f"📰 <b>{translated}</b>\n🔗 {link}"
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

# Flask 루트
@app.route("/")
def index():
    return "✅ CoinNews Bot 작동 중!"

# main 실행부
if __name__ == "__main__":
    # 텔레그램 봇 초기화
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 시작
    start_scheduler(application.bot)

    # 텔레그램 봇 polling 시작 (동기 방식)
    import threading
    threading.Thread(target=application.run_polling, daemon=True).start()

    # Flask 앱 실행
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
