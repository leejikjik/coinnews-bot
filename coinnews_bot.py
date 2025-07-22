import asyncio
import os
import feedparser
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # 단일 채널 ID 또는 그룹 ID

# RSS 피드 URL (예: Cointelegraph RSS)
RSS_FEED_URL = "https://cointelegraph.com/rss"

# /start 명령어 처리
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 봇이 작동 중입니다!")

# 뉴스 전송 함수
async def send_latest_news(app):
    feed = feedparser.parse(RSS_FEED_URL)
    if feed.entries:
        entry = feed.entries[0]
        title = entry.title
        link = entry.link
        message = f"📰 최신 코인 뉴스:\n\n📌 {title}\n🔗 {link}"
        await app.bot.send_message(chat_id=CHAT_ID, text=message)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # 봇 실행 전 뉴스 보내기
    await send_latest_news(app)

    # 봇 시작
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
