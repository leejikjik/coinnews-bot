import os
import asyncio
import logging
import feedparser
from flask import Flask
from deep_translator import GoogleTranslator
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Flask 앱
app = Flask(__name__)

@app.route("/")
def index():
    return "Coin News Bot is running!"

# 뉴스 번역 및 전송
def fetch_and_send_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    if not feed.entries:
        logging.warning("RSS 뉴스가 없습니다.")
        return

    entries = feed.entries[:5][::-1]  # 최신순 → 오래된순으로 출력
    bot = Bot(token=BOT_TOKEN)

    for entry in entries:
        title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        link = entry.link
        message = f"📰 {title}\n{link}"
        try:
            bot.send_message(chat_id=CHAT_ID, text=message)
        except Exception as e:
            logging.error(f"뉴스 전송 실패: {e}")

# 명령어 핸들러
async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스봇이 작동 중입니다.")

async def news_command(update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    if not feed.entries:
        await update.message.reply_text("뉴스를 가져올 수 없습니다.")
        return

    entries = feed.entries[:5][::-1]
    for entry in entries:
        title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        link = entry.link
        message = f"📰 {title}\n{link}"
        await update.message.reply_text(message)

# Telegram Bot 실행
async def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("news", news_command))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logging.info("🤖 Telegram Bot Started")

# Scheduler 시작
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(fetch_and_send_news, 'interval', minutes=60)
    scheduler.start()
    logging.info("✅ Scheduler Started")

# 진입점
def start():
    loop = asyncio.get_event_loop()
    start_scheduler()
    loop.run_until_complete(run_bot())

if __name__ == "__main__":
    start()
    app.run(host="0.0.0.0", port=10000)
