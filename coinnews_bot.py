import os
import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from telegram import Update, ChatMember
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ChatMemberHandler,
    ContextTypes, filters
)
import httpx
import feedparser
from deep_translator import GoogleTranslator

# =========================
# 환경변수 (Render UI)
# =========================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID", "").strip()
ADMIN_IDS = os.environ.get("ADMIN_IDS", "").strip()  # "123,456"
PORT = int(os.environ.get("PORT", "10000"))

if not TOKEN or not GROUP_ID:
    raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID 를 설정하세요.")
GROUP_ID_INT = int(GROUP_ID)
ADMIN_SET = {x.strip() for x in ADMIN_IDS.split(",") if x.strip()}

# =========================
# 앱/로깅/파일
# =========================
app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("coinbot")

DATA_FILE = "user_data.json"
NEWS_CACHE_FILE = "news_cache.json"
PRICES_CACHE_FILE = "prices_cache.json"       # 마지막 성공 시세 캐시
RANKINGS_CACHE_FILE = "rankings_cache.json"   # 마지막 성공 랭킹 캐시
SURGE_STATE_FILE = "surge_state.json"         # 급등 감지 상태(최근 기준가)

def _init_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
for path, default in [
    (DATA_FILE, {}),
    (NEWS_CACHE_FILE, {"seen_links": [], "title_ko": {}}),
    (PRICES_CACHE_FILE, {"updated_at": None, "prices": {}}),
    (RANKINGS_CACHE_FILE, {"updated_at": None, "highs": [], "lows": []}),
    (SURGE_STATE_FILE, {"last": {}}),
]:
    _init_file(path, default)

def jload(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def jsave(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================
# 유저 관리
# =========================
def load_users(): return jload(DATA_FILE, {})
def save_users(d): jsave(DATA_FILE, d)

def get_or_assign_user_id(user_id: int, username: str = "") -> int:
    d = load_users()
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
    save_users(d)
    return new_id

def inc_msg(user_id: int):
    d = load_users()
    k = str(user_id)
    if k in d:
        d[k]["messages"] = d[k].get("messages", 0) + 1
        d[k]["last_dm"] = datetime.now(timezone.utc).isoformat()
        save_users(d)

def find_by_cid(custom_id: str):
    d = load_users()
    for uid, info in d.items():
        if str(info.get("custom_id")) == str(custom_id):
            return int(uid), info
    return None, None

def find_by_username(username: str):
    if username.startswith("@"): username = username[1:]
    d = load_users()
    for uid, info in d.items():
        if (info.get("username") or "").lower() == username.lower():
            return int(uid), info
    return None, None

def is_admin(user_id: int) -> bool:
    return str(user_id) in ADMIN_SET

# =========================
# PTB 앱/루프
# =========================
application = ApplicationBuilder().token(TOKEN).build()
PTB_LOOP: asyncio.AbstractEventLoop | None = None

async def post_init(app_):
    global PTB_LOOP
    PTB_LOOP = asyncio.get_running_loop()
application.post_init = post_init

def submit_coro(coro):
    """스케줄러(별도 스레드)→ PTB 메인 루프로 안전 제출"""
    if PTB_LOOP is None:
        logger.warning("PTB loop not ready yet.")
        return
    asyncio.run_coroutine_threadsafe(coro, PTB_LOOP)

# =========================
# 마켓/지표 유틸
# =========================
TRACKED = ("btc", "eth", "xrp", "sol", "doge")
CG_IDS = {"btc":"bitcoin","eth":"ethereum","xrp":"ripple","sol":"solana","doge":"dogecoin"}
CP_TICKERS = {
    "btc":"btc-bitcoin","eth":"eth-ethereum","xrp":"xrp-xrp","sol":"sol-solana","doge":"doge-dogecoin"
}
NAMES = {"btc":"BTC (비트코인)","eth":"ETH (이더리움)","xrp":"XRP (리플)","sol":"SOL (솔라나)","doge":"DOGE (도지코인)"}

async def http_get_json(url, params=None, timeout=15, headers=None):
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        r = await client.get(url, params=params)
        return r

async def fetch_usdkrw_fallback():
    try:
        r = await http_get_json("https://api.exchangerate.host/latest", params={"base":"USD","symbols":"KRW"})
        if r.status_code == 200:
            return float(r.json()["rates"]["KRW"])
    except Exception:
        pass
    return 1400.0

# --- 가격: 기본(Coingecko) → 폴백1(CoinPaprika) → 폴백2(Upbit KRW & 자체 환율) ---
async def prices_primary_coingecko():
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(CG_IDS.values()), "vs_currencies":"usd,krw"}
    r = await http_get_json(url, params=params, timeout=15, headers={"Accept":"application/json"})
    if r.status_code == 429:
        raise RuntimeError("coingecko 429")
    if r.status_code != 200:
        raise RuntimeError(f"coingecko status {r.status_code}")
    data = r.json()
    out = {}
    for sym, cg in CG_IDS.items():
        if cg not in data: raise KeyError(f"missing {cg}")
        out[sym] = {"usd": float(data[cg]["usd"]), "krw": float(data[cg]["krw"])}
    return out

async def prices_fallback_coinpaprika():
    usdkrw = await fetch_usdkrw_fallback()
    out = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for sym in TRACKED:
            tid = CP_TICKERS[sym]
            r = await client.get(f"https://api.coinpaprika.com/v1/tickers/{tid}")
            r.raise_for_status()
            q = r.json()["quotes"]["USD"]
            usd = float(q["price"])
            out[sym] = {"usd": usd, "krw": usd * usdkrw}
    return out

async def prices_fallback_upbit_binance():
    """최후 폴백: KRW(업비트) → USD 추정(환율), 나머지는 CoinPaprika 혼합"""
    usdkrw = await fetch_usdkrw_fallback()
    out = {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # BTC만이라도 정확 KRW를 확보
            ur = await client.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
            ur.raise_for_status()
            up_btc_krw = float(ur.json()[0]["trade_price"])
            out["btc"] = {"usd": up_btc_krw/usdkrw, "krw": up_btc_krw}
    except Exception:
        pass
    # 나머지는 Paprika로 채움
    pap = await prices_fallback_coinpaprika()
    for sym in TRACKED:
        if sym not in out:
            out[sym] = pap[sym]
    return out

async def get_prices_usd_krw():
    """가격 with 캐시 & 다중 폴백. 실패 시 캐시 사용."""
    cache = jload(PRICES_CACHE_FILE, {"updated_at": None, "prices": {}})
    try:
        prices = await prices_primary_coingecko()
    except Exception as e1:
        logger.warning(f"CoinGecko 실패: {e1}")
        try:
            prices = await prices_fallback_coinpaprika()
        except Exception as e2:
            logger.warning(f"Paprika 실패: {e2}")
            try:
                prices = await prices_fallback_upbit_binance()
            except Exception as e3:
                logger.error(f"모든 소스 실패: {e3}")
                # 캐시 사용
                if cache["prices"]:
                    return cache["prices"], True  # True=stale
                raise
    # 성공 시 캐시 저장
    jsave(PRICES_CACHE_FILE, {"updated_at": datetime.now(timezone.utc).isoformat(), "prices": prices})
    return prices, False

async def kimp_components():
    """김프 계산: 업비트 KRW-BTC / (BTC-USD * USDKRW)"""
    async with httpx.AsyncClient(timeout=15) as client:
        ur = await client.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        ur.raise_for_status()
        up_krw = float(ur.json()[0]["trade_price"])
    try:
        prices, _ = await get_prices_usd_krw()
        btc_usd = prices["btc"]["usd"]
        usdkrw = prices["btc"]["krw"]/prices["btc"]["usd"] if prices["btc"]["usd"] else await fetch_usdkrw_fallback()
    except Exception:
        # 최후 대안
        btc_usd = (await prices_fallback_coinpaprika())["btc"]["usd"]
        usdkrw = await fetch_usdkrw_fallback()
    glb_krw = btc_usd * usdkrw
    kimp = (up_krw / glb_krw - 1.0) * 100
    return up_krw, glb_krw, kimp

# --- OHLCV / RSI / MACD ---
async def fetch_ohlcv_close(sym: str, days=200):
    if sym not in CP_TICKERS: return []
    tid = CP_TICKERS[sym]
    end = datetime.utcnow().date()
    start = end - timedelta(days=days+5)
    url = f"https://api.coinpaprika.com/v1/coins/{tid}/ohlcv/historical"
    r = await http_get_json(url, params={"start":start.isoformat(),"end":end.isoformat()}, timeout=20)
    if r.status_code != 200:
        return []
    data = r.json()
    return [float(x["close"]) for x in data if "close" in x]

def rsi(closes, period=14):
    if len(closes) < period+1: return None
    gains, losses = [], []
    for i in range(1,len(closes)):
        ch = closes[i]-closes[i-1]
        gains.append(max(ch,0)); losses.append(max(-ch,0))
    avg_g = sum(gains[:period])/period
    avg_l = sum(losses[:period])/period
    for i in range(period, len(closes)-1):
        avg_g = (avg_g*(period-1)+gains[i])/period
        avg_l = (avg_l*(period-1)+losses[i])/period
    if avg_l==0: return 100.0
    rs = avg_g/avg_l
    return 100 - 100/(1+rs)

def ema(values, period):
    k = 2/(period+1); e = values[0]; out=[]
    for v in values:
        e = v*k + e*(1-k); out.append(e)
    return out

def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow+signal: return None, None, None
    ef = ema(closes, fast); es = ema(closes, slow)
    macd_line = [a-b for a,b in zip(ef[-len(es):], es)]
    signal_line = ema(macd_line, signal)
    hist = macd_line[-1]-signal_line[-1]
    return macd_line[-1], signal_line[-1], hist

# =========================
# 뉴스/경제일정 (캐시 강화)
# =========================
def news_cache_load():
    return jload(NEWS_CACHE_FILE, {"seen_links": [], "title_ko": {}})

def news_cache_save(cache):
    jsave(NEWS_CACHE_FILE, cache)

async def fetch_news(limit=20):
    cache = news_cache_load()
    seen = set(cache.get("seen_links", []))
    title_ko = cache.get("title_ko", {})
    try:
        feed = feedparser.parse("https://cointelegraph.com/rss")
        entries = feed.entries[:limit]
    except Exception as e:
        logger.warning(f"뉴스 RSS 실패: {e}")
        return []
    items = []
    for e in entries:
        link = e.link; title = e.title
        if link in title_ko:
            ko = title_ko[link]
        else:
            try:
                ko = GoogleTranslator(source="auto", target="ko").translate(title)
            except Exception:
                ko = title  # 번역 실패 시 원문
            title_ko[link] = ko
        items.append((title, ko, link))
    cache["title_ko"] = title_ko
    news_cache_save(cache)
    return items

def mark_news_sent(links):
    cache = news_cache_load()
    s = set(cache.get("seen_links", [])); s.update(links)
    cache["seen_links"] = list(s)
    news_cache_save(cache)

def get_news_seen():
    return set(news_cache_load().get("seen_links", []))

async def fetch_calendar_today_kst():
    try:
        r = await http_get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15)
        if r.status_code != 200: return []
        data = r.json()
        today = datetime.now(timezone(timedelta(hours=9))).date()
        events = []
        for ev in data:
            try:
                d = datetime.strptime(ev.get("date",""), "%b %d, %Y").date()
                if d == today: events.append(ev)
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
        logger.warning(f"경제일정 실패: {e}")
        return []

# =========================
# 권한/멤버십
# =========================
async def is_member(user_id:int)->bool:
    try:
        cm = await application.bot.get_chat_member(chat_id=GROUP_ID_INT, user_id=user_id)
        return cm.status in ("member","administrator","creator")
    except Exception:
        return False

def dm_member_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private": return
        if not await is_member(update.effective_user.id):
            await update.message.reply_text("❌ 그룹방 참여자만 사용 가능합니다.")
            return
        return await func(update, context)
    return wrapper

# =========================
# DM 명령
# =========================
@dm_member_only
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = get_or_assign_user_id(update.effective_user.id, update.effective_user.username or "")
    inc_msg(update.effective_user.id)
    await update.message.reply_text(
        "🟢 작동 중입니다.\n"
        "/help - 도움말\n"
        "/price - 시세(USD/KRW/김프)\n"
        "/summary - 요약(시세/뉴스/일정)\n"
        "/analyze [btc|eth|xrp|sol|doge]\n"
        "/test - DM/멤버 체크\n"
        f"당신의 고유번호: {uid}"
    )

@dm_member_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_msg(update.effective_user.id)
    await update.message.reply_text(
        "📌 DM 전용 (그룹 참여자만)\n"
        "/start /help /test /price /summary /analyze [심볼]\n\n"
        "👮 관리자: /ban /unban /id /config /stats\n"
        "📰 /news 는 그룹 전용 (최초 전체, 이후 신규만)"
    )

@dm_member_only
async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_msg(update.effective_user.id)
    await update.message.reply_text("✅ DM OK & 그룹 멤버 확인 완료")

@dm_member_only
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_msg(update.effective_user.id)
    try:
        prices, stale = await get_prices_usd_krw()
        up, glb, k = await kimp_components()
        lines = ["📈 주요 코인 시세" + (" (캐시)" if stale else "")]
        for sym in TRACKED:
            usd = prices[sym]["usd"]; krw = prices[sym]["krw"]
            lines.append(f"{NAMES[sym]}: ${usd:,.2f} / ₩{krw:,.0f}")
        lines.append(f"\n🇰🇷 김프(BTC): 업비트 ₩{up:,.0f} / 글로벌 ₩{glb:,.0f} → {k:+.2f}%")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.exception("price_cmd")
        await update.message.reply_text("⚠️ 시세 조회 실패(일시적 제한). 잠시 후 다시 시도해주세요.")

@dm_member_only
async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_msg(update.effective_user.id)
    try:
        prices, stale = await get_prices_usd_krw()
        up, glb, k = await kimp_components()
        news_items = await fetch_news(limit=12)
        seen = get_news_seen()
        fresh = [(ko, link) for _, ko, link in news_items if link not in seen][:3]
        cal = await fetch_calendar_today_kst()

        price_line=[]
        for sym in TRACKED:
            usd = prices[sym]["usd"]; krw=prices[sym]["krw"]
            price_line.append(f"{NAMES[sym].split()[0]} ${usd:,.0f}/₩{krw:,.0f}")
        lines = [
            "📊 요약" + (" (시세 캐시)" if stale else ""),
            "• 시세: " + ", ".join(price_line),
            f"• 김프: 업비트 ₩{up:,.0f} / 글로벌 ₩{glb:,.0f} → {k:+.2f}%"
        ]
        if fresh:
            lines.append("• 뉴스:")
            for t, u in fresh: lines.append(f"  - {t}")
        if cal:
            lines.append("• 오늘 경제일정:")
            for ev in cal[:5]:
                lines.append(f"  - [{ev.get('country','')}] {ev.get('title','')} ({ev.get('impact','')})")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.exception("summary_cmd")
        await update.message.reply_text("⚠️ 요약 생성 실패(일시적 제한).")

@dm_member_only
async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inc_msg(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("사용법: /analyze [btc|eth|xrp|sol|doge]")
        return
    sym = context.args[0].lower()
    if sym not in TRACKED:
        await update.message.reply_text("지원: btc, eth, xrp, sol, doge")
        return
    try:
        closes = await fetch_ohlcv_close(sym, days=200)
        if not closes: raise RuntimeError("OHLCV 없음")
        r = rsi(closes, period=14)
        m, s, h = macd(closes, fast=12, slow=26, signal=9)
        tip=[]
        if r is not None:
            if r<=30: tip.append("RSI 과매도")
            elif r>=70: tip.append("RSI 과매수")
            else: tip.append("RSI 중립")
        if m is not None and s is not None and h is not None:
            if h>0 and m>s: tip.append("MACD 강세")
            elif h<0 and m<s: tip.append("MACD 약세")
            else: tip.append("MACD 중립")
        await update.message.reply_text(
            f"🔍 {NAMES[sym]} 분석\n"
            f"• RSI(14): {r:.2f}\n"
            f"• MACD: {m:.4f} / Signal: {s:.4f} / Hist: {h:.4f}\n"
            f"• 해석: {', '.join(tip)}"
        )
    except Exception as e:
        logger.exception("analyze_cmd")
        await update.message.reply_text("⚠️ 분석 실패(데이터 부족/제한).")

# =========================
# 관리자 명령 (DM 전용)
# =========================
async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("사용법: /id [@username | 고유번호]")
        return
    key = context.args[0]
    if key.startswith("@"):
        uid, info = find_by_username(key)
    elif key.isdigit():
        uid, info = find_by_cid(key)
    else:
        await update.message.reply_text("형식: @유저명 or 숫자 고유번호")
        return
    if not uid:
        await update.message.reply_text("유저를 찾을 수 없습니다.")
        return
    await update.message.reply_text(
        f"👤 조회\nTG ID: {uid}\n고유번호: {info.get('custom_id')}\n"
        f"유저명: @{info.get('username')}\n가입: {info.get('joined_at')}\n"
        f"누적DM: {info.get('messages',0)}"
    )

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id): return
    await update.message.reply_text(
        "⚙️ 설정\n"
        f"GROUP_ID: {GROUP_ID}\nADMIN_IDS: {ADMIN_IDS or '(미설정)'}\n"
        "명령: DM 전용(그룹참여자만)\n자동전송: 그룹 전용"
    )

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id): return
    d = load_users()
    total = len(d)
    banned = sum(1 for v in d.values() if v.get("banned"))
    msgs = sum(int(v.get("messages",0)) for v in d.values())
    await update.message.reply_text(f"📈 통계\n등록: {total}\n차단: {banned}\n누적DM: {msgs}")

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id): return
    if not context.args: 
        await update.message.reply_text("사용법: /ban [고유번호]")
        return
    target = context.args[0]
    uid, info = find_by_cid(target)
    if not uid:
        await update.message.reply_text("해당 고유번호 없음")
        return
    try:
        await application.bot.ban_chat_member(chat_id=GROUP_ID_INT, user_id=uid)
    except Exception: pass
    d = load_users(); d[str(uid)]["banned"]=True; save_users(d)
    await update.message.reply_text(f"⛔️ 차단 완료 (ID:{target})")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id): return
    if not context.args: 
        await update.message.reply_text("사용법: /unban [고유번호]")
        return
    target = context.args[0]
    uid, info = find_by_cid(target)
    if not uid:
        await update.message.reply_text("해당 고유번호 없음")
        return
    try:
        await application.bot.unban_chat_member(chat_id=GROUP_ID_INT, user_id=uid, only_if_banned=True)
    except Exception: pass
    d = load_users(); d[str(uid)]["banned"]=False; save_users(d)
    await update.message.reply_text(f"✅ 차단 해제 (ID:{target})")

# =========================
# 그룹 전용 /news
# =========================
async def news_cmd_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID_INT: return
    try:
        items = await fetch_news(limit=30)
        seen = get_news_seen()
        if not seen:
            batch = items[:10]
        else:
            batch = [x for x in items if x[2] not in seen]
        if not batch: return
        msg = "📰 코인 뉴스 업데이트\n" + "\n\n".join([f"• {ko}\n{link}" for _,ko,link in batch])
        await update.message.reply_text(msg)
        mark_news_sent([link for _,_,link in batch])
    except Exception as e:
        logger.warning(f"/news 오류: {e}")

# =========================
# 멤버 입장
# =========================
async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.chat_member
    if ch and ch.new_chat_member and ch.new_chat_member.status == ChatMember.MEMBER:
        user = ch.new_chat_member.user
        uid = get_or_assign_user_id(user.id, user.username or "")
        try:
            await context.bot.send_message(
                chat_id=ch.chat.id,
                text=(f"👋 {user.full_name}님 환영합니다! (고유번호:{uid})\n"
                      "📩 모든 기능은 DM에서 사용 가능합니다. DM으로 /start 를 보내보세요.")
            )
        except Exception: pass

# =========================
# 자동 전송 작업들 (캐시/폴백 반영)
# =========================
def load_surge_state():
    return jload(SURGE_STATE_FILE, {"last": {}})

def save_surge_state(st):
    jsave(SURGE_STATE_FILE, st)

async def auto_send_prices():
    try:
        prices, stale = await get_prices_usd_krw()
        up, glb, k = await kimp_components()
        lines = ["📈 실시간 시세" + (" (캐시)" if stale else "")]
        for sym in TRACKED:
            usd = prices[sym]["usd"]; krw = prices[sym]["krw"]
            emoji = "🟢"
            lines.append(f"{emoji} {NAMES[sym]}: ${usd:,.2f} / ₩{krw:,.0f}")
        lines.append(f"\n🇰🇷 김프(BTC): 업비트 ₩{up:,.0f} / 글로벌 ₩{glb:,.0f} → {k:+.2f}%")
        await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"자동 시세 실패: {e}")

async def auto_send_news():
    try:
        items = await fetch_news(limit=30)
        seen = get_news_seen()
        batch = items[:10] if not seen else [x for x in items if x[2] not in seen]
        if not batch: return
        msg = "📰 코인 뉴스 업데이트\n" + "\n\n".join([f"• {ko}\n{link}" for _,ko,link in batch])
        await application.bot.send_message(chat_id=GROUP_ID_INT, text=msg)
        mark_news_sent([link for _,_,link in batch])
    except Exception as e:
        logger.warning(f"자동 뉴스 실패: {e}")

async def auto_send_rankings(initial=False):
    cache = jload(RANKINGS_CACHE_FILE, {"updated_at": None, "highs": [], "lows": []})
    try:
        r = await http_get_json("https://api.coinpaprika.com/v1/tickers", timeout=25)
        if r.status_code != 200: raise RuntimeError(f"rank status {r.status_code}")
        data = r.json()
        entries=[]
        for t in data:
            q=t.get("quotes",{}).get("USD",{})
            if q.get("percent_change_24h") is None or q.get("price") is None: continue
            entries.append({"sym":t.get("symbol"),"p":float(q["price"]),"c":float(q["percent_change_24h"])})
        highs=sorted(entries,key=lambda x:x["c"],reverse=True)[:10]
        lows=sorted(entries,key=lambda x:x["c"])[:10]
        # 캐시 저장
        jsave(RANKINGS_CACHE_FILE, {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "highs": highs, "lows": lows
        })
    except Exception as e:
        logger.warning(f"랭킹 실패: {e}")
        highs = cache["highs"]; lows = cache["lows"]
        if not highs and not lows: return  # 캐시도 없으면 포기

    lines=["🏆 24시간 변동률 랭킹"]
    if initial: lines.insert(0,"⏱ 최초 실행 즉시 전송")
    lines.append("🔼 상승 TOP10")
    for i,it in enumerate(highs,1): lines.append(f"{i}. {it['sym']}: {it['c']:+.2f}% (${it['p']:,.4f})")
    lines.append("\n🔽 하락 TOP10")
    for i,it in enumerate(lows,1): lines.append(f"{i}. {it['sym']}: {it['c']:+.2f}% (${it['p']:,.4f})")
    await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))

async def auto_detect_surge():
    """10분 기준 +5% 급등 감지(TRACKED) — 가격 소스 다중 폴백 + 상태 파일 유지"""
    st = load_surge_state()
    last = st.get("last", {})
    try:
        # 1차: CoinGecko
        r = await http_get_json("https://api.coingecko.com/api/v3/simple/price",
                                params={"ids": ",".join(CG_IDS.values()), "vs_currencies": "usd"}, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"cg {r.status_code}")
        data=r.json()
        now=datetime.now(timezone.utc)
        alerts=[]
        for sym, cg in CG_IDS.items():
            if cg not in data: continue
            p=float(data[cg]["usd"])
            prev = last.get(sym)
            if prev:
                ts = datetime.fromisoformat(prev["ts"])
                op = float(prev["price"])
                if (now-ts)>=timedelta(minutes=10) and op>0:
                    chg=(p/op-1.0)*100
                    if chg>=5.0: alerts.append((sym,chg,p))
            # 갱신
            last[sym] = {"ts": now.isoformat(), "price": p}
        if alerts:
            lines=["🚀 급등 감지 (+10분 기준)"]
            for sym,chg,p in alerts:
                lines.append(f"• {NAMES[sym]}: {chg:+.2f}% (현재 ${p:,.4f})")
            await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"급등 감지 실패: {e}")
    # 상태 저장(성공/실패와 무관하게 최신 값 유지 시도됨)
    st["last"] = last
    save_surge_state(st)

async def auto_detect_oversold():
    """RSI 과매도(≤30) 탐지"""
    try:
        alerts=[]
        for sym in TRACKED:
            closes = await fetch_ohlcv_close(sym, days=200)
            if not closes: continue
            r = rsi(closes, period=14)
            if r is not None and r<=30:
                alerts.append((sym,r,closes[-1]))
        if alerts:
            lines=["🧭 과매도 감지 (RSI≤30, 일봉)"]
            for sym,rv,close in alerts:
                lines.append(f"• {NAMES[sym]}: RSI {rv:.2f}, 종가 ${close:,.2f}")
            await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"과매도 실패: {e}")

# =========================
# 기타
# =========================
async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("❓ 알 수 없는 명령어입니다. /help 참고")

@app.get("/")
def health(): return "OK"

# =========================
# 실행
# =========================
def start_flask():
    app.run(host="0.0.0.0", port=PORT)

def start_scheduler():
    sched = BackgroundScheduler(timezone="Asia/Seoul", daemon=True)
    # 시세 2분
    sched.add_job(lambda: submit_coro(auto_send_prices()), IntervalTrigger(minutes=2))
    # 뉴스 10분(최초 전체/이후 신규는 함수 내부 처리)
    sched.add_job(lambda: submit_coro(auto_send_news()), IntervalTrigger(minutes=10))
    # 랭킹 1시간 + 최초 즉시
    sched.add_job(lambda: submit_coro(auto_send_rankings(initial=False)), IntervalTrigger(hours=1))
    submit_coro(auto_send_rankings(initial=True))
    # 급등 2분(내부 10분 기준)
    sched.add_job(lambda: submit_coro(auto_detect_surge()), IntervalTrigger(minutes=2))
    # RSI 과매도 1시간
    sched.add_job(lambda: submit_coro(auto_detect_oversold()), IntervalTrigger(hours=1))
    # 경제일정 오전 9시 (뉴스 보강은 위 주기로 충분)
    sched.add_job(lambda: submit_coro(_send_calendar_morning_wrapper()), CronTrigger(hour=9, minute=0))
    sched.start()
    return sched

async def _send_calendar_morning_wrapper():
    try:
        cal = await fetch_calendar_today_kst()
        if not cal: return
        lines=["📅 오늘의 글로벌 경제일정 (요약)"]
        for ev in cal[:12]:
            lines.append(f"• [{ev.get('country','')}] {ev.get('title','')} ({ev.get('impact','')})")
        await application.bot.send_message(chat_id=GROUP_ID_INT, text="\n".join(lines))
    except Exception as e:
        logger.warning(f"일정 전송 실패: {e}")

def main():
    # 핸들러
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("test", test_cmd))
    application.add_handler(CommandHandler("price", price_cmd))
    application.add_handler(CommandHandler("summary", summary_cmd))
    application.add_handler(CommandHandler("analyze", analyze_cmd))

    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("config", config_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))

    application.add_handler(CommandHandler("news", news_cmd_group))
    application.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))

    # Flask는 백그라운드 스레드로 포트 바인딩
    Thread(target=start_flask, name="Flask", daemon=True).start()
    # 스케줄러 시작
    start_scheduler()

    # PTB는 메인 스레드. set_wakeup_fd 이슈 방지 위해 stop_signals=None
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
        stop_signals=None
    )

if __name__ == "__main__":
    main()
