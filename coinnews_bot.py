import os
import logging
import asyncio
import threading
from datetime import datetime, timedelta
import feedparser
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
import httpx

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Flask 앱
app = Flask(__name__)

# 로그 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# 가격 캐시
coin_cache = {}

# 시세 알림 함수
async def send_auto_price(application):
    url = "https://api.binance.com/api/v3/ticker/price"
    coins = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            result = response.json()
            now = datetime.now().strftime("%H:%M:%S")

            if isinstance(result, list):
                msg = f"📉 코인 시세 (Binance 기준)\n⏰ {now} 기준\n\n"
                for coin in coins:
                    coin_data = next((x for x in result if x["symbol"] == coin), None)
                    if coin_data:
                        symbol = coin.replace("USDT", "")
                        price = float(coin_data["price"])
                        prev_price = coin_cache.get(coin)
                        diff = f"{price - prev_price:.2f}" if prev_price else "N/A"
                        diff_str = f" ({diff:+.2f})" if prev_price else ""
                        msg += f"{symbol}: ${price:,.2f}{diff_str}\n"
                        coin_cache[coin] = price
                await application.bot.send_message(chat_id=CHAT_ID, text=msg)
            else:
                logging.error("[시세 오류] API 응답이 리스트 아님")
    except Exception as e:
        logging.error(f"[시세 오류] {e}")

# 뉴스 알림 함수
async def send_auto_news(application):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        if not entries:
            return
        msg = "📰 Cointelegraph 뉴스 (최신순)\n\n"
        for entry in reversed(entries):
            title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            link = entry.link
            msg += f"• <b>{title}</b>\n{link}\n\n"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"[뉴스 오류] {e}")

# 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇 작동 중\n/news : 뉴스\n/price : 코인 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        msg = "📰 최신 뉴스\n\n"
        for entry in reversed(entries):
            title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            msg += f"• <b>{title}</b>\n{entry.link}\n\n"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text("뉴스를 불러오지 못했습니다.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.binance.com/api/v3/ticker/price"
    coins = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            result = response.json()
            now = datetime.now().strftime("%H:%M:%S")
            msg = f"📉 실시간 시세\n⏰ {now} 기준\n\n"
            for coin in coins:
                coin_data = next((x for x in result if x["symbol"] == coin), None)
                if coin_data:
                    symbol = coin.replace("USDT", "")
                    price = float(coin_data["price"])
                    prev_price = coin_cache.get(coin)
                    diff = f"{price - prev_price:.2f}" if prev_price else "N/A"
                    diff_str = f" ({diff:+.2f})" if prev_price else ""
                    msg += f"{symbol}: ${price:,.2f}{diff_str}\n"
                    coin_cache[coin] = price
            await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text("시세 데이터를 불러오지 못했습니다.")

# 스케줄러 실행
def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(application)), "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(application)), "interval", minutes=1)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# Flask + 스케줄러 쓰레드
def flask_thread(application):
    start_scheduler(application)
    app.run(host="0.0.0.0", port=10000)

# 봇 실행
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    threading.Thread(target=flask_thread, args=(application,), daemon=True).start()
    application.run_polling()

if __name__ == "__main__":
    main()
