import os
import asyncio
import logging
import feedparser
import httpx
from datetime import datetime, timedelta
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    defaults,
)

# 설정
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
NEWS_URL = "https://cointelegraph.com/rss"
COINS = ["bitcoin", "ethereum", "ripple", "solana", "dogecoin"]

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Telegram Coin Bot Running"

# 가격 저장용
latest_prices = {}

# 텔레그램 봇 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 코인 뉴스/시세 자동 전송 봇입니다.\n/news: 뉴스 확인\n/price: 현재 시세 확인")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse(NEWS_URL)
    entries = feed.entries[:5][::-1]  # 오래된 순
    msg = ""
    for entry in entries:
        try:
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            msg += f"🔹 <b>{translated_title}</b>\n📝 {translated_summary}\n🔗 {entry.link}\n\n"
        except Exception as e:
            logger.warning(f"뉴스 번역 오류: {e}")
    if msg:
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await update.message.reply_text("❌ 뉴스 데이터를 불러오지 못했습니다.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not latest_prices:
        await update.message.reply_text("⏳ 시세 데이터를 불러오는 중입니다. 잠시 후 다시 시도해주세요.")
        return
    try:
        msg = "📊 현재 코인 시세 (1분 전 대비)\n"
        for coin in COINS:
            now = latest_prices[coin]["now"]
            before = latest_prices[coin]["before"]
            diff = now - before
            pct = (diff / before * 100) if before else 0
            msg += f"{coin.upper()} ➡️ ${now:.2f} ({'🔺' if diff > 0 else '🔻'} {abs(pct):.2f}%)\n"
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"/price 오류: {e}")
        await update.message.reply_text("❌ 가격 정보를 가져오는데 실패했습니다.")

# 코인 시세 자동 업데이트
async def fetch_prices():
    try:
        url = (
            f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(COINS)}&vs_currencies=usd"
        )
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            data = response.json()
        now = datetime.now()
        for coin in COINS:
            if coin not in latest_prices:
                latest_prices[coin] = {"before": data[coin]["usd"], "now": data[coin]["usd"], "time": now}
            else:
                latest_prices[coin]["before"] = latest_prices[coin]["now"]
                latest_prices[coin]["now"] = data[coin]["usd"]
                latest_prices[coin]["time"] = now
        logger.info("✅ 코인 시세 업데이트 완료")
    except Exception as e:
        logger.error(f"시세 업데이트 실패: {e}")

# 뉴스 자동 전송
async def send_auto_news(app: Application):
    try:
        feed = feedparser.parse(NEWS_URL)
        entries = feed.entries[:3][::-1]  # 오래된 3개
        msg = ""
        for entry in entries:
            try:
                title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
                summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
                msg += f"<b>{title}</b>\n📝 {summary}\n🔗 {entry.link}\n\n"
            except Exception as e:
                logger.warning(f"[자동 뉴스 번역 오류] {e}")
        if msg:
            await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[자동 뉴스 전송 오류] {e}")

# 가격 자동 전송
async def send_auto_price(app: Application):
    if not latest_prices:
        return
    try:
        msg = "📈 자동 코인 시세 알림 (1분 변화)\n"
        for coin in COINS:
            now = latest_prices[coin]["now"]
            before = latest_prices[coin]["before"]
            diff = now - before
            pct = (diff / before * 100) if before else 0
            msg += f"{coin.upper()} ➡️ ${now:.2f} ({'🔺' if diff > 0 else '🔻'} {abs(pct):.2f}%)\n"
        await app.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"[자동 시세 전송 오류] {e}")

# 스케줄러 설정
def start_scheduler(app: Application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(fetch_prices()), "interval", seconds=60)
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news(app)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price(app)), "interval", minutes=1)
    scheduler.start()
    logger.info("✅ Scheduler started")

# 텔레그램 봇 실행
async def main():
    application = Application.builder().token(BOT_TOKEN).defaults(defaults).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    await application.initialize()
    await application.start()
    logger.info("✅ Telegram 봇 시작됨")
    start_scheduler(application)
    await application.updater.start_polling()
    await application.updater.idle()

# 서버 시작
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    app.run(host="0.0.0.0", port=10000)
