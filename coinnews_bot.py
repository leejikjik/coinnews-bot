# coinnews_bot.py
import os
import logging
import asyncio
import httpx
import feedparser
from flask import Flask
from datetime import datetime, timedelta
from pytz import timezone
from telegram import Update, ChatMemberUpdated
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, ChatMemberHandler
)
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator

# 설정
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # 그룹방 ID
KST = timezone("Asia/Seoul")
app = Flask(__name__)
scheduler = BackgroundScheduler()
user_map = {}
sent_news_titles = set()
first_price_sent = False
first_rank_sent = False

# 기본 로그
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 사용자 제한
async def is_dm_allowed(update: Update):
    return update.effective_chat.type == "private"

async def is_group_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(chat_id=int(CHAT_ID), user_id=update.effective_user.id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ✅ 명령어 핸들러
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_dm_allowed(update) and await is_group_member(update, context):
        await update.message.reply_text("🟢 봇이 작동 중입니다.\n/price : 현재 시세\n/help : 명령어 안내")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_dm_allowed(update) and await is_group_member(update, context):
        msg = (
            "🛠 명령어 목록\n"
            "/start - 봇 작동 확인\n"
            "/price - 주요 코인 시세\n"
            "/news - 최신 뉴스 보기 (그룹 전용)\n"
            "/ban [고유번호] - 유저 강퇴 (관리자 전용)"
        )
        await update.message.reply_text(msg)

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ 테스트 완료 - 봇이 정상 작동 중입니다.")

# ✅ 코인 시세 전송
async def send_price_message(app):
    global first_price_sent
    coins = {
        "bitcoin": "비트코인",
        "ethereum": "이더리움",
        "xrp": "리플",
        "solana": "솔라나",
        "dogecoin": "도지코인"
    }
    result = []
    async with httpx.AsyncClient() as client:
        for coin_id, ko_name in coins.items():
            try:
                url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
                r = await client.get(url)
                data = r.json()
                price = float(data["quotes"]["USD"]["price"])
                change = float(data["quotes"]["USD"]["percent_change_1h"])
                arrow = "▲" if change >= 0 else "▼"
                color = "green" if change >= 0 else "red"
                result.append(f"<b>{data['symbol']} ({ko_name})</b> : ${price:.4f} <code><font color='{color}'>{arrow} {abs(change):.2f}%</font></code>")
            except Exception as e:
                logger.error(f"시세 오류: {e}")

    if result:
        try:
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text="📈 <b>실시간 코인 시세 (1시간 변동률)</b>\n" + "\n".join(result),
                parse_mode="HTML"
            )
            first_price_sent = True
        except Exception as e:
            logger.error(f"시세 전송 오류: {e}")

# ✅ 코인 랭킹 전송
async def send_coin_rank(app):
    global first_rank_sent
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coinpaprika.com/v1/tickers")
            data = sorted(r.json(), key=lambda x: x["quotes"]["USD"]["percent_change_24h"], reverse=True)[:10]
            lines = []
            for coin in data:
                lines.append(f"{coin['symbol']} ({coin['name']}) : <b>{coin['quotes']['USD']['percent_change_24h']:.2f}%</b>")
            text = "📊 <b>상승률 TOP10 (24h)</b>\n" + "\n".join(lines)
            await app.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
            first_rank_sent = True
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# ✅ 급등 코인 감지
async def detect_surge(app):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.coinpaprika.com/v1/tickers")
            coins = [c for c in r.json() if c["quotes"]["USD"]["percent_change_24h"] >= 20]
            if coins:
                msg = "🚨 <b>급등 코인 알림 (24h +20%)</b>\n"
                msg += "\n".join([f"{c['symbol']} ({c['name']}) : {c['quotes']['USD']['percent_change_24h']:.2f}%" for c in coins])
                await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

# ✅ 뉴스 전송
async def send_news(app, initial=False):
    global sent_news_titles
    feed = feedparser.parse("https://cointelegraph.com/rss")
    new_entries = []
    for entry in feed.entries[:5]:
        if entry.title not in sent_news_titles or initial:
            translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
            new_entries.append(f"📰 <b>{translated}</b>\n{entry.link}")
            sent_news_titles.add(entry.title)

    if new_entries:
        await app.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(new_entries), parse_mode="HTML")

# ✅ 입장시 유저 관리
async def welcome(update: ChatMemberUpdated, context: ContextTypes.DEFAULT_TYPE):
    user = update.chat_member.new_chat_member.user
    if user.id not in user_map:
        user_map[user.id] = len(user_map) + 1
    uid = user_map[user.id]
    await context.bot.send_message(chat_id=CHAT_ID, text=f"👋 <b>{user.full_name}</b> 님 환영합니다!\n고유번호: {uid}", parse_mode="HTML")

# ✅ /ban 명령어
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_dm_allowed(update):
        if context.args:
            try:
                target_uid = int(context.args[0])
                for user_id, uid in user_map.items():
                    if uid == target_uid:
                        await context.bot.ban_chat_member(chat_id=CHAT_ID, user_id=user_id)
                        await update.message.reply_text(f"🚫 유저 {uid} 차단 완료")
                        return
                await update.message.reply_text("❗ 해당 고유번호의 유저를 찾을 수 없습니다.")
            except:
                await update.message.reply_text("❗ 올바른 형식: /ban [고유번호]")

# ✅ 스케줄러
def start_scheduler(app):
    scheduler.add_job(lambda: asyncio.create_task(send_price_message(app)), "interval", minutes=2)
    scheduler.add_job(lambda: asyncio.create_task(send_coin_rank(app)), "interval", hours=1)
    scheduler.add_job(lambda: asyncio.create_task(detect_surge(app)), "interval", minutes=10)
    scheduler.add_job(lambda: asyncio.create_task(send_news(app)), "interval", minutes=15)
    scheduler.start()
    asyncio.create_task(send_price_message(app))
    asyncio.create_task(send_coin_rank(app))
    asyncio.create_task(send_news(app, initial=True))

# ✅ Flask keepalive
@app.route("/")
def home():
    return "Bot is running"

# ✅ 메인 실행
async def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("price", send_price_message))
    application.add_handler(CommandHandler("news", lambda u, c: send_news(c.application)))

    application.add_handler(ChatMemberHandler(welcome, ChatMemberHandler.CHAT_MEMBER))

    start_scheduler(application)
    await application.run_polling()

if __name__ == "__main__":
    from threading import Thread
    Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 10000}).start()
    asyncio.run(main())
