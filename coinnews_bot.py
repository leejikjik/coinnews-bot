import os
import logging
import feedparser
import asyncio
import httpx
from flask import Flask
from pytz import timezone
from datetime import datetime
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from threading import Thread

# 환경변수
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# 시간대
KST = timezone("Asia/Seoul")

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# Flask 앱
app = Flask(__name__)

@app.route("/")
def home():
    return "CoinNews Bot is running."

# 봇 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 봇입니다.\n/news 또는 /price 를 입력해보세요.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_news()
    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await fetch_price()
    await update.message.reply_text(msg)

# 뉴스 수집
async def fetch_news():
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        items = sorted(feed.entries[:5], key=lambda x: x.published_parsed)

        messages = []
        for entry in items:
            title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            summary = GoogleTranslator(source="auto", target="ko").translate(entry.summary)
            link = entry.link
            messages.append(f"📰 <b>{title}</b>\n{summary}\n<a href='{link}'>원문 보기</a>")
        return "\n\n".join(messages)
    except Exception as e:
        logging.error(f"[뉴스 오류] {e}")
        return "❌ 뉴스 로딩 실패"

# 시세 수집
async def fetch_price():
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        symbols = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
        data = resp.json()

        msg = f"📊 실시간 코인 시세\n🕒 {datetime.now(KST).strftime('%H:%M:%S')}\n\n"
        for coin in coins:
            price = data.get(coin, {}).get("usd")
            if price:
                msg += f"{symbols[coin]}: ${price:,.2f}\n"
        return msg
    except Exception as e:
        logging.error(f"[시세 오류] {e}")
        return "❌ 시세 로딩 실패"

# 자동 전송
async def send_auto_news(app):
    msg = await fetch_news()
    await app.bot.send_message(chat_id=CHAT_ID, text=f"🗞️ 코인 뉴스 업데이트\n\n{msg}", parse_mode="HTML", disable_web_page_preview=True)

async def send_auto_price(app):
    msg = await fetch_price()
    await app.bot.send_message(chat_id=CHAT_ID, text=f"💰 실시간 코인 시세\n\n{msg}")

# 스케줄러 실행
def start_scheduler(app):
    scheduler = BackgroundScheduler(timezone=KST)
    scheduler.add_job(lambda: asyncio.run(send_auto_news(app)), 'interval', minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(app)), 'interval', minutes=5)
    scheduler.start()

# 봇 실행
async def main():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    start_scheduler(app_bot)

    await app_bot.run_polling()

# 병렬 실행
def run():
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(main())

if __name__ == "__main__":
    run()
