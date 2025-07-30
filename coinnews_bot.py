import os
import logging
from datetime import datetime
from pytz import timezone
from flask import Flask
from threading import Thread
import feedparser
import httpx
from deep_translator import GoogleTranslator
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)
from apscheduler.schedulers.background import BackgroundScheduler

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 시간대
KST = timezone("Asia/Seoul")
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()
previous_prices = {}

# 주요 코인 한글 이름 포함
coins = {
    "bitcoin": "BTC (비트코인)",
    "ethereum": "ETH (이더리움)",
    "xrp": "XRP (리플)",
    "solana": "SOL (솔라나)",
    "dogecoin": "DOGE (도지코인)",
    "cardano": "ADA (에이다)",
    "toncoin": "TON (톤코인)",
    "avalanche": "AVAX (아발란체)",
    "tron": "TRX (트론)",
    "polkadot": "DOT (폴카닷)",
}

# 명령어: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("🟢 코인 뉴스 및 시세 봇 작동 중\n/news : 뉴스\n/price : 시세")

# 명령어: /news
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_news(update.effective_chat.id, context)

# 명령어: /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await send_price(update.effective_chat.id, context.bot)

# 함수: 뉴스 전송
async def send_news(chat_id, context):
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:5]
        messages = []
        for entry in reversed(entries):
            title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            published = datetime(*entry.published_parsed[:6]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            messages.append(f"📰 {title}\n🕒 {published}\n🔗 {entry.link}")
        await context.bot.send_message(chat_id=chat_id, text="\n\n".join(messages))
    except Exception as e:
        logger.error(f"뉴스 전송 오류: {e}")

# 함수: 시세 전송
async def send_price(chat_id, bot):
    try:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coincap.io/v2/assets")
            data = r.json().get("data", [])
            result = [f"📊 주요 코인 시세 ({now})"]
            for coin_id, label in coins.items():
                coin = next((c for c in data if c["id"] == coin_id), None)
                if coin:
                    price = float(coin["priceUsd"])
                    prev = previous_prices.get(coin_id)
                    diff = price - prev if prev else 0
                    sign = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                    change = f"{sign} {abs(diff):,.4f}" if prev else "➖ 변화 없음"
                    result.append(f"{label}: ${price:,.2f} ({change})")
                    previous_prices[coin_id] = price
            await bot.send_message(chat_id=chat_id, text="\n".join(result))
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# 함수: 급등 코인 감지
async def send_spike_coins(context):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coincap.io/v2/assets?limit=100")
            data = r.json().get("data", [])
            spiked = [
                f"🚀 {c['symbol']} ({c['name']}) +{float(c['changePercent24Hr']):.2f}%"
                for c in data if float(c["changePercent24Hr"]) >= 10
            ]
            if spiked:
                msg = "📈 급등 코인 (+10% 이상)\n" + "\n".join(spiked)
                await context.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"급등 코인 오류: {e}")

# 함수: 상승률/하락률 TOP10
async def send_rankings(context):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coincap.io/v2/assets?limit=100")
            data = r.json().get("data", [])
            top_up = sorted(data, key=lambda x: float(x["changePercent24Hr"]), reverse=True)[:10]
            top_down = sorted(data, key=lambda x: float(x["changePercent24Hr"]))[:10]
            up_msg = "\n".join([f"🔺 {c['symbol']} {float(c['changePercent24Hr']):+.2f}%" for c in top_up])
            down_msg = "\n".join([f"🔻 {c['symbol']} {float(c['changePercent24Hr']):+.2f}%" for c in top_down])
            msg = f"📊 24H 상승률 TOP10\n{up_msg}\n\n📉 하락률 TOP10\n{down_msg}"
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"코인 랭킹 오류: {e}")

# 스케줄러 시작
def start_scheduler(job_queue: JobQueue):
    job_queue.run_repeating(send_spike_coins, interval=60, first=60)
    job_queue.run_repeating(send_rankings, interval=600, first=10)
    job_queue.run_repeating(lambda ctx: send_price(CHAT_ID, ctx.bot), interval=60, first=5)
    job_queue.run_repeating(lambda ctx: send_news(CHAT_ID, ctx), interval=1800, first=15)
    logger.info("✅ JobQueue 스케줄러 시작됨")

# Flask 라우터
@app.route("/")
def index():
    return "✅ CoinNewsBot 작동 중"

# main 함수
def main():
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("price", price))

    job_queue = application.job_queue
    start_scheduler(job_queue)

    # 봇 run_polling은 메인 스레드에서 실행
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    application.run_polling()

if __name__ == "__main__":
    main()
