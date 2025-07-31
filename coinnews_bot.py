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

# 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROUP_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()
logging.basicConfig(level=logging.INFO)

# 번역기
def translate(text):
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text)
    except:
        return text

# 명령어: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🟢 코인 뉴스 봇 작동 중\n/news : 최신 뉴스\n/price : 실시간 시세"
        )

# 명령어: /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5][::-1]
        for entry in entries:
            translated = translate(entry.title)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📰 {translated}\n{entry.link}"
            )
    except Exception as e:
        logging.error(f"뉴스 오류: {e}")

# 시세 출력 함수
async def send_price_message(bot, chat_id):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = resp.json()

        target_ids = {
            "bitcoin": "BTC (비트코인)",
            "ethereum": "ETH (이더리움)",
            "ripple": "XRP (리플)",
            "solana": "SOL (솔라나)",
            "dogecoin": "DOGE (도지코인)"
        }

        result = []
        now = datetime.now().strftime("%H:%M:%S")
        for coin in data:
            if coin['id'] in target_ids:
                name = target_ids[coin['id']]
                price = float(coin['quotes']['USD']['price'])
                percent = float(coin['quotes']['USD']['percent_change_1h'])
                sign = "🔺" if percent >= 0 else "🔻"
                result.append(f"{name}: ${price:,.2f} ({sign}{percent:.2f}%)")

        message = f"⏰ {now} 기준 주요 코인 시세\n" + "\n".join(result)
        await bot.send_message(chat_id=chat_id, text=message)

    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 상승률/하락률 랭킹
async def send_top_rank(bot):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = resp.json()

        sorted_up = sorted(data, key=lambda x: x['quotes']['USD']['percent_change_1h'], reverse=True)[:10]
        sorted_down = sorted(data, key=lambda x: x['quotes']['USD']['percent_change_1h'])[:10]

        msg = "📈 1시간 상승률 Top 10\n"
        for coin in sorted_up:
            symbol = coin['symbol']
            name = coin['name']
            pct = coin['quotes']['USD']['percent_change_1h']
            msg += f"{symbol} ({name}) +{pct:.2f}%\n"

        msg += "\n📉 1시간 하락률 Top 10\n"
        for coin in sorted_down:
            symbol = coin['symbol']
            name = coin['name']
            pct = coin['quotes']['USD']['percent_change_1h']
            msg += f"{symbol} ({name}) {pct:.2f}%\n"

        await bot.send_message(chat_id=GROUP_ID, text=msg)
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# 급등 감지
async def detect_spike(bot):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = resp.json()

        now = datetime.utcnow()
        spike_list = []

        for coin in data:
            change = coin['quotes']['USD']['percent_change_1h']
            if change and change >= 5:
                spike_list.append((coin['symbol'], coin['name'], change))

        if spike_list:
            msg = f"🚨 최근 1시간 급등 코인\n"
            for s, n, c in spike_list:
                msg += f"{s} ({n}) +{c:.2f}%\n"
            await bot.send_message(chat_id=GROUP_ID, text=msg)

    except Exception as e:
        logging.error(f"급등 감지 오류: {e}")

# 명령어: /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_price_message(context.bot, update.effective_chat.id)

# 스케줄러 실행
def start_scheduler(bot):
    def wrap_async(func, *args):
        return lambda: asyncio.get_event_loop().create_task(func(*args))

    scheduler.add_job(wrap_async(send_price_message, bot, GROUP_ID), "interval", minutes=1, next_run_time=datetime.now())
    scheduler.add_job(wrap_async(send_top_rank, bot), "interval", minutes=10, next_run_time=datetime.now())
    scheduler.add_job(wrap_async(detect_spike, bot), "interval", minutes=5, next_run_time=datetime.now())

    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# Flask용 Keepalive
@app.route("/")
def index():
    return "Coin Bot Active"

# 실행
if __name__ == "__main__":
    from telegram.ext import Application

    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 봇은 asyncio 루프에서 실행
    loop = asyncio.get_event_loop()
    loop.create_task(application.initialize())
    loop.create_task(application.start())

    # 스케줄러 시작
    loop.call_soon(lambda: start_scheduler(application.bot))

    # Flask는 백그라운드 실행
    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 10000}).start()

    loop.run_forever()
