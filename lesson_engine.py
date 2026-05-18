# ============================================================
# lesson_engine.py — AI Learning System (Analytical, not fearful)
#
# Philosophy: Learn from mistakes, not fear them
# Send context for Sonnet to analyze, not avoid
# ============================================================

import json
import logging
from datetime import datetime
from pathlib import Path
import anthropic
from config import ANTHROPIC_API_KEY

logger = logging.getLogger("ProTradingBot")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

LESSONS_FILE = Path("lessons.json")
MAX_LESSONS  = 50
MATCH_BONUS  = 2   # Display maximum 2 lessons

# ──────────────────── System prompts ────────────────────

LEARN_SYSTEM = (
    'Crypto trade analyst. A losing trade just closed. '
    'Extract what the market was doing — not what went wrong. '
    'JSON only: {"pattern":"<15words: indicator state at entry>", '
    '"rsi_min":0,"rsi_max":100,"vol_min":0.0,"vol_max":99.0,'
    '"bb_min":0,"bb_max":100,'
    '"context":"<12words: what market condition caused this>",'
    '"insight":"<12words: what signal to watch next time>"} '
    'Tone: curious analyst, not blame. Focus on market behavior.'
)


# ──────────────────── File I/O ────────────────────

def _load_lessons() -> list:
    if not LESSONS_FILE.exists():
        return []
    try:
        return json.loads(LESSONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_lessons(lessons: list):
    lessons = lessons[-MAX_LESSONS:]
    LESSONS_FILE.write_text(
        json.dumps(lessons, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


# ──────────────────── Learn from losing trade ────────────────────

def learn_from_loss(symbol: str, trade: dict, indicators: dict) -> dict | None:
    """
    Use Haiku to analyze market condition at the time of loss
    Record as context not warning
    """
    reason = trade.get("reason", "")
    if reason not in ("SL", "TRAIL_SL"):
        return None

    pnl   = trade.get("pnl_pct", 0)
    entry = trade.get("entry_price", 0)
    exit_ = trade.get("exit_price", 0)
    rsi   = indicators.get("rsi", 50)
    vol   = indicators.get("volume_ratio", 1.0)
    bb    = indicators.get("bb_pct", 50)
    macd  = indicators.get("macd_hist", 0)
    atr   = indicators.get("atr", 0)

    prompt = (
        f"{symbol} {reason} pnl={pnl:+.2f}% | "
        f"entry={entry:.4g} exit={exit_:.4g} | "
        f"RSI={rsi:.1f} Vol={vol:.1f}x BB={bb:.1f}% "
        f"MACD={macd:.4f} ATR={atr:.4f}"
    )

    try:
        r = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=LEARN_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = r.content[0].text.strip()
        raw = raw.replace("```json","").replace("```","").strip()
        if not raw.endswith("}"): raw = raw[:raw.rfind("}")+1]
        d = json.loads(raw)

        lesson = {
            "id":       datetime.now().strftime("%Y%m%d_%H%M%S"),
            "symbol":   symbol,
            "reason":   reason,
            "pnl_pct":  round(pnl, 2),
            "pattern":  d.get("pattern", ""),
            "context":  d.get("context", ""),
            "insight":  d.get("insight", ""),
            "rsi_min":  float(d.get("rsi_min", max(0, rsi-15))),
            "rsi_max":  float(d.get("rsi_max", min(100, rsi+15))),
            "vol_min":  float(d.get("vol_min", max(0, vol-0.5))),
            "vol_max":  float(d.get("vol_max", vol+0.5)),
            "bb_min":   float(d.get("bb_min",  max(0, bb-15))),
            "bb_max":   float(d.get("bb_max",  min(100, bb+15))),
            "count":    1,
            "wins_after": 0,   # next trade with similar setup won or not
            "date":     datetime.now().isoformat(),
            "snapshot": {
                "rsi": round(rsi, 1),
                "vol": round(vol, 2),
                "bb":  round(bb, 1),
            }
        }

        # Dedup — if same pattern, increment count
        lessons = _load_lessons()
        matched = False
        for ex in lessons:
            if ex["symbol"] == symbol and ex["pattern"] == lesson["pattern"]:
                ex["count"] += 1
                ex["date"]   = lesson["date"]
                matched = True
                break

        if not matched:
            lessons.append(lesson)

        _save_lessons(lessons)
        logger.info(
            f"[LEARN] {symbol} {reason} | "
            f"context='{lesson['context']}' | "
            f"insight='{lesson['insight']}'"
        )
        return lesson

    except Exception as e:
        logger.warning(f"[LEARN] {symbol}: {e}")
        return None


def update_lesson_outcome(symbol: str, won: bool):
    """
    Update whether next trade after lesson won or lost
    Track whether this lesson actually helped
    """
    lessons = _load_lessons()
    for l in lessons:
        if l["symbol"] == symbol and l.get("pending_outcome"):
            l["wins_after"] = l.get("wins_after", 0) + (1 if won else 0)
            l["pending_outcome"] = False
            break
    _save_lessons(lessons)


# ──────────────────── Get analytical context for Sonnet ────────────────────

def get_relevant_lessons(symbol: str, indicators: dict) -> str:
    """
    Retrieve matching lessons as analytical context
    Not a warning — let Sonnet analyze if situation is similar or different
    """
    lessons = _load_lessons()
    if not lessons:
        return ""

    rsi = indicators.get("rsi", 50)
    vol = indicators.get("volume_ratio", 1.0)
    bb  = indicators.get("bb_pct", 50)

    sym_lessons = [l for l in lessons if l["symbol"] == symbol]
```python
if not sym_lessons:
    return ""

    # Find lesson that matches
    matched = []
    for l in sym_lessons:
        rsi_match = l["rsi_min"] <= rsi <= l["rsi_max"]
        vol_match = l["vol_min"] <= vol <= l["vol_max"]
        bb_match  = l["bb_min"]  <= bb  <= l["bb_max"]
        match_score = sum([rsi_match, vol_match, bb_match])

        if match_score >= 2:
            matched.append({**l, "match_score": match_score})

    if not matched:
        return ""

    matched.sort(key=lambda x: x["match_score"] + x.get("count", 1),
                 reverse=True)
    top = matched[:MATCH_BONUS]

    # ──────────────────── Analytical context ────────────────────
    # Tell Sonnet what happened before, let it analyze if different
    parts = []
    for l in top:
        prev_rsi = l["snapshot"].get("rsi", "?")
        prev_vol = l["snapshot"].get("vol", "?")
        prev_bb  = l["snapshot"].get("bb", "?")

        parts.append(
            f"[PAST x{l.get('count',1)}] "
            f"setup: RSI={prev_rsi} vol={prev_vol}x BB={prev_bb}% → {l['reason']} {l['pnl_pct']:+.1f}% | "
            f"context: {l['context']} | "
            f"insight: {l['insight']} | "
            f"NOW: RSI={rsi:.1f} vol={vol:.1f}x BB={bb:.1f}% — "
            f"same setup or different this time?"
        )

    result = "LEARNING CONTEXT: " + " || ".join(parts)
    logger.info(
        f"[LEARN] {symbol} matched {len(matched)} lessons → Sonnet analyzes"
    )
    return result


def has_past_losses(symbol: str) -> bool:
    lessons = _load_lessons()
    return any(l["symbol"] == symbol for l in lessons)


# ──────────────────── Summary ────────────────────

def log_lesson_summary():
    lessons = _load_lessons()
    if not lessons:
        return

    by_symbol = {}
    for l in lessons:
        s = l["symbol"]
        if s not in by_symbol:
            by_symbol[s] = {"count": 0, "patterns": set()}
        by_symbol[s]["count"]    += l.get("count", 1)
        by_symbol[s]["patterns"].add(l.get("pattern", "")[:30])

    logger.info("── Learning Summary ─────────────────────────")
    for sym, data in sorted(by_symbol.items(),
                            key=lambda x: x[1]["count"], reverse=True):
        logger.info(
            f"  {sym:<12} losses={data['count']:>3} "
            f"patterns={len(data['patterns'])}"
        )
    logger.info("─────────────────────────────────────────────")

import json
import logging
from datetime import datetime
from pathlib import Path
import anthropic
from config import ANTHROPIC_API_KEY

logger  = logging.getLogger("ProTradingBot")
client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

LESSONS_FILE   = Path("lessons.json")
MAX_LESSONS    = 50   # Store maximum 50 lessons
MATCH_BONUS    = 3    # If pattern matches → show how many lessons maximum

# ──────────────────── System prompts ────────────────────

LEARN_SYSTEM = (
    'Crypto trading pattern analyst. A losing trade just closed. '
    'Identify the technical pattern that caused the loss. '
    'JSON only: {"pattern":"<15words describing indicator combo>", '
    '"rsi_min":0,"rsi_max":100,"vol_min":0.0,"vol_max":99.0,'
    '"bb_min":0,"bb_max":100,'
    '"lesson":"<10words what to avoid>","severity":1-3} '
    'severity: 1=minor 2=moderate 3=avoid this setup entirely. '
    'Focus on indicators, not price action. Be specific.'
)

# ──────────────────── File I/O ────────────────────

def _load_lessons() -> list:
    if not LESSONS_FILE.exists():
        return []
    try:
        return json.loads(LESSONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_lessons(lessons: list):
    # Keep only the latest MAX_LESSONS items
    lessons = lessons[-MAX_LESSONS:]
    LESSONS_FILE.write_text(
        json.dumps(lessons, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


# ──────────────────── Learn from losing trade ────────────────────

def learn_from_loss(symbol: str, trade: dict, indicators: dict) -> dict | None:
    """
    Call Sonnet to analyze the pattern of a losing trade
    Save lesson in lessons.json
    Call only when SL or TRAIL_SL is hit
    """
    reason = trade.get("reason", "")
    if reason not in ("SL", "TRAIL_SL"):
        return None   # Don't learn from TP

    pnl    = trade.get("pnl_pct", 0)
    entry  = trade.get("entry_price", 0)
    exit_  = trade.get("exit_price", 0)
    rsi    = indicators.get("rsi", 50)
    vol    = indicators.get("volume_ratio", 1.0)
    bb     = indicators.get("bb_pct", 50)
    macd   = indicators.get("macd_hist", 0)
    atr    = indicators.get("atr", 0)

    prompt = (
        f"{symbol} {reason} | pnl={pnl:+.2f}% | "
        f"entry={entry:.4g} exit={exit_:.4g} | "
        f"RSI={rsi:.1f} Vol={vol:.1f}x BB={bb:.1f}% "
        f"MACD={macd:.4f} ATR={atr:.4f}"
    )

    try:
        r = client.messages.create(
            model="claude-haiku-4-5-20251001",   # Use Haiku to save tokens
            max_tokens=150,
            system=LEARN_SYSTEM,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = r.content[0].text.strip()
        raw = raw.replace("```json","").replace("```","").strip()
        if not raw.endswith("}"): raw = raw[:raw.rfind("}")+1]
        d = json.loads(raw)

        lesson = {
            "id":        datetime.now().strftime("%Y%m%d_%H%M%S"),
            "symbol":    symbol,
            "reason":    reason,
            "pnl_pct":   round(pnl, 2),
            "pattern":   d.get("pattern", ""),
            "lesson":    d.get("lesson", ""),
            "severity":  int(d.get("severity", 1)),
            "rsi_min":   float(d.get("rsi_min", 0)),
            "rsi_max":   float(d.get("rsi_max", 100)),
```
```python
            "vol_min":   float(d.get("vol_min", 0)),
            "vol_max":   float(d.get("vol_max", 99)),
            "bb_min":    float(d.get("bb_min", 0)),
            "bb_max":    float(d.get("bb_max", 100)),
            "count":     1,
            "date":      datetime.now().isoformat(),
            "indicators_snapshot": {
                "rsi": round(rsi, 1),
                "vol": round(vol, 2),
                "bb":  round(bb, 1),
            }
        }

        # Check if this pattern already exists (dedup)
        lessons = _load_lessons()
        matched = False
        for existing in lessons:
            if (existing["symbol"] == symbol and
                    existing["pattern"] == lesson["pattern"]):
                existing["count"] += 1
                existing["date"]   = lesson["date"]
                matched = True
                break

        if not matched:
            lessons.append(lesson)

        _save_lessons(lessons)
        logger.info(
            f"[LESSON] {symbol} {reason} | "
            f"pattern='{lesson['pattern']}' "
            f"severity={lesson['severity']}"
        )
        return lesson

    except Exception as e:
        logger.warning(f"[LESSON] learn_from_loss {symbol}: {e}")
        return None


# ──────────────────── Match lessons for upcoming buy ────────────────────

def get_relevant_lessons(symbol: str, indicators: dict) -> str:
    """
    Fetch lessons that match current indicators
    Return string to send to Sonnet

    Call only when buying a coin that has lost before
    """
    lessons = _load_lessons()
    if not lessons:
        return ""

    rsi = indicators.get("rsi", 50)
    vol = indicators.get("volume_ratio", 1.0)
    bb  = indicators.get("bb_pct", 50)

    # Filter only lessons of this symbol
    sym_lessons = [l for l in lessons if l["symbol"] == symbol]
    if not sym_lessons:
        return ""

    # Find lessons where pattern matches current indicators
    matched = []
    for l in sym_lessons:
        rsi_match = l["rsi_min"] <= rsi <= l["rsi_max"]
        vol_match = l["vol_min"] <= vol <= l["vol_max"]
        bb_match  = l["bb_min"]  <= bb  <= l["bb_max"]

        # Must match at least 2 out of 3
        match_count = sum([rsi_match, vol_match, bb_match])
        if match_count >= 2:
            matched.append({
                **l,
                "match_score": match_count + l.get("severity", 1),
            })

    if not matched:
        return ""

    # Sort by severity + match_score
    matched.sort(key=lambda x: x["match_score"] + x.get("count", 1),
                 reverse=True)
    top = matched[:MATCH_BONUS]

    # Create warning string for Sonnet
    warnings = []
    for l in top:
        warnings.append(
            f"[PAST LOSS x{l.get('count',1)}] "
            f"pattern='{l['pattern']}' | "
            f"lesson='{l['lesson']}' | "
            f"severity={l['severity']}"
        )

    result = "HISTORICAL WARNINGS: " + " | ".join(warnings)
    logger.info(f"[LESSON] {symbol} matched {len(matched)} lessons → sending to Sonnet")
    return result


# ──────────────────── Check if symbol has past losses ────────────────────

def has_past_losses(symbol: str) -> bool:
    """Check if this coin has past losses — used to decide whether to send lesson"""
    lessons = _load_lessons()
    return any(l["symbol"] == symbol for l in lessons)


# ──────────────────── Summary log ────────────────────

def log_lesson_summary():
    """Display summary of all lessons"""
    lessons = _load_lessons()
    if not lessons:
        return

    # Count by symbol
    by_symbol = {}
    for l in lessons:
        s = l["symbol"]
        if s not in by_symbol:
            by_symbol[s] = {"count": 0, "severity_sum": 0}
        by_symbol[s]["count"]        += l.get("count", 1)
        by_symbol[s]["severity_sum"] += l.get("severity", 1)

    logger.info("── Lesson Summary ───────────────────────────")
    for sym, data in sorted(by_symbol.items(),
                            key=lambda x: x[1]["severity_sum"], reverse=True):
        avg_sev = data["severity_sum"] / max(data["count"], 1)
        logger.info(
            f"  {sym:<12} losses={data['count']:>3} "
            f"avg_severity={avg_sev:.1f}"
        )
    logger.info("─────────────────────────────────────────────")
```