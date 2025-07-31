# coinnews_bot.py
import os
import logging
from datetime import datetime, timedelta
import asyncio
import feedparser
import httpx
from deep_translator import GoogleTranslator
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, ChatMember
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes,
                          MessageHandler, filters, ChatMemberHandler)

# === 환경변수 ===
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROUP_ID = int(os.environ.get("TELEGRAM_GROUP_ID"))

# === 초기 세팅 ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)
scheduler = BackgroundScheduler()
user_id_map = {}  # 고유번호 매핑
user_counter = 1
latest_news_links = set()
price_cache = {}

# === Helper ===
def percent_change(old, new):
    try:
        change = ((new - old) / old) * 100
        arrow = "🔼" if change >= 0 else "🔽"
        emoji = "🔵" if change >= 0 else "🔴"  # 🔵 = green, 🔴 = red
        return f"{emoji}{arrow} {abs(change):.2f}%"
    except:
        return "-"

async def is_group_member(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.OWNER, ChatMember.ADMINISTRATOR]
    except:
        return False

# === 명령어 ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    if not await is_group_member(update.effective_user.id, context): return
    await update.message.reply_text("\u2705 코인 정보봇입니다.\n/help 명령어로 사용법을 확인하세요.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    if not await is_group_member(update.effective_user.id, context): return
    await update.message.reply_text("""
<b>\u2753 사용 가능한 명령어</b>
/start - 봇 작동 확인
/help - 도움말 출력
/price - 주요 코인 시세 보기
""", parse_mode='HTML')

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    if not await is_group_member(update.effective_user.id, context): return
    await send_price_message(context)

# === 가격 전송 ===
async def fetch_price(symbol_id):
    url = f"https://api.coinpaprika.com/v1/tickers/{symbol_id}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        if r.status_code == 200:
            data = r.json()
            return float(data['quotes']['USD']['price'])
    return None

async def send_price_message(context: ContextTypes.DEFAULT_TYPE):
    coins = [
        ("BTC", "bitcoin", "비트코인"),
        ("ETH", "ethereum", "이더리움"),
        ("XRP", "xrp", "리플"),
        ("SOL", "solana", "솔라나"),
        ("DOGE", "dogecoin", "도지코인"),
    ]
    msg = "\u2728 <b>실시간 코인 시세</b> (USD)\n"
    for symbol, cid, name_kr in coins:
        price = await fetch_price(cid)
        if not price:
            continue
        change = percent_change(price_cache.get(cid, price), price)
        price_cache[cid] = price
        msg += f"{symbol} ({name_kr}) : ${price:.3f}  {change}\n"

    try:
        await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

# === 뉴스 ===
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    await send_news(context)

async def send_news(context: ContextTypes.DEFAULT_TYPE):
    global latest_news_links
    feed = feedparser.parse("https://cointelegraph.com/rss")
    new_items = []
    for entry in feed.entries[:5]:
        if entry.link in latest_news_links:
            continue
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        published = entry.published
        new_items.append(f"<b>{translated}</b>\n{published}\n{entry.link}\n")
        latest_news_links.add(entry.link)

    if new_items:
        msg = "\ud83d\udcf0 <b>코인 뉴스</b> (Cointelegraph)\n" + "\n".join(new_items)
        await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode='HTML')

# === 랭킹 ===
async def send_coin_ranking(context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.coinpaprika.com/v1/tickers"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            coins = r.json()
        top = sorted(coins, key=lambda x: x['quotes']['USD']['percent_change_24h'], reverse=True)[:10]
        bottom = sorted(coins, key=lambda x: x['quotes']['USD']['percent_change_24h'])[:10]
        msg = "<b>\ud83c\udf1f 코인 랭킹 (24h)</b>\n\n<b>\u2191 상승 TOP 10</b>\n"
        for c in top:
            msg += f"{c['symbol']} ({c['name']}) : {c['quotes']['USD']['percent_change_24h']:.2f}%\n"
        msg += "\n<b>\u2193 하락 TOP 10</b>\n"
        for c in bottom:
            msg += f"{c['symbol']} ({c['name']}) : {c['quotes']['USD']['percent_change_24h']:.2f}%\n"
        await context.bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"랭킹 전송 오류: {e}")

# === 입장 / 차단 관리 ===
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_counter
    for user in update.message.new_chat_members:
        if user.id not in user_id_map:
            user_id_map[user.id] = user_counter
            user_counter += 1
        uid = user_id_map[user.id]
        await update.effective_chat.send_message(
            f"\ud83d\udc4b 환영합니다 {user.full_name} (ID: {uid})\n/help 로 기능 확인하세요."
        )

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID: return
    if not context.args: return
    try:
        target_id = None
        for uid, num in user_id_map.items():
            if str(num) == context.args[0]:
                target_id = uid
                break
        if target_id:
            await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=target_id)
            await update.message.reply_text(f"\u274c 유저 ID {context.args[0]} 강퇴 완료")
        else:
            await update.message.reply_text("해당 고유번호 유저를 찾을 수 없습니다.")
    except Exception as e:
        logger.error(f"강퇴 오류: {e}")

# === 스케줄러 ===
def start_scheduler(app):
    scheduler.add_job(lambda: asyncio.run(send_price_message(app)), 'interval', minutes=2)
    scheduler.add_job(lambda: asyncio.run(send_coin_ranking(app)), 'interval', hours=1)
    scheduler.add_job(lambda: asyncio.run(send_news(app)), 'interval', minutes=5)
    scheduler.start()
    asyncio.run(send_price_message(app))  # 최초 실행
    asyncio.run(send_coin_ranking(app))
    asyncio.run(send_news(app))

# === Flask Thread ===
@app.route('/')
def home():
    return 'Bot is running'

# === Main ===
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('price', price))
    application.add_handler(CommandHandler('news', news))
    application.add_handler(CommandHandler('ban', ban))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    start_scheduler(application)
    application.run_polling()

if __name__ == '__main__':
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000))), daemon=True).start()
    asyncio.run(main())
