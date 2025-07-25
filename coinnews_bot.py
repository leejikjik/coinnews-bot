import os
import time
import feedparser
import asyncio
import httpx
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime
from deep_translator import GoogleTranslator

from telegram import Bot, Defaults
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RSS_FEED = "https://cointelegraph.com/rss"

default_config = Defaults(parse_mode='HTML')
app_telegram = ApplicationBuilder().token(TOKEN).defaults(default_config).build()
bot = Bot(token=TOKEN)

sent_news = set()
coin_cache = {}

coin_list = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "dogecoin": "DOGE"
}

async def fetch_news():
    global sent_news
    while True:
        feed = feedparser.parse(RSS_FEED)
        entries = sorted(feed.entries, key=lambda x: x.published_parsed)
        for entry in entries:
            if entry.link not in sent_news:
                sent_news.add(entry.link)
                title = entry.title
                link = entry.link
                date_raw = entry.get("published", "")
                try:
                    translated = GoogleTranslator(source='auto', target='ko').translate(title)
                except:
                    translated = title
                msg = f"<b>{translated}</b>\n<a href='{link}'>[원문 보기]</a>\n🕒 {date_raw}"
                try:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, disable_web_page_preview=False)
                except Exception as e:
                    print(f"[뉴스 전송 실패] {e}")
        await asyncio.sleep(60)

async def fetch_prices():
    global coin_cache
    while True:
        async with httpx.AsyncClient() as client:
            for coin in coin_list:
                try:
                    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
                    response = await client.get(url)
                    now = datetime.now().strftime("%H:%M:%S")
                    price = response.json()[coin]["usd"]
                    symbol = coin_list[coin]

                    if coin not in coin_cache:
                        coin_cache[coin] = []
                    coin_cache[coin].append((now, price))

                    if len(coin_cache[coin]) > 5:
                        coin_cache[coin].pop(0)

                except Exception as e:
                    print(f"[가격 수집 오류] {coin}: {e}")
        await asyncio.sleep(60)

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = ["<b>📉 주요 코인 가격 추적 (1분 단위)</b>"]
    for coin in coin_list:
        data = coin_cache.get(coin, [])
        if len(data) >= 2:
            t1, p1 = data[-2]
            t2, p2 = data[-1]
            diff = round(p2 - p1, 2)
            emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
            messages.append(f"{coin_list[coin]} | {t1}: ${p1} → {t2}: ${p2} ({emoji} {diff})")
        else:
            messages.append(f"{coin_list[coin]} | 데이터 수집 중...")
    await update.message.reply_text("\n".join(messages))

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>🤖 CoinNews봇 안내</b>\n"
        "- 실시간 코인 뉴스 자동 전달\n"
        "- 뉴스는 자동으로 한글 번역됩니다\n"
        "- /price: 주요 코인 가격 변화 1분 단위 확인"
    )

app_telegram.add_handler(CommandHandler("start", handle_start))
app_telegram.add_handler(CommandHandler("price", handle_price))

flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "✅ CoinNews 봇 실행 중!"

async def main():
    asyncio.create_task(fetch_news())
    asyncio.create_task(fetch_prices())
    await app_telegram.initialize()
    await app_telegram.start()
    await app_telegram.updater.start_polling()
    await app_telegram.updater.wait_until_closed()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    flask_app.run(host="0.0.0.0", port=10000)
