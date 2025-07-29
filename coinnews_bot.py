import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, CallbackContext
)
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from datetime import datetime
import feedparser
import httpx

# 기본 설정
logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
KST = datetime.now().astimezone().tzinfo

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 주요 10종 코인 ID (CoinPaprika 기준)
MAIN_COINS = [
    "bitcoin", "ethereum", "ripple", "solana", "dogecoin",
    "cardano", "polkadot", "tron", "avalanche", "chainlink"
]

async def send_message(bot, text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logging.error(f"메시지 전송 오류: {e}")

# 1. /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("🟢 작동 중\n/price : 코인시세\n/news : 최신뉴스")

# 2. /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_news(context.bot)

# 3. /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_main_prices(context.bot)

# 🔁 주요 10종 시세 출력
async def send_main_prices(bot):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            res.raise_for_status()
            data = res.json()

        output = ["📊 주요 코인 시세"]
        now = datetime.now().astimezone(KST).strftime("%Y-%m-%d %H:%M")
        output.append(f"🕒 {now} 기준\n")

        for coin in data:
            if coin["id"] in MAIN_COINS:
                name = coin["name"]
                symbol = coin["symbol"]
                price = round(coin["quotes"]["USD"]["price"], 3)
                change = coin["quotes"]["USD"]["percent_change_24h"]
                arrow = "🔺" if change > 0 else "🔻"
                output.append(f"{symbol} ({name}) {arrow} {price}$ ({change:+.2f}%)")

        await send_message(bot, "\n".join(output))
    except Exception as e:
        logging.error(f"/price 오류: {e}")

# 🔁 급등 코인 감지 (10% 이상)
async def send_surge_alert(bot):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            res.raise_for_status()
            data = res.json()

        surged = [
            f"{c['symbol']} ({c['name']}) 🔺 {c['quotes']['USD']['percent_change_24h']:.2f}%"
            for c in data if c['quotes']['USD']['percent_change_24h'] >= 10
        ]

        if surged:
            msg = "🚀 급등 코인 알림 (24H +10%)\n\n" + "\n".join(surged)
            await send_message(bot, msg)
    except Exception as e:
        logging.error(f"급등 코인 오류: {e}")

# 🔁 상승률/하락률 랭킹
async def send_top_movers(bot):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            res.raise_for_status()
            data = res.json()

        sorted_up = sorted(data, key=lambda x: x['quotes']['USD']['percent_change_24h'], reverse=True)[:10]
        sorted_down = sorted(data, key=lambda x: x['quotes']['USD']['percent_change_24h'])[:10]

        up_msg = ["📈 24H 상승률 TOP10"]
        for c in sorted_up:
            up_msg.append(f"{c['symbol']} {c['quotes']['USD']['percent_change_24h']:.2f}%")

        down_msg = ["📉 24H 하락률 TOP10"]
        for c in sorted_down:
            down_msg.append(f"{c['symbol']} {c['quotes']['USD']['percent_change_24h']:.2f}%")

        await send_message(bot, "\n".join(up_msg + ["\n"] + down_msg))
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")

# 🔁 뉴스 전송
async def send_news(bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]

        output = ["📰 Cointelegraph 뉴스\n"]
        for entry in entries:
            title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            link = entry.link
            output.append(f"• {title}\n{link}\n")

        await send_message(bot, "\n".join(output))
    except Exception as e:
        logging.error(f"뉴스 전송 오류: {e}")

# Flask (Keepalive용)
@app.route("/")
def index():
    return "✅ Coin Bot 작동 중입니다."

# 봇 및 스케줄러 실행
async def main():
    from telegram.ext import Application
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))

    # 배포 직후 1회 실행
    await send_main_prices(application.bot)
    await send_surge_alert(application.bot)
    await send_top_movers(application.bot)
    await send_news(application.bot)

    # 스케줄러 등록
    scheduler.add_job(lambda: asyncio.run(send_main_prices(application.bot)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_surge_alert(application.bot)), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_top_movers(application.bot)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_news(application.bot)), "interval", hours=1)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

    await application.run_polling()

if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(main())
