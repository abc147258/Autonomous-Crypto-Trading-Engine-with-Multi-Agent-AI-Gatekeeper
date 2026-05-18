"""
signals.py — Rule-based signal scoring (Enhanced v2)

Used together with Sonnet:
  1. Analyze indicators comprehensively
  2. Send signal summary to Sonnet for clearer context
  3. Sonnet can make better BUY/SELL/HOLD decisions
"""
from config import RSI_OVERSOLD, RSI_OVERBOUGHT, FEAR_GREED_BUY, FEAR_GREED_SELL

DEFAULT_WEIGHTS = {
    "rsi":        1.0,
    "macd":       1.0,
    "ma":         1.0,
    "bollinger":  1.0,
    "fear_greed": 1.0,
    "volume":     0.5,
    "ema_trend":  1.5,
    "ma200":      2.0,
    "atr_regime": 0.5,
    "vol_spike":  1.5,
}
SCORE_KEYS = ["rsi","macd","ma","bollinger","fear_greed",
              "volume","ema_trend","ma200","atr_regime","vol_spike"]


def score_rsi(rsi) -> tuple:
    if rsi is None: return 0, "N/A"
    if rsi < RSI_OVERSOLD:
        return 1, f"RSI {rsi:.0f} oversold"
    if rsi > RSI_OVERBOUGHT:
        return -1, f"RSI {rsi:.0f} overbought"
    return 0, f"RSI {rsi:.0f} neutral"


def score_macd(macd, signal, histogram) -> tuple:
    if macd is None or signal is None: return 0, "N/A"
    if macd > signal and histogram and histogram > 0:
        return 1, f"MACD bullish"
    if macd < signal and histogram and histogram < 0:
        return -1, f"MACD bearish"
    return 0, "MACD neutral"


def score_ma(price, ma50, ma200) -> tuple:
    if ma50 is None or ma200 is None: return 0, "N/A"
    if ma50 > ma200 and price > ma50:
        return 1, "Price>MA50>MA200 uptrend"
    if ma50 < ma200 and price < ma50:
        return -1, "Price<MA50<MA200 downtrend"
    if price > ma200:
        return 0, "Above MA200 mixed"
    return -1, "Below MA200 bearish"


def score_bollinger(price, bb_upper, bb_lower, bb_mid) -> tuple:
    if bb_upper is None or bb_lower is None: return 0, "N/A"
    bw = bb_upper - bb_lower
    if bw == 0: return 0, "N/A"
    pos = (price - bb_lower) / bw
    if pos < 0.15: return 1, f"Near lower BB oversold"
    if pos > 0.85: return -1, f"Near upper BB overbought"
    return 0, f"Inside BB neutral"


def score_fear_greed(fg_value) -> tuple:
    if fg_value is None: return 0, "N/A"
    if fg_value <= FEAR_GREED_BUY:
        return 1, f"F&G {fg_value} Extreme Fear buy zone"
    if fg_value >= FEAR_GREED_SELL:
        return -1, f"F&G {fg_value} Extreme Greed sell zone"
    if fg_value < 40: return 0.5, f"F&G {fg_value} Fear slightly bullish"
    if fg_value > 60: return -0.5, f"F&G {fg_value} Greed slightly bearish"
    return 0, f"F&G {fg_value} Neutral"


def score_volume(vol_ratio) -> tuple:
    if vol_ratio is None: return 0, "N/A"
    if vol_ratio > 1.5: return 0.5, f"Vol {vol_ratio:.1f}x high"
    if vol_ratio < 0.5: return -0.5, f"Vol {vol_ratio:.1f}x dead"
    return 0, f"Vol {vol_ratio:.1f}x normal"


def score_ema_trend(ema9_above_21: bool, ema21_above_50: bool,
                    price: float, ma50) -> tuple:
    if ma50 is None: return 0, "N/A"
    if ema9_above_21 and ema21_above_50 and price > ma50:
        return 1.5, "EMA 9>21>50 strong uptrend"
    if ema9_above_21 and ema21_above_50:
        return 1.0, "EMA 9>21>50 uptrend"
    if not ema9_above_21 and not ema21_above_50 and price < ma50:
        return -1.5, "EMA 9<21<50 strong downtrend"
    if not ema9_above_21 and not ema21_above_50:
        return -1.0, "EMA 9<21<50 downtrend"
    return 0, "EMA mixed neutral"


def score_ma200_trend(price: float, ma200) -> tuple:
    if ma200 is None: return 0, "N/A"
    dist = (price - ma200) / ma200 * 100
    if dist > 10:  return  1.0, f"Price {dist:.1f}% above MA200 strong bull"
    if dist > 0:   return  0.5, f"Price {dist:.1f}% above MA200 bull"
    if dist < -10: return -2.0, f"Price {dist:.1f}% below MA200 strong bear"
    return -1.0, f"Price {dist:.1f}% below MA200 bear"


def score_atr_regime(atr: float, price: float) -> tuple:
    if atr <= 0 or price <= 0: return 0, "N/A"
    atr_pct = atr / price * 100
    if atr_pct > 4.0: return 0, f"ATR={atr_pct:.1f}% HIGH_VOL"
    if atr_pct > 2.0: return 0.5, f"ATR={atr_pct:.1f}% NORMAL_VOL"
    return 0, f"ATR={atr_pct:.1f}% LOW_VOL"


def score_volume_spike(volume_ratio: float,
                       price_change_pct: float = 0) -> tuple:
    if volume_ratio is None: return 0, "N/A"
    if volume_ratio >= 3.0 and price_change_pct > 1.0:
        return 2.0, f"Vol {volume_ratio:.1f}x + +{price_change_pct:.1f}% strong momentum"
    if volume_ratio >= 3.0 and price_change_pct < -1.0:
        return -2.0, f"Vol {volume_ratio:.1f}x + {price_change_pct:.1f}% distribution"
    if volume_ratio >= 2.0: return 1.0, f"Vol {volume_ratio:.1f}x elevated"
    if volume_ratio >= 1.5: return 0.5, f"Vol {volume_ratio:.1f}x above avg"
    if volume_ratio < 0.5:  return -0.5, f"Vol {volume_ratio:.1f}x dead"
    return 0, f"Vol {volume_ratio:.1f}x normal"


def get_weights(symbol: str | None = None) -> dict:
    weights = DEFAULT_WEIGHTS.copy()
    if symbol is None: return weights
    try:
        import json
        from pathlib import Path
        f = Path("lessons.json")
        if not f.exists(): return weights
        lessons = json.loads(f.read_text(encoding="utf-8"))
        sl = [l for l in lessons if l.get("symbol") == symbol]
        if not sl: return weights
        for key, word in [("rsi","rsi"),("macd","macd"),("volume","vol")]:
            n = sum(l.get("count",1) for l in sl if word in l.get("pattern","").lower())
            if n >= 3:
                weights[key] = max(0.3, weights[key] - n*0.1)
    except Exception:
        pass
    return weights


def aggregate_score(score_list: list, weights: dict | None = None) -> tuple:
    w = weights or DEFAULT_WEIGHTS
    total = max_w = 0.0
    for i, (score, _) in enumerate(score_list):
        key    = SCORE_KEYS[i] if i < len(SCORE_KEYS) else "rsi"
        weight = w.get(key, 1.0)
        total  += score * weight
        max_w  += abs(weight)
    conf = round(abs(total)/max_w*100) if max_w else 0
    if total >= 2.0:   action = "BUY";  conf = min(conf+10, 95)
    elif total <= -2.0: action = "SELL"; conf = min(conf+10, 95)
    else:               action = "HOLD"
    return action, round(total, 2), conf


def get_signal_summary(scores: list, action: str,
                        score: float, conf: int) -> str:
    bull = [d for s, d in scores if s > 0 and d != "N/A"]
    bear = [d for s, d in scores if s < 0 and d != "N/A"]
    out  = [f"RULE_SIGNAL:{action}({conf}%) score={score:+.1f}"]
    if bull: out.append(f"BULL:{' | '.join(bull[:3])}")
    if bear: out.append(f"BEAR:{' | '.join(bear[:2])}")
    return " || ".join(out)


def should_call_sonnet(score: float, symbol=None,
                        vol_spike: bool = False,
                        momentum_spike: bool = False) -> bool:
    if vol_spike or momentum_spike: return True
    return abs(score) >= 1.0


def analyze_coin(ind: dict, fg_value, symbol: str | None = None) -> dict:
    price  = ind["price"]
    short  = ind.get("short", ind)
    mid    = ind.get("mid", ind)
    w      = get_weights(symbol)
    vr     = short.get("volume_ratio") or mid.get("volume_ratio") or 1.0
    pc     = ind.get("price_change_pct", 0)
    atr    = ind.get("atr", short.get("atr", 0))
    e9_21  = ind.get("ema9_above_21", True)
    e21_50 = ind.get("ema21_above_50", True)
    ma50v  = short.get("ma50") or mid.get("ma50")
    ma200v = short.get("ma200") or mid.get("ma200")

    def build(tf):
        return [
            score_rsi(tf.get("rsi")),
            score_macd(tf.get("macd"), tf.get("macd_signal"), tf.get("macd_hist")),
            score_ma(price, tf.get("ma50") or ma50v, tf.get("ma200") or ma200v),
            score_bollinger(price, tf.get("bb_upper"), tf.get("bb_lower"), tf.get("bb_mid")),
            score_fear_greed(fg_value),
            score_volume(tf.get("volume_ratio") or vr),
            score_ema_trend(e9_21, e21_50, price, ma50v),
            score_ma200_trend(price, tf.get("ma200") or ma200v),
            score_atr_regime(atr, price),
            score_volume_spike(vr, pc),
        ]

    ss = build(short); ms = build(mid)
    sa, sc, scf = aggregate_score(ss, w)
    ma, mc, mcf = aggregate_score(ms, w)

    return {
        "short": {"action":sa,"score":sc,"confidence":scf,"details":ss,
                  "summary":get_signal_summary(ss,sa,sc,scf)},
        "mid":   {"action":ma,"score":mc,"confidence":mcf,"details":ms,
                  "summary":get_signal_summary(ms,ma,mc,mcf)},
        "weights_used": w,
    }
