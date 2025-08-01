import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, ChatMember
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, ChatMemberHandler
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import feedparser
from deep_translator import GoogleTranslator
import httpx

# 환경 변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")  # 예: "123456789,987654321"

# Flask 서버
app = Flask(__name__)

# 로그 설정
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# 사용자 고유 ID 관리
user_data_file = "user_data.json"
if not os.path.exists(user_data_file):
    with open(user_data_file, "w") as f:
        json.dump({}, f)

def load_user_data():
    with open(user_data_file, "r") as f:
        return json.load(f)

def save_user_data(data):
    with open(user_data_file, "w") as f:
        json.dump(data, f)

def get_or_assign_user_id(user_id, username=None):
    data = load_user_data()
    if str(user_id) in data:
        return data[str(user_id)]["custom_id"]
    else:
        new_id = len(data) + 1
        data[str(user_id)] = {
            "custom_id": new_id,
            "username": username or "",
            "joined_at": datetime.now().isoformat(),
            "messages": 0,
        }
        save_user_data(data)
        return new_id

def is_admin(user_id):
    return str(user_id) in ADMIN_IDS.split(",")

# 텔레그램 앱 초기화
application = ApplicationBuilder().token(TOKEN).build()

### 명령어 핸들러들

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    if str(user_id) not in load_user_data():
        await update.message.reply_text("❌ 그룹방에 먼저 참여해야 사용 가능합니다.")
        return
    await update.message.reply_text("✅ 작동 중입니다.\n/help 명령어로 전체 기능 확인!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "/start - 작동 확인\n"
        "/price - 주요 코인 시세\n"
        "/news - 최신 코인 뉴스\n"
        "/summary - 요약 정보\n"
        "/analyze [코인] - 코인 분석\n"
        "/id [@유저명 or 고유번호] - 유저 정보\n"
        "/ban [고유번호] - 강퇴 (관리자)\n"
        "/unban [고유번호] - 차단 해제 (관리자)\n"
        "/config - 설정 요약 (관리자)\n"
        "/stats - 유저 통계 (관리자)\n"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        async with httpx.AsyncClient() as client:
            coins = ["bitcoin", "ethereum", "xrp", "solana", "dogecoin"]
            names = {
                "bitcoin": "BTC (비트코인)",
                "ethereum": "ETH (이더리움)",
                "xrp": "XRP (리플)",
                "solana": "SOL (솔라나)",
                "dogecoin": "DOGE (도지코인)",
            }
            result = ""
            for coin in coins:
                url = f"https://api.coinpaprika.com/v1/tickers/{coin}"
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                price = data["quotes"]["USD"]["price"]
                percent = data["quotes"]["USD"]["percent_change_1h"]
                arrow = "▲" if percent >= 0 else "▼"
                result += f"{names[coin]}: ${price:,.4f} ({arrow} {abs(percent):.2f}%)\n"
            await update.message.reply_text(result.strip())
    except Exception as e:
        await update.message.reply_text("⚠️ 시세 정보를 가져오는 중 오류 발생.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != int(CHAT_ID):
        return
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        sent = []
        for entry in reversed(feed.entries[:5]):
            title = entry.title
            link = entry.link
            translated = GoogleTranslator(source="auto", target="ko").translate(title)
            msg = f"📰 {translated}\n{link}"
            sent.append(msg)
        for msg in sent:
            await update.message.reply_text(msg)
    except Exception:
        await update.message.reply_text("⚠️ 뉴스 로딩 중 오류.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ 알 수 없는 명령어입니다. /help 참고")

### 유저 입장 감지
async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if result.new_chat_member.status == ChatMember.MEMBER:
        user = result.new_chat_member.user
        uid = get_or_assign_user_id(user.id, user.username)
        await context.bot.send_message(chat_id=result.chat.id, text=f"👋 {user.full_name}님 환영합니다! (ID: {uid})")

### 관리자 명령어: /ban, /unban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /ban [고유번호]")
        return
    target_id = context.args[0]
    data = load_user_data()
    for uid, info in data.items():
        if str(info["custom_id"]) == target_id:
            await context.bot.ban_chat_member(chat_id=CHAT_ID, user_id=int(uid))
            await update.message.reply_text(f"⛔️ 차단 완료 (ID: {target_id})")
            return
    await update.message.reply_text("해당 ID의 유저를 찾을 수 없습니다.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /unban [고유번호]")
        return
    target_id = context.args[0]
    data = load_user_data()
    for uid, info in data.items():
        if str(info["custom_id"]) == target_id:
            await context.bot.unban_chat_member(chat_id=CHAT_ID, user_id=int(uid), only_if_banned=True)
            await update.message.reply_text(f"✅ 차단 해제 완료 (ID: {target_id})")
            return
    await update.message.reply_text("해당 ID의 유저를 찾을 수 없습니다.")

### 자동 전송 작업
async def send_auto_price():
    try:
        async with httpx.AsyncClient() as client:
            coins = ["bitcoin", "ethereum", "xrp", "solana", "dogecoin"]
            names = {
                "bitcoin": "BTC (비트코인)",
                "ethereum": "ETH (이더리움)",
                "xrp": "XRP (리플)",
                "solana": "SOL (솔라나)",
                "dogecoin": "DOGE (도지코인)",
            }
            result = "📈 실시간 시세 알림\n"
            for coin in coins:
                url = f"https://api.coinpaprika.com/v1/tickers/{coin}"
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                data = r.json()
                price = data["quotes"]["USD"]["price"]
                percent = data["quotes"]["USD"]["percent_change_1h"]
                arrow = "▲" if percent >= 0 else "▼"
                emoji = "🟢" if percent >= 0 else "🔴"
                result += f"{emoji} {names[coin]}: ${price:,.4f} ({arrow} {abs(percent):.2f}%)\n"
            await application.bot.send_message(chat_id=CHAT_ID, text=result.strip())
    except Exception as e:
        logging.error(f"자동 시세 전송 오류: {e}")

### Flask Keepalive
@app.route("/")
def index():
    return "Bot is running"

### 실행 함수
def run():
    loop = asyncio.get_event_loop()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # 스케줄러 실행
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(send_auto_price()), IntervalTrigger(minutes=2))
    scheduler.start()

    # Flask 실행
    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # 봇 실행
    application.run_polling()

if __name__ == "__main__":
    run()
