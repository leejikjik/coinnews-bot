import os
import logging
import httpx
import feedparser
from flask import Flask
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
import threading

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 시간대
KST = timezone("Asia/Seoul")

# Flask
app = Flask(__name__)

# 코인 목록
coins = {
    "btc-bitcoin": "비트코인",
    "eth-ethereum": "이더리움",
    "xrp-xrp": "리플",
    "sol-solana": "솔라나",
    "doge-dogecoin": "도지코인",
}
previous_prices = {}

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 코인 뉴스 및 시세 봇 작동 중\n/news : 뉴스\n/price : 시세\n/chart : 코인 가격 차트 보기"
    )

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 사용 가능한 명령어:\n/start - 봇 상태 확인\n/news - 최신 뉴스\n/price - 주요 코인 시세\n/chart - 가격 차트 보기"
    )

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        messages = []
        for entry in reversed(entries):
            translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            messages.append(f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}")
        await update.message.reply_text("\n\n".join(messages))
    except Exception as e:
        logger.error(f"/news 오류: {e}")
        await update.message.reply_text("❌ 뉴스 가져오기 실패")

# /price 버튼 출력
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(name, callback_data=coin_id)] for coin_id, name in coins.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💱 시세를 확인할 코인을 선택하세요:", reply_markup=reply_markup)

# 버튼 클릭 시 시세 전송
async def price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    coin_id = query.data
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = r.json()
            coin_data = next((c for c in data if c["id"] == coin_id), None)
            if coin_data:
                name = coins[coin_id]
                price = coin_data["quotes"]["USD"]["price"]
                change = coin_data["quotes"]["USD"].get("percent_change_24h", 0)
                result = f"📈 {name}\n💰 현재가: {price:,.2f} USD\n📊 24시간 변동률: {'🔺' if change>0 else '🔻'} {abs(change):.2f}%\n🕒 {now}"
                await query.message.reply_text(result)
            else:
                await query.message.reply_text("❌ 코인 정보를 찾을 수 없습니다.")
    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await query.message.reply_text("❌ 시세 가져오기 실패")

# /chart (더미 기능)
async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 곧 차트 이미지 기능이 제공될 예정입니다.")

# 자동 뉴스
async def send_auto_news(application):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entry = feed.entries[0]
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        msg = f"📰 {translated}\n🕒 {published}\n🔗 {entry.link}"
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"자동 뉴스 오류: {e}")

# 자동 시세
async def send_auto_price(application):
    try:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = r.json()
            result = [f"📊 자동 코인 시세 ({now})"]
            for coin_id, name in coins.items():
                coin_data = next((c for c in data if c["id"] == coin_id), None)
                if coin_data:
                    price = coin_data["quotes"]["USD"]["price"]
                    change = coin_data["quotes"]["USD"].get("percent_change_24h", 0)
                    result.append(f"{name}: {price:,.2f} USD ({'🔺' if change>0 else '🔻'} {abs(change):.2f}%)")
            await application.bot.send_message(chat_id=CHAT_ID, text="\n".join(result))
    except Exception as e:
        logger.error(f"자동 시세 오류: {e}")

# 루트
@app.route("/")
def home():
    return "✅ CoinNewsBot 작동 중"

# 스케줄러
def start_scheduler(application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_news(application)), "interval", minutes=30)
    scheduler.add_job(lambda: asyncio.run(send_auto_price(application)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ 스케줄러 작동 시작")

# 봇 실행
def run_bot():
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("help", help_command))
    app_bot.add_handler(CommandHandler("news", news))
    app_bot.add_handler(CommandHandler("price", price))
    app_bot.add_handler(CommandHandler("chart", chart))
    app_bot.add_handler(CallbackQueryHandler(price_callback))
    start_scheduler(app_bot)
    app_bot.run_polling()

# 병렬 실행
def run_all():
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    run_bot()

if __name__ == "__main__":
    run_all()
