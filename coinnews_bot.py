import os
import logging
import asyncio
import json
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import Flask
from telegram import Update, ChatMember
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, ChatMemberHandler
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import httpx
import feedparser
from deep_translator import GoogleTranslator

# =========================
# 환경 변수 (Render UI에서 설정)
# =========================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID", "").strip()  # 예: -100xxxxxxxxxx
ADMIN_IDS = os.environ.get("ADMIN_IDS", "").strip()         # 예: "123,456"
PORT = int(os.environ.get("PORT", "10000"))

if not TOKEN or not GROUP_ID:
    raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID 를 설정하세요.")

GROUP_ID_INT = int(GROUP_ID)

# =========================
# Flask (Render 프로세스 바인딩)
# =========================
app = Flask(__name__)

@app.get("/")
def health():
    return "OK"

# =========================
# 로깅
# =========================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("coinbot")

# =========================
# 파일 경로들
# =========================
DATA_FILE = "user_data.json"       # 유저/활동 기록
NEWS_CACHE_FILE = "news_cache.json"  # 뉴스 중복 캐시(링크/번역 저장)

# 초기 파일 생성
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False)

if not os.path.exists(NEWS_CACHE_FILE):
    with open(NEWS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_links": [], "title_map": {}}, f, ensure_ascii=False)

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================
# 유저 고유 ID/로그 관리
# =========================
def load_user_data():
    return load_json(DATA_FILE, {})

def save_user_data(d):
    save_json(DATA_FILE, d)

def get_or_assign_user_id(user_id: int, username: str = "") -> int:
    d = load_user_data()
    k = str(user_id)
    if k in d:
        return d[k]["custom_id"]
    new_id = len(d) + 1
    d[k] = {
        "custom_id": new_id,
        "username": username or "",
        "joined_at": datetime.now(timezone.utc).isoformat(),
        "messages": 0,
        "banned": False,
        "last_dm": None,
    }
    save_user_data(d)
    return new_id

def inc_message_count(user_id: int):
    d = load_user_data()
    k = str(user_id)
    if k in d:
        d[k]["messages"] = d[k].get("messages", 0) + 1
        d[k]["last_dm"] = datetime.now(timezone.utc).isoformat()
        save_user_data(d)

def find_user_by_custom_id(custom_id: str):
    d = load_user_data()
    for uid, info in d.items():
        if str(info.get("custom_id")) == str(custom_id):
            return int(uid), info
    return None, None

def find_user_by_username(username: str):
    if username.startswith("@"):
        username = username[1:]
    d = load_user_data()
    for uid, info in d.items():
        if (info.get("username") or "").lower() == username.lower():
            return int(uid), info
    return None, None

def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return False
    return str(user_id) in [x.strip() for x in ADMIN_IDS.split(",") if x.strip()]

# =========================
# PTB 앱 & 이벤트루프 공유
# =========================
application = ApplicationBuilder().token(TOKEN).build()
PTB_LOOP: asyncio.AbstractEventLoop | None = None

async def post_init(app):
    global PTB_LOOP
    PTB_LOOP = asyncio.get_running_loop()
application.post_init = post_init

def submit_coro(coro):
    """스케줄러 스레드 → PTB 이벤트루프 안전 제출"""
    if PTB_LOOP is None:
        logger.warning("PTB loop not ready yet.")
        return
    asyncio.run_coroutine_threadsafe(coro, PTB_LOOP)

# =========================
# 데이터 소스/유틸
# =========================
COINPAPRIKA_TICKER_IDS = {
    "btc": "btc-bitcoin",
    "eth": "eth-ethereum",
    "xrp": "xrp-xrp",
    "sol": "sol-solana",
    "doge": "doge-dogecoin",
}

COIN_NAMES = {
    "btc": "BTC (비트코인)",
    "eth": "ETH (이더리움)",
    "xrp": "XRP (리플)",
    "sol": "SOL (솔라나)",
    "doge": "DOGE (도지코인)",
}

TRACKED = ("btc", "eth", "xrp", "sol", "doge")

async def fetch_usdkrw():
    async with httpx.AsyncClient(timeout=15) as client:
        xr = await client.get("https://api.exchangerate.host/latest?base=USD&symbols=KRW")
        xr.raise_for_status()
        return float(xr.json()["rates"]["KRW"])

async def fetch_usd_prices(symbols=TRACKED):
    out = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for s in symbols:
            tid = COINPAPRIKA_TICKER_IDS[s]
            url = f"https://api.coinpaprika.com/v1/tickers/{tid}"
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            usd = data["quotes"]["USD"]
            out[s] = {
                "price": float(usd["price"]),
                "pct_1h": float(usd.get("percent_change_1h") or 0.0),
                "pct_24h": float(usd.get("percent_change_24h") or 0.0),
                "pct_7d": float(usd.get("percent_change_7d") or 0.0),
                "symbol": s,
                "ticker_id": tid,
            }
    return out

async def fetch_all_tickers():
    """코인 랭킹용: 전 시장 24h 변동률 기준 (상/하락 TOP10)"""
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get("https://api.coinpaprika.com/v1/tickers")
        r.raise_for_status()
        data = r.json()
    # 필요한 정보만 축약
    results = []
    for t in data:
        q = t.get("quotes", {}).get("USD", {})
        pct24 = q.get("percent_change_24h")
        price = q.get("price")
        if pct24 is None or price is None:
            continue
        results.append({
            "name": t.get("name"),
            "symbol": t.get("symbol"),
            "price": float(price),
            "pct_24h": float(pct24),
        })
    return results

async def fetch_ohlcv(symbol: str, days: int = 200):
    if symbol.lower() not in COINPAPRIKA_TICKER_IDS:
        raise ValueError("지원하지 않는 심볼")
    tid = COINPAPRIKA_TICKER_IDS[symbol.lower()]
    end = datetime.utcnow().date()
    start = end - timedelta(days=days + 5)
    url = f"https://api.coinpaprika.com/v1/coins/{tid}/ohlcv/historical?start={start}&end={end}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    closes = [float(x["close"]) for x in data if "close" in x]
    return closes

def calc_rsi(closes, period: int = 14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis = []
    for i in range(period, len(closes) - 1):
        gain = gains[i]
        loss = losses[i]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = (avg_gain / avg_loss) if avg_loss != 0 else float("inf")
        rsis.append(100 - (100 / (1 + rs)))
    return rsis[-1] if rsis else None

def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    out = []
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [a - b for a, b in zip(ema_fast[-len(ema_slow):], ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = macd_line[-1] - signal_line[-1]
    return macd_line[-1], signal_line[-1], hist

async def calc_kimp():
    """김프 = (업비트 KRW-BTC / (바이낸스 BTCUSDT * USDKRW)) - 1"""
    async with httpx.AsyncClient(timeout=15) as client:
        ur = await client.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        ur.raise_for_status()
        upbit_price = float(ur.json()[0]["trade_price"])
        br = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        br.raise_for_status()
        btc_usdt = float(br.json()["price"])
        xr = await client.get("https://api.exchangerate.host/latest?base=USD&symbols=KRW")
        xr.raise_for_status()
        usdkrw = float(xr.json()["rates"]["KRW"])
    global_krw = btc_usdt * usdkrw
    kimp = (upbit_price / global_krw - 1.0) * 100
    return upbit_price, global_krw, kimp

async def fetch_news(limit=15):
    """뉴스 + 번역 캐싱(중복 번역 방지)"""
    cache = load_json(NEWS_CACHE_FILE, {"seen_links": [], "title_map": {}})
    seen = set(cache.get("seen_links", []))
    title_map = cache.get("title_map", {})

    feed = feedparser.parse("https://cointelegraph.com/rss")
    items = []
    for e in feed.entries[:limit]:
        link = e.link
        title = e.title
        if link in title_map:
            title_ko = title_map[link]
        else:
            title_ko = GoogleTranslator(source="auto", target="ko").translate(title)
            title_map[link] = title_ko
        items.append((title, title_ko, link))

    # 캐시 갱신 저장
    cache["title_map"] = title_map
    save_json(NEWS_CACHE_FILE, cache)
    return items

def mark_news_as_sent(links):
    cache = load_json(NEWS_CACHE_FILE, {"seen_links": [], "title_map": {}})
    sent = set(cache.get("seen_links", []))
    sent.update(links)
    cache["seen_links"] = list(sent)
    save_json(NEWS_CACHE_FILE, cache)

def get_news_seen():
    cache = load_json(NEWS_CACHE_FILE, {"seen_links": [], "title_map": {}})
    return set(cache.get("seen_links", []))

# =========================
# 권한/멤버십 체크
# =========================
async def is_member_of_group(user_id: int) -> bool:
    """그룹방 참여자만 DM 명령 사용 가능"""
    try:
        cm = await application.bot.get_chat_member(chat_id=GROUP_ID_INT, user_id=user_id)
        return cm.status in ("member", "administrator", "creator")
    except Exception:
        return False

def ensure_private_and_member(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            return
        user_id = update.effective_user.id
        if not await is_member_of_group(user_id):
            await update.message.reply_text("❌ 그룹방 참여자만 사용 가능합니다. 그룹에 먼저 참여해주세요.")
            return
        return await func(update, context)
    return wrapper

# =========================
# 명령어 핸들러 (DM 전용 + 멤버 제한)
# =========================
@ensure_private_and_member
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = get_or_assign_user_id(update.effective_user.id, update.effective_user.username or "")
    inc_message_count(update.effective_user.id)
    await update.message.reply_text(
        "🟢 작동 중입니다.\n"
        "모든 명령어는 1:1 대화에서만 사용할 수 있습니다.\n"
        "그룹방에는 자동 전송만 이뤄집니다.\n"
        f"당신의 고유번호: {uid}\n"
        "도움말: /help"
    )

@ensure_private_and_member
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_message_count(update.effective_user.id)
    txt = (
        "📌 명령어 목록 (DM 전용, 그룹 참여자만)\n"
        "/start - 작동 확인\n"
        "/price - 주요 코인 시세(USD/KRW/김프 색상)\n"
        "/summary - 시세/뉴스/김프/일정 요약\n"
        "/analyze [btc|eth|xrp|sol|doge] - RSI/MACD 분석\n"
        "/test - DM/그룹 구분 테스트\n"
        "\n👮 관리자 전용\n"
        "/ban [고유번호]\n"
        "/unban [고유번호]\n"
        "/id [@username | 고유번호]\n"
        "/config\n"
        "/stats\n"
        "\n/news 는 그룹방 전용이며, 최초 전체 → 이후 신규만 자동 전송합니다."
    )
    await update.message.reply_text(txt)

@ensure_private_and_member
async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_message_count(update.effective_user.id)
    await update.message.reply_text("✅ DM OK (그룹방에서는 이 명령을 사용할 수 없습니다).")

@ensure_private_and_member
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_message_count(update.effective_user.id)
    try:
        usdkrw = await fetch_usdkrw()
        prices = await fetch_usd_prices()
        up_krw, glb_krw, kimp = await calc_kimp()

        lines = ["📈 주요 코인 시세"]
        for s in TRACKED:
            p = prices[s]
            arrow = "▲" if p["pct_1h"] >= 0 else "▼"
            emoji = "🟢" if p["pct_1h"] >= 0 else "🔴"
            krw = p["price"] * usdkrw
            lines.append(f"{emoji} {COIN_NAMES[s]}: ${p['price']:,.2f} / ₩{krw:,.0f} ({arrow}{abs(p['pct_1h']):.2f}%/1h)")
        lines.append(f"\n🇰🇷 김프(BTC): 업비트 ₩{up_krw:,.0f} / 글로벌 ₩{glb_krw:,.0f} → {kimp:+.2f}%")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.exception("price_cmd error")
        await update.message.reply_text("⚠️ 시세 조회 중 오류가 발생했습니다.")

@ensure_private_and_member
async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_message_count(update.effective_user.id)
    try:
        usdkrw = await fetch_usdkrw()
        prices = await fetch_usd_prices()
        up, glb, kimp = await calc_kimp()
        # 뉴스 3개(번역 캐시)
        items = await fetch_news(limit=6)
        seen = get_news_seen()
        fresh = [(ko, link) for _, ko, link in items if link not in seen][:3]
        # 일정(오늘, 상위)
        cal = await fetch_calendar_today_kst()

        lines = ["📊 요약"]
        # 가격
        price_line = []
        for s in TRACKED:
            p = prices[s]
            arrow = "▲" if p["pct_24h"] >= 0 else "▼"
            price_line.append(f"{COIN_NAMES[s].split()[0]} ${p['price']:,.0f}/₩{(p['price']*usdkrw):,.0f}({arrow}{abs(p['pct_24h']):.1f}%)")
        lines.append("• 시세: " + ", ".join(price_line))
        # 김프
        lines.append(f"• 김프: 업비트 ₩{up:,.0f} / 글로벌 ₩{glb:,.0f} → {kimp:+.2f}%")
        # 뉴스
        if fresh:
            lines.append("• 뉴스:")
            for t, u in fresh:
                lines.append(f"  - {t}")
        # 일정
        if cal:
            lines.append("• 오늘의 경제일정(상위):")
            for ev in cal[:5]:
                country = ev.get("country", "")
                title = ev.get("title", "")
                impact = ev.get("impact", "")
                lines.append(f"  - [{country}] {title} ({impact})")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.exception("summary_cmd error")
        await update.message.reply_text("⚠️ 요약 생성 중 오류가 발생했습니다.")

@ensure_private_and_member
async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_message_count(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("사용법: /analyze [btc|eth|xrp|sol|doge]")
        return
    sym = context.args[0].lower()
    if sym not in COINPAPRIKA_TICKER_IDS:
        await update.message.reply_text("지원 심볼: btc, eth, xrp, sol, doge")
        return
    try:
        closes = await fetch_ohlcv(sym, days=200)
        if not closes:
            await update.message.reply_text("데이터가 부족합니다.")
            return
        rsi = calc_rsi(closes, period=14)
        macd, signal, hist = calc_macd(closes, fast=12, slow=26, signal=9)
        now = closes[-1]

        tips = []
        if rsi is not None:
            if rsi <= 30: tips.append("과매도(관심)")
            elif rsi >= 70: tips.append("과매수(리스크 관리)")
            else: tips.append("중립")
        if macd is not None and signal is not None and hist is not None:
            if hist > 0 and macd > signal:
                tips.append("MACD 상향 교차(강세)")
            elif hist < 0 and macd < signal:
                tips.append("MACD 하향 교차(약세)")
            else:
                tips.append("MACD 중립")

        msg = (
            f"🔍 {COIN_NAMES[sym]} 분석\n"
            f"• 종가(최근): ${now:,.2f}\n"
            f"• RSI(14): {rsi:.2f}  |  MACD: {macd:.4f}, Signal: {signal:.4f}, Hist: {hist:.4f}\n"
            f"• 해석: {', '.join(tips)}"
        )
        await update.message.reply_text(msg)
    except Exception as e:
        logger.exception("analyze_cmd error")
        await update.message.reply_text("⚠️ 분석 중 오류가 발생했습니다.")

# =========================
# 관리자 전용 명령
# =========================
async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # DM 전용 + 관리자
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /id [@유저명 | 고유번호]")
        return
    key = context.args[0]
    if key.startswith("@"):
        uid, info = find_user_by_username(key)
    elif key.isdigit():
        uid, info = find_user_by_custom_id(key)
    else:
        await update.message.reply_text("형식 오류: @유저명 또는 숫자 고유번호 입력")
        return
    if not uid:
        await update.message.reply_text("해당 유저를 찾을 수 없습니다.")
        return
    await update.message.reply_text(
        f"👤 조회 결과\n"
        f"• TG ID: {uid}\n"
        f"• 고유번호: {info.get('custom_id')}\n"
        f"• 유저명: @{info.get('username')}\n"
        f"• 가입: {info.get('joined_at')}\n"
        f"• 누적메시지: {info.get('messages',0)}"
    )

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    msg = (
        "⚙️ 현재 설정\n"
        f"• GROUP_ID: {GROUP_ID}\n"
        f"• ADMIN_IDS: {ADMIN_IDS or '(미설정)'}\n"
        "• 명령 사용: DM 전용(그룹 참여자만)\n"
        "• 자동 전송: 그룹방 전용"
    )
    await update.message.reply_text(msg)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    d = load_user_data()
    total = len(d)
    banned = sum(1 for v in d.values() if v.get("banned"))
    msgs = sum(int(v.get("messages", 0)) for v in d.values())
    await update.message.reply_text(
        f"📈 유저 통계\n"
        f"• 전체 등록: {total}\n"
        f"• 차단: {banned}\n"
        f"• 누적 메시지: {msgs}"
    )

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /ban [고유번호]")
        return
    target = context.args[0]
    uid, info = find_user_by_custom_id(target)
    if not uid:
        await update.message.reply_text("해당 ID의 유저를 찾을 수 없습니다.")
        return
    try:
        await application.bot.ban_chat_member(chat_id=GROUP_ID_INT, user_id=uid)
    except Exception:
        pass
    d = load_user_data()
    d[str(uid)]["banned"] = True
    save_user_data(d)
    await update.message.reply_text(f"⛔️ 차단 완료 (ID: {target})")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /unban [고유번호]")
        return
    target = context.args[0]
    uid, info = find_user_by_custom_id(target)
    if not uid:
        await update.message.reply_text("해당 ID의 유저를 찾을 수 없습니다.")
        return
    try:
        await application.bot.unban_chat_member(chat_id=GROUP_ID_INT, user_id=uid, only_if_banned=True)
    except Exception:
        pass
    d = load_user_data()
    d[str(uid)]["banned"] = False
    save_user_data(d)
    await update.message.reply_text(f"✅ 차단 해제 완료 (ID: {target})")

# =========================
# 그룹 전용: /news (초기 전체 → 이후 신규만)
# =========================
async def news_cmd_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID_INT:
        return
    try:
        items = await fetch_news(limit=20)
        seen = get_news_seen()
        if not seen:
            # 최초: 전체(상위 10) 전송
            batch = items[:10]
        else:
            # 이후: 신규만
            batch = [x for x in items if x[2] not in seen]

        if not batch:
            return

        msg = "📰 코인 뉴스 업데이트\n" + "\n\n".join([f"• {ko}\n{link}" for _, ko, link in batch])
        await update.message.reply_text(msg)
        mark_news_as_sent([link for _, _, link in batch])
    except Exception as e:
        logger.warning(f"/news 오류: {e}")

# =========================
# 멤버 입장/유도 메시지/고유번호 부여
# =========================
async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.chat_member
    if ch and ch.new_chat_member and ch.new_chat_member.status == ChatMember.MEMBER:
        user = ch.new_chat_member.user
        uid = get_or_assign_user_id(user.id, user.username or "")
        try:
            await context.bot.send_message(
                chat_id=ch.chat.id,
                text=(
                    f"👋 {user.full_name}님 환영합니다! (고유번호: {uid})\n"
                    "📩 모든 기능은 1:1 대화(DM)에서 사용 가능합니다. DM으로 /start 를 보내보세요."
                )
            )
        except Exception:
            pass

# =========================
# 자동 전송 작업 (그룹방)
# =========================
_last_prices_for_surge = {}  # 급등 감지용 {symbol: (timestamp, price)}

async def auto_send_prices():
    """2분마다: 5종 + KRW + 김프 + 색상"""
    try:
        usdkrw = await fetch_usdkrw()
        prices = await fetch_usd_prices()
        up_krw, glb_krw, kimp = await calc_kimp()

        lines = ["📈 실시간 시세"]
        for s in TRACKED:
            p = prices[s]
            arrow = "▲" if p["pct_1h"] >= 0 else "▼"
            emoji = "🟢" if p["pct_1h"] >= 0 else "🔴"
            krw = p["price"] * usdkrw
            lines.append(f"{emoji} {COIN_NAMES[s]}: ${p['price']:,.2f} / ₩{krw:,.0f} ({arrow}{abs(p['pct_1h']):.2f}%/1h)")
        lines.append(f"\n🇰🇷 김프(BTC): 업비트 ₩{up_krw:,.0f} / 글로벌 ₩{glb_krw:,.0f} → {kimp:+.2f}%")
        await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"자동 시세 전송 오류: {e}")

async def auto_send_news():
    """10분마다: 최초 전체, 이후 신규만"""
    try:
        items = await fetch_news(limit=30)
        seen = get_news_seen()
        if not seen:
            batch = items[:10]
        else:
            batch = [x for x in items if x[2] not in seen]
        if not batch:
            return
        msg = "📰 코인 뉴스 업데이트\n" + "\n\n".join([f"• {ko}\n{link}" for _, ko, link in batch])
        await application.bot.send_message(chat_id=GROUP_ID_INT, text=msg)
        mark_news_as_sent([link for _, _, link in batch])
    except Exception as e:
        logger.warning(f"자동 뉴스 전송 오류: {e}")

async def auto_send_calendar_morning():
    """매일 오전(09:00 KST) 글로벌 경제일정 요약"""
    try:
        cal = await fetch_calendar_today_kst()
        if not cal: 
            return
        lines = ["📅 오늘의 글로벌 경제일정 (요약)"]
        for ev in cal[:12]:
            country = ev.get("country","")
            title = ev.get("title","")
            impact = ev.get("impact","")
            lines.append(f"• [{country}] {title} ({impact})")
        await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"경제일정 전송 오류: {e}")

async def auto_send_rankings(initial=False):
    """1시간 간격: 상승/하락 TOP10 (최초 1회 즉시)"""
    try:
        data = await fetch_all_tickers()
        if not data:
            return
        # 정렬
        highs = sorted(data, key=lambda x: x["pct_24h"], reverse=True)[:10]
        lows = sorted(data, key=lambda x: x["pct_24h"])[:10]
        lines = ["🏆 24시간 변동률 랭킹"]
        lines.append("🔼 상승 TOP10")
        for i, it in enumerate(highs, 1):
            lines.append(f"{i}. {it['symbol']}: {it['pct_24h']:+.2f}%  (${it['price']:,.4f})")
        lines.append("\n🔽 하락 TOP10")
        for i, it in enumerate(lows, 1):
            lines.append(f"{i}. {it['symbol']}: {it['pct_24h']:+.2f}%  (${it['price']:,.4f})")
        if initial:
            lines.insert(0, "⏱ 최초 실행 즉시 전송")
        await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"랭킹 전송 오류: {e}")

async def auto_detect_surge():
    """
    10분 기준 +5% 급등 감지 (TRACKED 5종)
    10분 전 대비 5% 이상 상승 시 알림.
    """
    try:
        now = datetime.now(timezone.utc)
        prices = await fetch_usd_prices()
        alerts = []
        for sym in TRACKED:
            p = prices[sym]["price"]
            prev = _last_prices_for_surge.get(sym)
            if prev:
                ts, oldp = prev
                # 10분 이상 경과한 기준만 체크
                if (now - ts) >= timedelta(minutes=10):
                    if oldp > 0:
                        change = (p / oldp - 1.0) * 100
                        if change >= 5.0:
                            alerts.append((sym, change, p))
                    # 갱신
                    _last_prices_for_surge[sym] = (now, p)
            else:
                _last_prices_for_surge[sym] = (now, p)

        if alerts:
            lines = ["🚀 급등 감지 (+10분 기준)"]
            for sym, chg, price in alerts:
                lines.append(f"• {COIN_NAMES[sym]}: {chg:+.2f}%  (현재 ${price:,.4f})")
            await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"급등 감지 오류: {e}")

async def auto_detect_oversold():
    """RSI 과매도(≤30) 탐지 (TRACKED, 일봉 기준)"""
    try:
        alerts = []
        for sym in TRACKED:
            closes = await fetch_ohlcv(sym, days=200)
            if not closes:
                continue
            rsi = calc_rsi(closes, period=14)
            if rsi is not None and rsi <= 30:
                alerts.append((sym, rsi, closes[-1]))
        if alerts:
            lines = ["🧭 과매도 감지 (RSI≤30, 일봉)"]
            for sym, rsi, last in alerts:
                lines.append(f"• {COIN_NAMES[sym]}: RSI {rsi:.2f}, 종가 ${last:,.2f}")
            await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"과매도 탐지 오류: {e}")

# =========================
# 경제일정(오늘) 수집
# =========================
async def fetch_calendar_today_kst():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
            r.raise_for_status()
            data = r.json()
        now_kst = datetime.now(timezone(timedelta(hours=9))).date()
        events = []
        for ev in data:
            dt_str = f"{ev.get('date','')} {ev.get('time','')}"
            # 날짜만 비교(타임존 불확실성 완화)
            try:
                d_only = datetime.strptime(ev.get("date",""), "%b %d, %Y").date()
                if d_only == now_kst:
                    events.append(ev)
            except Exception:
                continue
        def impact_rank(x):
            imp = (x.get("impact") or "").lower()
            if "high" in imp: return 0
            if "medium" in imp: return 1
            return 2
        events.sort(key=impact_rank)
        return events
    except Exception as e:
        logger.warning(f"경제일정 수집 실패: {e}")
        return []

# =========================
# 알 수 없는 명령
# =========================
async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("❓ 알 수 없는 명령어입니다. /help 참고")
    # 그룹에서는 무시 (그룹은 자동 전송 전용)

# =========================
# 애플리케이션 구성 & 실행
# =========================
def start_bot_in_thread():
    # DM 전용 + 멤버 제한 명령
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("test", test_cmd))
    application.add_handler(CommandHandler("price", price_cmd))
    application.add_handler(CommandHandler("summary", summary_cmd))
    application.add_handler(CommandHandler("analyze", analyze_cmd))

    # 관리자 전용 (DM)
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("config", config_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))

    # 그룹 전용
    application.add_handler(CommandHandler("news", news_cmd_group))
    application.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))

    application.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))
    application.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Seoul", daemon=True)

    # 시세: 2분 간격
    scheduler.add_job(lambda: submit_coro(auto_send_prices()),
                      trigger=IntervalTrigger(minutes=2))

    # 뉴스: 10분 간격 (최초 전체, 이후 신규만)
    scheduler.add_job(lambda: submit_coro(auto_send_news()),
                      trigger=IntervalTrigger(minutes=10))

    # 랭킹: 1시간 간격 + 최초 1회 즉시
    scheduler.add_job(lambda: submit_coro(auto_send_rankings(initial=False)),
                      trigger=IntervalTrigger(hours=1))
    # 최초 즉시 한 번
    submit_coro(auto_send_rankings(initial=True))

    # 급등 감지: 2분마다 체크(내부 10분 기준 비교)
    scheduler.add_job(lambda: submit_coro(auto_detect_surge()),
                      trigger=IntervalTrigger(minutes=2))

    # RSI 과매도 탐지: 매시간
    scheduler.add_job(lambda: submit_coro(auto_detect_oversold()),
                      trigger=IntervalTrigger(hours=1))

    # 경제일정: 매일 오전 9시(KST)
    scheduler.add_job(lambda: submit_coro(auto_send_calendar_morning()),
                      trigger=CronTrigger(hour=9, minute=0))

    scheduler.start()
    return scheduler

def run():
    # PTB 스레드
    t = Thread(target=start_bot_in_thread, name="PTB", daemon=True)
    t.start()

    # 스케줄러 시작
    start_scheduler()

    # Flask 포트 바인딩
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    run()
