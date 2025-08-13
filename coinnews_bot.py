import os
import json
import logging
import asyncio
from threading import Thread
from datetime import datetime
from flask import Flask
from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ChatMemberHandler,
    ContextTypes, filters
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import feedparser
from deep_translator import GoogleTranslator
import httpx

# ===== 설정 =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROUP_ID = int(os.environ.get("TELEGRAM_GROUP_ID", "0"))
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)
scheduler = BackgroundScheduler(timezone="Asia/Seoul", daemon=True)

application = ApplicationBuilder().token(TOKEN).build()

# ===== 데이터 저장 =====
USER_LOG_FILE = "user_logs.json"
NEWS_CACHE_FILE = "news_cache.json"

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

user_logs = load_json(USER_LOG_FILE)
news_cache = load_json(NEWS_CACHE_FILE)

# ===== 유틸 =====
async def send_dm(user_id, text):
    try:
        await application.bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        logger.warning(f"DM 전송 실패: {e}")

def is_dm(update: Update):
    return update.effective_chat.type == "private"

def is_group(update: Update):
    return update.effective_chat.type in ["group", "supergroup"]

def member_in_group(user_id):
    return user_id in user_logs

def is_admin(user_id):
    return user_id in ADMIN_IDS

async def restricted_dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE, func):
    if not is_dm(update):
        return
    if not member_in_group(update.effective_user.id):
        await update.message.reply_text("그룹방에 참여해야 사용 가능합니다.")
        return
    await func(update, context)

# ===== 명령어 =====
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 봇이 작동 중입니다.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start /price /summary /analyze /help /test")

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("테스트 OK")

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = await get_prices()
    await update.message.reply_text(prices)

async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("뉴스 요약 기능 준비중")

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("RSI/MACD 분석 준비중")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if context.args:
        await update.message.reply_text(f"ID: {context.args[0]}")
    else:
        await update.message.reply_text(f"ID: {update.effective_user.id}")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("환경 설정 보기")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(json.dumps(user_logs, ensure_ascii=False, indent=2))

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if context.args:
        uid = int(context.args[0])
        user_logs.pop(uid, None)
        save_json(USER_LOG_FILE, user_logs)
        await update.message.reply_text(f"{uid} 차단 완료")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if context.args:
        uid = int(context.args[0])
        user_logs[uid] = {"joined": str(datetime.now())}
        save_json(USER_LOG_FILE, user_logs)
        await update.message.reply_text(f"{uid} 차단 해제")

async def news_cmd_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return
    await send_news()

async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return

# ===== 뉴스 =====
async def send_news():
    url = "https://news.google.com/rss/search?q=cryptocurrency&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    new_items = []
    for entry in feed.entries:
        if entry.link not in news_cache:
            news_cache[entry.link] = True
            title = GoogleTranslator(source="auto", target="ko").translate(entry.title)
            new_items.append(f"{title}\n{entry.link}")
    if new_items:
        save_json(NEWS_CACHE_FILE, news_cache)
        await application.bot.send_message(chat_id=GROUP_ID, text="\n\n".join(new_items))

# ===== 시세 =====
async def get_prices():
    url = "https://api.binance.com/api/v3/ticker/price"
    coins = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        data = resp.json()
    prices = {item["symbol"]: item["price"] for item in data if item["symbol"] in coins}
    return "\n".join([f"{k}: {v}" for k, v in prices.items()])

async def auto_send_prices():
    msg = await get_prices()
    await application.bot.send_message(chat_id=GROUP_ID, text=msg)

# ===== 감지 =====
async def auto_send_rankings(initial=False):
    await application.bot.send_message(chat_id=GROUP_ID, text="📊 랭킹 전송")

async def auto_detect_surge():
    await application.bot.send_message(chat_id=GROUP_ID, text="🚀 급등 코인 감지")

async def auto_detect_oversold():
    await application.bot.send_message(chat_id=GROUP_ID, text="📉 과매도 탐지")

async def auto_send_calendar_morning():
    await application.bot.send_message(chat_id=GROUP_ID, text="🌏 오늘의 경제일정")

# ===== 유저 입장 =====
async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member: ChatMember = update.chat_member
    user = chat_member.new_chat_member.user
    if chat_member.new_chat_member.status == "member":
        user_logs[user.id] = {"joined": str(datetime.now())}
        save_json(USER_LOG_FILE, user_logs)
        await send_dm(user.id, "환영합니다! DM에서 명령어를 사용하세요.")

# ===== 실행 =====
def start_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 명령어 등록
    application.add_handler(CommandHandler("start", lambda u,c: restricted_dm_command(u,c,start_cmd)))
    application.add_handler(CommandHandler("help", lambda u,c: restricted_dm_command(u,c,help_cmd)))
    application.add_handler(CommandHandler("test", lambda u,c: restricted_dm_command(u,c,test_cmd)))
    application.add_handler(CommandHandler("price", lambda u,c: restricted_dm_command(u,c,price_cmd)))
    application.add_handler(CommandHandler("summary", lambda u,c: restricted_dm_command(u,c,summary_cmd)))
    application.add_handler(CommandHandler("analyze", lambda u,c: restricted_dm_command(u,c,analyze_cmd)))

    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("config", config_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))

    application.add_handler(CommandHandler("news", news_cmd_group))
    application.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))

    application.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))

    application.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(auto_send_prices()), IntervalTrigger(minutes=2))
    scheduler.add_job(lambda: asyncio.run(send_news()), IntervalTrigger(minutes=10))
    scheduler.add_job(lambda: asyncio.run(auto_send_rankings()), IntervalTrigger(hours=1))
    scheduler.add_job(lambda: asyncio.run(auto_detect_surge()), IntervalTrigger(minutes=2))
    scheduler.add_job(lambda: asyncio.run(auto_detect_oversold()), IntervalTrigger(hours=1))
    scheduler.add_job(lambda: asyncio.run(auto_send_calendar_morning()), CronTrigger(hour=9, minute=0))
    scheduler.start()

def run():
    t = Thread(target=start_bot_in_thread, name="PTB", daemon=True)
    t.start()
    start_scheduler()
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    run()
