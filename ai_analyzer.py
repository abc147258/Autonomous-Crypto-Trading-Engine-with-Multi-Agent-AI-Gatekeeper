# ============================================================
# ai_analyzer.py — Two-stage AI Pipeline (Token Optimized)
#
# Stage 1: Haiku  → Filter news + assess sentiment (cheap, fast)
#                   Call every scan but cache 30 minutes
#
# Stage 2: Sonnet → Decide BUY/SELL/HOLD + set TP/SL
#                   Call only when Haiku says it's interesting
#                   or there's an open position
# ============================================================

import json
import time
import feedparser
import anthropic
from config import ANTHROPIC_API_KEY
from lesson_engine import get_relevant_lessons, has_past_losses
from signals import analyze_coin, should_call_sonnet, get_weights

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ──────────────────── News cache ────────────────────
_news_cache = {"ts": 0, "data": None}
NEWS_CACHE_TTL = 1800  # 30 minutes

# ──────────────────── RSS Sources ────────────────────
NEWS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://cryptopanic.com/news/rss/",
]

# ──────────────────── Haiku threshold ────────────────────
# If |news_score| >= this, it's considered interesting → Call Sonnet
NEWS_TRIGGER_SCORE = 3


# ──────────────────── Stage 1: Haiku — News Filter ────────────────────

HAIKU_SYSTEM = (
    'Crypto news analyst. JSON only, no explanation: '
    '{"sentiment":"bullish|bearish|neutral","score":-10to10,'
    '"key_events":["<5words","<5words"],"risk":"<8words",'
    '"should_analyze":true} '
    'should_analyze=true if score abs>=3 (market-moving news)'
)


def _fetch_headlines(max_items: int = 8) -> str:
    headlines = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:max_items // len(NEWS_FEEDS)]:
                headlines.append(e.get("title", "")[:80])
        except Exception:
            pass
    return " | ".join(headlines[:max_items])


def get_news_context(force: bool = False) -> dict:
    """
    Stage 1: Haiku filters news, cached 30 minutes
    Returns dict with should_analyze flag
    """
    now = time.time()

    # Use cache if not forced and not expired
    if (not force
            and _news_cache["data"]
            and (now - _news_cache["ts"]) < NEWS_CACHE_TTL):
        return _news_cache["data"]

    headlines = _fetch_headlines()
    if not headlines:
        default = {
            "ts": now, "sentiment": "neutral", "score": 0,
            "key_events": [], "risk": "no news",
            "should_analyze": False, "summary": "",
        }
        _news_cache.update({"ts": now, "data": default})
        return default

    try:
        r = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=HAIKU_SYSTEM,
            messages=[{"role": "user", "content": f"News: {headlines}"}]
        )
        raw = r.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        d   = json.loads(raw)

        result = {
            "ts":             now,
            "sentiment":      d.get("sentiment", "neutral"),
            "score":          int(d.get("score", 0)),
            "key_events":     d.get("key_events", []),
            "risk":           d.get("risk", ""),
            "should_analyze": bool(d.get("should_analyze", False)),
            "summary":        headlines[:150],
        }

    except Exception as e:
        result = {
            "ts": now, "sentiment": "neutral", "score": 0,
            "key_events": [], "risk": f"err:{str(e)[:20]}",
            "should_analyze": False, "summary": headlines[:150],
        }

    _news_cache.update({"ts": now, "data": result})
    return result


# ──────────────────── Stage 2: Sonnet — Trading Decision + Dynamic TP/SL ────────────────────

SONNET_SYSTEM = (
    'Expert crypto trader. Analyze indicators + news + ATR volatility. '
    'Return JSON only, no markdown: '
    '{"a":"BUY|SELL|HOLD","c":0-100,"r":"<10words",'
    '"tp_pct":0.0,"sl_pct":0.0,"trail_activate":0.0,"trail_distance":0.0} '
    'tp_pct/sl_pct = % from entry. '
    'trail_activate = % profit before trailing starts. '
    'trail_distance = % below peak for trailing SL. '
    'Use ATR% to calibrate: High ATR = wider TP/SL/trail. Low ATR = tighter. '
    'Sideways: tight TP(1-3x ATR). Trending: wide TP(3-5x ATR). '
    'VOLUME SPIKE (vol>=3x): momentum entry — wider TP, tighter SL, trail immediately. '
    'MOMENTUM SPIKE (price>=2%/candle): confirm trend direction first. '
    'trail_activate >= tp_pct*0.4, trail_distance >= sl_pct*0.5. '
    'BUY/SELL: all values > 0. HOLD: all 0.'
)


def analyze_symbol(
    symbol: str,
    indicators: dict,
    open_position: dict | None = None,
    news_context: dict | None = None,
) -> dict:
    """
    Stage 2: Call Sonnet only when:
    1. Haiku says it's interesting (should_analyze=True)
    2. There's an open position (must watch always)
    3. No news context → use indicators only

    Sonnet will set TP/SL % based on ATR + volatility
    """
    ind = indicators
    atr = ind.get("atr", 0)
    price = ind.get("price", 0)

    # ──────────────────── Check if should call Sonnet ────────────────────
    has_open_pos   = open_position is not None
    news_important = news_context and news_context.get("should_analyze", False)

    rsi  = ind.get("rsi", 50)
    macd = ind.get("macd_hist", 0)
    bb   = ind.get("bb_pct", 50)
    vol  = ind.get("volume_ratio", 1.0)

    # ──────────────────── signals.py pre-filter (instead of old ad-hoc checks) ────────────────────
    # Use score-based system that lesson_engine can adjust weights for
    if not has_open_pos and not news_important:

        # Calculate score from signals.py
fg_val = 50  # neutral fallback
sig_result  = analyze_coin(ind, fg_val, symbol)
short_score = sig_result["short"]["score"]
mid_score   = sig_result["mid"]["score"]
combined    = (short_score + mid_score) / 2

# Spike detection — Still present because signals.py doesn't cover
vol_spike      = vol >= 3.0
price_chg      = abs(ind.get("price_change_pct", 0))
momentum_spike = price_chg >= 2.0
bb_width       = (ind.get("bb_upper", 0) - ind.get("bb_lower", 0))
bb_mid_val     = ind.get("bb_upper", 0) - bb_width/2 if bb_width > 0 else 0
bb_squeeze     = (bb_width > 0 and bb_mid_val > 0
                  and bb_width/bb_mid_val < 0.03
                  and (bb < 15 or bb > 85))

# Decide whether to call Sonnet
call_sonnet = should_call_sonnet(
    combined, symbol, vol_spike or bb_squeeze, momentum_spike
)

if not call_sonnet:
    return {
        "symbol":         symbol,
        "action":         "HOLD",
        "confidence":     0,
        "reason":         f"signals neutral (score={combined:.1f}), skipping Sonnet",
        "tp_price":       None,
        "sl_price":       None,
        "tp_pct":         0.0,
        "sl_pct":         0.0,
        "trail_activate": 0.0,
        "trail_distance": 0.0,
        "atr_pct":        round(atr/price*100, 3) if price > 0 else 0,
        "indicators":     indicators,
        "sonnet_called":  False,
        "signal_score":   combined,
    }

# Interesting → Call Sonnet without sending news (if neutral)
if news_context is not None:
    news_context = None

# Log spike type
if vol_spike:
    pass  # Will log in prompt
elif momentum_spike:
    pass

# ──────────────────── Build prompt ────────────────────
# ATR as % of price — let Sonnet use to decide TP/SL
atr_pct = round(atr / price * 100, 3) if price > 0 else 0

lines = [
    f"{symbol} ${ind['price']:.4g} RSI={ind['rsi']:.0f}",
    f"EMA:{int(ind['ema9_above_21'])}{int(ind['ema21_above_50'])} "
    f"MACD={ind['macd_hist']:.3g} BB={ind['bb_pct']:.0f}% "
    f"Vol={ind['volume_ratio']:.1f}x ATR={atr_pct:.2f}%",
]

# ──────────────────── Send Rule-based Signal Summary to Sonnet ────────────────────
# Sonnet sees context from signals.py more clearly
try:
    from signals import analyze_coin as sig_analyze
    fg_val     = 50  # neutral fallback
    sig_result = sig_analyze(ind, fg_val, symbol)
    short_sum  = sig_result["short"]["summary"]
    mid_sum    = sig_result["mid"]["summary"]
    lines.append(f"4H_SIGNAL: {short_sum}")
    lines.append(f"MTF_SIGNAL: {mid_sum}")
except Exception:
    pass

# Add spike context if available
price_chg = ind.get("price_change_pct", 0)
if vol >= 3.0:
    lines.append(f"SPIKE: vol={vol:.1f}x avg (momentum entry)")
elif abs(price_chg) >= 2.0:
    direction = "up" if price_chg > 0 else "down"
    lines.append(f"SPIKE: price {price_chg:+.1f}% ({direction} momentum)")

# Add news context
if news_context and news_context.get("sentiment") != "neutral":
    score  = news_context.get("score", 0)
    events = ",".join(news_context.get("key_events", [])[:2])
    risk   = news_context.get("risk", "")
    lines.append(
        f"NEWS:{news_context['sentiment']}({score:+d}) "
        f"events={events} risk={risk}"
    )

# ──────────────────── Lesson Warning (only for coins with past losses) ────────────────────
if not open_position and has_past_losses(symbol):
    lesson_warning = get_relevant_lessons(symbol, ind)
    if lesson_warning:
        lines.append(lesson_warning)

# Add open position
if open_position:
    lines.append(
        f"POS pnl={open_position.get('pnl_pct', 0):.1f}% "
        f"tp={open_position['tp_price']:.4g} "
        f"sl={open_position['sl_price']:.4g}"
    )

prompt = " | ".join(lines)

# ──────────────────── Call Sonnet ────────────────────
try:
    r = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=120,
        system=SONNET_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = r.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    if not raw.endswith("}"):
        idx = raw.rfind("}")
        raw = raw[:idx + 1] if idx != -1 else raw + '"}'

    d      = json.loads(raw)
    action = d.get("a", "HOLD").upper()
    tp_pct = float(d.get("tp_pct", 0.0))
    sl_pct = float(d.get("sl_pct", 0.0))
    trail_activate  = float(d.get("trail_activate", 0.0))
    trail_distance  = float(d.get("trail_distance", 0.0))

    # ──────────────────── Validate TP/SL ────────────────────
    if action == "BUY":
        tp_pct = max(0.5, min(tp_pct, 30.0))
        sl_pct = max(0.5, min(sl_pct, 15.0))
        # TP must be at least 1.5x greater than SL
        if tp_pct < sl_pct * 1.5:
            tp_pct = sl_pct * 1.5

        # ──────────────────── Validate Trailing ────────────────────
        # trail_activate: 40-80% of TP
        if trail_activate <= 0:
            trail_activate = round(tp_pct * 0.5, 2)
        trail_activate = max(sl_pct * 0.5,
                         min(trail_activate, tp_pct * 0.8))
```python
            # trail_distance: 50-80% of SL
            if trail_distance <= 0:
                trail_distance = round(sl_pct * 0.6, 2)
            trail_distance = max(sl_pct * 0.3,
                             min(trail_distance, sl_pct * 0.9))

        else:
            tp_pct = sl_pct = trail_activate = trail_distance = 0.0

        # Calculate actual TP/SL prices
        tp_price = round(price*(1+tp_pct/100), 8) if tp_pct > 0 else None
        sl_price = round(price*(1-sl_pct/100), 8) if sl_pct > 0 else None

        return {
            "symbol":          symbol,
            "action":          action,
            "confidence":      int(d.get("c", 0)),
            "reason":          d.get("r", ""),
            "tp_price":        tp_price,
            "sl_price":        sl_price,
            "tp_pct":          tp_pct,
            "sl_pct":          sl_pct,
            "trail_activate":  trail_activate,
            "trail_distance":  trail_distance,
            "atr_pct":         atr_pct,
            "indicators":      indicators,
            "sonnet_called":   True,
        }

    except Exception as e:
        return {
            "symbol":        symbol,
            "action":        "HOLD",
            "confidence":    0,
            "reason":        f"Err:{str(e)[:30]}",
            "tp_price":      None,
            "sl_price":      None,
            "tp_pct":        0.0,
            "sl_pct":        0.0,
            "atr_pct":       atr_pct,
            "indicators":    indicators,
            "sonnet_called": True,
        }
```