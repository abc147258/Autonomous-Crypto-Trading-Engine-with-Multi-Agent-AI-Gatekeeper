# ============================================================
# signal_writer.py — Write signal.json (shared state)
# Called from notifier in both lite and full mode
# ============================================================

import json
from datetime import datetime
from pathlib import Path
from config import (
    DEAD_VOL_CONFIDENCE_THRESHOLD,
    EXTREME_FEAR_THRESHOLD,
    AI_BEARISH_THRESHOLD,
    BUY_SIGNAL_MIN_CONFIDENCE,
)

SIGNAL_FILE = Path("signal.json")


def write_signal(
    sig_btc: dict | None,
    sig_eth: dict | None,
    fg: dict | None,
    ai: dict | None = None,
    mode: str = "lite",
    all_signals: dict = None,
):
    """
    Analyze combined results and write signal.json
    bot_controller.py reads this file every 60 seconds
    """
    now = datetime.now().isoformat()

    # ──────────────────── Dead Vol ────────────────────
    def is_dead(sig):
        if not sig:
            return True
        return (
            sig["short"]["action"] == "HOLD"
            and sig["mid"]["action"] == "HOLD"
            and sig["short"]["confidence"] < DEAD_VOL_CONFIDENCE_THRESHOLD
            and sig["mid"]["confidence"] < DEAD_VOL_CONFIDENCE_THRESHOLD
        )

    market_dead  = is_dead(sig_btc) and is_dead(sig_eth)
    extreme_fear = bool(fg and fg["value"] <= EXTREME_FEAR_THRESHOLD)
    ai_bearish   = bool(
        ai
        and ai.get("sentiment") == "bearish"
        and ai.get("sentiment_score", 0) < AI_BEARISH_THRESHOLD
    )

    should_stop = market_dead or extreme_fear or ai_bearish

    stop_reasons = []
    if market_dead:  stop_reasons.append("dead_vol")
    if extreme_fear: stop_reasons.append(f"extreme_fear(fg={fg['value']})")
    if ai_bearish:   stop_reasons.append(f"ai_bearish(score={ai.get('sentiment_score',0)})")

    # ──────────────────── Buy Signals ────────────────────
    buy_signals = []
    for coin, sig in [("BTC", sig_btc), ("ETH", sig_eth)]:
        if not sig:
            continue
        for tf in ["short", "mid"]:
            if (sig[tf]["action"] == "BUY"
                    and sig[tf]["confidence"] >= BUY_SIGNAL_MIN_CONFIDENCE):
                buy_signals.append(f"{coin}_{tf}(conf={sig[tf]['confidence']}%)")

    has_buy_signal = bool(buy_signals)

    data = {
        "updated_at":      now,
        "mode":            mode,
        "should_stop_bot": should_stop,
        "should_run_bot":  not should_stop,
        "stop_reasons":    stop_reasons,
        "market_dead":     market_dead,
        "extreme_fear":    extreme_fear,
        "ai_bearish":      ai_bearish,
        "has_buy_signal":  has_buy_signal,
        "buy_signals":     buy_signals,
        "fg_value":        fg["value"] if fg else None,
        "fg_label":        fg["label"] if fg else None,
        "ai_sentiment":    ai.get("sentiment")       if ai else None,
        "ai_score":        ai.get("sentiment_score") if ai else None,
        "btc_short":       sig_btc["short"] if sig_btc else None,
        "btc_mid":         sig_btc["mid"]   if sig_btc else None,
        "eth_short":       sig_eth["short"] if sig_eth else None,
        "eth_mid":         sig_eth["mid"]   if sig_eth else None,
        "all_signals":     all_signals or {},
    }

    SIGNAL_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    status = "STOP" if should_stop else ("BUY" if has_buy_signal else "HOLD/RUN")
    print(f"[signal] {mode.upper()} → {status} | {stop_reasons or buy_signals or ['neutral']}")
    return data