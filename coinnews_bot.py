import os
import asyncio
import logging
import feedparser
import httpx
from flask import Flask
from pytz import timezone
from datetime import datetime
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, BotCommand, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    ContextTypes, Application, Defaults
)
from dotenv import load_dotenv

# 환경변수 불러오기
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 기본 설정
logging.basicConfig(level=logging.INFO)
KST = timezone("Asia/Seoul")
latest_sent_titles = []

# 봇 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📰 코인 뉴스 알림 봇입니다.\n"
        "/start : 도움말\n"
        "/price : 실시간 코인가격\n"
        "매 시간마다 최신 뉴스와 함께 자동 전송됩니다."
    )

# 가격 추적 명령어
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with httpx.AsyncClient() as client:
            url = 'https://api.coingecko.com/api/v3/simple/price'
            params = {
                'ids': 'bitcoin,ethereum',
                'vs_currencies': 'usd',
                'include_24hr_change': 'true'
            }
            r = await client.get(url, params=params)
            data = r.json()

            def fmt(symbol):
                name = symbol.upper()
                price = data[symbol]['usd']
                change = data[symbol]['usd_24h_change']
                emoji = "🔺" if change > 0 else "🔻"
                return f"{name}: ${price:,.2f} ({emoji}{abs(change):.2f}%)"

            msg = "📈 실시간 코인 가격 (24H 기준)\n\n"
            msg += fmt('bitcoin') + "\n"
            msg += fmt('ethereum')
            await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text("가격 정보를 가져오는 중 오류가 발생했습니다.")
        logging.error(e)

# 뉴스 전송 함수
async def send_news():
    global latest_sent_titles
    feed = feedparser.parse("https://cointelegraph.com/rss")
    new_entries = []

    for entry in reversed(feed.entries):  # 오래된 순 정렬
        if entry.title not in latest_sent_titles:
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            pub_date = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            new_entries.append(f"📰 {translated_title}\n🕒 {pub_date}\n\n{translated_summary}\n🔗 {entry.link}")
            latest_sent_titles.append(entry.title)

    if new_entries:
        for entry in new_entries[-3:]:  # 최근 3개까지만 전송
            await app_bot.bot.send_message(chat_id=CHAT_ID, text=entry)

# Flask 앱으로 Render 환경 유지용
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running."

# 스케줄러 세팅
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: asyncio.run(send_news()), 'interval', minutes=60)
scheduler.start()

# 기본 메시지 포맷
defaults = Defaults(tzinfo=KST)

# 텔레그램 앱 빌더
app_bot = ApplicationBuilder().token(TOKEN).defaults(defaults).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("price", price))

# 실행 함수
async def main():
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    await app_bot.updater.wait()

# Render 호환: asyncio.run 대신 직접 루프 실행
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except RuntimeError as e:
        if "already running" in str(e):
            loop.create_task(main())
            loop.run_forever()
        else:
            raise
