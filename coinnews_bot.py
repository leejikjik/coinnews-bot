import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
sent_links = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스 봇이 작동 중입니다!")

async def fetch_news():
    url = "https://www.coindeskkorea.com/news/articleList.html?sc_section_code=S1N1&view_type=sm"
    headers = {"User-Agent": "Mozilla/5.0"}
    news_items = []

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(".list-block")
            for article in articles:
                a_tag = article.select_one("a")
                title_tag = article.select_one(".titles")
                summary_tag = article.select_one(".lead")

                if a_tag and title_tag and summary_tag:
                    link = "https://www.coindeskkorea.com" + a_tag["href"]
                    title = title_tag.text.strip()
                    summary = summary_tag.text.strip()

                    if link not in sent_links:
                        news_items.append({
                            "title": title,
                            "summary": summary,
                            "link": link
                        })
    return news_items

async def send_news(application):
    news_list = await fetch_news()
    for news in reversed(news_list):
        if news["link"] not in sent_links:
            msg = f"📰 <b>{news['title']}</b>\n📌 {news['summary']}\n🔗 {news['link']}"
            try:
                await application.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 전송 완료: {news['title']}")
                sent_links.add(news["link"])
            except Exception as e:
                print(f"❌ 전송 실패: {e}")

async def scheduler(application):
    while True:
        try:
            await send_news(application)
        except Exception as e:
            print(f"오류 발생: {e}")
        await asyncio.sleep(60)

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    # 뉴스 보내는 루프 비동기로 실행
    asyncio.create_task(scheduler(application))

    print("✅ 봇 실행 중...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
