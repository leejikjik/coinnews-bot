import os
import threading
import logging
import feedparser
import asyncio
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from datetime import datetime
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import httpx

# 환경변수
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# 로깅 설정
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# 시간대 설정
KST = timezone("Asia/Seoul")

# Flask 앱
app = Flask(__name__)

# 전역 application 변수
application = None

# 뉴스 수집 함수
def fetch_and_send_news():
    try:
        feed_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(feed_url)
        news_items = []

        for entry in feed.entries[:5][::-1]:  # 오래된 순
            translated_title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            translated_summary = GoogleTranslator(source="auto", target="ko").translate(entry.summary)
            news_items.append(f"📰 <b>{translated_title}</b>\n{translated_summary}\n<a href='{entry.link}'>원문 보기</a>\n")

        message = "\n\n".join(news_items)

        asyncio.run(application.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML", disable_web_page_preview=True))
        print("[뉴스] 전송 완료")
    except Exception as e:
        print("[뉴스 오류]", e)

# 시세 수집 함수
async def fetch_and_send_prices():
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        symbols = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        data = response.json()

        msg = f"📊 실시간 코인 시세 (USD 기준)\n🕒 {datetime.now(KST).strftime('%H:%M:%S')}\n\n"
        for coin in coins:
            price = data.get(coin, {}).get("usd")
            if price:
                msg += f"{symbols[coin]}: ${price:.2f}\n"

        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
        print("[시세] 전송 완료")
    except Exception as e:
        print("[시세 오류]", e)

# 스케줄러 설정
def start_scheduler():
    scheduler = BackgroundScheduler(timezone=KST)
    scheduler.add_job(fetch_and_send_news, "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.run(fetch_and_send_prices()), "interval", minutes=5)
    scheduler.start()

# Telegram 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇입니다. /news 또는 /price 를 입력해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed_url = "https://cointelegraph.com/rss"
        feed = feedparser.parse(feed_url)
        news_items = []

        for entry in feed.entries[:5][::-1]:  # 오래된 순
            translated_title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            translated_summary = GoogleTranslator(source="auto", target="ko").translate(entry.summary)
            news_items.append(f"📰 <b>{translated_title}</b>\n{translated_summary}\n<a href='{entry.link}'>원문 보기</a>\n")

        message = "\n\n".join(news_items)
        await update.message.reply_text(message, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text("❌ 뉴스 로딩 실패")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        symbols = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        data = response.json()

        msg = f"📊 실시간 코인 시세 (USD 기준)\n🕒 {datetime.now(KST).strftime('%H:%M:%S')}\n\n"
        for coin in coins:
            price = data.get(coin, {}).get("usd")
            if price:
                msg += f"{symbols[coin]}: ${price:.2f}\n"

        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text("❌ 시세 조회 실패")

# Telegram 봇 스레드
def telegram_bot_thread():
    global application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    application.run_polling()

# Flask 실행
@app.route("/")
def home():
    return "CoinNews Bot is running."

# 메인 실행
if __name__ == "__main__":
    # Flask 및 Telegram 병렬 실행
    threading.Thread(target=telegram_bot_thread).start()
    threading.Thread(target=start_scheduler).start()
    app.run(host="0.0.0.0", port=10000)
