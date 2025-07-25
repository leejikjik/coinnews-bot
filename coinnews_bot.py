import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from flask import Flask
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    Defaults, JobQueue
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from deep_translator import GoogleTranslator
import feedparser
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 타임존
KST = timezone(timedelta(hours=9))

# 추적할 코인 목록
TRACK_COINS = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
price_cache = {}

# Flask 앱 (Render용 KeepAlive)
app = Flask(__name__)
@app.route("/")
def home():
    return "Bot is running."

# 뉴스 크롤링
async def fetch_news():
    rss_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(rss_url)
    articles = feed.entries[:5]
    messages = []
    for entry in reversed(articles):  # 오래된 뉴스부터 출력
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(KST)
        time_str = pub_date.strftime("%Y-%m-%d %H:%M:%S")
        msg = f"📰 <b>{translated}</b>\n{entry.link}\n🕒 {time_str}"
        messages.append(msg)
    return messages

# 뉴스 전송
async def send_news(context: ContextTypes.DEFAULT_TYPE):
    messages = await fetch_news()
    for msg in messages:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

# 가격 추적
async def fetch_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200:
            return response.json().get(symbol, {}).get("usd")
        return None

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    for symbol in TRACK_COINS:
        now = await fetch_price(symbol)
        if now is None:
            continue
        old = price_cache.get(symbol)
        price_cache[symbol] = now
        if old:
            diff = now - old
            direction = "📈 상승" if diff > 0 else ("📉 하락" if diff < 0 else "➖ 보합")
            text = f"💰 {symbol.upper()} 1분 추적\n이전: ${old:.2f} → 현재: ${now:.2f}\n변동: {direction} (${diff:.2f})"
            await context.bot.send_message(chat_id=CHAT_ID, text=text)

# /start 명령어
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 코인 뉴스 & 가격 알림 봇 작동 중!\n"
        "/news : 최근 코인 뉴스 보기\n"
        "/price : 실시간 가격 확인 (1분 전 대비)"
    )
    await update.message.reply_text(text)

# /news 명령어
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = await fetch_news()
    for msg in messages:
        await update.message.reply_text(msg, parse_mode="HTML")

# /price 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    for symbol in TRACK_COINS:
        now = await fetch_price(symbol)
        old = price_cache.get(symbol)
        price_cache[symbol] = now
        if old and now:
            diff = now - old
            direction = "📈" if diff > 0 else ("📉" if diff < 0 else "➖")
            lines.append(f"{symbol.upper()}: ${old:.2f} → ${now:.2f} | {direction} (${diff:.2f})")
        elif now:
            lines.append(f"{symbol.upper()}: 현재가 ${now:.2f} (초기 추적)")
        else:
            lines.append(f"{symbol.upper()}: 데이터 오류")
    await update.message.reply_text("\n".join(lines))

# 메인 함수
async def main():
    defaults = Defaults(tzinfo=KST)
    app_ = ApplicationBuilder().token(TOKEN).defaults(defaults).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("news", news))
    app_.add_handler(CommandHandler("price", price))

    app_.job_queue.run_repeating(track_prices, interval=60, first=10)

    await app_.initialize()
    await app_.start()
    logger.info("🔔 Telegram Bot Started")
    await app_.updater.start_polling()
    await app_.updater.idle()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host='0.0.0.0', port=10000)
