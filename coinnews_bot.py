import os
import logging
import asyncio
from datetime import datetime, timedelta
import feedparser
import httpx
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update, Chat, ChatMemberUpdated
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# 환경변수
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROUP_CHAT_ID = os.environ.get("TELEGRAM_GROUP_CHAT_ID")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")  # 쉼표로 구분된 숫자 ID들
ADMIN_ID_LIST = [int(i.strip()) for i in ADMIN_IDS.split(",") if i.strip().isdigit()]

# 기본 설정
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
scheduler = BackgroundScheduler()
user_db = {}  # {user_id: {'id': xxxx, 'name': '닉네임'}}
news_cache = set()
coin_history = {}
user_counter = 1000
user_activity = {}

# 📌 고유 ID 발급 함수
def assign_user_id(user_id, username):
    global user_counter
    if user_id not in user_db:
        user_counter += 1
        user_db[user_id] = {"id": user_counter, "name": username or f"user{user_counter}"}
    return user_db[user_id]["id"]

# ✅ 관리자 확인
def is_admin(user_id):
    return user_id in ADMIN_ID_LIST

# ✅ 개인 채팅에서만 실행
def private_chat_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != ChatType.PRIVATE:
            return
        return await func(update, context)
    return wrapper

# ✅ 그룹 유저 인증 여부 확인
def is_registered(user_id):
    return user_id in user_db

# ✅ 메시지 활동 기록
def record_activity(user_id):
    user_activity.setdefault(user_id, {"messages": 0, "last": datetime.now()})
    user_activity[user_id]["messages"] += 1
    user_activity[user_id]["last"] = datetime.now()

# ✅ 1. /start
@private_chat_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("❌ 그룹에 먼저 참여해주세요.")
        return
    msg = "🟢 코인봇 사용 안내\n/help : 명령어 목록\n/price : 주요 코인 시세\n/news : 최신 뉴스\n/summary : 요약\n/analyze [코인]"
    await update.message.reply_text(msg)

# ✅ 2. /help
@private_chat_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🧾 사용 가능한 명령어:\n"
        "/start - 봇 시작 안내\n"
        "/price - 주요 코인 시세 보기\n"
        "/news - 최신 뉴스 보기\n"
        "/summary - 오늘 요약\n"
        "/analyze [코인] - 분석 요약\n"
        "\n👑 관리자 전용:\n"
        "/ban [id] /unban [id]\n"
        "/id [@username or id]\n"
        "/config /stats"
    )
    await update.message.reply_text(msg)

# ✅ 3. /test
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("✅ 개인 메시지 테스트 응답 완료")
    elif str(update.effective_chat.id) == GROUP_CHAT_ID:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="✅ 그룹방 테스트 응답 완료")

# ✅ 4. 뉴스 전송
async def send_news(context: ContextTypes.DEFAULT_TYPE):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    new_items = []
    for entry in feed.entries[:5]:
        if entry.link in news_cache:
            continue
        news_cache.add(entry.link)
        translated = GoogleTranslator(source="auto", target="ko").translate(entry.title)
        new_items.append(f"🗞 {translated}\n🔗 {entry.link}")
    if new_items:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="\n\n".join(new_items))

# ✅ 5. 가격 전송
async def send_price(context: ContextTypes.DEFAULT_TYPE):
    coin_ids = {
        "bitcoin": "비트코인",
        "ethereum": "이더리움",
        "ripple": "리플",
        "solana": "솔라나",
        "dogecoin": "도지코인",
    }
    msg = "💰 실시간 코인 시세\n\n"
    async with httpx.AsyncClient() as client:
        res = await client.get("https://api.coinpaprika.com/v1/tickers")
        upbit = await client.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE")

    coin_data = {c["id"]: c for c in res.json()}
    upbit_data = {item["market"]: item for item in upbit.json()}

    for pid, name in coin_ids.items():
        data = coin_data.get(pid, {})
        price_usd = data.get("quotes", {}).get("USD", {}).get("price", 0)
        change = data.get("quotes", {}).get("USD", {}).get("percent_change_1h", 0)

        upbit_price = 0
        if pid == "bitcoin":
            upbit_price = upbit_data.get("KRW-BTC", {}).get("trade_price", 0)
        elif pid == "ethereum":
            upbit_price = upbit_data.get("KRW-ETH", {}).get("trade_price", 0)
        elif pid == "ripple":
            upbit_price = upbit_data.get("KRW-XRP", {}).get("trade_price", 0)
        elif pid == "solana":
            upbit_price = upbit_data.get("KRW-SOL", {}).get("trade_price", 0)
        elif pid == "dogecoin":
            upbit_price = upbit_data.get("KRW-DOGE", {}).get("trade_price", 0)

        kimchi_premium = (upbit_price / (price_usd * 1300) - 1) * 100 if price_usd else 0

        arrow = "📈" if change > 0 else "📉"
        msg += (
            f"{name} ({pid.upper()})\n"
            f"{arrow} USD: ${price_usd:,.2f} ({change:+.2f}%)\n"
            f"🇰🇷 원화: ₩{upbit_price:,.0f} | 김프: {kimchi_premium:+.2f}%\n\n"
        )

    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)

# ✅ 유저 입장 감지 및 고유 ID 부여
async def member_update(update: ChatMemberUpdated, context: ContextTypes.DEFAULT_TYPE):
    if update.chat.id != int(GROUP_CHAT_ID):
        return
    user = update.chat_member.new_chat_member.user
    assign_user_id(user.id, user.username)
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"👋 {user.mention_html()}님 환영합니다!\n1:1 개인 메시지로 /start 입력해 기능을 사용해보세요.",
        parse_mode=ParseMode.HTML,
    )

# ✅ Flask 서버
@app.route("/")
def index():
    return "Coin Bot Running"

# ✅ 메인
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))

    scheduler.add_job(send_news, "interval", minutes=30, args=[application.bot])
    scheduler.add_job(send_price, "interval", minutes=2, args=[application.bot])
    scheduler.start()

    await application.run_polling()

# ✅ 실행
if __name__ == "__main__":
    import threading

    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(main())
