import os
import logging
import asyncio
from flask import Flask
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import feedparser
from deep_translator import GoogleTranslator
import httpx

# .env 로딩
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Flask 앱 생성
app = Flask(__name__)

# 번역기
translator = GoogleTranslator(source="en", target="ko")

# 명령어 핸들러들
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📥 /start 명령어 수신")
    await update.message.reply_text("코인 뉴스봇에 오신 것을 환영합니다!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📥 /news 명령어 수신")
    messages = get_translated_news()
    for msg in messages:
        await update.message.reply_text(msg, parse_mode="HTML")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📥 /price 명령어 수신")
    msg = get_price_change_message()
    await update.message.reply_text(msg, parse_mode="HTML")

# 뉴스 번역
def get_translated_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    entries = feed.entries[:5]
    messages = []
    for entry in reversed(entries):
        try:
            title = translator.translate(entry.title)
            summary = translator.translate(entry.summary)
            link = entry.link
            message = f"<b>{title}</b>\n{summary}\n<a href='{link}'>[기사 보기]</a>"
            messages.append(message)
        except Exception as e:
            logging.error(f"❌ 뉴스 번역 오류: {e}")
    return messages

# 코인 가격 추적
price_cache = {}

def get_price_change_message():
    global price_cache
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    symbols = {"bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL", "dogecoin": "DOGE"}
    msg_lines = ["<b>[코인 시세]</b>"]

    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=krw"
        response = httpx.get(url, timeout=10)
        data = response.json()

        for coin in coins:
            now = data[coin]["krw"]
            old = price_cache.get(coin, now)
            diff = now - old
            emoji = "🔼" if diff > 0 else "🔽" if diff < 0 else "⏺"
            pct = (diff / old * 100) if old else 0
            msg_lines.append(f"{symbols[coin]}: {now:,.0f}원 {emoji} ({pct:+.2f}%)")
            price_cache[coin] = now
    except Exception as e:
        logging.error(f"❌ 가격 정보 오류: {e}")
        return "❌ 코인 가격을 가져오지 못했습니다."
    
    return "\n".join(msg_lines)

# 스케줄러
def start_scheduler(app_bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: app_bot.bot.send_message(chat_id=CHAT_ID, text=get_price_change_message(), parse_mode="HTML"), trigger="interval", minutes=1)
    scheduler.add_job(lambda: [app_bot.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML") for msg in get_translated_news()], trigger="interval", minutes=15)
    scheduler.start()
    logging.info("✅ 스케줄러 실행됨")

# 텔레그램 봇 실행
async def run_bot():
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    start_scheduler(app_bot)
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    logging.info("✅ 텔레그램 봇 작동 중")

# Flask + Telegram 병렬 실행
@app.before_first_request
def start_bot_in_background():
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    logging.info("▶️ Telegram 봇 루프 시작 요청됨")

@app.route("/")
def index():
    return "✅ Telegram Coin Bot is Running!"

# 실행
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
