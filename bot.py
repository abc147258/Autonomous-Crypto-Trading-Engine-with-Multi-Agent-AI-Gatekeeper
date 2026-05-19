# ============================================================
# bot.py — AI Trading Bot (Full Protection Version)
# ============================================================

import time
import logging
import json
import shutil
import signal
import sys
import threading
from datetime import datetime, date
from pathlib import Path

from config import (
    TRADING_PAIRS, SCAN_INTERVAL_SECONDS,
    MAX_OPEN_TRADES, MIN_BUY_CONFIDENCE, MIN_SELL_CONFIDENCE,
    TAKE_PROFIT_PCT, STOP_LOSS_PCT,
)
from binance_client import BinanceTrader
from indicators    import get_all_indicators, get_mtf_trend, get_market_regime
from ai_analyzer import analyze_symbol, get_news_context
from lesson_engine import learn_from_loss, log_lesson_summary
from fear_greed    import get_fear_greed
STOP_FLAG_FILE = Path("bot.stop")

# ─── Graceful Shutdown ────────────────────────────────────────
_shutdown_event = threading.Event()
_shutdown_reason = ""

def _handle_signal(signum, frame):
    """Receive SIGINT/SIGTERM and set shutdown event"""
    global _shutdown_reason
    sig_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else "SIGTERM"
    _shutdown_reason = sig_name
    logger.warning(f"[STOP] Received {sig_name} — starting graceful shutdown...")
    _shutdown_event.set()

def _interruptible_sleep(seconds: float):
    """
    Interruptible sleep — stops immediately if shutdown event is set
    """
    _shutdown_event.wait(timeout=seconds)

def _graceful_exit(trader, state, reason: str = ""):
    """
    Clean bot shutdown:
    1. Save state
    2. Log final summary
    3. Do not close positions (TP/SL will handle on restart)
    """
    logger.info("=" * 60)
    logger.info(f"  🛑 Graceful Shutdown — {reason or 'user request'}")
    logger.info("=" * 60)

    positions = state.get("positions", {})
    if positions:
        logger.info(f"  Open positions: {len(positions)}")
        for sym, pos in positions.items():
            pnl = pos.get("pnl_pct", 0)
            logger.info(
                f"  └ {sym} @ {pos.get('entry_price',0):.4g} "
                f"TP={pos.get('tp_price',0):.4g} "
                f"SL={pos.get('sl_price',0):.4g} "
                f"PnL={pnl:+.2f}%"
            )
        logger.warning(
            "  [WARN] Positions still open — bot restart will handle TP/SL"
        )
    else:
        logger.info("  No open positions")

    s  = state.get("stats", {})
    tt = s.get("total_trades", 0)
    if tt > 0:
        wr = s.get("wins", 0) / tt * 100
        logger.info(
            f"  Stats: trades={tt} "
            f"wr={wr:.1f}% "
            f"pnl={s.get('total_pnl',0):.2f}%"
        )

    log_performance_summary(state)
    log_lesson_summary()
    save_state(state)

    logger.info("  [OK] State saved — bot stopped safely")
    logger.info("=" * 60)

# ─── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_pro.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("ProTradingBot")

STATE_FILE  = Path("state.json")
BACKUP_FILE = Path("state_backup.json")

# ─── Settings ─────────────────────────────────────────────────
TRAILING_ACTIVATE_PCT    = 3.0
TRAILING_DISTANCE_PCT    = 2.5
MAX_DAILY_LOSS_PCT       = 5.0
PORTFOLIO_STOP_LOSS_PCT  = 15.0
MTF_CACHE_TTL            = 900
MAX_RECONNECT_TRIES      = 5
LIMIT_ORDER_SLIPPAGE_PCT = 0.1
LIMIT_ORDER_TIMEOUT_S    = 30
SL_COOLDOWN_SECONDS      = 57600  # cooldown 16h after SL (4 × 4h candles from backtest)
SL_COOLDOWN_OVERRIDE_CONF = 85   # conf above this overrides cooldown
DOWNTREND_MIN_CONF       = 90
DOWNTREND_SIZE_MULT      = 0.5

# ── ATR-based TP/SL (backtest ROI +112%) ─────────────────────
ATR_TP_MULT              = 4.2   # TP = entry + ATR × 4.2
ATR_SL_MULT              = 2.8   # SL = entry - ATR × 2.8

# ─── State ────────────────────────────────────────────────────
def load_state() -> dict:
    for f in [STATE_FILE, BACKUP_FILE]:
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if f == BACKUP_FILE:
                    logger.warning("Loaded from backup — state.json corrupted")
                return data
            except Exception:
                continue
    return {"positions": {}, "trade_history": [],
            "stats": {"total_trades": 0, "wins": 0,
                      "losses": 0, "total_pnl": 0.0},
            "daily": {"date": str(date.today()), "loss_pct": 0.0}}

def save_state(state: dict):
    try:
        if STATE_FILE.exists():
            shutil.copy2(STATE_FILE, BACKUP_FILE)
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"save_state error: {e}")

def get_daily(state: dict) -> dict:
    """Reset daily stats if new day"""
    today = str(date.today())
    if state.get("daily", {}).get("date") != today:
        state["daily"] = {"date": today, "loss_pct": 0.0}
    return state["daily"]

# ─── Auto Trade Amount ────────────────────────────────────────
def get_trade_amount(trader: BinanceTrader, state: dict) -> float:
    """
    Calculate trade amount from total portfolio value
    = remaining USDT + value of all open positions
    divided equally by MAX_OPEN_TRADES
    """
    try:
        usdt_balance = trader.get_usdt_balance()

        position_value = 0.0
        for symbol, pos in state.get("positions", {}).items():
            price = trader.get_price(symbol)
            if price > 0:
                position_value += price * pos.get("qty", 0)

        total   = usdt_balance + position_value
        usable  = total * 0.95
        amount  = usable / MAX_OPEN_TRADES
        amount  = max(amount, 10.0)

        logger.info(
            f"  [AUTO AMT] USDT={usdt_balance:.2f} "
            f"Positions={position_value:.2f} "
            f"Total={total:.2f} "
            f"→ {amount:.2f} USDT/trade"
        )
        return round(amount, 2)
    except Exception as e:
        logger.error(f"get_trade_amount: {e}")
        return 10.0

# ─── Portfolio Stop Loss ──────────────────────────────────────
def check_portfolio_stop(trader: BinanceTrader, state: dict) -> bool:
    try:
        usdt    = trader.get_usdt_balance()
        pos_val = sum(
            trader.get_price(sym) * pos.get("qty", 0)
            for sym, pos in state.get("positions", {}).items()
        )
        equity = usdt + pos_val
        peak   = state.get("peak_equity", equity)
        if equity > peak:
            state["peak_equity"] = equity
            peak = equity
        drawdown = (peak - equity) / peak * 100 if peak > 0 else 0
        logger.info(
            f"[PORTFOLIO] Equity=${equity:.2f} Peak=${peak:.2f} DD={drawdown:.1f}%"
        )
        if drawdown >= PORTFOLIO_STOP_LOSS_PCT:
            logger.critical(
                f"🚨 PORTFOLIO STOP! DD={drawdown:.1f}% >= {PORTFOLIO_STOP_LOSS_PCT}%"
            )
            return True
        return False
    except Exception as e:
        logger.error(f"check_portfolio_stop: {e}"); return False

# ─── Limit Order with Fallback ────────────────────────────────
def buy_with_limit(trader: BinanceTrader, symbol: str,
                   usdt_amount: float) -> dict | None:
    """Limit order with fallback to market on timeout"""
    try:
        import math
        price       = trader.get_price(symbol)
        if price <= 0: return None
        limit_price = round(price * (1 - LIMIT_ORDER_SLIPPAGE_PCT / 100), 8)
        info        = trader.get_symbol_info(symbol)
        step        = info["step_size"]
        precision   = max(0, -int(math.log10(step))) if step < 1 else 0
        qty         = round(int(usdt_amount / limit_price / step) * step, precision)
        if qty <= 0:
            return trader.buy_market(symbol, usdt_amount)

        logger.info(f"  [LIMIT] {symbol} qty={qty} @ ${limit_price:,.4f} (mkt=${price:,.4f})")
        order    = trader.client.order_limit_buy(
            symbol=symbol, quantity=qty, price=f"{limit_price:.8f}"
        )
        order_id = order.get("orderId")

        start = time.time()
        while time.time() - start < LIMIT_ORDER_TIMEOUT_S:
            time.sleep(2)
            status = trader.client.get_order(symbol=symbol, orderId=order_id)
            if status["status"] == "FILLED":
                fills = status.get("fills", [])
                if fills:
                    tc = sum(float(f["price"])*float(f["qty"]) for f in fills)
                    tq = sum(float(f["qty"]) for f in fills)
                    entry = tc/tq if tq > 0 else limit_price
                else:
                    entry = limit_price
                logger.info(f"  [LIMIT FILLED] {symbol} @ ${entry:,.4f}")
                return {"symbol": symbol, "qty": qty,
                        "entry_price": round(entry, 8), "order_id": order_id}
            elif status["status"] in ("CANCELED", "REJECTED", "EXPIRED"):
                break

        try: trader.client.cancel_order(symbol=symbol, orderId=order_id)
        except Exception: pass
        logger.warning(f"  [LIMIT TIMEOUT] {symbol} → market order")
        return trader.buy_market(symbol, usdt_amount)

    except Exception as e:
        logger.error(f"buy_with_limit {symbol}: {e}")
        return trader.buy_market(symbol, usdt_amount)

# ─── Performance Tracker ──────────────────────────────────────
def update_performance(state: dict, pnl_pct: float,
                       conf: int, regime: str, exit_type: str):
    """Record win rate by confidence band, regime, and exit type"""
    if "performance" not in state:
        state["performance"] = {}
    perf = state["performance"]

    band = ("85+" if conf >= 85 else "75-84" if conf >= 75
            else "65-74" if conf >= 65 else "55-64")

    for key in [f"conf_{band}", f"regime_{regime}", f"exit_{exit_type}"]:
        if key not in perf:
            perf[key] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        perf[key]["trades"]    += 1
        perf[key]["total_pnl"] += pnl_pct
        if pnl_pct >= 0: perf[key]["wins"] += 1
    return state

def log_performance_summary(state: dict):
    perf = state.get("performance", {})
    if not perf: return
    logger.info("── Performance Summary ──────────────────────")
    for key in sorted(perf.keys()):
        d = perf[key]
        if d["trades"] == 0: continue
        wr  = d["wins"]/d["trades"]*100
        avg = d["total_pnl"]/d["trades"]
        logger.info(f"  [{key:<20}] trades={d['trades']:>4} wr={wr:>5.1f}% avg={avg:>+6.2f}%")
    logger.info("─────────────────────────────────────────────")

# ─── Confidence-based Position Sizing ───────────────────────
def get_position_size(base_amount: float, conf: int,
                      total_portfolio: float) -> float:
    """
    Higher confidence = larger position size
    Max cap: 30% of portfolio per trade

    conf 55-64% → 0.5x
    conf 65-74% → 1.0x
    conf 75-84% → 1.5x
    conf 85%+   → 2.0x
    """
    if conf >= 85:
        multiplier = 2.0
    elif conf >= 75:
        multiplier = 1.5
    elif conf >= 65:
        multiplier = 1.0
    else:
        multiplier = 0.5

    amount = base_amount * multiplier

    max_amount = total_portfolio * 0.30
    amount = min(amount, max_amount)
    amount = max(amount, 10.0)

    return round(amount, 2)

def get_trader_with_retry() -> BinanceTrader | None:
    """Create BinanceTrader with retry on connection failure"""
    for attempt in range(1, MAX_RECONNECT_TRIES + 1):
        try:
            trader = BinanceTrader()
            trader.get_usdt_balance()
            if attempt > 1:
                logger.info(f"Reconnected successfully (attempt {attempt})")
            return trader
        except Exception as e:
            wait = attempt * 10
            logger.error(
                f"Reconnect attempt {attempt}/{MAX_RECONNECT_TRIES} "
                f"failed: {e} — waiting {wait}s"
            )
            time.sleep(wait)
    logger.error("All reconnect attempts failed, stopping bot")
    return None

# ─── MTF Cache ────────────────────────────────────────────────
_mtf_cache = {}

def get_mtf_data(trader: BinanceTrader, symbol: str) -> tuple[dict, dict]:
    now    = time.time()
    cached = _mtf_cache.get(symbol)
    if cached and (now - cached["ts"]) < MTF_CACHE_TTL:
        return cached["mtf"], cached["regime"]
    try:
        df_1h  = trader.get_candles_1h(symbol)
        mtf    = get_mtf_trend(df_1h)
        regime = get_market_regime(df_1h)
        _mtf_cache[symbol] = {"ts": now, "mtf": mtf, "regime": regime}
        return mtf, regime
    except Exception as e:
        logger.error(f"MTF {symbol}: {e}")
        return ({"trend": "UNKNOWN", "strength": 3, "aligned": True},
                {"regime": "UNKNOWN", "tp_multiplier": 1.0,
                 "sl_multiplier": 1.0, "should_trade": True})

# ─── Dynamic Market Guard ─────────────────────────────────────
def is_market_active(symbol, df):
    if df is None or len(df) < 30:
        return False, "Data insufficient"

    recent_ranges  = (df["high"] - df["low"]) / df["close"] * 100
    avg_volatility = recent_ranges.iloc[-21:-1].mean()
    current_range  = recent_ranges.iloc[-1]
    current_volume = df["volume"].iloc[-1]
    avg_volume     = df["volume"].iloc[-11:-1].mean()

    if current_range < (avg_volatility * 0.5):
        return False, f"Quiet ({current_range:.2f}% < Avg {avg_volatility:.2f}%)"
    if current_volume < (avg_volume * 0.3):
        return False, "Dead Volume"

    return True, "Active/Trending"

# ─── Trailing Stop ────────────────────────────────────────────
def update_trailing_stop(pos: dict, current_price: float,
                         current_atr: float = 0) -> dict:
    """Trailing SL — dynamic ATR (backtest ROI +112%)"""
    entry   = pos["entry_price"]
    highest = pos.get("highest_price", entry)

    if current_price > highest:
        highest = current_price
        pos["highest_price"] = highest

        if current_atr > 0:
            new_sl = round(current_price - current_atr * ATR_SL_MULT, 8)
        else:
            dist   = pos.get("trailing_distance", TRAILING_DISTANCE_PCT)
            new_sl = round(current_price * (1 - dist/100), 8)

        if new_sl > pos["sl_price"]:
            old_sl = pos["sl_price"]
            pos["sl_price"]        = new_sl
            pos["trailing_active"] = True
            logger.info(
                f"  [TRAILING] {pos['symbol']} "
                f"High={highest:.6g} SL {old_sl:.6g} → {new_sl:.6g} "
                f"(ATR×{ATR_SL_MULT})"
            )
    return pos

# ─── TP / SL Check ────────────────────────────────────────────
def check_tp_sl(trader: BinanceTrader, state: dict) -> dict:
    to_close = []

    for symbol, pos in state["positions"].items():
        try:
            price = trader.get_price(symbol)
        except Exception as e:
            logger.error(f"get_price {symbol}: {e}")
            continue

        if price == 0:
            continue

        pnl_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
        pos["current_price"] = price
        pos["pnl_pct"]       = round(pnl_pct, 3)

        try:
            df_atr = trader.get_candles(symbol)
            from indicators import get_all_indicators
            ind_atr = get_all_indicators(df_atr)
            atr_now = ind_atr.get("atr", 0)
        except Exception:
            atr_now = 0
        pos = update_trailing_stop(pos, price, atr_now)
        state["positions"][symbol] = pos

        if price >= pos["tp_price"]:
            to_close.append((symbol, "TP", price, pnl_pct))
        elif price <= pos["sl_price"]:
            reason = "TRAIL_SL" if pos.get("trailing_active") else "SL"
            to_close.append((symbol, reason, price, pnl_pct))

    for symbol, reason, price, pnl_pct in to_close:
        pos    = state["positions"][symbol]
        result = trader.sell_market(symbol, pos["qty"])
        if result:
            won = pnl_pct >= 0
            s   = state["stats"]
            s["total_trades"] += 1
            s["wins"]         += 1 if won else 0
            s["losses"]       += 0 if won else 1
            s["total_pnl"]    += pnl_pct

            if not won:
                state["daily"]["loss_pct"] = \
                    state["daily"].get("loss_pct", 0) + abs(pnl_pct)

            # Performance tracker
            conf_closed   = pos.get("confidence", 65)
            regime_closed = pos.get("regime", "UNKNOWN")
            update_performance(state, pnl_pct, conf_closed,
                               regime_closed, reason)

            if reason in ("SL", "TRAIL_SL"):
                state.setdefault("sl_cooldown_log", {})[symbol] = \
                    datetime.now().isoformat()
                logger.info(f"  [COOLDOWN] {symbol} cooldown {SL_COOLDOWN_SECONDS//3600}h")

                # ── AI Lesson Learning ─────────────────────────
                try:
                    df_learn  = trader.get_candles(symbol)
                    ind_learn = get_all_indicators(df_learn)
                    learn_from_loss(symbol, {
                        "reason":      reason,
                        "pnl_pct":     pnl_pct,
                        "entry_price": pos["entry_price"],
                        "exit_price":  price,
                    }, ind_learn)
                except Exception as e:
                    logger.warning(f"  [LESSON] learn failed: {e}")

            state["trade_history"].append({
                "symbol":      symbol,
                "entry_price": pos["entry_price"],
                "exit_price":  result["exit_price"],
                "qty":         pos["qty"],
                "pnl_pct":     round(pnl_pct, 3),
                "reason":      reason,
                "closed_at":   datetime.now().isoformat(),
            })
            del state["positions"][symbol]
            logger.info(f"[{reason}] {symbol} @ {price:.6g} | PnL {pnl_pct:.2f}%")

    return state

# ─── Main Loop ────────────────────────────────────────────────
def run_bot():
    logger.info("=" * 60)
    logger.info("  AI Trading Bot [Full Protection Version]")
    logger.info(f"  ATR TP×{ATR_TP_MULT} SL×{ATR_SL_MULT} | conf>={65}%")
    logger.info(f"  Max daily loss: {MAX_DAILY_LOSS_PCT}%")
    logger.info(f"  Press Ctrl+C to stop safely")
    logger.info("=" * 60)

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    trader = get_trader_with_retry()
    if not trader:
        return

    state = load_state()
    if "daily" not in state:
        state["daily"] = {"date": str(date.today()), "loss_pct": 0.0}

    # SL Cooldown tracker
    sl_cooldown: dict = {}

    bal = trader.get_usdt_balance()
    logger.info(f"USDT Balance: {bal:.2f} USDT")
    logger.info(f"Per trade approx: {bal * 0.95 / MAX_OPEN_TRADES:.2f} USDT")

    while True:
        try:
            if STOP_FLAG_FILE.exists():
                logger.info("Stop flag found — starting graceful shutdown")
                _shutdown_event.set()
                _graceful_exit(trader, state, "stop flag")
                break

            if _shutdown_event.is_set():
                _graceful_exit(trader, state, _shutdown_reason)
                break
            logger.info(f"--- Scan {datetime.now().strftime('%H:%M:%S')} ---")

            try:
                trader.get_usdt_balance()
            except Exception:
                logger.warning("Binance disconnected, reconnecting...")
                trader = get_trader_with_retry()
                if not trader:
                    logger.error("Reconnect failed, waiting 60s then retry")
                    time.sleep(60)
                    continue

            # ── Reset daily stats ──────────────────────────────
            daily = get_daily(state)

            # ── Max Daily Loss Guard ───────────────────────────
            if daily["loss_pct"] >= MAX_DAILY_LOSS_PCT:
                logger.warning(
                    f"[MAX DAILY LOSS] Daily loss {daily['loss_pct']:.2f}% >= {MAX_DAILY_LOSS_PCT}% — stop opening new positions today"
                )
                state = check_tp_sl(trader, state)
                save_state(state)
                time.sleep(SCAN_INTERVAL_SECONDS)
                continue

            # ── TP/SL Check ────────────────────────────────────
            state = check_tp_sl(trader, state)
            save_state(state)

            # ── Portfolio Stop Loss ────────────────────────────
            if check_portfolio_stop(trader, state):
                logger.critical("Stopping bot due to portfolio drawdown limit")
                save_state(state)
                break

            open_count = len(state["positions"])
            logger.info(
                f"Positions: {open_count}/{MAX_OPEN_TRADES} | "
                f"Daily loss: {daily['loss_pct']:.2f}%/{MAX_DAILY_LOSS_PCT}%"
            )

            # ── Fear & Greed Index ─────────────────────────
            fg = get_fear_greed()
            logger.info(
                f"[F&G] {fg['value']}/100 {fg['label']} | {fg['advice']}"
            )

            news_ctx = get_news_context()
            if news_ctx["should_analyze"]:
                logger.info(
                    f"[NEWS] ⚡ {news_ctx['sentiment']}({news_ctx['score']:+d}) "
                    f"events={news_ctx['key_events']} risk={news_ctx['risk']}"
                )
            else:
                logger.info(
                    f"[NEWS] neutral({news_ctx['score']:+d}) — Sonnet skips no-position pairs"
                )

            for symbol in TRADING_PAIRS:
                try:
                    df       = trader.get_candles(symbol)
                    open_pos = state["positions"].get(symbol)

                    is_active, msg = is_market_active(symbol, df)
                    if not open_pos and not is_active:
                        logger.info(f"[{symbol}] SKIP | {msg}")
                        continue

                    mtf, regime = get_mtf_data(trader, symbol)

                    if not open_pos and regime["regime"] == "BEAR":
                        logger.info(f"[{symbol}] SKIP | Regime=BEAR")
                        continue

                    if not open_pos and mtf["trend"] == "BEAR":
                        logger.info(f"[{symbol}] SKIP | 1h BEAR")
                        continue

                    indicators = get_all_indicators(df)
                    decision = analyze_symbol(symbol, indicators, open_pos, news_ctx)

                    if decision.get("sonnet_called"):
                        logger.info(
                            f"  [{symbol}] Sonnet → {decision['action']}({decision['confidence']}%) "
                            f"TP={decision.get('tp_pct',0):.1f}% SL={decision.get('sl_pct',0):.1f}% "
                            f"ATR={decision.get('atr_pct',0):.2f}%"
                        )
                    else:
                        logger.info(f"  [{symbol}] HOLD (news neutral, Sonnet skipped)")

                    action = decision.get("action", "HOLD")
                    conf   = decision.get("confidence", 0)
                    reason = decision.get("reason", "")

                    trail_info = ""
                    if open_pos and open_pos.get("trailing_active"):
                        trail_info = f" 🔒TRAIL={open_pos['sl_price']:.6g}"

                    logger.info(
                        f"[{symbol}] {action} ({conf}%) | {reason} | "
                        f"1h={mtf['trend']} Regime={regime['regime']}{trail_info}"
                    )

                    # ── BUY ───────────────────────────────────────────
                    if action == "BUY" and conf >= 65 \
                            and not open_pos and mtf["trend"] != "BEAR":

                        # ── 1. SL Cooldown check ──────────────────────
                        cooldown_key = state.get("sl_cooldown_log", {}).get(symbol)
                        if cooldown_key:
                            elapsed = (datetime.now() -
                                      datetime.fromisoformat(cooldown_key)).total_seconds()
                            if elapsed < SL_COOLDOWN_SECONDS:
                                if conf >= SL_COOLDOWN_OVERRIDE_CONF:
                                    logger.info(
                                        f"  [{symbol}] COOLDOWN OVERRIDE "
                                        f"conf={conf}% >= {SL_COOLDOWN_OVERRIDE_CONF}%"
                                    )
                                    state["sl_cooldown_log"].pop(symbol, None)
                                else:
                                    remain = int((SL_COOLDOWN_SECONDS-elapsed)//3600)
                                    logger.info(
                                        f"  [{symbol}] BUY blocked — "
                                        f"cooldown {remain}h remaining"
                                    )
                                    continue
                            else:
                                state.get("sl_cooldown_log", {}).pop(symbol, None)

                        # ── 2. Downtrend Mode detection ───────────────
                        ema9  = indicators.get("ema9",  0)
                        ema21 = indicators.get("ema21", 0)
                        ema50 = indicators.get("ema50", 0)
                        is_downtrend = (ema9 > 0 and ema21 > 0 and ema50 > 0
                                        and ema9 < ema21 < ema50)

                        if is_downtrend:
                            if conf < DOWNTREND_MIN_CONF:
                                logger.info(
                                    f"  [{symbol}] BUY blocked — "
                                    f"Downtrend conf={conf}% < {DOWNTREND_MIN_CONF}%"
                                )
                                continue
                            logger.info(
                                f"  [{symbol}] DOWNTREND MODE — "
                                f"conf={conf}% >= {DOWNTREND_MIN_CONF}% passed"
                            )

                        # ── F&G filter ────────────────────────────────
                        if fg["value"] <= 15:
                            logger.info(
                                f"  [SKIP BUY] {symbol} "
                                f"F&G={fg['value']} Extreme Fear"
                            )
                            continue

                        if open_count < MAX_OPEN_TRADES:
                            # ── Position sizing by confidence ─────────
                            base_amt  = get_trade_amount(trader, state)
                            total_val = base_amt * MAX_OPEN_TRADES
                            trade_amt = get_position_size(base_amt, conf, total_val)

                            if is_downtrend:
                                trade_amt = round(trade_amt * DOWNTREND_SIZE_MULT, 2)
                                trade_amt = max(trade_amt, 10.0)

                            size_tag = (
                                "2.0x" if conf>=85 else
                                "1.5x" if conf>=75 else
                                "1.0x" if conf>=65 else "0.5x"
                            )
                            if is_downtrend:
                                size_tag += f" (downtrend ×{DOWNTREND_SIZE_MULT})"

                            logger.info(
                                f"  [SIZE] {symbol} conf={conf}% → "
                                f"{size_tag} = ${trade_amt:.2f} USDT"
                            )

                            result = buy_with_limit(trader, symbol, trade_amt)
                            if result:
                                tp_mult = regime["tp_multiplier"] * fg["tp_mult"]
                                sl_mult = regime["sl_multiplier"] * fg["sl_mult"]

                                if is_downtrend:
                                    sl_mult = min(sl_mult, 0.8)

                                entry      = result["entry_price"]
                                tp_pct_use = decision.get("tp_pct") or TAKE_PROFIT_PCT
                                sl_pct_use = decision.get("sl_pct") or STOP_LOSS_PCT

                                atr_val = decision.get("atr_pct", 0) / 100 * entry
                                if atr_val > 0:
                                    result["tp_price"] = round(
                                        entry + atr_val * ATR_TP_MULT * tp_mult, 8
                                    )
                                    result["sl_price"] = round(
                                        entry - atr_val * ATR_SL_MULT * sl_mult, 8
                                    )
                                else:
                                    result["tp_price"] = round(
                                        entry * (1 + tp_pct_use / 100 * tp_mult), 8
                                    )
                                    result["sl_price"] = round(
                                        entry * (1 - sl_pct_use / 100 * sl_mult), 8
                                    )

                                trail_act  = decision.get("trail_activate") \
                                             or TRAILING_ACTIVATE_PCT
                                trail_dist = decision.get("trail_distance") \
                                             or TRAILING_DISTANCE_PCT

                                if is_downtrend:
                                    trail_act  = min(trail_act, 1.5)
                                    trail_dist = min(trail_dist * sl_mult, trail_act * 0.6)

                                trail_dist = round(trail_dist * sl_mult, 2)

                                # ── 3. Breakeven Mode ─────────────────
                                result["breakeven_mode"]      = True
                                result["highest_price"]       = entry
                                result["trailing_active"]     = False
                                result["trailing_activate"]   = trail_act
                                result["trailing_distance"]   = trail_dist
                                result["regime"]              = regime["regime"]
                                result["mtf_trend"]           = mtf["trend"]
                                result["confidence"]          = conf
                                result["size_multiplier"]     = size_tag
                                result["is_downtrend"]        = is_downtrend
                                state["positions"][symbol]    = result
                                open_count += 1
                                save_state(state)
                                logger.info(
                                    f"  BOUGHT {symbol} @ {entry} "
                                    f"amt={trade_amt:.2f} USDT ({size_tag}) "
                                    f"TP={result['tp_price']}(+{tp_pct_use:.1f}%) "
                                    f"SL={result['sl_price']}(-{sl_pct_use:.1f}%) "
                                    f"Trail: act={trail_act:.1f}% dist={trail_dist:.1f}% "
                                    f"Breakeven=ON"
                                )

                    # ── SELL (AI) ─────────────────────────────────────
                    elif action == "SELL" and open_pos \
                            and conf >= MIN_SELL_CONFIDENCE:
                        if open_pos.get("trailing_active") \
                                and open_pos.get("pnl_pct", 0) < 0:
                            logger.info(f"  [SKIP AI_SELL] {symbol} trailing active")
                        else:
                            result = trader.sell_market(symbol, open_pos["qty"])
                            if result:
                                pnl_pct = (
                                    (result["exit_price"] - open_pos["entry_price"])
                                    / open_pos["entry_price"] * 100
                                )
                                won = pnl_pct >= 0
                                s   = state["stats"]
                                s["total_trades"] += 1
                                s["wins"]         += 1 if won else 0
                                s["losses"]       += 0 if won else 1
                                s["total_pnl"]    += pnl_pct

                                if not won:
                                    state["daily"]["loss_pct"] += abs(pnl_pct)

                                state["trade_history"].append({
                                    "symbol":      symbol,
                                    "entry_price": open_pos["entry_price"],
                                    "exit_price":  result["exit_price"],
                                    "qty":         open_pos["qty"],
                                    "pnl_pct":     round(pnl_pct, 3),
                                    "reason":      "AI_SELL",
                                    "closed_at":   datetime.now().isoformat(),
                                })
                                del state["positions"][symbol]
                                open_count -= 1
                                save_state(state)
                                logger.info(
                                    f"  SOLD {symbol} @ {result['exit_price']} "
                                    f"PnL={pnl_pct:.2f}%"
                                )

                    time.sleep(1.5)

                except Exception as e:
                    logger.error(f"Error {symbol}: {e}")
                    continue

            s  = state["stats"]
            wr = s["wins"] / s["total_trades"] * 100 if s["total_trades"] > 0 else 0
            logger.info(
                f"Stats: trades={s['total_trades']} "
                f"wr={wr:.1f}% pnl={s['total_pnl']:.2f}%"
            )
            log_performance_summary(state)
            log_lesson_summary()

            save_state(state)
            logger.info(f"Sleeping {SCAN_INTERVAL_SECONDS}s... (Ctrl+C to stop)")
            _interruptible_sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            _graceful_exit(trader, state, "KeyboardInterrupt")
            break
        except Exception as e:
            logger.error(f"System Error: {e}")
            if _shutdown_event.is_set():
                _graceful_exit(trader, state, _shutdown_reason)
                break
            time.sleep(15)

    if _shutdown_event.is_set() and state:
        _graceful_exit(trader, state, _shutdown_reason)

if __name__ == "__main__":
    run_bot()
