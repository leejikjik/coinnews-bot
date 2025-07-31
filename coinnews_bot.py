import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import httpx
import feedparser
from deep_translator import GoogleTranslator
import pytz

# 기본 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()
logging.basicConfig(level=logging.INFO)

# 시간대 설정
KST = pytz.timezone("Asia/Seoul")

# 주요 코인 목록
COINS = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인",
}

# 개인 DM에서만 응답
def is_private_chat(update: Update):
    return update.effective_chat.type == "private"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private_chat(update):
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 현재 시세")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in feed.entries[:5]:
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        messages.append(f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}")
    await update.message.reply_text("\n\n".join(messages[::-1]))

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    await send_price_message(context.bot, update.effective_chat.id)

# 시세 전송 함수
async def send_price_message(bot, chat_id):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = resp.json()
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        result = [f"📊 주요 코인 시세 ({now})"]
        for coin_id, ko_name in COINS.items():
            coin = next((c for c in data if c["id"] == coin_id), None)
            if coin:
                price = float(coin["quotes"]["USD"]["price"])
                change = float(coin["quotes"]["USD"]["percent_change_1h"])
                result.append(f"{coin['symbol']} ({ko_name})\n💰 {price:.2f} USD ({change:+.2f}% 1h)")
        await bot.send_message(chat_id=chat_id, text="\n\n".join(result))
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 랭킹 전송 함수
async def send_top_rank(bot):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = resp.json()
        sorted_up = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)[:10]
        sorted_down = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"])[:10]
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"📈 1시간 상승률 TOP10 ({now})\n"
        for coin in sorted_up:
            msg += f"{coin['symbol']} ↑ {coin['quotes']['USD']['percent_change_1h']:.2f}%\n"
        msg += f"\n📉 1시간 하락률 TOP10\n"
        for coin in sorted_down:
            msg += f"{coin['symbol']} ↓ {coin['quotes']['USD']['percent_change_1h']:.2f}%\n"
        await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# 급등 감지 함수
async def detect_spike(bot):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = resp.json()
        spikes = [c for c in data if c["quotes"]["USD"]["percent_change_1h"] > 5]
        if spikes:
            msg = f"🚀 급등 알림\n"
            for c in spikes:
                msg += f"{c['symbol']} +{c['quotes']['USD']['percent_change_1h']:.2f}% (1h)\n"
            await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"급등 감지 오류: {e}")

# 스케줄러 래퍼
def start_scheduler(bot):
    def wrap_async(func):
        return lambda: asyncio.get_event_loop().create_task(func(bot))
    scheduler.add_job(wrap_async(send_price_message), "interval", minutes=1, args=[bot, CHAT_ID])
    scheduler.add_job(wrap_async(send_top_rank), "interval", minutes=10)
    scheduler.add_job(wrap_async(detect_spike), "interval", minutes=5)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# Flask 서버
@app.route("/")
def home():
    return "Coin Bot Running!"

# Flask 실행
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# main
if __name__ == "__main__":
    from telegram.ext import Application
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # 스케줄러 및 서버 쓰레드 실행
    threading.Thread(target=run_flask).start()
    start_scheduler(application.bot)

    # run_polling은 asyncio.run 없이 직접 실행
    application.run_polling()
