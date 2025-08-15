import os
import json
import time
import hmac
import hashlib
import logging
import sqlite3
import asyncio
from typing import Dict, Any, Optional, Tuple, List

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

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]                  # 필수
WEBHOOK_URL        = os.environ["WEBHOOK_URL"]                         # 필수 (예: https://<your-service>.onrender.com/webhook)
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "secret-token")  # 선택(보안용)
GROUP_CHAT_ID      = os.environ["GROUP_CHAT_ID"]                       # 자동 전송할 그룹 ID (예: -1001234567890)
ADMIN_USER_ID      = int(os.environ.get("ADMIN_USER_ID", "0"))         # 관리자 텔레그램 ID
WATCHLIST          = os.environ.get("WATCHLIST", "BTCUSDT,ETHUSDT").replace(" ", "").split(",")
PUMP_THRESHOLD_PCT = float(os.environ.get("PUMP_THRESHOLD_PCT", "2.5"))  # 급등 감지 임계값(%) - 5분 기준
TIMEZONE           = os.environ.get("TZ", "Asia/Seoul")

# Render/컨테이너에서 TZ 적용
try:
    import time as _time
    os.environ["TZ"] = TIMEZONE
    _time.tzset()  # 일부 환경에서만 적용됨
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
    # Telegram이 보내는 헤더: X-Telegram-Bot-Api-Secret-Token
    token = req.headers.get("X-Telegram-Bot-Api-Secret-Token")
    return token == WEBHOOK_SECRET

@flask_app.post("/webhook")
def telegram_webhook():
    # 보안 토큰 검사(선택)
    if not _check_webhook_secret(request):
        return jsonify({"ok": False, "error": "invalid secret"}), 401

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "invalid json"}), 400

    # Update 객체로 변환 후 PTB 애플리케이션에 전달
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
    """
    글로벌 계정 롱/숏 비율. 값>1 = 롱 우위, <1 = 숏 우위.
    /futures/data/globalLongShortAccountRatio
    """
    url = f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio"
    data = await get_json(url, {"symbol": symbol, "period": interval, "limit": limit})
    if not data:
        return None
    # 가장 최근 값 사용
    return float(data[-1]["longShortRatio"])

async def binance_taker_long_short_ratio(symbol: str, interval: str = "5m", limit: int = 1) -> Optional[float]:
    """
    메이커/테이커 롱숏 체결 비율(롱/숏). >1이면 롱체결 우위.
    /futures/data/takerlongshortRatio
    """
    url = f"{BINANCE_FAPI}/futures/data/takerlongshortRatio"
    data = await get_json(url, {"symbol": symbol, "period": interval, "limit": limit})
    if not data:
        return None
    return float(data[-1]["buySellRatio"])

async def binance_open_interest(symbol: str) -> Optional[float]:
    """
    미결제약정 USD 값 (추세 강도 보조)
    /fapi/v1/openInterest
    """
    url = f"{BINANCE_FAPI}/fapi/v1/openInterest"
    data = await get_json(url, {"symbol": symbol})
    if "openInterest" in data:
        return float(data["openInterest"])
    return None

async def binance_price_change_pct(symbol: str, minutes: int = 5) -> Optional[float]:
    """
    N분 수익률(%) – 급등 감지
    /fapi/v1/continuousKlines or /fapi/v1/klines
    여기서는 선물 심플하게 /fapi/v1/klines 사용
    """
    url = f"{BINANCE_FAPI}/fapi/v1/klines"
    # 5분봉 2개 가져와서 직전 종가 대비 현재 종가 변화율 계산
    data = await get_json(url, {"symbol": symbol, "interval": "5m", "limit": 2})
    if len(data) < 2:
        return None
    prev_close = float(data[-2][4])
    last_close = float(data[-1][4])
    if prev_close == 0:
        return None
    return (last_close - prev_close) / prev_close * 100.0

def sigmoid(x: float) -> float:
    # 안정적 스케일링용
    import math
    return 1.0 / (1.0 + math.exp(-x))

async def compute_long_short_probability(symbol: str, interval: str = "5m") -> Dict[str, Any]:
    """
    여러 지표를 단순 가중 평균해 '롱확률/숏확률' 산출.
    """
    glsr = await binance_global_long_short_ratio(symbol, interval=interval)
    tlsr = await binance_taker_long_short_ratio(symbol, interval=interval)
    oi   = await binance_open_interest(symbol)

    # 기본 가중치
    w_glsr = 0.45
    w_tlsr = 0.45
    w_oi   = 0.10  # OI는 강도 보조

    # 각 비율을 확률로 변환(>1이면 롱 우위)
    def ratio_to_prob(r: Optional[float]) -> Optional[float]:
        if r is None:
            return None
        # r=1이면 50%, r=2면 ~66%, r=0.5면 ~33% 정도가 되게 변환
        # p = r / (1 + r)
        return r / (1.0 + r)

    p_glsr = ratio_to_prob(glsr)  # 0~1
    p_tlsr = ratio_to_prob(tlsr)

    # 결측치 처리
    comps = []
    weights = []
    if p_glsr is not None:
        comps.append(p_glsr)
        weights.append(w_glsr)
    if p_tlsr is not None:
        comps.append(p_tlsr)
        weights.append(w_tlsr)

    # OI로 약간의 보정(큰 OI일수록 자신감 ↑ → 중앙값으로 끌어올림)
    if oi is not None and oi > 0 and len(comps) > 0:
        avg = sum(comps[i] * weights[i] for i in range(len(comps))) / sum(weights)
        bump = sigmoid((oi / 1e6) - 1.0) * 0.05  # 0~+5% 정도
        avg = min(max(avg + bump, 0.0), 1.0)
    elif len(comps) > 0:
        avg = sum(comps[i] * weights[i] for i in range(len(comps))) / sum(weights)
    else:
        avg = 0.5  # 데이터 없으면 중립

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

# 명령어: DM에서만 동작하도록 필터링
only_dm = filters.ChatType.PRIVATE

async def _ensure_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        # 그룹에서는 명령어 무시 (자동 전송만 허용)
        return False
    return True

def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context):
        return
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
    if not await _ensure_dm(update, context):
        return
    text = (
        "사용 방법\n"
        "• /ratio 심볼 [간격]\n"
        "   - 예) /ratio BTCUSDT 5m  |  /ratio ETHUSDT 1h\n"
        "• /watchlist : 현재 모니터링 심볼 확인\n"
        "관리자 전용(개인 DM): /admin_broadcast 메시지"
    )
    await update.message.reply_text(text)

async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context):
        return
    await update.message.reply_text("모니터링 목록: " + ", ".join(WATCHLIST))

async def ratio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_dm(update, context):
        return
    args = context.args
    if len(args) == 0:
        await update.message.reply_text("예) /ratio BTCUSDT [5m|15m|1h]")
        return
    symbol = args[0].upper()
    interval = args[1] if len(args) >= 2 else "5m"
    try:
        result = await compute_long_short_probability(symbol, interval)
        price_change = await binance_price_change_pct(symbol, minutes=5)
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
        if price_change is not None:
            lines.append(f"5분 변화율: {price_change:+.2f}%")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.exception("ratio_cmd error")
        await update.message.reply_text(f"오류: {e}")

async def admin_broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 관리자 전용 + DM 전용
    if not await _ensure_dm(update, context):
        return
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("권한이 없습니다.")
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("사용법: /admin_broadcast 메시지내용")
        return
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"[공지] {msg}")
    await update.message.reply_text("전송 완료")

# 그룹에서 들어오는 일반 메시지는 무시(봇이 불필요하게 반응하지 않도록)
async def ignore_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return  # 아무 것도 하지 않음

# 핸들러 등록
application.add_handler(CommandHandler("start", start_cmd, filters=only_dm))
application.add_handler(CommandHandler("help", help_cmd, filters=only_dm))
application.add_handler(CommandHandler("watchlist", watchlist_cmd, filters=only_dm))
application.add_handler(CommandHandler("ratio", ratio_cmd, filters=only_dm))
application.add_handler(CommandHandler("admin_broadcast", admin_broadcast_cmd, filters=only_dm))

application.add_handler(MessageHandler(filters.ChatType.GROUPS, ignore_in_group))

# ----------------------------------
# 스케줄러 (APScheduler AsyncIOScheduler)
#  - PTB와 같은 이벤트 루프 사용 → 충돌 방지
# ----------------------------------
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

async def hourly_report(context: ContextTypes.DEFAULT_TYPE):
    """
    1시간 변화 리포트
    """
    lines = ["⏰ 1시간 리포트"]
    for sym in WATCHLIST:
        try:
            r = await compute_long_short_probability(sym, "1h")
            lines.append(f"• {sym}  롱 {r['long_prob_pct']}% / 숏 {r['short_prob_pct']}%")
        except Exception as e:
            lines.append(f"• {sym} 데이터 오류: {e}")
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(lines))

async def four_hour_report(context: ContextTypes.DEFAULT_TYPE):
    lines = ["⏰ 4시간 리포트"]
    for sym in WATCHLIST:
        try:
            r = await compute_long_short_probability(sym, "4h")
            lines.append(f"• {sym}  롱 {r['long_prob_pct']}% / 숏 {r['short_prob_pct']}%")
        except Exception as e:
            lines.append(f"• {sym} 데이터 오류: {e}")
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(lines))

async def pump_detector(context: ContextTypes.DEFAULT_TYPE):
    """
    5분 급등 감지
    """
    alerts = []
    for sym in WATCHLIST:
        try:
            pct = await binance_price_change_pct(sym, minutes=5)
            if pct is not None and pct >= PUMP_THRESHOLD_PCT:
                alerts.append(f"🚀 {sym} 단기 급등: +{pct:.2f}% (5분)")
        except Exception as e:
            logger.warning(f"pump_detector {sym} error: {e}")
    if alerts:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="\n".join(alerts))

def setup_scheduler(app: Application):
    # PTB JobQueue 없이 APScheduler 사용(요구사항 반영)
    # 같은 이벤트 루프에 붙여서 코루틴 실행
    scheduler.add_job(lambda: app.create_task(hourly_report(app.bot)), CronTrigger(minute=0))          # 매시 정각
    scheduler.add_job(lambda: app.create_task(four_hour_report(app.bot)), CronTrigger(minute=0, hour="*/4"))  # 4시간마다
    scheduler.add_job(lambda: app.create_task(pump_detector(app.bot)), CronTrigger(minute="*/5"))      # 5분마다
    scheduler.start()

# ----------------------------------
# 부트스트랩
# ----------------------------------
async def on_startup(app: Application):
    # 명령어 셋 (DM에서 사용자 편의를 위해)
    await app.bot.set_my_commands([
        BotCommand("start", "시작하기"),
        BotCommand("help", "도움말"),
        BotCommand("watchlist", "모니터링 목록 보기"),
        BotCommand("ratio", "롱/숏 확률 보기"),
    ])
    # 웹훅 등록 (Flask 엔드포인트와 시크릿)
    await app.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message", "edited_message", "channel_post", "callback_query", "chat_member"]
    )
    init_db()
    logger.info("Startup OK, webhook set.")

async def on_shutdown(app: Application):
    await client.aclose()
    logger.info("HTTP client closed.")

def main():
    # PTB 앱 실행은 폴링이 아닌 '수동 웹훅 처리 + Flask 서버' 조합
    application.post_init = lambda app: setup_scheduler(app)
    application.run_webhook(  # 내부 HTTP 서버를 쓰지 않고, 이벤트 루프만 구동하기 위한 트릭
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        webhook_url=None,  # 실제 수신은 Flask가 담당 / 여기선 루프만 돌려줌
        stop_signals=None, # Render에서 신호 처리 이슈 회피
        close_loop=False,  # 아래에서 Flask가 같은 프로세스에서 동작
        drop_pending_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )

if __name__ == "__main__":
    # Flask와 PTB 이벤트 루프를 하나의 프로세스에서 구동
    # Flask는 WSGI 서버(gunicorn)로 띄우고, PTB는 위 main()으로 루프 구동
    # Render에서는 gunicorn이 app:flask_app 을 실행하고,
    # 같은 프로세스 내에서 PTB 루프가 함께 돈다(아래 WSGI 서버가 임포트 시 main()을 트리거하지 않도록 주의)
    # → Render에서는 gunicorn 명령에 따라 Flask만 직접 실행되므로,
    #    PTB 루프 기동은 아래 ‘render.yaml’의 별도 “background worker”로 돌립니다.
    # 로컬 테스트 시에는 아래 라인으로 Flask를 띄우고, PTB는 별도 터미널에서 python ptb_worker.py 처럼 돌리는 방식을 권장.
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
