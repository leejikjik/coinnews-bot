# coinnews_bot.py

import os
import logging
import asyncio
import httpx
import feedparser
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from datetime import datetime, timedelta
import pytz

# 환경변수에서 토큰과 채팅 ID 읽기 (Render 환경 변수 UI 사용)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 주요 코인 목록
TRACK_COINS = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
COIN_SYMBOLS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ripple": "XRP",
    "solana": "SOL",
    "dogecoin": "DOGE"
}

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# 가격 저장용 딕셔너리
previous_prices = {}

# 번역기 초기화
translator = GoogleTranslator(source="auto", target="ko")

# 텔레그램 봇 Application 객체 생성
bot = ApplicationBuilder().token(BOT_TOKEN).build()

# /start 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 알리미 봇입니다.\n/news 또는 /price 명령어를 사용해보세요.")

# /news 명령어 핸들러
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed_url = "https://cointelegraph.com/rss"
    parsed_feed = feedparser.parse(feed_url)
    messages = []

    for entry in parsed_feed.entries[:5][::-1]:  # 오래된 뉴스부터 5개
        title = translator.translate(entry.title)
        link = entry.link
        published = datetime(*entry.published_parsed[:6]).astimezone(pytz.timezone("Asia/Seoul")).strftime('%Y-%m-%d %H:%M')
        messages.append(f"📰 <b>{title}</b>\n🕒 {published}\n🔗 {link}")

    for msg in messages:
        await update.message.reply_html(msg)

# /price 명령어 핸들러
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_price_message()
    if msg:
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("❌ 시세 정보를 불러오지 못했습니다.")

# 시세 메시지 생성 함수
async def get_price_message():
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            data = response.json()
        
        price_map = {item["symbol"]: float(item["price"]) for item in data}
        msg = "📈 코인 시세 (1분 변화 기준)\n"

        for coin in TRACK_COINS:
            symbol = COIN_SYMBOLS[coin].upper()
            pair = symbol + "USDT"
            current_price = price_map.get(pair)

            if not current_price:
                continue

            previous = previous_prices.get(symbol)
            diff = ""
            if previous:
                change = current_price - previous
                percent = (change / previous) * 100 if previous != 0 else 0
                emoji = "🔺" if change > 0 else ("🔻" if change < 0 else "➖")
                diff = f"{emoji} {change:+.2f} ({percent:+.2f}%)"
            else:
                diff = "🔄 변화 정보 없음"

            msg += f"\n{symbol}: ${current_price:.2f}  {diff}"
            previous_prices[symbol] = current_price

        return msg

    except Exception as e:
        logging.error(f"가격 불러오기 오류: {e}")
        return None

# 자동 뉴스 전송 함수
async def send_auto_news():
    feed_url = "https://cointelegraph.com/rss"
    parsed_feed = feedparser.parse(feed_url)

    messages = []
    for entry in parsed_feed.entries[:3][::-1]:  # 최근 3개 뉴스
        title = translator.translate(entry.title)
        link = entry.link
        published = datetime(*entry.published_parsed[:6]).astimezone(pytz.timezone("Asia/Seoul")).strftime('%Y-%m-%d %H:%M')
        messages.append(f"📰 <b>{title}</b>\n🕒 {published}\n🔗 {link}")

    for msg in messages:
        await bot.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

# 자동 시세 전송 함수
async def send_auto_price():
    msg = await get_price_message()
    if msg:
        await bot.bot.send_message(chat_id=CHAT_ID, text=msg)

# 스케줄러 설정
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), "interval", minutes=1)
    scheduler.start()
    logging.info("✅ 스케줄러 시작됨")

# Flask 루트 페이지
@app.route("/")
def home():
    return "✅ Telegram Coin News Bot is running."

# 봇 명령어 핸들러 등록
bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("news", news))
bot.add_handler(CommandHandler("price", price))

# 메인 실행
if __name__ == "__main__":
    import threading

    def flask_thread():
        app.run(host="0.0.0.0", port=10000)

    def bot_thread():
        start_scheduler()
        bot.run_polling()

    threading.Thread(target=flask_thread).start()
    threading.Thread(target=bot_thread).start()
