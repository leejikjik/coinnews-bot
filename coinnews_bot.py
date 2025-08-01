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
from datetime import datetime, timezone, timedelta
from deep_translator import GoogleTranslator
import feedparser
import httpx
from concurrent.futures import ThreadPoolExecutor

# 환경 변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 기본 설정
app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
executor = ThreadPoolExecutor()

# 스케줄러
scheduler = BackgroundScheduler()

# UTC → KST 변환
def utc_to_kst(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=9)))

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:5]:
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published = utc_to_kst(datetime(*entry.published_parsed[:6]))
            msg = f"📰 <b>{translated}</b>\n🕒 {published.strftime('%Y-%m-%d %H:%M')}\n🔗 {entry.link}"
            messages.append(msg)
        for msg in messages:
            await update.message.reply_html(msg)

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        url = "https://api.coinpaprika.com/v1/tickers"
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, timeout=10)
                data = res.json()
                selected = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
                msg = "📊 주요 코인 시세:\n\n"
                for coin in data:
                    if coin["id"] in selected:
                        name = coin["name"]
                        symbol = coin["symbol"]
                        price = float(coin["quotes"]["USD"]["price"])
                        change = float(coin["quotes"]["USD"]["percent_change_1h"])
                        arrow = "📈" if change > 0 else "📉"
                        msg += f"{arrow} {symbol} ({name})\n  💰 ${price:,.2f} ({change:+.2f}%)\n\n"
                await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text("❌ 시세 조회 실패")

# 자동 시세 전송 함수
async def send_auto_price():
    url = "https://api.coinpaprika.com/v1/tickers"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            data = res.json()
            selected = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
            msg = "⏰ <b>2분 간격 시세 업데이트</b>\n\n"
            for coin in data:
                if coin["id"] in selected:
                    name = coin["name"]
                    symbol = coin["symbol"]
                    price = float(coin["quotes"]["USD"]["price"])
                    change = float(coin["quotes"]["USD"]["percent_change_1h"])
                    arrow = "📈" if change > 0 else "📉"
                    msg += f"{arrow} {symbol} ({name})\n  💰 ${price:,.2f} ({change:+.2f}%)\n\n"
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
                )
    except Exception as e:
        logging.error(f"❌ 시세 자동 전송 실패: {e}")

# 비동기 작업을 스레드에서 실행
def schedule_async_task(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro())
    loop.close()

# 스케줄러 실행
def run():
    scheduler.add_job(lambda: executor.submit(schedule_async_task, send_auto_price), "interval", minutes=2)
    scheduler.start()

    app.run(host="0.0.0.0", port=10000)

# 봇 실행
async def main():
    app_builder = ApplicationBuilder().token(TOKEN).build()

    app_builder.add_handler(CommandHandler("start", start))
    app_builder.add_handler(CommandHandler("news", news))
    app_builder.add_handler(CommandHandler("price", price))

    # 봇 run_polling은 메인 루프에서 실행
    await app_builder.initialize()
    await app_builder.start()
    await app_builder.updater.start_polling()
    await app_builder.updater.idle()

# Flask는 백그라운드 스레드에서, 봇은 메인에서
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run)
    flask_thread.start()

    asyncio.run(main())
