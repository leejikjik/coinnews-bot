import os
import logging
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 기본 설정
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")       # 개인 DM용
GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")     # 그룹방용

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

KST = timezone(timedelta(hours=9))
COINS = {
    "bitcoin": "BTC (비트코인)",
    "ethereum": "ETH (이더리움)",
    "ripple": "XRP (리플)",
    "solana": "SOL (솔라나)",
    "dogecoin": "DOGE (도지코인)",
}

# 텔레그램 명령어 핸들러 (개인 DM에서만 작동)
async def is_private(update: Update):
    return update.effective_chat.type == "private"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_private(update):
        await update.message.reply_text("✅ 봇이 작동 중입니다.\n/news : 최신 뉴스\n/price : 주요 코인 시세\n/test : 테스트 메시지")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_private(update):
        await update.message.reply_text("✅ 테스트 응답 확인!")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_private(update):
        feed = feedparser.parse("https://cointelegraph.com/rss")
        news_list = []
        for entry in feed.entries[:5]:
            translated_title = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            translated_summary = GoogleTranslator(source='auto', target='ko').translate(entry.summary)
            news_list.append(f"📰 <b>{translated_title}</b>\n{translated_summary}\n<a href='{entry.link}'>원문 보기</a>")
        message = "\n\n".join(news_list)
        await update.message.reply_text(message, parse_mode="HTML", disable_web_page_preview=True)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_private(update):
        await update.message.reply_text(await fetch_price_message(), parse_mode="HTML")

# 가격 정보 메시지 생성
async def fetch_price_message():
    now = datetime.now(KST).strftime("%H:%M:%S")
    url = "https://api.coinpaprika.com/v1/tickers"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10.0)
            data = res.json()
            selected = {coin['id']: coin for coin in data if coin['id'] in COINS}
            lines = [f"📊 <b>{now} 기준 주요 코인 시세</b>"]
            for cid, label in COINS.items():
                c = selected.get(cid)
                if c:
                    price = float(c["quotes"]["USD"]["price"])
                    change = float(c["quotes"]["USD"]["percent_change_1h"])
                    emoji = "📈" if change > 0 else "📉"
                    lines.append(f"{emoji} {label} : ${price:,.2f} ({change:+.2f}%)")
            return "\n".join(lines)
    except Exception as e:
        logging.error(f"시세 전송 오류: {e}")
        return "❌ 코인 시세를 불러오는 데 실패했습니다."

# 랭킹 메시지
async def fetch_top_rank():
    url = "https://api.coinpaprika.com/v1/tickers"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()
            sorted_up = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"], reverse=True)[:10]
            sorted_down = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_1h"])[:10]
            lines = ["🔥 <b>1시간 급등/하락 랭킹</b>"]
            lines.append("\n🚀 상승 TOP10")
            for c in sorted_up:
                lines.append(f"🟢 {c['symbol']} : {c['quotes']['USD']['percent_change_1h']:+.2f}%")
            lines.append("\n📉 하락 TOP10")
            for c in sorted_down:
                lines.append(f"🔴 {c['symbol']} : {c['quotes']['USD']['percent_change_1h']:+.2f}%")
            return "\n".join(lines)
    except Exception as e:
        logging.error(f"랭킹 전송 오류: {e}")
        return None

# 스케줄링 작업
async def send_auto_price():
    msg = await fetch_price_message()
    if msg:
        await app_instance.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")

async def send_auto_rank():
    msg = await fetch_top_rank()
    if msg:
        await app_instance.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")

# 초기 자동 전송용
async def initial_send():
    await send_auto_price()
    await send_auto_rank()

# Flask 서버
@app.route("/")
def home():
    return "Coin News Bot Running"

# Telegram 실행
async def run_bot():
    global app_instance
    app_instance = ApplicationBuilder().token(TOKEN).build()
    app_instance.add_handler(CommandHandler("start", start))
    app_instance.add_handler(CommandHandler("news", news))
    app_instance.add_handler(CommandHandler("price", price))
    app_instance.add_handler(CommandHandler("test", test))

    scheduler.add_job(lambda: asyncio.run(send_auto_price()), "interval", minutes=1)
    scheduler.add_job(lambda: asyncio.run(send_auto_rank()), "interval", minutes=10)
    asyncio.create_task(initial_send())
    await app_instance.initialize()
    await app_instance.start()
    await app_instance.updater.start_polling()
    await app_instance.updater.idle()

# 메인 실행
if __name__ == "__main__":
    import threading

    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(run_bot())
