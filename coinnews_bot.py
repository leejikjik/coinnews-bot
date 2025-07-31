# coinnews_bot.py

import os
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio
import httpx
import feedparser
from deep_translator import GoogleTranslator
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID")

flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Bot is running!"

last_prices = {}
sent_news_links = set()
user_map = {}  # user_id: {"name": str, "username": str}

async def is_group_member(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        if await is_group_member(context.bot, update.effective_user.id):
            await update.message.reply_text("✅ 봇이 작동 중입니다!\n/price : 주요 코인 시세\n/id : 내 고유번호\n/help : 명령어 안내")
        else:
            await update.message.reply_text("⚠️ 이 기능은 그룹 참가자만 사용할 수 있습니다.")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        if await is_group_member(context.bot, update.effective_user.id):
            await update.message.reply_text("✅ 테스트 성공!")
        else:
            await update.message.reply_text("⚠️ 이 기능은 그룹 참가자만 사용할 수 있습니다.")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(f"🆔 당신의 고유번호는 {update.effective_user.id} 입니다.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 사용 가능한 명령어:\n\n"
        "/start - 봇 작동 확인 (DM 전용, 그룹 참가자만 사용 가능)\n"
        "/price - 주요 코인 시세 (DM 전용)\n"
        "/id - 내 고유번호 확인 (DM 전용)\n"
        "/news - 최신 뉴스 확인 (그룹 전용)\n"
        "/help - 도움말 보기\n\n"
        "👮 관리자 전용:\n"
        "/ban [고유번호] - 유저 강퇴\n"
        "/whois [@username 또는 이름] - 유저 고유번호 조회"
    )

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ 이 명령어는 그룹방에서만 사용 가능합니다.")
        return

    feed = feedparser.parse("https://cointelegraph.com/rss")
    new_msgs = []
    for entry in feed.entries[::-1]:
        if entry.link in sent_news_links:
            continue
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 <b>{translated}</b>\n{entry.link}"
        new_msgs.append(msg)
        sent_news_links.add(entry.link)

    if not new_msgs:
        await update.message.reply_text("✅ 새로운 뉴스가 없습니다.")
    else:
        for msg in new_msgs:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="HTML")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    if not await is_group_member(context.bot, update.effective_user.id):
        await update.message.reply_text("⚠️ 이 기능은 그룹 참가자만 사용할 수 있습니다.")
        return
    await send_price(context.bot, update.effective_chat.id)

async def send_price(bot, chat_id):
    coins = {
        "btc-bitcoin": "BTC (비트코인)",
        "eth-ethereum": "ETH (이더리움)",
        "xrp-xrp": "XRP (리플)",
        "sol-solana": "SOL (솔라나)",
        "doge-dogecoin": "DOGE (도지코인)",
    }
    try:
        async with httpx.AsyncClient() as client:
            msg = "<b>📊 주요 코인 시세</b>\n"
            for coin_id, name in coins.items():
                url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    price = data["quotes"]["USD"]["price"]
                    prev = last_prices.get(coin_id)
                    diff_pct = ""
                    symbol = ""
                    color = ""
                    if prev:
                        change = (price - prev) / prev * 100
                        if change > 0:
                            symbol = "▲"
                            color = "#00C851"  # green
                        elif change < 0:
                            symbol = "▼"
                            color = "#ff4444"  # red
                        diff_pct = f" <b><font color='{color}'>{symbol} {abs(change):.2f}%</font></b>"
                    last_prices[coin_id] = price
                    msg += f"{name} : ${price:,.2f}{diff_pct}\n"
            await bot.send_message(chat_id=chat_id, text=msg.strip(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"시세 전송 오류: {e}")

async def send_ranking(bot):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()
            ranked = sorted(data, key=lambda x: x["quotes"]["USD"]["percent_change_24h"], reverse=True)
            top10_up = ranked[:10]
            top10_down = ranked[-10:]
            msg = "📊 코인 랭킹 (24시간 기준)\n\n📈 <b>상승률 TOP10</b>\n"
            for c in top10_up:
                msg += f"{c['symbol']} : {c['quotes']['USD']['percent_change_24h']:.2f}%\n"
            msg += "\n📉 <b>하락률 TOP10</b>\n"
            for c in top10_down:
                msg += f"{c['symbol']} : {c['quotes']['USD']['percent_change_24h']:.2f}%\n"
            await bot.send_message(chat_id=GROUP_ID, text=msg.strip(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"코인 랭킹 오류: {e}")

async def send_hot(bot):
    try:
        url = "https://api.coinpaprika.com/v1/tickers"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()
            hot = [c for c in data if c["quotes"]["USD"]["percent_change_24h"] > 30]
            if not hot:
                return
            msg = "🚨 급등 감지 코인 (24시간 기준)\n"
            for c in hot:
                msg += f"{c['symbol']} : +{c['quotes']['USD']['percent_change_24h']:.2f}%\n"
            await bot.send_message(chat_id=GROUP_ID, text=msg.strip(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"급등 감지 오류: {e}")

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        user_map[user.id] = {"name": user.first_name, "username": user.username or ""}
        msg = f"👋 {user.first_name}님, 환영합니다!\n당신의 고유번호는 <code>{user.id}</code> 입니다."
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="HTML")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != int(CHAT_ID): return
    if not context.args: return
    try:
        target_id = int(context.args[0])
        await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=target_id)
        await update.message.reply_text(f"✅ {target_id} 강퇴 완료")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 강퇴 실패: {e}")

async def whois(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != int(CHAT_ID): return
    if not context.args: return
    keyword = context.args[0].lower()
    found = []
    for uid, info in user_map.items():
        if keyword in info["name"].lower() or keyword in info["username"].lower():
            found.append(f"{info['name']} (@{info['username']}) → <code>{uid}</code>")
    if found:
        await update.message.reply_text("\n".join(found), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ 일치하는 유저 없음")

# 스케줄러
scheduler = BackgroundScheduler()

def start_scheduler(bot):
    loop = asyncio.get_event_loop()
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_price(bot, GROUP_ID), loop), 'interval', minutes=2)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_ranking(bot), loop), 'interval', hours=1)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(send_hot(bot), loop), 'interval', minutes=10)
    scheduler.add_job(lambda: asyncio.run_coroutine_threadsafe(auto_news(bot), loop), 'interval', hours=1)
    scheduler.start()
    asyncio.run_coroutine_threadsafe(send_ranking(bot), loop)  # 최초 1회 전송
    asyncio.run_coroutine_threadsafe(auto_news(bot), loop)     # 최초 뉴스 전송

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("whois", whois))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()
    start_scheduler(app.bot)
    app.run_polling()

async def auto_news(bot):
    feed = feedparser.parse("https://cointelegraph.com/rss")
    for entry in feed.entries[::-1]:
        if entry.link in sent_news_links:
            continue
        translated = GoogleTranslator(source='auto', target='ko').translate(entry.title)
        msg = f"📰 <b>{translated}</b>\n{entry.link}"
        await bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="HTML")
        sent_news_links.add(entry.link)

if __name__ == "__main__":
    main()
