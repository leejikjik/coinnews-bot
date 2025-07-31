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
from datetime import datetime, timedelta
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 주요 코인 목록 및 한글명 매핑
COINS = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인"
}

# Flask keep-alive
@app.route("/")
def index():
    return "Coin News Bot Running"

# 개인 채팅 체크
def is_private_chat(update: Update):
    return update.effective_chat.type == "private"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private_chat(update):
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 주요 코인 시세\n/test : 작동 확인")

# /test
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private_chat(update):
        await update.message.reply_text("✅ 봇이 정상 작동 중입니다.\nFlask + Telegram + Scheduler 모두 실행 중.")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        messages = []
        for entry in reversed(entries):
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            messages.append(f"📰 <b>{translated_title}</b>\n{entry.link}")
        for msg in messages:
            await update.message.reply_html(msg)
    except Exception as e:
        logger.error(f"뉴스 전송 오류: {e}")
        await update.message.reply_text("❌ 뉴스 로딩에 실패했습니다.")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    await send_price(context.bot, update.effective_chat.id)

# 시세 전송 함수
async def send_price(bot: Bot, chat_id):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        lines = []
        now = datetime.now().strftime("%H:%M:%S")
        lines.append(f"📊 주요 코인 시세 ({now})")
        for coin_id, kor_name in COINS.items():
            coin = next((c for c in data if c['id'] == coin_id), None)
            if coin:
                symbol = coin['symbol']
                price = round(coin['quotes']['USD']['price'], 4)
                change = coin['quotes']['USD']['percent_change_1h']
                lines.append(f"{symbol} ({kor_name})\n💰 ${price:,} ({change:+.2f}%)\n")

        await bot.send_message(chat_id=chat_id, text="\n".join(lines))
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 랭킹 전송
async def send_rank(bot: Bot, chat_id):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        sorted_up = sorted(data, key=lambda x: x['quotes']['USD']['percent_change_24h'], reverse=True)[:10]
        sorted_down = sorted(data, key=lambda x: x['quotes']['USD']['percent_change_24h'])[:10]

        msg = "📈 24시간 상승률 TOP 10:\n"
        for coin in sorted_up:
            msg += f"{coin['symbol']} ({coin['name']}) {coin['quotes']['USD']['percent_change_24h']:+.2f}%\n"
        msg += "\n📉 24시간 하락률 TOP 10:\n"
        for coin in sorted_down:
            msg += f"{coin['symbol']} ({coin['name']}) {coin['quotes']['USD']['percent_change_24h']:+.2f}%\n"

        await bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# 급등 감지
async def detect_spike(bot: Bot, chat_id):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        spikes = [coin for coin in data if coin['quotes']['USD']['percent_change_1h'] >= 5]
        if not spikes:
            return

        msg = "🚨 1시간 내 급등 코인:\n"
        for coin in spikes:
            msg += f"{coin['symbol']} ({coin['name']}) {coin['quotes']['USD']['percent_change_1h']:+.2f}%\n"
        await bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

# 배포 직후 1회 전송
async def send_initial(bot: Bot):
    await send_price(bot, CHAT_ID)
    await send_rank(bot, CHAT_ID)
    await detect_spike(bot, CHAT_ID)

# 봇 및 스케줄러 실행
def run_bot():
    from telegram.ext import Application
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("test", test))

    loop = asyncio.get_event_loop()
    bot = application.bot

    # 스케줄러 작업 등록
    scheduler.add_job(lambda: asyncio.run(send_price(bot, CHAT_ID)), 'interval', minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_rank(bot, CHAT_ID)), 'interval', minutes=10)
    scheduler.add_job(lambda: asyncio.run(detect_spike(bot, CHAT_ID)), 'interval', minutes=1)

    scheduler.start()
    loop.create_task(application.run_polling())
    loop.create_task(send_initial(bot))
    loop.run_forever()

# 시작
if __name__ == "__main__":
    run_bot()
    app.run(host="0.0.0.0", port=10000)
