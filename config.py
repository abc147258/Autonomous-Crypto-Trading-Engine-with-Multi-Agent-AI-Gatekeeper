# ============================================================
# config.py — Read all values from .env
# No API keys in this file, safe to push to GitHub
# ============================================================

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the same folder as config.py
load_dotenv(Path(__file__).parent / ".env")


def _get(key: str, default=None, cast=None):
    val = os.getenv(key, default)
    if val is None:
        return default
    if cast:
        try:
            return cast(val)
        except Exception:
            return default
    return val


# --- Binance ---
BINANCE_API_KEY     = _get("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY  = _get("BINANCE_SECRET_KEY", "")
BINANCE_TH_BASE_URL = _get("BINANCE_TH_BASE_URL", "https://api.binance.com")
USE_TESTNET         = _get("USE_TESTNET", "False").lower() == "true"

# --- Anthropic ---
ANTHROPIC_API_KEY   = _get("ANTHROPIC_API_KEY", "")

# --- Email ---
EMAIL_SENDER   = _get("EMAIL_SENDER", "")
EMAIL_PASSWORD = _get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = _get("EMAIL_RECEIVER", "")

# --- Whale Alert ---
WHALE_ALERT_API_KEY = _get("WHALE_ALERT_API_KEY", "")

# --- Trading Pairs ---
_pairs_raw   = _get("TRADING_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,ADAUSDT,DOGEUSDT,XRPUSDT")
TRADING_PAIRS = [p.strip() for p in _pairs_raw.split(",")]

# --- Risk Management ---
TAKE_PROFIT_PCT   = _get("TAKE_PROFIT_PCT",   "8.0",  float)
STOP_LOSS_PCT     = _get("STOP_LOSS_PCT",      "4.0",  float)
TRADE_AMOUNT_USDT = _get("TRADE_AMOUNT_USDT",  "80",   float)
MAX_OPEN_TRADES   = _get("MAX_OPEN_TRADES",    "7",    int)

# --- AI Confidence ---
MIN_BUY_CONFIDENCE  = _get("MIN_BUY_CONFIDENCE",  "65", int)
MIN_SELL_CONFIDENCE = _get("MIN_SELL_CONFIDENCE",  "60", int)

# --- Timeframe ---
CANDLE_INTERVAL = _get("CANDLE_INTERVAL", "15m")
CANDLE_LIMIT    = _get("CANDLE_LIMIT",    "100", int)

# --- Bot Loop ---
SCAN_INTERVAL_SECONDS = _get("SCAN_INTERVAL_SECONDS", "180", int)

# --- Dashboard ---
DASHBOARD_PORT = _get("DASHBOARD_PORT", "8050", int)

# --- Signal Thresholds ---
DEAD_VOL_CONFIDENCE_THRESHOLD = _get("DEAD_VOL_CONFIDENCE_THRESHOLD", "35",  int)
EXTREME_FEAR_THRESHOLD        = _get("EXTREME_FEAR_THRESHOLD",        "20",  int)
AI_BEARISH_THRESHOLD          = _get("AI_BEARISH_THRESHOLD",          "-50", int)
BUY_SIGNAL_MIN_CONFIDENCE     = _get("BUY_SIGNAL_MIN_CONFIDENCE",     "60",  int)
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 65
FEAR_GREED_BUY = 25
FEAR_GREED_SELL= 75

# --- Notifier Schedule ---
LITE_CHECK_INTERVAL_HOURS = _get("LITE_CHECK_INTERVAL_HOURS", "1", int)
_full_hours_raw = _get("FULL_CHECK_HOURS", "08:00,16:00,00:00")
FULL_CHECK_HOURS = [h.strip() for h in _full_hours_raw.split(",")]


# --- Validation (Alert if important keys are missing) ---
def validate():
    missing = []
    if not BINANCE_API_KEY:    missing.append("BINANCE_API_KEY")
    if not BINANCE_SECRET_KEY: missing.append("BINANCE_SECRET_KEY")
    if not ANTHROPIC_API_KEY:  missing.append("ANTHROPIC_API_KEY")
    if not EMAIL_SENDER:       missing.append("EMAIL_SENDER")
    if not EMAIL_PASSWORD:     missing.append("EMAIL_PASSWORD")
    if missing:
        print(f"⚠️  .env missing keys: {', '.join(missing)}")
        print("   Please enter values in .env before running")
        return False
    return True


if __name__ == "__main__":
    if validate():
        print("✅ config loaded successfully")
        print(f"  Binance: {'*'*8}{BINANCE_API_KEY[-4:]}")
        print(f"  Pairs:   {TRADING_PAIRS}")
        print(f"  TP/SL:   {TAKE_PROFIT_PCT}% / {STOP_LOSS_PCT}%")