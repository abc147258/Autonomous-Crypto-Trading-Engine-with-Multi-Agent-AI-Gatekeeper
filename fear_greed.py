# ============================================================
# fear_greed.py — Crypto Fear & Greed Index
# ============================================================

import requests
import logging

logger = logging.getLogger("ProTradingBot")

# ──────────────────── Thresholds (Based on config.py) ────────────────────
EXTREME_FEAR_THRESHOLD  = 15   # <= 15 → Stop bot (from 25)
FEAR_THRESHOLD          = 35   # <= 35 → Caution
GREED_THRESHOLD         = 70   # >= 70 → Caution
EXTREME_GREED_THRESHOLD = 85   # >= 85 → TP faster

_cache = {"ts": 0, "data": None}
CACHE_TTL = 3600  # 1 hour


def get_fear_greed() -> dict:
    """
    Fetch Fear & Greed Index from alternative.me
    Free, no API key required
    Return dict:
      value      : 0-100
      label      : Extreme Fear / Fear / Neutral / Greed / Extreme Greed
      should_buy : bool — Should buy?
      tp_mult    : float — Adjust TP
      sl_mult    : float — Adjust SL
    """
    import time
    now = time.time()

    # Use cache if not expired
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    try:
        r    = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=5,
        )
        data = r.json()["data"][0]
        val  = int(data["value"])
        lbl  = data["value_classification"]

        # Make decision based on index
        if val <= EXTREME_FEAR_THRESHOLD:
            # Extreme Fear — Stop entire bot
            should_buy = False
            tp_mult    = 0.7
            sl_mult    = 0.8
            advice     = "🚨 EXTREME FEAR — Stop new positions"

        elif val <= FEAR_THRESHOLD:
            # Fear — Can trade but be cautious
            should_buy = True
            tp_mult    = 0.85
            sl_mult    = 0.9
            advice     = "😨 FEAR — Trade cautiously, shorter TP"

        elif val >= EXTREME_GREED_THRESHOLD:
            # Extreme Greed — TP fast, possible correction ahead
            should_buy = True
            tp_mult    = 0.8
            sl_mult    = 1.0
            advice     = "🤑 EXTREME GREED — TP fast, watch for correction"

        elif val >= GREED_THRESHOLD:
            # Greed — market good but start being cautious
            should_buy = True
            tp_mult    = 0.9
            sl_mult    = 1.0
            advice     = "😏 GREED — Good market but start being cautious"

        else:
            # Neutral — trade normally
            should_buy = True
            tp_mult    = 1.0
            sl_mult    = 1.0
            advice     = "😐 NEUTRAL — Normal market"

        result = {
            "value":      val,
            "label":      lbl,
            "should_buy": should_buy,
            "tp_mult":    tp_mult,
            "sl_mult":    sl_mult,
            "advice":     advice,
        }

        _cache["ts"]   = now
        _cache["data"] = result

        logger.info(f"[F&G] {val}/100 — {advice}")
        return result

    except Exception as e:
        logger.warning(f"[F&G] Unable to fetch data: {e} — Using default value")
        return {
            "value":      50,
            "label":      "Neutral",
            "should_buy": True,
            "tp_mult":    1.0,
            "sl_mult":    1.0,
            "advice":     "NEUTRAL (fallback)",
        }