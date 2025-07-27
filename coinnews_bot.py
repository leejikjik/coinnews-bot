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

# 환경변수 로딩
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Flask 앱 설정
app = Flask(__name__)

# 번역기
translator = GoogleTranslator(source="en", target="ko")

# 명령어: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📥 /start 명령어 수신")
    await update.message.reply_text("코인 뉴스봇에 오신 것을 환영합니다!")

# 명령어: /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📥 /news 명령어 수신")
    messages = get_translated_news()
    for msg in messages:
        await update.message.reply_text(msg, parse_mode="HTML")

# 명령어: /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("📥 /price 명령어 수신")
    msg = get_price_change_message()
    await update.message.reply_text(msg, parse_mode="HTML")

# 뉴스 가져오기 및 번역
def get_translated_news():
    feed_url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(feed_url)
    entries = feed.entries[:5]
    messages = []
    for entry in reversed(entries):
        try:
            translated_title = translator.translate(entry.title)
            translated_summary = translator.translate(entry.summary)
            message = f"<b>{translated_title}</b>\n{translated_summary}\n<a href='{entry.link}'>[기사 보기]</a>"
            messages.append(message)
        except Exception as e:
            logging.error(f"❌ 번역 실패: {e}")
    return messages

# 가격 변동 메시지 생성
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
            now_price = data[coin]["krw"]
            old_price = price_cache.get(coin, now_price)
            diff = now_price - old_price
            emoji = "🔼" if diff > 0 else "🔽" if diff < 0 else "⏺"
            percent = (diff / old_price * 100) if old_price else 0
            msg_lines.append(f"{symbols[coin]}: {now_price:,.0f}원 {emoji} ({percent:+.2f}%)")
            price_cache[coin] = now_price

    except Exception as e:
        logging.error(f"❌ 가격 API 오류: {e}")
        return "가격 정보를 불러오지 못했습니다."

    return "\n".join(msg_lines)

# 스케줄러 시작
def start_scheduler(bot_app):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: bot_app.bot.send_message(chat_id=CHAT_ID, text=get_price_change_message(), parse_mode="HTML"), trigger='interval', minutes=1)
    scheduler.add_job(lambda: [bot_app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML") for msg in get_translated_news()], trigger='interval', minutes=15)
    scheduler.start()
    logging.info("✅ 뉴스/시세 스케줄러 시작됨")

# Flask 라우트
@app.route("/")
def index():
    return "✅ Telegram Coin Bot is Running!"

# 텔레그램 봇 실행 함수
async def run_telegram_bot():
    app_bot = Application.builder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))

    start_scheduler(app_bot)

    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    logging.info("✅ 텔레그램 봇 작동 시작됨")

# 메인 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(run_telegram_bot())
    app.run(host="0.0.0.0", port=10000)
