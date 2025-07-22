# coinnews_bot.py

import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

sent_ids = set()

async def fetch_news():
    url = "https://cointelegraph.com/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select("a.post-card-inline__title-link")
            news_list = []
            for article in articles[:5]:
                link = "https://cointelegraph.com" + article["href"]
                title = article.get_text(strip=True)
                if link not in sent_ids:
                    sent_ids.add(link)
                    news_list.append((title, link))
            return news_list

async def send_news(application):
    news_items = await fetch_news()
    for title, link in news_items:
        message = f"📰 <b>{title}</b>\n🔗 {link}"
        await application.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        print(f"✅ 전송 완료: {title}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 봇이 작동 중입니다!")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # 뉴스 전송 루프
    async def news_loop():
        while True:
            try:
                await send_news(app)
            except Exception as e:
                print(f"오류 발생: {e}")
            await asyncio.sleep(180)

    asyncio.create_task(news_loop())
    print("🚀 코인 뉴스 봇 시작됨")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
