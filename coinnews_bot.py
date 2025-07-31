import os
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
import feedparser
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID")

# 주요 코인 리스트 (symbol: name)
COIN_LIST = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "xrp": "리플",
    "solana": "솔라나",
    "dogecoin": "도지코인"
}

app = Flask(__name__)
scheduler = BackgroundScheduler()

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "/news : 최신 코인 뉴스\n/price : 주요 코인 시세\n/getid : chat_id 확인"
    )

# /test
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text("✅ 봇이 정상 작동 중입니다.")

# /getid (chat_id 출력)
async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    print(f"[📥 CHAT ID] {chat_id}")
    await update.message.reply_text(
        f"✅ 이 채팅의 chat_id는 `{chat_id}` 입니다.",
        parse_mode="Markdown"
    )

# /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        messages = []
        for entry in feed.entries[:5][::-1]:
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            url = entry.link
            messages.append(f"\u2b50 *{translated_title}*\n{url}")
        await update.message.reply_text("\n\n".join(messages), parse_mode="Markdown")
    except Exception as e:
        logger.error("뉴스 전송 오류: %s", e)
        await update.message.reply_text("❌ 뉴스 불러오기 실패")

# /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_price(update.effective_chat.id, context)

# 시세 메시지 전송 함수
async def send_price(chat_id, context):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = res.json()

        coin_data = {}
        for coin in data:
            if coin["id"] in COIN_LIST:
                coin_data[coin["id"]] = coin

        messages = []
        for coin_id, kr_name in COIN_LIST.items():
            coin = coin_data.get(coin_id)
            if not coin:
                continue
            name = coin["symbol"]
            price = round(coin["quotes"]["USD"]["price"], 4)
            change = round(coin["quotes"]["USD"]["percent_change_1h"], 2)
            emoji = "🔼" if change >= 0 else "🔽"
            messages.append(f"{name} ({kr_name})\n\u2728 {price}$ ({emoji} {change}%)\n")

        text = "\n".join(messages)
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.error("시세 전송 오류: %s", e)

# 초기 실행 시 한 번 전송
async def startup_notify(app):
    class DummyContext:
        def __init__(self, bot):
            self.bot = bot
    try:
        from telegram import Bot
        context = DummyContext(Bot(BOT_TOKEN))
        await send_price(GROUP_ID, context)
    except Exception as e:
        logger.error("초기 시세 전송 실패: %s", e)

# 스케줄러 등록
def start_scheduler(application):
    scheduler.add_job(lambda: application.create_task(send_price(GROUP_ID, application.bot)), 'interval', minutes=1)
    scheduler.start()

# 메인
if __name__ == '__main__':
    from telegram.ext import Application
    import asyncio

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("getid", get_chat_id))

    # 스케줄러 및 Flask
    start_scheduler(application)

    loop = asyncio.get_event_loop()
    loop.create_task(startup_notify(application))

    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    application.run_polling()
