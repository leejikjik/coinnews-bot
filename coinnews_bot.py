# bot.py
import os
import asyncio
import feedparser
import httpx
import pytz
from flask import Flask
from threading import Thread
from datetime import datetime
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from email.utils import parsedate_to_datetime
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Flask 웹서버
app = Flask(__name__)
@app.route('/')
def home():
    return 'Bot is running!'

def run_web():
    app.run(host='0.0.0.0', port=10000)

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

async def send_news(single=False):
    global sent_links
    feed = feedparser.parse(RSS_FEED_URL)
    entries = sorted(feed.entries, key=lambda e: parsedate_to_datetime(e.published))  # 시간순 정렬

    count = 0
    for entry in entries:
        if single and count >= 1:
            break
        if entry.link not in sent_links or single:
            if not single:
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
                count += 1
            except Exception as e:
                print(f"[ERROR] 전송 실패: {e}")
    if not single:
        save_sent_links()

async def send_price_diff(force_first=False):
    global prev_prices
    current = await fetch_prices()
    if not current:
        return

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
        elif force_first:
            lines.append(f"🔹 {symbol}: 현재 가격 {now:.2f}")

    if force_first or prev_prices:
        msg = "\n".join(lines)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode='Markdown')

    prev_prices = current

# Telegram 명령어 핸들러들
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_news(single=True)

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = await fetch_prices()
    if not coins:
        await update.message.reply_text("가격 정보를 가져올 수 없습니다.")
        return
    lines = ["💰 *현재 코인 가격*\n"]
    for symbol, price in coins.items():
        lines.append(f"{symbol}: {price:.2f} USD")
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

# 주 실행 루프
async def run_bot():
    await send_price_diff(force_first=True)
    while True:
        await send_news()
        await send_price_diff()
        await asyncio.sleep(CHECK_INTERVAL)

# 앱 실행 시작
if __name__ == "__main__":
    # Flask 웹서버 시작
    Thread(target=run_web).start()

    # Telegram 명령어 앱 실행
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("price", price_command))

    # 백그라운드 봇 루프 실행
    Thread(target=lambda: asyncio.run(run_bot())).start()
    app.run_polling()
