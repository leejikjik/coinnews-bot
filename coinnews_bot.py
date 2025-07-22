import os
import logging
import asyncio
import feedparser
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
RSS_FEED_URL = "https://cointelegraph.com/rss"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

latest_titles = set()

async def fetch_rss():
    global latest_titles
    feed = feedparser.parse(RSS_FEED_URL)
    new_items = []

    for entry in feed.entries:
        if entry.title not in latest_titles:
            latest_titles.add(entry.title)
            new_items.append(f"📰 <b>{entry.title}</b>\n{entry.link}")

    return new_items

async def send_news(context: ContextTypes.DEFAULT_TYPE):
    news_items = await fetch_rss()
    for item in news_items:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=item, parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 봇이 작동 중입니다!")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /start 명령어 등록
    app.add_handler(CommandHandler("start", start))

    # 10분마다 뉴스 전송
    app.job_queue.run_repeating(send_news, interval=600, first=10)

    print("🤖 봇이 실행 중입니다...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
