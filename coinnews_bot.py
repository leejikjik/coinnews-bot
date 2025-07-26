import os
import asyncio
import logging
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from feedparser import parse
from deep_translator import GoogleTranslator
import requests
from datetime import datetime

# 환경변수 불러오기
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# Flask 서버 (Render keepalive용)
app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

# 뉴스 가져오기
def fetch_news():
    feed_url = 'https://cointelegraph.com/rss'
    feed = parse(feed_url)
    news_items = []
    for entry in feed.entries[:5]:
        title = entry.title
        link = entry.link
        translated = GoogleTranslator(source='auto', target='ko').translate(title)
        news_items.append(f"📰 {translated}\n🔗 {link}")
    return '\n\n'.join(reversed(news_items))

# 가격 추적
prev_prices = {}

def fetch_prices():
    coins = {
        'bitcoin': 'BTC',
        'ethereum': 'ETH',
        'ripple': 'XRP',
        'solana': 'SOL',
        'dogecoin': 'DOGE'
    }
    try:
        res = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=" + ",".join(coins.keys()) + "&vs_currencies=usd")
        data = res.json()
        now = datetime.now().strftime('%H:%M:%S')
        messages = [f"📊 [코인 가격 - {now}]"]
        for k, symbol in coins.items():
            current = data.get(k, {}).get("usd")
            if current:
                before = prev_prices.get(k)
                diff = f"(+{current - before:.2f})" if before and current > before else f"({current - before:.2f})" if before else ""
                messages.append(f"{symbol}: ${current:.2f} {diff}")
                prev_prices[k] = current
        return '\n'.join(messages)
    except Exception as e:
        return f"❌ 가격 정보를 가져오지 못했습니다.\n{e}"

# 텔레그램 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start command received.")
    await update.message.reply_text("👋 안녕하세요! 코인 뉴스 & 가격 추적 봇입니다.\n\n/news : 최신 뉴스\n/price : 현재 가격")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("News command received.")
    text = fetch_news()
    await update.message.reply_text(text)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Price command received.")
    text = fetch_prices()
    await update.message.reply_text(text)

# 주기적 작업
async def scheduled_news(context: ContextTypes.DEFAULT_TYPE):
    try:
        text = fetch_news()
        await context.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logging.error(f"뉴스 전송 실패: {e}")

async def scheduled_price(context: ContextTypes.DEFAULT_TYPE):
    try:
        text = fetch_prices()
        await context.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        logging.error(f"가격 전송 실패: {e}")

# 봇 실행 함수
async def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    # job_queue 시작
    job_queue = application.job_queue
    job_queue.run_repeating(scheduled_news, interval=300, first=10)
    job_queue.run_repeating(scheduled_price, interval=60, first=20)

    await application.initialize()
    await application.start_polling()
    await application.updater.wait()

# 메인 진입점
if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    # Flask 서버와 텔레그램 봇을 asyncio 루프에서 병렬 실행
    loop.create_task(run_bot())

    # Flask 서버 실행
    app.run(host='0.0.0.0', port=10000, use_reloader=False)
