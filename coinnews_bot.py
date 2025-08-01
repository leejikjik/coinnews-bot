# ⚠️ 전체 코드가 길어 canvas에 올립니다.
# 아래에서 실전 배포용 코드를 확인하세요.

import os
import logging
import asyncio
from flask import Flask
from datetime import datetime, timedelta
import httpx
import feedparser
from deep_translator import GoogleTranslator
from telegram import Update, ChatMember, ChatMemberUpdated, constants
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler,
    filters, ChatMemberHandler
)
from apscheduler.schedulers.background import BackgroundScheduler

# 로깅
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID"))
GROUP_ID = int(os.environ.get("TELEGRAM_GROUP_ID"))
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "").split(",")))

# Flask
app = Flask(__name__)

# 전역 상태 저장
sent_news_links = set()
user_db = {}  # user_id: {"username": str, "joined": datetime, "number": int}
user_number_counter = 1000

# --- 도우미 함수 ---
def get_price_color(change):
    if change > 0:
        return f"\u2705 ▲{change:.2f}%"
    elif change < 0:
        return f"\u274C ▼{abs(change):.2f}%"
    else:
        return "\u2B1C 0.00%"

def get_kimp(krw_price, usd_price):
    try:
        rate = krw_price / (usd_price * 1400) * 100
        return f"김프: {rate - 100:.2f}%"
    except:
        return "김프 계산 오류"

# --- 메시지 필터 ---
def is_private_user(update: Update) -> bool:
    return update.effective_chat.type == "private"

def is_group(update: Update) -> bool:
    return update.effective_chat.id == GROUP_ID

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- 기능: 코인 시세 ---
async def fetch_price():
    url_base = "https://api.coinpaprika.com/v1/tickers"
    coins = ["btc-bitcoin", "eth-ethereum", "xrp-xrp", "sol-solana", "doge-dogecoin"]
    names = ["비트코인", "이더리움", "리플", "솔라나", "도지"]
    messages = []

    async with httpx.AsyncClient() as client:
        for coin, name in zip(coins, names):
            try:
                res = await client.get(f"{url_base}/{coin}")
                data = res.json()
                price = data['quotes']['USD']['price']
                change = data['quotes']['USD']['percent_change_1h']
                color = get_price_color(change)
                messages.append(f"{data['symbol']} ({name}): ${price:,.2f} {color}")
            except Exception as e:
                logger.error(f"시세 에러 {coin}: {e}")
                messages.append(f"{coin} 시세 오류")

    return "\n".join(messages)

# --- 기능: 뉴스 ---
async def fetch_news():
    url = "https://cointelegraph.com/rss"
    feed = feedparser.parse(url)
    new_items = []
    for entry in feed.entries[:5]:
        if entry.link in sent_news_links:
            continue
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        new_items.append(f"📰 {translated}\n{entry.link}")
        sent_news_links.add(entry.link)
    return "\n\n".join(new_items)

# --- 명령어 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_user(update):
        return
    if update.effective_user.id not in user_db:
        await update.message.reply_text("그룹방 참여 후 사용 가능합니다.")
        return
    await update.message.reply_text("/help 로 사용법 확인 가능해요!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_user(update): return
    await update.message.reply_text(
        "/summary - 오늘 요약\n/analyze [코인] - 기술분석\n/id [@username or ID] - 유저번호확인"
    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 작동 확인")

# --- 유저 입장 시 처리 ---
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        global user_number_counter
        if user.id not in user_db:
            user_db[user.id] = {
                "username": user.username or user.full_name,
                "joined": datetime.now(),
                "number": user_number_counter
            }
            user_number_counter += 1
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"👋 {user.full_name}님 환영합니다!\n1:1 채팅으로 /start 입력해보세요!"
        )

# --- 스케줄러 작업 ---
async def send_auto_price():
    msg = await fetch_price()
    try:
        await app_bot.send_message(chat_id=GROUP_ID, text=f"📈 코인 시세 (2분)", parse_mode=constants.ParseMode.HTML)
        await app_bot.send_message(chat_id=GROUP_ID, text=msg)
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

async def send_auto_news():
    msg = await fetch_news()
    if msg:
        await app_bot.send_message(chat_id=GROUP_ID, text=f"📰 신규 뉴스\n{msg}")

# --- Flask Keepalive ---
@app.route('/')
def home():
    return 'Bot is running'

# --- 메인 실행 ---
def run():
    global app_bot
    application = ApplicationBuilder().token(TOKEN).build()
    app_bot = application.bot

    # 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    # 스케줄러 시작
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_auto_price()), 'interval', minutes=2)
    scheduler.add_job(lambda: asyncio.create_task(send_auto_news()), 'interval', minutes=10)
    scheduler.start()

    # Flask는 Thread로 실행
    import threading
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))).start()

    # Bot 실행
    application.run_polling()

if __name__ == '__main__':
    run()
