import os
import json
import time
import logging
import sqlite3
from typing import Dict, Any, Optional

import httpx
from flask import Flask, request, jsonify
from telegram import Update, BotCommand
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ----------------------------------
# 기본 설정
# ----------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("coin-longshort")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_URL        = os.environ["WEBHOOK_URL"]
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "secret-token")
GROUP_CHAT_ID      = os.environ["GROUP_CHAT_ID"]
ADMIN_USER_ID      = int(os.environ.get("ADMIN_USER_ID", "0"))
WATCHLIST          = os.environ.get("WATCHLIST", "BTCUSDT,ETHUSDT").replace(" ", "").split(",")
PUMP_THRESHOLD_PCT = float(os.environ.get("PUMP_THRESHOLD_PCT", "2.5"))
TIMEZONE           = os.environ.get("TZ", "Asia/Seoul")

try:
    os.environ["TZ"] = TIMEZONE
    import time as _time
    _time.tzset()
except Exception:
    pass

# ----------------------------------
# Flask
# ----------------------------------
flask_app = Flask(__name__)

@flask_app.get("/")
def health():
    return jsonify({"status": "ok", "service": "coin-longshort-bot"})

def _check_webhook_secret(req) -> bool:
    return req.headers.get("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET

@flask_app.post("/webhook")
def telegram_webhook():
    if not _check_webhook_secret(request):
        return jsonify({"ok": False, "error": "invalid secret"}), 401
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "invalid json"}), 400

    update = Update.de_json(data, application.bot)
    application.create_task(application.process_update(update))
    return jsonify({"ok": True})

# ----------------------------------
# 저장소 (SQLite)
# ----------------------------------
DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_seen_ts INTEGER,
        unique_key TEXT
    )
    """)
    conn.commit()
    conn.close()

def upsert_user(user_id: int, username: str) -> str:
    unique_key = f"U{user_id}"
    ts = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT unique_key FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO users (user_id, username, first_seen_ts, unique_key) VALUES (?, ?, ?, ?)",
                  (user_id, username or "", ts, unique_key))
        conn.commit()
    conn.close()
    return unique_key

# ----------------------------------
# 바이낸스 지표 수집 & 계산
# ----------------------------------
BINANCE_FAPI = "https://fapi.binance.com"
client = httpx.AsyncClient(timeout=10)

async def get_json(url: str, params: Dict[str, Any] = None) -> Any:
    r = await client.get(url, params=params)
    r.raise_for_status()
    return r.json()

async def binance_global_long_short_ratio(symbol: str, interval: str = "5m", limit: int = 1) -> Optional[float]:
    url = f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio"
    data = await get_json(url, {"symbol": symbol, "period": interval, "limit": limit})
    if not data:
        return None
    return float(data[-1]["longShortRatio"])

async def binance_taker_long_short_ratio(symbol: str, interval: str = "5m", limit: int = 1) -> Optional[float]:
    url = f"{BINANCE_FAPI}/futures/data/takerlongshortRatio"
    data = await get_json(url, {"symbol": symbol, "period": interval, "limit": limit})
    if not data:
        return None
    return float(data[-1]["buySellRatio"])

async def binance_open_interest(symbol: str) -> Optional[float]:
    url = f"{BINANCE_FAPI}/fapi/v1/openInterest"
    data = await get_json(url, {"symbol": symbol})
    if "openInterest" in data:
        return float(data["openInterest"])
    return None

async def binance_price_change_pct(symbol: str, minutes: int = 5) -> Optional[float]:
    url = f"{BINANCE_FAPI}/fapi/v1/klines"
    data = await get_json(url, {"symbol": symbol, "interval": "5m", "limit": 2})
    if len(data) < 2:
        return None
    prev_close = float(data[-2][4])
    last_close = float(data[-1][4])
    if prev_close == 0:
        return None
    return (last_close - prev_close) / prev_close * 100.0

def _ratio_to_prob(r: Optional[float]) -> Optional[float]:
    if r is None:
        return None
    return r / (1.0 + r)

async def compute_long_short_probability(symbol: str, interval: str = "5m") -> Dict[str, Any]:
    glsr = await binance_global_long_short_ratio(symbol, interval=interval)
    tlsr = await binance_taker_long_short_ratio(symbol, interval=interval)
    oi   = await binance_open_interest(symbol)

    w_glsr = 0.45
    w_tlsr = 0.45
    w_oi   = 0.10

    comps, weights = [], []
    p_glsr = _ratio_to_prob(glsr)
    p_tlsr = _ratio_to_prob(tlsr)

    if p_glsr is not None:
        comps.append(p_glsr); weights.append(w_glsr)
    if p_tlsr is not None:
        comps.append(p_tlsr); weights.append(w_tlsr)

    if comps:
        avg = sum(c*w for c, w in zip(comps, weights)) / sum(weights)
        if oi:
            # OI가 크면 약간 롱/숏 신뢰도 상향(중립에서 ±로 치우친 값 유지)
            import math
            bump = (1.0 / (1.0 + math.exp(-((oi/1e6)-1.0)))) * 0.05
            avg = min(max(avg + bump, 0.0), 1.0)
    else:
        avg = 0.5

    long_prob = round(avg * 100.0, 2)
    short_prob = round(100.0 - long_prob, 2)
    return {
        "symbol": symbol,
        "interval": interval,
        "global_long_short_ratio": glsr,
        "taker_long_short_ratio": tlsr,
        "open_interest": oi,
        "long_prob_pct": long_prob,
        "short_prob_pct": short_prob,
    }

# ----------------------------------
# Telegram (PTB v20.3+)
# ----------------------------------
application: Application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).updater(None).build()
only_dm = filters.ChatType.PRIVATE

async def _ensure_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return update.effective_chat and update.effective_chat.type == ChatType.PRIVATE

def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and str(user_id) == str(ADMIN_USER_ID)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context): return
    user = update.effective_user
    uniq = upsert_user(user.id, user.username or "")
    text = (
        f"환영합니다, {user.first_name or '사용자'}님!\n"
        f"• 고유 ID: `{uniq}`\n"
        f"• 사용 가능 명령어: /ratio /watchlist /help\n\n"
        f"※ 그룹방에서는 자동 리포트만 전송됩니다."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context): return
    text = (
        "사용 방법\n"
        "• /ratio 심볼 [간격]\n"
        "   - 예) /ratio BTCUSDT 5m  |  /ratio ETHUSDT 1h\n"
        "• /watchlist : 현재 모니터링 심볼\n"
        "관리자 전용: /admin_broadcast 메시지"
    )
    await update.message.reply_text(text)

async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context): return
    await update.message.reply_text("모니터링 목록: " + ", ".join(WATCHLIST))

async def ratio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context): return
    args = context.args
    if not args:
        await update.message.reply_text("예) /ratio BTCUSDT [5m|15m|1h]")
        return
    symbol = args[0].upper()
    interval = args[1] if len(args) >= 2 else "5m"
    try:
        result = await compute_long_short_probability(symbol, interval)
        pct5 = await binance_price_change_pct(symbol, minutes=5)
        lines = [
            f"📊 *{symbol}* ({interval})",
            f"롱 확률: *{result['long_prob_pct']}%*",
            f"숏 확률: *{result['short_prob_pct']}%*",
        ]
        if result["global_long_short_ratio"] is not None:
            lines.append(f"GLSR(글로벌): {result['global_long_short_ratio']:.3f}")
        if result["taker_long_short_ratio"] is not None:
            lines.append(f"TLSR(테이커): {result['taker_long_short_ratio']:.3f}")
        if result["open_interest"] is not None:
            lines.append(f"Open Interest: {result['open_interest']:.0f}")
        if pct5 is not None:
            lines.append(f"5분 변화율: {pct5:+.2f}%")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.exception("ratio_cmd error")
        await update.message.reply_text(f"오류: {e}")

async def admin_broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context): return
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("사용법: /admin_broadcast 메시지내용")
        return
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"[공지] {msg}")
    await update.message.reply_text("전송 완료")

async def ignore_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return

application.add_handler(CommandHandler("start", start_cmd, filters=only_dm))
application.add_handler(CommandHandler("help", help_cmd, filters=only_dm))
application.add_handler(CommandHandler("watchlist", watchlist_cmd, filters=only_dm))
application.add_handler(CommandHandler("ratio", ratio_cmd, filters=only_dm))
application.add_handler(CommandHandler("admin_broadcast", admin_broadcast_cmd, filters=only_dm))
application.add_handler(MessageHandler(filters.ChatType.GROUPS, ignore_in_group))

# ----------------------------------
# 스케줄러
# ----------------------------------
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

async def hourly_report(bot):
    lines = ["⏰ 1시간 리포트"]
    for sym in WATCHLIST:
        try:
            r = await compute_long_short_probability(sym, "1h")
            lines.append(f"• {sym}  롱 {r['long_prob_pct']}% / 숏 {r['short_prob_pct']}%")
        except Exception as e:
            lines.append(f"• {sym} 데이터 오류: {e}")
    await bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(lines))

async def four_hour_report(bot):
    lines = ["⏰ 4시간 리포트"]
    for sym in WATCHLIST:
        try:
            r = await compute_long_short_probability(sym, "4h")
            lines.append(f"• {sym}  롱 {r['long_prob_pct']}% / 숏 {r['short_prob_pct']}%")
        except Exception as e:
            lines.append(f"• {sym} 데이터 오류: {e}")
    await bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(lines))

async def pump_detector(bot):
    alerts = []
    for sym in WATCHLIST:
        try:
            pct = await binance_price_change_pct(sym, minutes=5)
            if pct is not None and pct >= PUMP_THRESHOLD_PCT:
                alerts.append(f"🚀 {sym} 단기 급등: +{pct:.2f}% (5분)")
        except Exception as e:
            logger.warning(f"pump_detector {sym} error: {e}")
    if alerts:
        await bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(alerts))

def setup_scheduler(app: Application):
    scheduler.add_job(lambda: app.create_task(hourly_report(app.bot)), CronTrigger(minute=0))
    scheduler.add_job(lambda: app.create_task(four_hour_report(app.bot)), CronTrigger(minute=0, hour="*/4"))
    scheduler.add_job(lambda: app.create_task(pump_detector(app.bot)), CronTrigger(minute="*/5"))
    scheduler.start()

# ----------------------------------
# 부트스트랩
# ----------------------------------
async def on_startup(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "시작하기"),
        BotCommand("help", "도움말"),
        BotCommand("watchlist", "모니터링 목록 보기"),
        BotCommand("ratio", "롱/숏 확률 보기"),
    ])
    await app.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message","edited_message","channel_post","callback_query","chat_member"]
    )
    init_db()
    logger.info("Startup OK, webhook set.")

async def on_shutdown(app: Application):
    await client.aclose()
    logger.info("HTTP client closed.")

def main():
    application.post_init = lambda app: setup_scheduler(app)
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        webhook_url=None,
        stop_signals=None,
        close_loop=False,
        drop_pending_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
