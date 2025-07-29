import os
import logging
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 로깅
logging.basicConfig(level=logging.INFO)

# 환경 변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Flask 서버
app = Flask(__name__)

# 전역 스케줄러
scheduler = BackgroundScheduler()

# 한국 시간
KST = timezone(timedelta(hours=9))

# 명령어 제한: 그룹방이면 안내만
async def restrict_to_private(update: Update):
    if update.message and update.message.chat.type != "private":
        await update.message.reply_text("❗ 이 명령어는 봇과 1:1 채팅에서만 사용 가능합니다.")
        return False
    return True

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_to_private(update): return
    await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 코인 시세\n/chart : 시세 버튼")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_to_private(update): return
    feed = feedparser.parse("https://cointelegraph.com/rss")
    if not feed.entries:
        await update.message.reply_text("뉴스를 불러올 수 없습니다.")
        return
    entries = feed.entries[::-1][:5]
    msgs = []
    for entry in entries:
        title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        link = entry.link
        msgs.append(f"📰 <b>{title}</b>\n<a href=\"{link}\">자세히 보기</a>")
    for msg in msgs:
        await update.message.reply_html(msg, disable_web_page_preview=True)

# /price
price_cache = {}

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await restrict_to_private(update): return
    keyboard = [
        [
            InlineKeyboardButton("BTC", callback_data="price_bitcoin"),
            InlineKeyboardButton("ETH", callback_data="price_ethereum"),
        ],
        [
            InlineKeyboardButton("XRP", callback_data="price_xrp"),
            InlineKeyboardButton("SOL", callback_data="price_solana"),
        ],
        [
            InlineKeyboardButton("DOGE", callback_data="price_dogecoin"),
        ]
    ]
    await update.message.reply_text("📊 코인을 선택하세요:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    coin_id = query.data.replace("price_", "")
    url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=10)
            data = r.json()
    except Exception:
        await query.message.reply_text("❌ 시세 데이터를 불러올 수 없습니다.")
        return

    price_usd = float(data['quotes']['USD']['price'])
    percent = data['quotes']['USD']['percent_change_1h']
    direction = "📈 상승" if percent > 0 else "📉 하락"
    await query.message.reply_text(
        f"💰 <b>{data['name']}</b>\n"
        f"가격: ${price_usd:.2f}\n"
        f"1시간 변화율: {percent:.2f}% {direction}",
        parse_mode="HTML"
    )

# 자동 시세 전송
async def send_auto_price():
    coins = ["bitcoin", "ethereum"]
    results = []
    async with httpx.AsyncClient() as client:
        for coin_id in coins:
            r = await client.get(f"https://api.coinpaprika.com/v1/tickers/{coin_id}", timeout=10)
            data = r.json()
            name = data['name']
            price = float(data['quotes']['USD']['price'])
            percent = data['quotes']['USD']['percent_change_1h']
            arrow = "📈" if percent > 0 else "📉"
            results.append(f"{arrow} <b>{name}</b>\n${price:.2f} | {percent:.2f}%")
    now = datetime.now(KST).strftime("%H:%M:%S")
    text = f"⏱ {now} 기준 코인 시세\n\n" + "\n\n".join(results)
    await app_bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")

# 자동 뉴스 전송
async def send_auto_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    if not feed.entries:
        return
    entry = feed.entries[0]
    title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
    link = entry.link
    text = f"🗞️ <b>{title}</b>\n<a href=\"{link}\">자세히 보기</a>"
    await app_bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML", disable_web_page_preview=True)

# 스케줄러 실행
def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_news()), "interval", minutes=10)
    scheduler.start()
    logging.info("✅ 스케줄러 작동 시작")

# Flask Keepalive
@app.route("/")
def home():
    return "✅ Telegram Coin Bot is running!"

# 메인 실행
if __name__ == "__main__":
    from telegram.ext import Application

    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    app_bot.add_handler(CallbackQueryHandler(handle_price_callback))

    start_scheduler()

    import threading
    def run_flask():
        app.run(host="0.0.0.0", port=10000)

    threading.Thread(target=run_flask).start()
    app_bot.run_polling()
