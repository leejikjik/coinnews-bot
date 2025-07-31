import os
import logging
import asyncio
import feedparser
import httpx
from flask import Flask
from datetime import datetime, timedelta
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from deep_translator import GoogleTranslator
from telegram import Update, Chat, ChatMember, ChatMemberUpdated, constants
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler,
    filters, ChatMemberHandler
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # 그룹방 ID

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

application = ApplicationBuilder().token(TOKEN).build()
scheduler = BackgroundScheduler()

KST = timezone("Asia/Seoul")

user_ids = {}
sent_news_links = set()

coin_kor = {
    'bitcoin': '비트코인',
    'ethereum': '이더리움',
    'xrp': '리플',
    'solana': '솔라나',
    'dogecoin': '도지코인'
}

# 📌 1:1 채팅 제한 (그룹 참가자만)
def is_user_allowed(user_id):
    return str(user_id) in user_ids

# ✅ 명령어: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != Chat.PRIVATE:
        return
    user_id = str(update.effective_user.id)
    if not is_user_allowed(user_id):
        await update.message.reply_text("❌ 그룹방 참가자만 사용할 수 있습니다.")
        return
    await update.message.reply_text("🟢 봇 작동 중입니다. /help 로 명령어 확인 가능")

# ✅ 명령어: /help
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != Chat.PRIVATE:
        return
    text = """
📌 사용 가능한 명령어:
/start - 봇 작동 확인
/price - 주요 코인 시세 확인
/news - 최신 뉴스 보기
/summary - 오늘의 요약
/analyze [코인] - 코인 분석
/test - 테스트 응답
/help - 도움말
"""
    await update.message.reply_text(text)

# ✅ 명령어: /test
async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"✅ 테스트 성공! ({'DM' if update.message.chat.type == 'private' else '그룹방'})"
    await update.message.reply_text(text)

# ✅ 뉴스 출력
async def send_news():
    feed = feedparser.parse("https://cointelegraph.com/rss")
    messages = []
    for entry in reversed(feed.entries[:5]):
        if entry.link in sent_news_links:
            continue
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        time_obj = datetime(*entry.published_parsed[:6], tzinfo=timezone('UTC')).astimezone(KST)
        messages.append(f"📰 <b>{translated}</b>\n🕒 {time_obj.strftime('%m/%d %H:%M')}\n🔗 {entry.link}")
        sent_news_links.add(entry.link)
    if messages:
        await application.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages), parse_mode=constants.ParseMode.HTML)

# ✅ 시세 출력
async def send_price():
    coins = ['bitcoin', 'ethereum', 'xrp', 'solana', 'dogecoin']
    url = f'https://api.coinpaprika.com/v1/tickers'
    upbit_url = 'https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE'
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10)
            upbit_res = await client.get(upbit_url, timeout=10)
            data = res.json()
            upbit_data = {item['market']: item for item in upbit_res.json()}

        filtered = [c for c in data if c['id'] in coins]
        lines = []
        for c in filtered:
            cid = c['id']
            symbol = c['symbol']
            name = coin_kor.get(cid, cid)
            price = float(c['quotes']['USD']['price'])
            percent = c['quotes']['USD']['percent_change_1h']
            change = f"📈 <b><font color='green'>▲{percent:.2f}%</font></b>" if percent > 0 else f"📉 <b><font color='red'>▼{abs(percent):.2f}%</font></b>"

            krw_key = f"KRW-{symbol}"
            if krw_key in upbit_data:
                krw_price = upbit_data[krw_key]['trade_price']
                kimchi = ((krw_price / (price * 1300)) - 1) * 100
                kimchi_text = f"🧂 김프: {kimchi:.2f}%"
            else:
                krw_price = None
                kimchi_text = ""

            lines.append(f"💰 {symbol} ({name})\n💵 ${price:,.2f} | ₩{krw_price:,.0f if krw_price else 0}\n{change}  {kimchi_text}")

        await application.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(lines), parse_mode=constants.ParseMode.HTML)

    except Exception as e:
        logging.error(f"[가격 오류] {e}")

# ✅ 유저 입장 감지 + 고유 ID 부여
async def track_join(update: ChatMemberUpdated, context: ContextTypes.DEFAULT_TYPE):
    user = update.chat_member.new_chat_member.user
    user_ids[str(user.id)] = user.username or user.full_name
    text = f"👋 <b>{user.full_name}</b>님 환영합니다!\n\n👉 <b>1:1 채팅</b>으로 저를 눌러 대화해보세요!"
    await context.bot.send_message(chat_id=update.chat.id, text=text, parse_mode=constants.ParseMode.HTML)

# ✅ 명령어: /price (DM 전용)
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != Chat.PRIVATE:
        return
    if not is_user_allowed(str(update.effective_user.id)):
        await update.message.reply_text("❌ 그룹방 참가자만 사용 가능")
        return
    await send_price()

# ✅ 명령어: /news (DM 전용)
async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != Chat.PRIVATE:
        return
    if not is_user_allowed(str(update.effective_user.id)):
        await update.message.reply_text("❌ 그룹방 참가자만 사용 가능")
        return
    await send_news()

# ✅ 명령어: /summary, /analyze (개발 중 placeholder)
async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 요약 기능은 준비 중입니다.")

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 분석 기능은 준비 중입니다.")

# ✅ Flask keep-alive
@app.route('/')
def home():
    return 'Bot running'

# ✅ 스케줄 시작
def start_scheduler():
    scheduler.add_job(lambda: asyncio.run(send_news()), 'interval', minutes=10)
    scheduler.add_job(lambda: asyncio.run(send_price()), 'interval', minutes=2)
    scheduler.start()

# ✅ 핸들러 등록
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_cmd))
application.add_handler(CommandHandler("test", test_cmd))
application.add_handler(CommandHandler("price", price_cmd))
application.add_handler(CommandHandler("news", news_cmd))
application.add_handler(CommandHandler("summary", summary_cmd))
application.add_handler(CommandHandler("analyze", analyze_cmd))
application.add_handler(ChatMemberHandler(track_join, ChatMemberHandler.CHAT_MEMBER))

# ✅ 메인 실행
if __name__ == '__main__':
    start_scheduler()
    import threading
    threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 10000}).start()
    application.run_polling()
