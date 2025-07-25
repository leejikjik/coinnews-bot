# bot.py
import os
import asyncio
import feedparser
from telegram import Bot
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RSS_FEED_URL = "https://cointelegraph.com/rss"
CHECK_INTERVAL = 300  # 5분

bot = Bot(token=TELEGRAM_TOKEN)
sent_links_file = "sent_links.txt"
sent_links = set()

def load_sent_links():
    if os.path.exists(sent_links_file):
        with open(sent_links_file, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_links():
    with open(sent_links_file, "w", encoding="utf-8") as f:
        for link in sent_links:
            f.write(link + "\n")

async def fetch_and_send():
    global sent_links
    sent_links = load_sent_links()
    print(f"[{datetime.now()}] 봇 시작됨. 이전 뉴스 {len(sent_links)}건 로드됨.")

    while True:
        try:
            print(f"[{datetime.now()}] 새 뉴스 체크 중...")
            feed = feedparser.parse(RSS_FEED_URL)
            new_count = 0
            for entry in feed.entries:
                if entry.link not in sent_links:
                    sent_links.add(entry.link)
                    published = entry.get("published", "")
                    message = f"\u2728 *{entry.title}*\n{published}\n{entry.link}"
                    try:
                        await bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            text=message,
                            parse_mode='Markdown',
                            disable_web_page_preview=False
                        )
                        print(f"[{datetime.now()}] [SENT] {entry.title}")
                        new_count += 1
                    except Exception as e:
                        print(f"[{datetime.now()}] [ERROR] 전송 실패: {e}")
            if new_count:
                save_sent_links()
        except Exception as e:
            print(f"[{datetime.now()}] [ERROR] 피드 파싱 실패: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(fetch_and_send())
    except KeyboardInterrupt:
        print(f"[{datetime.now()}] 종료됨.")
        save_sent_links()
