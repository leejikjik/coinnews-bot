import os
import logging
import asyncio
from datetime import datetime, timedelta
import pytz
import feedparser
from deep_translator import GoogleTranslator
import httpx
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, JobQueue
)

# Set timezone
KST = pytz.timezone('Asia/Seoul')

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot token and chat ID
BOT_TOKEN = os.getenv("BOT_TOKEN") or "<여기에_토큰_입력>"
CHAT_ID = os.getenv("CHAT_ID") or "<여기에_CHAT_ID_입력>"

# Flask setup
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running."

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# Crypto symbols to track
SYMBOLS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "dogecoin": "DOGE"
}

previous_prices = {}

async def fetch_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200:
            return response.json().get(symbol, {}).get("usd")
        else:
            return None

async def track_prices(context: ContextTypes.DEFAULT_TYPE):
    global previous_prices
    kst_now = datetime.now(KST).strftime('%H:%M:%S')
    result = f"\ud83d\uddcb {kst_now} \uae30\uc900 1\ubd84\uac04 \uac00\uaca9 \ubcc0\ud654\n"
    for symbol, name in SYMBOLS.items():
        current = await fetch_price(symbol)
        previous = previous_prices.get(symbol)
        if current is not None:
            if previous is not None:
                diff = round(current - previous, 2)
                arrow = "\ud83d\udd3a" if diff > 0 else ("\ud83d\udd3b" if diff < 0 else "\u27a1")
                result += f"{name}: ${previous} -> ${current} {arrow} ({diff})\n"
            else:
                result += f"{name}: ${current}\n"
            previous_prices[symbol] = current
        else:
            result += f"{name}: API \uc624\ub958\n"
    await context.bot.send_message(chat_id=CHAT_ID, text=result)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "\ud83d\udcb0 \uac00\uaca9 \ud604\ud669\n"
    for symbol, name in SYMBOLS.items():
        current = await fetch_price(symbol)
        if current:
            text += f"{name}: ${current}\n"
        else:
            text += f"{name}: API \uc624\ub958\n"
    await context.message.reply_text(text)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\ud83d\udcf0 \ucf54\uc778 \ub274\uc2a4&\uac00\uaca9 \ucd94\uc801 \ubcf4\ud1b5\uc785\ub2c8\ub2e4!\n/news \ub610\ub294 /price \uba85\ub839\uc744 \uc0ac\uc6a9\ud574\ubcf4\uc138\uc694.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    for entry in feed.entries[:3]:
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        kst_time = datetime(*entry.published_parsed[:6], tzinfo=pytz.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        msg = f"\ud83d\udcf0 *{translated}*\n{entry.link}\n\ud83d\udd52 {kst_time} \ud55c\uad6d\uc2dc\uac04\uae30\uc900"
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')

async def main():
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(CommandHandler("price", price))
    app_.add_handler(CommandHandler("news", news))

    job_queue: JobQueue = app_.job_queue
    job_queue.run_repeating(track_prices, interval=60, first=5)

    await app_.initialize()
    await app_.start()
    await app_.updater.start_polling()
    await app_.updater.idle()

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
