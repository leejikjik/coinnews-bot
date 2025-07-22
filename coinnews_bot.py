import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup

# 로그 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# .env 불러오기
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# 코인 뉴스 가져오기 함수
async def fetch_coin_news():
    url = "https://cointelegraph.com/"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.select("a.post-card-inline__title-link")[:5]  # 상위 5개

            news = []
            for article in articles:
                title = article.text.strip()
                link = "https://cointelegraph.com" + article.get("href")
                news.append(f"📰 {title}\n🔗 {link}")
            return "\n\n".join(news)
    except Exception as e:
        logging.error(f"❌ 뉴스 크롤링 실패: {e}")
        return "🚫 코인 뉴스를 불러오지 못했습니다."

# /start 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 코인 뉴스 봇이 정상 작동 중입니다!")

# 뉴스 자동 전송 루프
async def send_news_periodically(app):
    while True:
        news = await fetch_coin_news()
        try:
            await app.bot.send_message(chat_id=CHANNEL_ID, text=news)
            logging.info("✅ 뉴스 전송 성공")
        except Exception as e:
            logging.error(f"❌ 뉴스 전송 실패: {e}")
        await asyncio.sleep(60 * 60)  # 1시간마다 전송

# 메인 함수
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # 뉴스 전송 작업 비동기로 실행
    asyncio.create_task(send_news_periodically(app))

    print("✅ 코인 뉴스 봇 시작됨...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
