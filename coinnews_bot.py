import os
import asyncio
import feedparser
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
bot = Bot(token=BOT_TOKEN)

sent_links = set()

async def fetch_cointelegraph_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    news_items = []

    for entry in feed.entries:
        link = entry.link
        if link in sent_links:
            continue
        title = entry.title
        summary = entry.summary
        news_items.append({
            "link": link,
            "title": title,
            "summary": summary,
        })
    return news_items

async def send_news_to_channel():
    news_list = await fetch_cointelegraph_news()
    for news in reversed(news_list):
        if news["link"] not in sent_links:
            message = f"📰 <b>{news['title']}</b>\n📌 {news['summary']}\n\n🔗 {news['link']}"
            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 전송 완료: {news['title']}")
                sent_links.add(news["link"])
            except Exception as e:
                print(f"❌ 전송 실패: {e}")

async def main_loop():
    print("⏰ 코인텔레그래프 뉴스 감지 시작...")
    while True:
        try:
            await send_news_to_channel()
        except Exception as e:
            print(f"오류 발생: {e}")
        await asyncio.sleep(60)

# /start 명령어 처리
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 봇이 정상 작동 중입니다!")

if __name__ == "__main__":
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))

    # 뉴스 전송 루프 실행
    loop = asyncio.get_event_loop()
    loop.create_task(main_loop())

    print("✅ 텔레그램 봇 실행 중...")
    application.run_polling()
