import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, filters
)
import httpx
import feedparser
from deep_translator import GoogleTranslator
import random

# ========== 기본 설정 ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROUP_ID = int(os.environ.get("TELEGRAM_GROUP_ID"))
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "").split(",")))

app = Flask(__name__)
scheduler = BackgroundScheduler()

# 사용자 활동 로그 파일
USER_LOG_FILE = "user_logs.json"
if not os.path.exists(USER_LOG_FILE):
    with open(USER_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)

# 뉴스 캐싱 (중복 방지)
news_cache = set()

# ============================================================
# 유틸
# ============================================================
def load_user_logs():
    with open(USER_LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_user_logs(data):
    with open(USER_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_user_log(user_id, username):
    logs = load_user_logs()
    if str(user_id) not in logs:
        logs[str(user_id)] = {
            "username": username,
            "unique_id": random.randint(100000, 999999),
            "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "activity": []
        }
    logs[str(user_id)]["activity"].append(
        {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": "command"}
    )
    save_user_logs(logs)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============================================================
# 코인 시세 가져오기 (CoinGecko API 사용)
# ============================================================
async def get_prices():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": "bitcoin,ethereum,ripple,solana,dogecoin",
        "vs_currencies": "usd,krw"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    mapping = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "ripple": "XRP",
        "solana": "SOL",
        "dogecoin": "DOGE"
    }

    msg_lines = []
    for coin, symbol in mapping.items():
        usd = data[coin]["usd"]
        krw = data[coin]["krw"]
        kimchi_premium = ((krw / (usd * 1400)) - 1) * 100
        color = "🟢" if kimchi_premium > 0 else "🔴"
        msg_lines.append(f"{symbol}: ${usd} / ₩{krw:,} ({color}{kimchi_premium:.2f}%)")

    return "\n".join(msg_lines)

# ============================================================
# 명령어 핸들러
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    add_user_log(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text(
        "🟢 봇이 작동 중입니다.\n"
        "/price - 현재 시세\n"
        "/summary - 뉴스 요약\n"
        "/analyze - RSI/MACD 분석\n"
        "/help - 도움말"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    msg = await get_prices()
    await update.message.reply_text(msg)

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
    feed = feedparser.parse(url)
    new_items = []
    for entry in feed.entries:
        if entry.link not in news_cache:
            news_cache.add(entry.link)
            translated = GoogleTranslator(source="en", target="ko").translate(entry.title)
            new_items.append(f"📰 {translated}\n{entry.link}")
    if new_items:
        await context.bot.send_message(chat_id=GROUP_ID, text="\n\n".join(new_items))

# ============================================================
# 스케줄 작업
# ============================================================
async def auto_send_prices():
    msg = await get_prices()
    await app_bot.send_message(chat_id=GROUP_ID, text=msg)

async def auto_send_news():
    await news(Update(update_id=0), ContextTypes.DEFAULT_TYPE)

def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(auto_send_prices()), "interval", minutes=2)
    scheduler.add_job(lambda: asyncio.run(auto_send_news()), "interval", minutes=10)
    scheduler.start()

# ============================================================
# 실행
# ============================================================
@app.route("/")
def home():
    return "Bot is running."

if __name__ == "__main__":
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))

    # 봇 객체를 글로벌로 저장해서 scheduler에서 사용
    app_bot = application.bot

    start_scheduler()

    # Render 환경에서 main thread 실행 + signal 등록 방지
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
        stop_signals=None
    )
