import os
import logging
import asyncio
from flask import Flask
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pytz import timezone
import feedparser
from deep_translator import GoogleTranslator
import httpx

# === 기본 설정 ===
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()
application = ApplicationBuilder().token(TOKEN).build()
bot = Bot(token=TOKEN)

# === 이전 가격 저장용 ===
previous_prices = {}

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세"
        )

# === /news ===
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        items = feed.entries[:5][::-1]  # 오래된 뉴스부터
        msgs = []

        for item in items:
            title = GoogleTranslator(source="en", target="ko").translate(item.title)
            link = item.link
            published = item.published
            msgs.append(f"📰 <b>{title}</b>\n{published}\n<a href='{link}'>원문 보기</a>\n")

        for msg in msgs:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[뉴스 오류] {e}")

# === /price ===
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await send_auto_price(context.bot)
    except Exception as e:
        logger.error(f"[수동 시세 오류] {e}")

# === 시세 자동 전송 ===
async def send_auto_price(bot: Bot):
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        coins = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
        names = {
            "BTCUSDT": "BTC",
            "ETHUSDT": "ETH",
            "XRPUSDT": "XRP",
            "SOLUSDT": "SOL",
            "DOGEUSDT": "DOGE"
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.error(f"[시세 오류] Binance API 응답 코드: {resp.status_code}")
                return

            data = resp.json()
            if not isinstance(data, list):
                logger.error(f"[시세 오류] 잘못된 응답 형식: {data}")
                return

        kst_now = datetime.now(timezone("Asia/Seoul")).strftime("%H:%M:%S")
        lines = [f"📉 {kst_now} 기준 실시간 코인 시세"]

        for coin in coins:
            price = float(next((i["price"] for i in data if i["symbol"] == coin), 0))
            prev = previous_prices.get(coin, price)
            diff = price - prev
            percent = (diff / prev * 100) if prev else 0
            emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            lines.append(f"{names[coin]}: ${price:,.2f} {emoji} ({diff:+.2f}, {percent:+.2f}%)")
            previous_prices[coin] = price

        await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines))
    except Exception as e:
        logger.error(f"[시세 오류] {e}")

# === 스케줄러 ===
def start_scheduler():
    scheduler.add_job(
        lambda: asyncio.run(send_auto_price(bot)),
        trigger="interval",
        seconds=60,
    )
    scheduler.start()
    logger.info("✅ 스케줄러 시작됨")

# === Flask 기본 라우팅 ===
@app.route("/")
def index():
    return "✅ CoinNews Bot is running!"

# === 봇 실행 스레드 ===
def run_bot():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    application.run_polling()

# === 메인 실행 ===
if __name__ == "__main__":
    import threading

    threading.Thread(target=run_bot).start()
    start_scheduler()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
