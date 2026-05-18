# ============================================================
# notifier.py — Crypto Market Notifier (Lite + Full mode)
#
# Lite mode  (every 1h)  : price + indicators + F&G → signal.json
# Full mode  (3x per day): everything + Claude AI + email
# ============================================================

import requests
import feedparser
import smtplib
import json
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config import (
    EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER,
    ANTHROPIC_API_KEY, WHALE_ALERT_API_KEY,
)
from signal_writer import write_signal

# ──────────────────── copy indicators.py from bot folder as well ────────────────────
# notifier uses calc_rsi, calc_ema, calc_sma, calc_macd,
# calc_bollinger from bot's indicators.py directly
# (see "Files to copy" section in SETUP_GUIDE.md)


# ──────────────────── Helpers ────────────────────
def fmt(n: float) -> str:
    if n >= 1_000_000_000: return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:     return f"${n/1_000_000:.2f}M"
    if n >= 1_000:         return f"${n:,.0f}"
    return f"${n:.2f}"


# ──────────────────── Data fetchers ────────────────────

def get_prices() -> dict | None:
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_24hr_vol": "true",
                    "include_market_cap": "true"},
            timeout=10,
        )
        d = r.json()
        return {
            "btc": {"price": d["bitcoin"]["usd"],
                    "change": d["bitcoin"]["usd_24h_change"],
                    "vol": d["bitcoin"]["usd_24h_vol"],
                    "mcap": d["bitcoin"]["usd_market_cap"]},
            "eth": {"price": d["ethereum"]["usd"],
                    "change": d["ethereum"]["usd_24h_change"],
                    "vol": d["ethereum"]["usd_24h_vol"],
                    "mcap": d["ethereum"]["usd_market_cap"]},
        }
    except Exception as e:
        print(f"[!] prices: {e}"); return None


def get_fear_greed() -> dict | None:
    try:
        data = requests.get(
            "https://api.alternative.me/fng/?limit=2", timeout=10
        ).json()["data"]
        v = int(data[0]["value"])
        return {
            "value":     v,
            "label":     data[0]["value_classification"],
            "yesterday": int(data[1]["value"]),
            "should_buy": v > 20,
            "tp_mult":   1.2 if v < 30 else (0.8 if v > 75 else 1.0),
            "sl_mult":   0.8 if v < 30 else (1.2 if v > 75 else 1.0),
            "advice":    "Buy zone" if v < 30 else ("Sell zone" if v > 75 else "Neutral"),
        }
    except Exception as e:
        print(f"[!] F&G: {e}"); return None


def get_ohlcv_binance(symbol: str, interval: str = "1d", limit: int = 200) -> list:
    """Fetch OHLCV from Binance public (no key needed)"""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        candles = r.json()
        return [float(c[4]) for c in candles]   # closes only
    except Exception as e:
        print(f"[!] OHLCV {symbol}: {e}"); return []


def get_news(max_items: int = 8) -> list:
    feeds = ["https://cryptopanic.com/news/rss/",
             "https://cointelegraph.com/rss"]
    news = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:max_items]:
                news.append({"title": e.get("title", ""),
                             "link":  e.get("link",  ""),
                             "source": feed.feed.get("title", "Crypto")})
        except Exception as ex:
            print(f"[!] RSS: {ex}")
    return news[:max_items]


def get_whale_alerts() -> list:
    if not WHALE_ALERT_API_KEY or WHALE_ALERT_API_KEY == "YOUR_WHALE_ALERT_API_KEY":
        return []
    try:
        import time as _time
        r = requests.get(
            "https://api.whale-alert.io/v1/transactions",
            params={"api_key": WHALE_ALERT_API_KEY,
                    "min_value": 1_000_000,
                    "start": int(_time.time()) - 3600,
                    "limit": 5},
            timeout=10,
        )
        r.raise_for_status()
        return [{"symbol":     t.get("symbol", "").upper(),
                 "amount_usd": t.get("amount_usd", 0),
                 "from":       t.get("from", {}).get("owner_type", "?"),
                 "to":         t.get("to",   {}).get("owner_type", "?"),
                 "chain":      t.get("blockchain", "")}
                for t in r.json().get("transactions", [])[:5]]
    except Exception as e:
        print(f"[!] whale: {e}"); return []


# ──────────────────── Indicators (inline — independent from bot's indicators.py) ────────────────────

def _sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None

def _ema(closes, n):
    if len(closes) < n: return None
    k, ema = 2/(n+1), sum(closes[:n])/n
    for p in closes[n:]: ema = p*k + ema*(1-k)
    return ema

def _rsi(closes, n=14):
    if len(closes) < n+1: return None
    gs, ls = [], []
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]; gs.append(max(d,0)); ls.append(max(-d,0))
    ag, al = sum(gs[:n])/n, sum(ls[:n])/n
    for i in range(n, len(gs)):
        ag = (ag*(n-1)+gs[i])/n; al = (al*(n-1)+ls[i])/n
    return round(100-100/(1+ag/al), 2) if al else 100
```python
def _macd(closes):
    e12,e26 = _ema(closes,12),_ema(closes,26)
    if not e12 or not e26: return None,None,None
    ml = e12-e26
    mv = [_ema(closes[:i+1],12)-_ema(closes[:i+1],26)
          for i in range(max(26,len(closes)-20), len(closes))
          if _ema(closes[:i+1],12) and _ema(closes[:i+1],26)]
    sig = _ema(mv,9) if len(mv)>=9 else None
    return round(ml,4), sig, round(ml-sig,4) if sig else None

def _bollinger(closes, n=20, k=2):
    if len(closes)<n: return None,None,None
    w=closes[-n:]; m=sum(w)/n
    std=(sum((x-m)**2 for x in w)/n)**0.5
    return round(m+k*std,4),round(m,4),round(m-k*std,4)

def get_signals_from_closes(closes_d, closes_4h, fg_value: int) -> dict:
    """Calculate signals from closes arrays with details for all indicators"""

    def score(closes, timeframe):
        if not closes or len(closes) < 30:
            return {"action": "HOLD", "score": 0, "confidence": 0, "details": []}

        rsi              = _rsi(closes)
        ma50             = _sma(closes, 50)
        ma200            = _sma(closes, 200)
        macd, sig_line, hist = _macd(closes)
        bb_up, bb_mid, bb_lo = _bollinger(closes)
        price            = closes[-1]

        scores  = []
        details = []

        # ──────────────────── RSI ────────────────────
        if rsi is not None:
            if rsi < 30:
                scores.append(2); details.append(f"RSI={rsi:.0f} extreme oversold 🟢🟢")
            elif rsi < 40:
                scores.append(1); details.append(f"RSI={rsi:.0f} oversold 🟢")
            elif rsi > 70:
                scores.append(-2); details.append(f"RSI={rsi:.0f} extreme overbought 🔴🔴")
            elif rsi > 60:
                scores.append(-1); details.append(f"RSI={rsi:.0f} overbought 🔴")
            else:
                scores.append(0); details.append(f"RSI={rsi:.0f} neutral ⚪")

        # ──────────────────── MACD ────────────────────
        if macd is not None and sig_line is not None:
            if macd > sig_line and hist and hist > 0:
                scores.append(1); details.append(f"MACD bullish cross 🟢")
            elif macd < sig_line and hist and hist < 0:
                scores.append(-1); details.append(f"MACD bearish cross 🔴")
            else:
                scores.append(0); details.append(f"MACD neutral ⚪")

        # ──────────────────── MA (mid only) ────────────────────
        if timeframe == "mid" and ma50 and ma200:
            if ma50 > ma200 and price > ma50:
                scores.append(2); details.append(f"Price>MA50>MA200 uptrend 🟢🟢")
            elif ma50 > ma200 and price > ma200:
                scores.append(1); details.append(f"Above MA200 mild bull 🟢")
            elif ma50 < ma200 and price < ma50:
                scores.append(-2); details.append(f"Price<MA50<MA200 downtrend 🔴🔴")
            elif price < ma200:
                scores.append(-1); details.append(f"Below MA200 bearish 🔴")
            else:
                scores.append(0); details.append(f"Mixed MA signals ⚪")

        # ──────────────────── Bollinger Bands ────────────────────
        if bb_up and bb_lo:
            bw = bb_up - bb_lo
            if bw > 0:
                pos = (price - bb_lo) / bw
                if pos < 0.10:
                    scores.append(2); details.append(f"BB extreme lower {pos:.0%} 🟢🟢")
                elif pos < 0.25:
                    scores.append(1); details.append(f"BB near lower {pos:.0%} 🟢")
                elif pos > 0.90:
                    scores.append(-2); details.append(f"BB extreme upper {pos:.0%} 🔴🔴")
                elif pos > 0.75:
                    scores.append(-1); details.append(f"BB near upper {pos:.0%} 🔴")
                else:
                    scores.append(0); details.append(f"BB mid zone {pos:.0%} ⚪")

        # ──────────────────── Volume trend (short only) ────────────────────
        if timeframe == "short" and len(closes) >= 10:
            # Use price momentum instead of volume (because notifier only uses closes)
            momentum = (closes[-1] - closes[-5]) / closes[-5] * 100
            if momentum > 3:
                scores.append(1); details.append(f"Momentum +{momentum:.1f}% 🟢")
            elif momentum < -3:
                scores.append(-1); details.append(f"Momentum {momentum:.1f}% 🔴")
            else:
                scores.append(0); details.append(f"Momentum {momentum:.1f}% ⚪")

        # ──────────────────── Fear & Greed (mid only) ────────────────────
        if timeframe == "mid":
            if fg_value <= 15:
                scores.append(2); details.append(f"F&G={fg_value} extreme fear 🟢🟢")
            elif fg_value <= 25:
                scores.append(1); details.append(f"F&G={fg_value} fear zone 🟢")
            elif fg_value >= 85:
                scores.append(-2); details.append(f"F&G={fg_value} extreme greed 🔴🔴")
            elif fg_value >= 75:
                scores.append(-1); details.append(f"F&G={fg_value} greed zone 🔴")
            else:
                scores.append(0); details.append(f"F&G={fg_value} neutral ⚪")

        # ──────────────────── Aggregate ────────────────────
        total      = sum(scores)
        max_score  = sum(abs(s) for s in scores) or 1
        confidence = min(int(abs(total) / max_score * 100), 95)

        # Need confidence >= 40% to BUY/SELL
        if total >= 3 and confidence >= 40:
            action = "BUY"
        elif total <= -3 and confidence >= 40:
            action = "SELL"
        else:
            action = "HOLD"

        return {
            "action":     action,
            "score":      round(total, 1),
            "confidence": confidence,
```
```python
            "details":    details,
            "rsi":        round(rsi, 1) if rsi else None,
        }

    return {
        "short": score(closes_4h, "short"),
        "mid":   score(closes_d,  "mid"),
    }


# ──────────────────── Claude AI analysis ────────────────────

def analyze_with_claude(news_list, btc_price, eth_price, fg_value) -> dict | None:
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-..."):
        return None
    news_text = " | ".join([n['title'][:50] for n in news_list[:5]])
    prompt = (
        f"Crypto market analysis. JSON only, no explanation, no backticks.\n"
        f"BTC=${btc_price:,.0f} ETH=${eth_price:,.0f} FG={fg_value}\n"
        f"News: {news_text}\n"
        f'{{"sentiment":"bullish|bearish|neutral","sentiment_score":-100to100,'
        f'"key_themes":["x","y"],"short_term_outlook":"max 8 words",'
        f'"mid_term_outlook":"max 8 words","key_risk":"max 6 words","key_catalyst":"max 6 words"}}'
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001",
                  "max_tokens": 200,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["content"][0]["text"].strip()
        raw = raw.replace("```json","").replace("```","").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[!] Claude: {e}"); return None


# ──────────────────── Email builder ────────────────────

ACTION_STYLE = {
    "BUY":  {"bg":"#0d2b1e","border":"#10b981","text":"#10b981","badge":"#064e35"},
    "SELL": {"bg":"#2b0d0d","border":"#ef4444","text":"#ef4444","badge":"#4e0606"},
    "HOLD": {"bg":"#1a1a2e","border":"#6b7280","text":"#9ca3af","badge":"#374151"},
}

def _signal_card(label, result):
    if not result: return "<td></td>"
    c = ACTION_STYLE[result["action"]]
    return f"""<td style="width:50%;padding:0 6px;vertical-align:top;">
      <div style="background:{c['bg']};border:1px solid {c['border']};border-radius:10px;padding:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="color:#888;font-size:11px;">{label}</span>
          <span style="background:{c['badge']};color:{c['text']};font-size:13px;font-weight:700;padding:3px 10px;border-radius:6px;">{result['action']}</span>
        </div>
        <div style="color:#fff;font-size:11px;">Score: <b>{result['score']:+.1f}</b> | Confidence: <b>{result['confidence']}%</b></div>
      </div></td>"""

def build_email(prices, fg, sig_btc, sig_eth, news, whales, ai, mode) -> str:
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    def px(sym, d):
        col = "#10b981" if d["change"]>=0 else "#ef4444"
        arr = "▲" if d["change"]>=0 else "▼"
        return f"""<td style="width:50%;padding:0 6px;">
          <div style="background:#16162a;border:1px solid #2d2d4e;border-radius:10px;padding:16px;text-align:center;">
            <div style="color:#666;font-size:11px;letter-spacing:2px;">{sym}</div>
            <div style="color:#fff;font-size:26px;font-weight:700;">{fmt(d['price'])}</div>
            <div style="color:{col};font-size:13px;">{arr} {abs(d['change']):.2f}%</div>
            <div style="color:#555;font-size:10px;margin-top:4px;">Vol: {fmt(d['vol'])}</div>
          </div></td>"""

    prices_html = ""
    if prices:
        prices_html = f"""<table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
          <tr>{px("₿ BTC",prices['btc'])}{px("Ξ ETH",prices['eth'])}</tr></table>"""

    fg_html = ""
    if fg:
        v=fg["value"]
        col = "#ef4444" if v<=25 else("#f97316" if v<=45 else("#eab308" if v<=55 else("#84cc16" if v<=75 else"#10b981")))
        bg  = "#2d1a1a" if v<=25 else("#2d1e10" if v<=45 else("#2a2210" if v<=55 else("#1a2510" if v<=75 else"#0f2520")))
        delta = v-fg["yesterday"]
        fg_html = f"""<div style="background:{bg};border:1px solid {col}55;border-radius:10px;padding:16px;margin-bottom:20px;display:flex;gap:16px;align-items:center;">
          <div style="text-align:center;min-width:60px;"><div style="color:{col};font-size:36px;font-weight:800;">{v}</div><div style="color:{col};font-size:10px;">/100</div></div>
          <div><div style="color:#fff;font-size:15px;font-weight:600;">Fear & Greed: {fg['label']}</div>
          <div style="color:#777;font-size:12px;">{'▲' if delta>=0 else '▼'} {abs(delta)} from yesterday</div></div></div>"""

    sig_html = ""
    for coin, sig in [("₿ BTC", sig_btc), ("Ξ ETH", sig_eth)]:
        if sig:
            sig_html += f"""<div style="margin-bottom:16px;">
              <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:8px;">{coin} SIGNALS</div>
              <table style="width:100%;border-collapse:collapse;"><tr>
                {_signal_card("SHORT-TERM (4h)", sig['short'])}
                {_signal_card("MID-TERM (daily)", sig['mid'])}
              </tr></table></div>"""

    ai_html = ""
    if ai:
        col = "#10b981" if ai["sentiment"]=="bullish" else("#ef4444" if ai["sentiment"]=="bearish" else"#9ca3af")
        bg  = "#0d2b1e" if ai["sentiment"]=="bullish" else("#2b0d0d" if ai["sentiment"]=="bearish" else"#1a1a2e")
        themes = " ".join([f'<span style="background:#2d2d4e;color:#a78bfa;font-size:11px;padding:2px 8px;border-radius:4px;">{t}</span>' for t in ai.get("key_themes",[])])
```
```python
        ai_html = f"""<div style="background:{bg};border:1px solid {col}44;border-radius:10px;padding:16px;margin-bottom:20px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <div style="color:#888;font-size:11px;letter-spacing:2px;">AI ANALYSIS</div>
            <span style="color:{col};font-size:12px;font-weight:700;text-transform:uppercase;">{ai['sentiment']} ({ai['sentiment_score']:+d})</span>
          </div>
          <div style="margin-bottom:10px;">{themes}</div>
          <table style="width:100%;font-size:12px;border-collapse:collapse;">
            <tr><td style="color:#888;padding:3px 0;width:120px;">Short:</td><td style="color:#ddd;">{ai.get('short_term_outlook','')}</td></tr>
            <tr><td style="color:#888;padding:3px 0;">Mid:</td><td style="color:#ddd;">{ai.get('mid_term_outlook','')}</td></tr>
            <tr><td style="color:#ef4444;padding:3px 0;">Risk:</td><td style="color:#ddd;">{ai.get('key_risk','')}</td></tr>
            <tr><td style="color:#10b981;padding:3px 0;">Catalyst:</td><td style="color:#ddd;">{ai.get('key_catalyst','')}</td></tr>
          </table></div>"""

    news_html = ""
    if news:
        items = "".join([f"""<tr><td style="padding:8px 0;border-bottom:1px solid #2d2d4e;">
          <a href="{n['link']}" style="color:#a78bfa;text-decoration:none;font-size:13px;">{n['title']}</a>
          <div style="color:#555;font-size:11px;">{n['source']}</div></td></tr>""" for n in news[:6]])
        news_html = f"""<div style="background:#16162a;border:1px solid #2d2d4e;border-radius:10px;padding:16px;margin-bottom:20px;">
          <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:12px;">📰 Latest News</div>
          <table style="width:100%;border-collapse:collapse;">{items}</table></div>"""

    whale_html = ""
    if whales:
        items = "".join([f"""<tr><td style="padding:6px 0;border-bottom:1px solid #2d2d4e;font-size:12px;">
          <span style="color:#fbbf24;font-weight:700;">{w['symbol']}</span>
          <span style="color:#fff;"> {fmt(w['amount_usd'])} </span>
          <span style="color:#777;">{w['from']} → {w['to']} ({w['chain']})</span></td></tr>""" for w in whales])
        whale_html = f"""<div style="background:#16162a;border:1px solid #2d2d4e;border-radius:10px;padding:16px;margin-bottom:20px;">
          <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:12px;">🐋 WHALE MOVEMENTS</div>
          <table style="width:100%;border-collapse:collapse;">{items}</table></div>"""

    mode_badge = f'<span style="background:#2d2d4e;color:#a78bfa;font-size:10px;padding:2px 8px;border-radius:4px;">{mode.upper()}</span>'

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0d0d1a;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">
  <div style="text-align:center;margin-bottom:24px;">
    <div style="color:#a78bfa;font-size:11px;letter-spacing:3px;margin-bottom:6px;">CRYPTO SIGNAL BRIEF {mode_badge}</div>
    <div style="color:#555;font-size:12px;">{now}</div>
  </div>
  {prices_html}{fg_html}{sig_html}{ai_html}{news_html}{whale_html}
  <div style="text-align:center;color:#444;font-size:11px;margin-top:12px;">
    CoinGecko · Binance · Alternative.me · CryptoPanic · Claude AI<br>⚠️ Not investment advice
  </div>
</div></body></html>"""


def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())


# ──────────────────── Main runners ────────────────────

TRADING_PAIRS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","ADAUSDT","DOGEUSDT","XRPUSDT"]

def _scan_all_pairs(fg_val: int) -> dict:
    """Fetch OHLCV and calculate signals for all pairs"""
    all_signals = {}
    for pair in TRADING_PAIRS:
        closes_d  = get_ohlcv_binance(pair, "1d", 200)
        closes_4h = get_ohlcv_binance(pair, "4h", 100)
        if closes_d:
            all_signals[pair] = get_signals_from_closes(closes_d, closes_4h, fg_val)
            print(f"  [{pair}] short={all_signals[pair]['short']['action']}({all_signals[pair]['short']['confidence']}%) mid={all_signals[pair]['mid']['action']}({all_signals[pair]['mid']['confidence']}%)")
    return all_signals


def run_lite():
    """Every 1h — Check prices + indicators for all 7 pairs without calling Claude without sending email"""
    print(f"[{datetime.now().strftime('%H:%M')}] LITE check...")
    prices = get_prices()
    fg     = get_fear_greed()

    all_signals = {}
    if prices:
        fg_val      = fg["value"] if fg else 50
        all_signals = _scan_all_pairs(fg_val)

    sig_btc = all_signals.get("BTCUSDT")
    sig_eth = all_signals.get("ETHUSDT")

    sig = write_signal(sig_btc, sig_eth, fg, ai=None, mode="lite", all_signals=all_signals)
    print(f"[lite] {'STOP' if sig['should_stop_bot'] else 'RUN'} | F&G={sig['fg_value']}")


def run_full():
    """3 times per day — Run everything + Claude + email"""
    print(f"[{datetime.now().strftime('%H:%M')}] FULL check...")
    prices = get_prices()
    fg     = get_fear_greed()
    news   = get_news()
    whales = get_whale_alerts()

    all_signals = {}
    if prices:
        fg_val      = fg["value"] if fg else 50
        all_signals = _scan_all_pairs(fg_val)
```
```python
    sig_btc = all_signals.get("BTCUSDT")
    sig_eth = all_signals.get("ETHUSDT")

    ai = None
    if prices:
        ai = analyze_with_claude(
            news,
            prices["btc"]["price"],
            prices["eth"]["price"],
            fg["value"] if fg else 50,
        )

    write_signal(sig_btc, sig_eth, fg, ai, mode="full", all_signals=all_signals)

    # Build subject
    parts = ["🔔 Crypto Signal"]
    if sig_btc: parts.append(f"BTC {sig_btc['short']['action']}/{sig_btc['mid']['action']}")
    if sig_eth: parts.append(f"ETH {sig_eth['short']['action']}/{sig_eth['mid']['action']}")
    if ai:      parts.append(f"AI:{ai['sentiment']}")
    subject = " | ".join(parts)

    html = build_email(prices, fg, sig_btc, sig_eth, news, whales, ai, "full")
    send_email(subject, html)
    print(f"[full] Email sent: {subject}")


if __name__ == "__main__":
    # Test run full mode directly
    run_full()
```