import os
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    Application,
)
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio
import httpx
import feedparser
from deep_translator import GoogleTranslator
import threading

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID")

# Flask 앱 (Render keep-alive)
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Bot is running!"

# 봇 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("✅ 봇이 작동 중입니다!\n/news : 최신 뉴스\n/price : 주요 코인 시세")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("✅ 테스트 성공!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in feed.entries[:5][::-1]:
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 <b>{translated}</b>\n{entry.link}"
        messages.append(msg)
    for msg in messages:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="HTML")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_price(context.bot, update.effective_chat.id)

# 주요 코인 시세
async def send_price(bot, chat_id):
    coins = {
        "bitcoin": "BTC (비트코인)",
        "ethereum": "ETH (이더리움)",
        "ripple": "XRP (리플)",
        "solana": "SOL (솔라나)",
        "dogecoin": "DOGE (도지코인)",
    }
    try:
        async with httpx.AsyncClient() as client:
            prices = {}
            for coin_id, name in coins.items():
                url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    prices[name] = data["quotes"]["USD"]["price"]
            msg = "<b>📊 주요 코인 시세</b>\n"
            for name, price in prices.items():
                msg += f"{name} : ${price:,.2f}\n"
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 급등/하락 랭킹
async def send_ranking(bot):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()
            ranked = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_24h"], reverse=True)
            top10_up = ranked[:10]
            top10_down = ranked[-10:]
            msg = "📈 <b>24시간 상승률 TOP10</b>\n"
            for c in top10_up:
                msg += f"{c['symbol']} : {c['quotes']['USD']['percent_change_24h']:.2f}%\n"
            msg += "\n📉 <b>하락률 TOP10</b>\n"
            for c in top10_down:
                msg += f"{c['symbol']} : {c['quotes']['USD']['percent_change_24h']:.2f}%\n"
            await bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# 자동 뉴스
async def auto_news(bot):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:3][::-1]:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            msg = f"📰 <b>{translated}</b>\n{entry.link}"
            messages.append(msg)
        for msg in messages:
            await bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"뉴스 전송 오류: {e}")

# 스케줄러
def start_scheduler(bot):
    loop = asyncio.get_event_loop()
    scheduler = BackgroundScheduler()

    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_price(bot, GROUP_ID), loop), 'interval', minutes=1)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_ranking(bot), loop), 'interval', minutes=10)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(auto_news(bot), loop), 'interval', hours=1)

    scheduler.start()

# 메인
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # Flask 백그라운드 실행
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=10000)).start()

    # run_polling 전에 스케줄러 시작
    start_scheduler(application.bot)

    application.run_polling()

if __name__ == "__main__":
    main()
