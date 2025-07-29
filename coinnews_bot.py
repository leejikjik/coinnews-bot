import os
import logging
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

app = Flask(__name__)
scheduler = BackgroundScheduler()
KST = timezone(timedelta(hours=9))

# 개인채팅에서만 응답 허용
def is_private(update: Update) -> bool:
    return update.effective_chat.type == "private"

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private(update):
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 실시간 시세")
    else:
        await update.message.reply_text("❗ 이 명령어는 봇과 1:1 채팅에서만 사용 가능합니다.")

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_private(update):
        await update.message.reply_text("/news - 최신 뉴스\n/price - 실시간 시세 확인\n/chart - (준비중)")
    else:
        await update.message.reply_text("❗ 이 명령어는 봇과 1:1 채팅에서만 사용 가능합니다.")

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        await update.message.reply_text("❗ 이 명령어는 봇과 1:1 채팅에서만 사용 가능합니다.")
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        articles = feed.entries[:5][::-1]  # 오래된 순 → 최신
        messages = []
        for entry in articles:
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%m/%d %H:%M")
            messages.append(f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}")
        await update.message.reply_text("\n\n".join(messages))
    except Exception as e:
        logger.error(f"news error: {e}")
        await update.message.reply_text("❌ 뉴스를 불러오는 중 오류 발생")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        await update.message.reply_text("❗ 이 명령어는 봇과 1:1 채팅에서만 사용 가능합니다.")
        return
    coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
    keyboard = [
        [InlineKeyboardButton(coin.upper(), callback_data=f"price_{coin}")]
        for coin in coins
    ]
    await update.message.reply_text("💰 확인할 코인을 선택하세요:", reply_markup=InlineKeyboardMarkup(keyboard))

# 가격 비교 저장용
previous_prices = {}

# 버튼 콜백
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    if data.startswith("price_"):
        coin_id = data.split("_")[1]
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    raise Exception("응답 오류")
                data = response.json()
                price = data["market_data"]["current_price"]["usd"]
                percent = data["market_data"]["price_change_percentage_24h"]
                now = datetime.now(KST).strftime("%H:%M:%S")

                prev = previous_prices.get(coin_id, price)
                diff = price - prev
                direction = "📈" if diff > 0 else "📉" if diff < 0 else "⏸️"
                result = (
                    f"{direction} {coin_id.upper()} 시세\n"
                    f"현재: ${price:,.2f}\n"
                    f"1분 전: ${prev:,.2f}\n"
                    f"변동: ${diff:,.4f} ({percent:.2f}%)\n"
                    f"🕒 {now} (KST)"
                )
                previous_prices[coin_id] = price
                await query.message.reply_text(result)
        except Exception as e:
            logger.error(f"price error: {e}")
            await query.message.reply_text("⚠️ 시세 정보를 불러올 수 없습니다.")

# 자동 시세 전송
async def send_auto_price(app):
    try:
        coins = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]
        messages = []
        async with httpx.AsyncClient(timeout=10) as client:
            for coin_id in coins:
                res = await client.get(f"https://api.coingecko.com/api/v3/coins/{coin_id}")
                if res.status_code != 200:
                    continue
                data = res.json()
                price = data["market_data"]["current_price"]["usd"]
                percent = data["market_data"]["price_change_percentage_24h"]
                now = datetime.now(KST).strftime("%H:%M:%S")
                messages.append(f"💰 {coin_id.upper()}: ${price:,.2f} ({percent:.2f}%) 🕒 {now}")
        if messages:
            await app.bot.send_message(chat_id=CHAT_ID, text="📊 실시간 코인 시세\n" + "\n".join(messages))
    except Exception as e:
        logger.error(f"auto price error: {e}")

# 스케줄러
def start_scheduler(app):
    scheduler.add_job(lambda: asyncio.run(send_auto_price(app)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# Flask 서버
@app.route("/")
def home():
    return "Bot is running!"

# 실행
if __name__ == "__main__":
    from telegram.ext import Application
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("chart", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    start_scheduler(application)

    import threading
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 10000}).start()

    application.run_polling()
