import os
import asyncio
import logging
from flask import Flask
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
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
    logging.info("Fetching news...")  # 로그 추가
    feed_url = 'https://cointelegraph.com/rss'
    feed = requests.get(feed_url).json()
    news_items = []
    for entry in feed['entries'][:5]:
        title = entry['title']
        link = entry['link']
        news_items.append(f"📰 {title}\n🔗 {link}")
    return '\n\n'.join(news_items)

# 가격 추적
def fetch_prices():
    logging.info("Fetching prices...")  # 로그 추가
    coins = {
        'bitcoin': 'BTC',
        'ethereum': 'ETH',
        'ripple': 'XRP',
        'solana': 'SOL',
        'dogecoin': 'DOGE'
    }
    try:
        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins.keys())}&vs_currencies=usd")
        data = res.json()
        now = datetime.now().strftime('%H:%M:%S')
        messages = [f"📊 [코인 가격 - {now}]"]
        for k, symbol in coins.items():
            current = data.get(k, {}).get("usd")
            if current:
                messages.append(f"{symbol}: ${current:.2f}")
        return '\n'.join(messages)
    except Exception as e:
        return f"❌ 가격 정보를 가져오지 못했습니다.\n{e}"

# 텔레그램 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start command received.")  # 로그 추가
    await update.message.reply_text("👋 안녕하세요! 코인 뉴스 & 가격 추적 봇입니다.\n\n/news : 최신 뉴스\n/price : 현재 가격")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("News command received.")  # 로그 추가
    text = fetch_news()
    await update.message.reply_text(text)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Price command received.")  # 로그 추가
    text = fetch_prices()
    await update.message.reply_text(text)

# 봇 실행 함수
async def run_bot():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    
    # polling 시작
    await application.initialize()
    await application.start_polling()

# 메인 진입점
if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    # 텔레그램 봇과 Flask 서버를 동일한 이벤트 루프에서 비동기적으로 실행
    loop.create_task(run_bot())

    # Flask 서버 실행
    app.run(host='0.0.0.0', port=10000, use_reloader=False)
