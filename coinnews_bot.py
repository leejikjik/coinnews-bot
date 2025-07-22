import os
import asyncio
import aiohttp
import logging
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Bot
from datetime import datetime

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# .env 파일 로드
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# 봇 초기화
bot = Bot(token=BOT_TOKEN)

# 중복 전송 방지용 ID 저장소
sent_ids = set()

# 코인니스 뉴스 크롤링 함수
async def fetch_coinness_news():
    url = "https://kr.coinness.com"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as res:
            html = await res.text()
            soup = BeautifulSoup(html, "html.parser")
            articles = soup.select(".news_list .list_content li")
            news_items = []
            for item in articles:
                link_tag = item.find("a", href=True)
                if not link_tag:
                    continue
                link = url + link_tag["href"]
                news_id = link.split("/")[-1]
                if news_id in sent_ids:
                    continue
                title = item.find("p", class_="title")
                summary = item.find("p", class_="summary")
                if title and summary:
                    news_items.append({
                        "id": news_id,
                        "title": title.get_text(strip=True),
                        "summary": summary.get_text(strip=True),
                        "link": link
                    })
            return news_items

# 채널로 뉴스 전송 함수
async def send_news_to_channel():
    news_list = await fetch_coinness_news()
    for news in reversed(news_list):
        if news["id"] not in sent_ids:
            message = f"📰 <b>{news['title']}</b>\n📌 {news['summary']}\n\n🔗 {news['link']}"
            try:
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 전송 완료: {news['title']}")
                sent_ids.add(news["id"])
            except Exception as e:
                logger.error(f"❌ 전송 실패: {e}")

# 주기 실행 루프
async def main_loop():
    logger.info("⏰ 코인니스 뉴스 감지 시작...")
    while True:
        try:
            await send_news_to_channel()
        except Exception as e:
            logger.error(f"오류 발생: {e}")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main_loop())
