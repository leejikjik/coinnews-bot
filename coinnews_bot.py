import os
import logging
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 주요 코인 설정
COINS = {
    "bitcoin": "BTC (비트코인)",
    "ethereum": "ETH (이더리움)",
    "xrp": "XRP (리플)",
    "solana": "SOL (솔라나)",
    "dogecoin": "DOGE (도지코인)",
}

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# 텔레그램 명령어 핸들러들
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("✅ 코인 뉴스/시세 알림 봇입니다.\n/news : 최신 뉴스\n/price : 주요 코인 시세")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        msgs = []
        for entry in feed.entries[:5][::-1]:  # 오래된 순 정렬
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            msgs.append(f"📰 {translated}\n{entry.link}")
        await update.message.reply_text("\n\n".join(msgs))
    except Exception as e:
        logging.error(f"뉴스 오류: {e}")
        await update.message.reply_text("뉴스를 불러오지 못했습니다.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            tickers = res.json()
            msg = "📈 실시간 코인 시세\n\n"
            for cid, name in COINS.items():
                coin = next((c for c in tickers if c["id"] == cid), None)
                if coin:
                    price = float(coin["quotes"]["USD"]["price"])
                    change = float(coin["quotes"]["USD"]["percent_change_1h"])
                    emoji = "🔺" if change >= 0 else "🔻"
                    msg += f"{name}\n{price:,.2f} USD {emoji} ({change:+.2f}%)\n\n"
        await update.message.reply_text(msg.strip())
    except Exception as e:
        logging.error(f"시세 오류: {e}")
        await update.message.reply_text("시세 정보를 불러오지 못했습니다.")

# 자동 시세 전송
async def send_price_message(bot, chat_id):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            tickers = res.json()
            msg = "📊 주요 코인 시세\n\n"
            for cid, name in COINS.items():
                coin = next((c for c in tickers if c["id"] == cid), None)
                if coin:
                    price = float(coin["quotes"]["USD"]["price"])
                    change = float(coin["quotes"]["USD"]["percent_change_1h"])
                    emoji = "🔺" if change >= 0 else "🔻"
                    msg += f"{name}\n{price:,.2f} USD {emoji} ({change:+.2f}%)\n\n"
        await bot.send_message(chat_id=chat_id, text=msg.strip())
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")

# 급등 감지
async def detect_spike(bot):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            tickers = res.json()
            spikes = []
            for c in tickers:
                change = float(c["quotes"]["USD"]["percent_change_1h"])
                if change > 5:
                    spikes.append(f"🚀 {c['symbol']} +{change:.2f}%")
            if spikes:
                await bot.send_message(chat_id=CHAT_ID, text="📡 급등 알림:\n" + "\n".join(spikes))
    except Exception as e:
        logging.error(f"급등 감지 오류: {e}")

# 상승/하락률 랭킹
async def send_top_rank(bot):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            tickers = res.json()
            tickers = [t for t in tickers if float(t["quotes"]["USD"]["volume_24h"]) > 10_000_000]

            top_gainers = sorted(tickers, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)[:10]
            top_losers = sorted(tickers, key=lambda x: x["quotes"]["USD"]["percent_change_1h"])[:10]

            msg = "🏆 1시간 상승률 TOP 10\n"
            for coin in top_gainers:
                msg += f"🔺 {coin['symbol']} {coin['quotes']['USD']['percent_change_1h']:.2f}%\n"

            msg += "\n📉 1시간 하락률 TOP 10\n"
            for coin in top_losers:
                msg += f"🔻 {coin['symbol']} {coin['quotes']['USD']['percent_change_1h']:.2f}%\n"

            await bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# 스케줄러 시작
def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_price_message(application.bot, CHAT_ID)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_top_rank(application.bot)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(detect_spike(application.bot)), "interval", minutes=5)

    # 배포 직후 1회 실행
    asyncio.run(send_price_message(application.bot, CHAT_ID))
    asyncio.run(send_top_rank(application.bot))
    asyncio.run(detect_spike(application.bot))

    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# 봇 실행
async def main():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    start_scheduler(application)
    await application.run_polling()

# Flask keepalive
@app.route("/")
def home():
    return "Bot is running!"

# 최종 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
