# bot.py
import os
import asyncio
import feedparser
import httpx
import pytz
from telegram import Bot
from datetime import datetime
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from email.utils import parsedate_to_datetime

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RSS_FEED_URL = "https://cointelegraph.com/rss"
CHECK_INTERVAL = 60  # 1분

bot = Bot(token=TELEGRAM_TOKEN)
sent_links_file = "sent_links.txt"
sent_links = set()
prev_prices = {}

COINS = {
    "bitcoin": "BTC",
    "ethereum": "ETH"
}

async def fetch_prices():
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(COINS.keys())}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url)
            data = resp.json()
            return {COINS[coin]: data[coin]['usd'] for coin in COINS}
        except:
            return {}

def load_sent_links():
    if os.path.exists(sent_links_file):
        with open(sent_links_file, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_links():
    with open(sent_links_file, "w", encoding="utf-8") as f:
        for link in sent_links:
            f.write(link + "\n")

async def send_news():
    global sent_links
    sent_links = load_sent_links()
    print(f"[{datetime.now()}] 뉴스 확인 시작")

    feed = feedparser.parse(RSS_FEED_URL)
    for entry in feed.entries:
        if entry.link not in sent_links:
            sent_links.add(entry.link)
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            title_prefix = "🚨 [속보] " if any(k in entry.title.lower() for k in ["breaking", "urgent", "alert"]) else "✨ "
            try:
                pub_dt = parsedate_to_datetime(entry.published)
                pub_dt_kst = pub_dt.astimezone(pytz.timezone("Asia/Seoul"))
                pub_str = pub_dt_kst.strftime("%Y-%m-%d %H:%M (KST)")
            except:
                pub_str = "시간 정보 없음"

            message = f"{title_prefix}*{translated_title}*\n🕒 {pub_str}\n{entry.link}"
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=False
                )
                print(f"[SENT] {translated_title}")
            except Exception as e:
                print(f"[ERROR] 전송 실패: {e}")
    save_sent_links()

async def send_price_diff():
    global prev_prices
    current = await fetch_prices()
    if not current:
        return

    if prev_prices:
        lines = ["💰 *1분 단위 코인 변동 상황*\n"]
        for coin, symbol in COINS.items():
            before = prev_prices.get(symbol)
            now = current.get(symbol)
            if before and now:
                diff = now - before
                pct = (diff / before) * 100
                emoji = "📈" if diff > 0 else "📉"
                strong = "🔥급등" if abs(pct) >= 3 else ""
                lines.append(f"{emoji} {symbol}: {before:.2f} → {now:.2f} (Δ {diff:+.2f}, {pct:+.2f}%) {strong}")
        msg = "\n".join(lines)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode='Markdown')
    prev_prices = current

async def run_bot():
    while True:
        await send_news()
        await send_price_diff()
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("[종료]")
        save_sent_links()
        
