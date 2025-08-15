import os
import json
import time
import uuid
import math
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from threading import Thread

import httpx
import feedparser
import numpy as np
import pandas as pd
from flask import Flask, request, jsonify

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base

from telegram import Update, Bot, Chat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters,
)

# =========================
# 기본 설정
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("coin-predict-bot")

TZ = timezone(timedelta(hours=9))  # Asia/Seoul

# =========================
# 환경 변수 (Render UI에서 설정)
# =========================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
GROUP_IDS = [int(x) for x in os.environ.get("TELEGRAM_GROUP_IDS", "").split(",") if x.strip()]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # 예: https://your-service.onrender.com
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "secret-path")  # /webhook/<SECRET>
PORT = int(os.environ.get("PORT", "10000"))

# 주기(분)
NEWS_INTERVAL_MIN = int(os.environ.get("NEWS_INTERVAL_MIN", "30"))
RANK_INTERVAL_MIN = int(os.environ.get("RANK_INTERVAL_MIN", "30"))
SPIKE_INTERVAL_MIN = int(os.environ.get("SPIKE_INTERVAL_MIN", "3"))
PREDICT_INTERVAL_MIN = int(os.environ.get("PREDICT_INTERVAL_MIN", "5"))

# 급등 감지 임계값(%) – 5분 기준
SPIKE_THRESHOLD = float(os.environ.get("SPIKE_THRESHOLD", "2.0"))

# 예측 기본 심볼(쉼표 구분)
SYMBOLS = [s.strip().upper() for s in os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

# =========================
# Flask 앱 (Render web)
# =========================
flask_app = Flask(__name__)

# =========================
# DB (SQLite) – Render 디스크는 배포마다 초기화될 수 있음
# =========================
Base = declarative_base()
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///bot_data.sqlite3")
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String(255))
    first_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.now(TZ))
    unique_code = Column(String(64), index=True)

class NewsCache(Base):
    __tablename__ = "news_cache"
    id = Column(Integer, primary_key=True)
    source = Column(String(64), nullable=False)
    guid = Column(String(512), nullable=False)
    title = Column(String(512), nullable=False)
    url = Column(Text, nullable=False)
    published_at = Column(DateTime, nullable=False)
    __table_args__ = (UniqueConstraint("source", "guid", name="uq_news_source_guid"),)

class PriceCache(Base):
    __tablename__ = "price_cache"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), index=True)
    interval = Column(String(16))
    ts = Column(DateTime, index=True)     # 봉 시각
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

Base.metadata.create_all(bind=engine)

# =========================
# 전역 런타임(PTB + Scheduler)
# =========================
application: Application = None
async_loop = asyncio.new_event_loop()
scheduler = AsyncIOScheduler(event_loop=async_loop, timezone="Asia/Seoul")

# =========================
# 유틸 – HTTP
# =========================
HTTP_TIMEOUT = httpx.Timeout(10.0, read=10.0, write=10.0, connect=10.0)

async def http_get_json(url, params=None):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

async def http_get_text(url, params=None):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.text

# =========================
# 지표 계산 (RSI / MACD)
# =========================
def calc_rsi(close_prices: pd.Series, period: int = 14) -> pd.Series:
    delta = close_prices.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_macd(close_prices: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd, signal_line, hist

# =========================
# 데이터 소스 (Binance, Upbit, 환율)
# =========================
BINANCE = "https://api.binance.com"
UPBIT = "https://api.upbit.com/v1"
EXRATE = "https://api.exchangerate.host/latest"

async def binance_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{BINANCE}/api/v3/klines"
    js = await http_get_json(url, params={"symbol": symbol, "interval": interval, "limit": limit})
    cols = ["open_time","open","high","low","close","volume","close_time","qav","num_trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(js, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul")
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    return df[["open_time","open","high","low","close","volume"]]

async def binance_24hr_tickers() -> list:
    url = f"{BINANCE}/api/v3/ticker/24hr"
    return await http_get_json(url)

async def binance_price(symbol: str = "BTCUSDT") -> float:
    url = f"{BINANCE}/api/v3/ticker/price"
    js = await http_get_json(url, params={"symbol": symbol})
    return float(js["price"])

async def upbit_ticker(market: str = "KRW-BTC") -> float:
    url = f"{UPBIT}/ticker"
    js = await http_get_json(url, params={"markets": market})
    return float(js[0]["trade_price"])

async def usdkrw_rate() -> float:
    js = await http_get_json(EXRATE, params={"base": "USD", "symbols": "KRW"})
    return float(js["rates"]["KRW"])

# =========================
# 캐싱 (간단 TTL)
# =========================
_cache = {}

def get_cache(key):
    item = _cache.get(key)
    if not item:
        return None
    if item["exp"] < time.time():
        _cache.pop(key, None)
        return None
    return item["val"]

def set_cache(key, val, ttl=60):
    _cache[key] = {"val": val, "exp": time.time() + ttl}

# =========================
# 김프 계산
# =========================
async def kimchi_premium() -> str:
    try:
        btc_krw = await upbit_ticker("KRW-BTC")
        btc_usdt = await binance_price("BTCUSDT")
        krw = await usdkrw_rate()
        global_btc_krw = btc_usdt * krw
        premium = (btc_krw / global_btc_krw - 1.0) * 100.0
        return f"김프(BTC): {premium:+.2f}% (업비트 {btc_krw:,.0f}원 / 바이낸스 {btc_usdt:,.0f} USDT, 환율 {krw:,.2f})"
    except Exception as e:
        logger.exception("kimchi_premium error")
        return f"김프 계산 실패: {e}"

# =========================
# 예측 로직 (RSI + MACD 앙상블)
# =========================
def decide_signal(rsi: float, macd: float, macd_signal: float, macd_hist: float) -> dict:
    """
    간단 앙상블:
      - RSI<30 강한 롱 성향, RSI>70 강한 숏 성향
      - MACD > signal 이면 롱 우위, < 이면 숏 우위
      - Hist의 부호로 모멘텀 보강
    """
    long_score = 0.0
    short_score = 0.0

    if not math.isnan(rsi):
        if rsi < 30: long_score += 2
        elif rsi < 45: long_score += 1
        elif rsi > 70: short_score += 2
        elif rsi > 55: short_score += 1

    if not (math.isnan(macd) or math.isnan(macd_signal)):
        if macd > macd_signal: long_score += 1.5
        elif macd < macd_signal: short_score += 1.5

    if not math.isnan(macd_hist):
        if macd_hist > 0: long_score += 0.5
        elif macd_hist < 0: short_score += 0.5

    total = long_score + short_score
    if total == 0:
        return {"bias": "중립", "long_prob": 50, "short_prob": 50}

    long_prob = round(100 * long_score / total)
    short_prob = 100 - long_prob
    bias = "롱" if long_prob > short_prob else ("숏" if short_prob > long_prob else "중립")
    return {"bias": bias, "long_prob": long_prob, "short_prob": short_prob}

async def build_signal_text(symbol: str, interval: str = "15m") -> str:
    df = await binance_klines(symbol, interval=interval, limit=200)
    close = df["close"]
    rsi_series = calc_rsi(close)
    macd, sig, hist = calc_macd(close)
    rsi = float(rsi_series.iloc[-1])
    macd_v = float(macd.iloc[-1]); sig_v = float(sig.iloc[-1]); hist_v = float(hist.iloc[-1])
    result = decide_signal(rsi, macd_v, sig_v, hist_v)

    txt = (
        f"#{symbol} ({interval}) 예측\n"
        f"• RSI: {rsi:.1f}\n"
        f"• MACD: {macd_v:.4f} / Signal: {sig_v:.4f} / Hist: {hist_v:.4f}\n"
        f"• 바이어스: *{result['bias']}*  "
        f"(롱 {result['long_prob']}% / 숏 {result['short_prob']}%)"
    )
    return txt

# =========================
# 뉴스/랭킹/급등 감지
# =========================
NEWS_FEEDS = [
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("binance_blog", "https://www.binance.com/en/blog/rss"),
]

def parse_rss(url: str):
    return feedparser.parse(url)

async def fetch_and_filter_news():
    sess = SessionLocal()
    try:
        new_items = []
        for source, url in NEWS_FEEDS:
            feed = await asyncio.get_event_loop().run_in_executor(None, parse_rss, url)
            for e in feed.entries[:30]:
                guid = e.get("id") or e.get("guid") or e.get("link")
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                published = None
                if getattr(e, "published_parsed", None):
                    published = datetime.fromtimestamp(time.mktime(e.published_parsed), TZ)
                else:
                    published = datetime.now(TZ)
                # 중복 체크
                exists = sess.query(NewsCache).filter_by(source=source, guid=guid).first()
                if exists: continue
                item = NewsCache(source=source, guid=guid, title=title, url=link, published_at=published)
                sess.add(item)
                new_items.append(item)
        sess.commit()
        return new_items
    except Exception as e:
        logger.exception("fetch_and_filter_news error")
        return []
    finally:
        sess.close()

async def build_top_gainers_text(limit=10):
    tickers = await binance_24hr_tickers()
    # USDT 페어만, 가격변동률 상위
    filt = [t for t in tickers if t.get("symbol","").endswith("USDT")]
    sorted_list = sorted(filt, key=lambda x: float(x.get("priceChangePercent", 0.0)), reverse=True)[:limit]
    lines = [f"{i+1}. {t['symbol']}: {float(t['priceChangePercent']):+,.2f}%"
             for i, t in enumerate(sorted_list)]
    return "*바이낸스 24h 상위 상승률*\n" + "\n".join(lines)

async def detect_spikes(symbols, threshold=2.0) -> list:
    """최근 5분 변동률 급등 코인 리스트"""
    alerts = []
    for sym in symbols:
        df = await binance_klines(sym, interval="1m", limit=6)
        if len(df) < 2:
            continue
        p_now = df["close"].iloc[-1]
        p_prev5 = df["close"].iloc[0]
        chg = (p_now / p_prev5 - 1) * 100
        if abs(chg) >= threshold:
            alerts.append((sym, chg))
    return alerts

# =========================
# 텔레그램 핸들러 (DM 명령 전용)
# =========================
def private_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != ChatType.PRIVATE:
            # 그룹/채널에서는 명령어 무시
            return
        return await func(update, context)
    return wrapper

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != ChatType.PRIVATE:
            return
        uid = update.effective_user.id if update.effective_user else 0
        if uid not in ADMIN_IDS:
            await update.message.reply_text("관리자 전용 명령어입니다.")
            return
        return await func(update, context)
    return wrapper

@private_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sess = SessionLocal()
    try:
        uid = update.effective_user.id
        user = sess.query(User).filter_by(telegram_id=uid).first()
        if not user:
            user = User(
                telegram_id=uid,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                unique_code=str(uuid.uuid4())[:8].upper(),
                created_at=datetime.now(TZ)
            )
            sess.add(user)
            sess.commit()

        kb = [[InlineKeyboardButton("김프 보기", callback_data="kimchi")]]
        await update.message.reply_text(
            f"안녕하세요! 환영합니다.\n"
            f"• 고유 ID: {user.unique_code}\n"
            f"• 이 방의 명령은 *1:1 DM에서만* 실행됩니다.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    finally:
        sess.close()

@private_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "/start - 인사 및 고유ID 발급\n"
        "/id - 내 고유ID 보기\n"
        "/signal <심볼> [interval] - RSI/MACD 기반 롱·숏 확률\n"
        "/kimchi - 김치 프리미엄(BTC)\n"
        "/gainers - 24h 상위 상승률(바이낸스)\n"
        "\n[관리자 전용]\n"
        "/broadcast <메시지>\n"
        "/predict_now - 즉시 예측 브로드캐스트\n"
        "/news_now - 새 뉴스 브로드캐스트\n"
        "/rank_now - 랭킹 브로드캐스트\n"
        "/spike_now - 급등 감지 브로드캐스트\n"
    )
    await update.message.reply_text(txt)

@private_only
async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sess = SessionLocal()
    try:
        uid = update.effective_user.id
        user = sess.query(User).filter_by(telegram_id=uid).first()
        if not user:
            await cmd_start(update, context)
            return
        await update.message.reply_text(f"고유 ID: {user.unique_code}")
    finally:
        sess.close()

@private_only
async def cmd_kimchi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await kimchi_premium())

@private_only
async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("사용법: /signal BTCUSDT [15m|1h|4h|1d...]")
        return
    symbol = args[0].upper()
    interval = args[1] if len(args) > 1 else "15m"
    try:
        txt = await build_signal_text(symbol, interval)
        await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.exception("/signal error")
        await update.message.reply_text(f"신호 생성 실패: {e}")

@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_IDS:
        await update.message.reply_text("GROUP_IDS 미설정")
        return
    msg = " ".join(context.args) if context.args else None
    if not msg:
        await update.message.reply_text("사용법: /broadcast <메시지>")
        return
    for gid in GROUP_IDS:
        try:
            await context.bot.send_message(chat_id=gid, text=msg)
        except Exception:
            logger.exception("broadcast error")
    await update.message.reply_text("브로드캐스트 완료")

@admin_only
async def cmd_predict_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_predictions(context.bot)
    await update.message.reply_text("예측 전송 완료")

@admin_only
async def cmd_news_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_news(context.bot)
    await update.message.reply_text("뉴스 전송 완료")

@admin_only
async def cmd_rank_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_rankings(context.bot)
    await update.message.reply_text("랭킹 전송 완료")

@admin_only
async def cmd_spike_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await broadcast_spikes(context.bot)
    await update.message.reply_text("급등 전송 완료")

# 버튼 콜백 (김프)
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "kimchi":
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(await kimchi_premium())

# =========================
# 스케줄 작업
# =========================
async def broadcast_predictions(bot: Bot):
    if not GROUP_IDS:
        return
    for sym in SYMBOLS:
        try:
            txt = await build_signal_text(sym, "15m")
            for gid in GROUP_IDS:
                await bot.send_message(chat_id=gid, text=txt, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            logger.exception("broadcast_predictions error")

async def broadcast_news(bot: Bot):
    items = await fetch_and_filter_news()
    if not items:
        return
    # 최신순 상위 5개만
    items = sorted(items, key=lambda x: x.published_at, reverse=True)[:5]
    text = "*새 코인 뉴스*\n" + "\n".join([f"• {it.title}\n{it.url}" for it in items])
    for gid in GROUP_IDS:
        try:
            await bot.send_message(chat_id=gid, text=text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception:
            logger.exception("broadcast_news error")

async def broadcast_rankings(bot: Bot):
    try:
        text = await build_top_gainers_text(limit=10)
        for gid in GROUP_IDS:
            await bot.send_message(chat_id=gid, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        logger.exception("broadcast_rankings error")

async def broadcast_spikes(bot: Bot):
    try:
        alerts = await detect_spikes(SYMBOLS, threshold=SPIKE_THRESHOLD)
        if not alerts:
            return
        lines = [f"• {sym}: {chg:+.2f}%" for sym, chg in alerts]
        txt = "*5분 급등/급락 감지*\n" + "\n".join(lines)
        for gid in GROUP_IDS:
            await bot.send_message(chat_id=gid, text=txt, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        logger.exception("broadcast_spikes error")

# =========================
# PTB 애플리케이션 & 웹훅 연동
# =========================
async def setup_handlers(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("kimchi", cmd_kimchi))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("predict_now", cmd_predict_now))
    app.add_handler(CommandHandler("news_now", cmd_news_now))
    app.add_handler(CommandHandler("rank_now", cmd_rank_now))
    app.add_handler(CommandHandler("spike_now", cmd_spike_now))
    app.add_handler(MessageHandler(filters.ALL & filters.StatusUpdate.ALL, lambda *_: None))  # 잡음 억제
    app.add_handler(MessageHandler(filters.UpdateType.CALLBACK_QUERY, on_callback))

async def start_ptb():
    global application
    application = ApplicationBuilder().token(TOKEN).build()
    await setup_handlers(application)
    await application.initialize()
    await application.start()
    logger.info("PTB started")

    # 스케줄러 작업 등록 (동일 이벤트 루프)
    if not scheduler.running:
        # 예측 브로드캐스트
        scheduler.add_job(lambda: application.create_task(broadcast_predictions(application.bot)),
                          trigger="interval", minutes=PREDICT_INTERVAL_MIN, id="predict_job", replace_existing=True)
        # 뉴스
        scheduler.add_job(lambda: application.create_task(broadcast_news(application.bot)),
                          trigger="interval", minutes=NEWS_INTERVAL_MIN, id="news_job", replace_existing=True)
        # 랭킹
        scheduler.add_job(lambda: application.create_task(broadcast_rankings(application.bot)),
                          trigger="interval", minutes=RANK_INTERVAL_MIN, id="rank_job", replace_existing=True)
        # 급등 감지
        scheduler.add_job(lambda: application.create_task(broadcast_spikes(application.bot)),
                          trigger="interval", minutes=SPIKE_INTERVAL_MIN, id="spike_job", replace_existing=True)

        scheduler.start()
        logger.info("Scheduler started")

    # 웹훅 설정
    if WEBHOOK_URL:
        try:
            await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook/{WEBHOOK_SECRET}", drop_pending_updates=True)
            logger.info("Webhook set OK")
        except Exception:
            logger.exception("Webhook set failed")

async def stop_ptb():
    if application:
        await application.stop()
        await application.shutdown()

def run_async_loop():
    asyncio.set_event_loop(async_loop)
    async_loop.create_task(start_ptb())
    async_loop.run_forever()

# =========================
# Flask 라우트
# =========================
@flask_app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now(TZ).isoformat()})

@flask_app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        # PTB 이벤트 루프에서 처리
        fut = asyncio.run_coroutine_threadsafe(application.process_update(update), async_loop)
        fut.result(timeout=5)
    except Exception as e:
        logger.exception("webhook error")
        return "error", 500
    return "ok", 200

@flask_app.route("/set_webhook", methods=["POST", "GET"])
def set_hook():
    if not WEBHOOK_URL:
        return "WEBHOOK_URL not set", 400
    try:
        bot = Bot(TOKEN)
        bot.set_webhook(url=f"{WEBHOOK_URL}/webhook/{WEBHOOK_SECRET}", drop_pending_updates=True)
        return "webhook set", 200
    except Exception as e:
        logger.exception("set_webhook error")
        return f"error: {e}", 500

# =========================
# 엔트리포인트
# =========================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    # PTB + Scheduler 루프를 별도 스레드에서 가동
    t = Thread(target=run_async_loop, daemon=True)
    t.start()

    # Flask (Render가 바인딩하는 PORT 사용)
    flask_app.run(host="0.0.0.0", port=PORT)
