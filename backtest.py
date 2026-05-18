# ============================================================
# backtest.py — Backtest with Signal Mode Comparison
# Run: python backtest.py
#
# Mode 1: No Signal  — rule-based original (get_signal)
# Mode 2: With Signal — signals.py 10 indicators
# ============================================================

import pandas as pd
import numpy as np
from binance_client import BinanceTrader

# ──────────────────── Try importing signals.py ────────────────────
try:
    from signals import (
        score_rsi, score_macd, score_bollinger, score_ma,
        score_fear_greed, score_volume,
        score_ema_trend, score_ma200_trend,
        score_atr_regime, score_volume_spike,
        aggregate_score, DEFAULT_WEIGHTS,
    )
    USE_SIGNALS = True
    print("✅ signals.py loaded successfully — Will run both modes")
except ImportError:
    USE_SIGNALS = False
    print("⚠️  signals.py not found — Will run No Signal mode only")

# ──────────────────── Config ────────────────────
PAIRS        = ["BTCUSDT", "ETHUSDT", "SOLUSDT",
                "BNBUSDT", "DOGEUSDT", "XRPUSDT"]
INITIAL_CASH = 10_000.0
MAX_TRADES   = 5
SIZE_PCT     = 0.12
YEARS        = 5
CD_BARS      = 4

# ──────────────────── Configs to test ────────────────────
CONFIGS = [
    {"name": "Original",  "ATR_TP": 4.2, "ATR_SL": 2.2, "MIN_CONF": 0.55},
    {"name": "Wider_SL",  "ATR_TP": 4.2, "ATR_SL": 3.0, "MIN_CONF": 0.55},
    {"name": "High_Conf", "ATR_TP": 4.2, "ATR_SL": 2.8, "MIN_CONF": 0.65},
    {"name": "TP55_SL30", "ATR_TP": 5.5, "ATR_SL": 3.0, "MIN_CONF": 0.55},
    {"name": "TP60_SL30", "ATR_TP": 6.0, "ATR_SL": 3.0, "MIN_CONF": 0.55},
]


# ──────────────────── Fetch Data ────────────────────
def fetch(trader, symbol):
    from datetime import datetime, timezone, timedelta
    import time
    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=YEARS*365)).timestamp() * 1000)
    all_df, current_start = [], start_ms

    while current_start < end_ms:
        try:
            klines = trader.client.get_klines(
                symbol=symbol, interval="4h",
                startTime=current_start, limit=1000,
            )
            if not klines: break
            df = pd.DataFrame(klines, columns=[
                "open_time","open","high","low","close","volume",
                "close_time","quote_vol","trades","taker_buy_base",
                "taker_buy_quote","ignore",
            ])
            for col in ["open","high","low","close","volume"]:
                df[col] = pd.to_numeric(df[col])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df = df.set_index("open_time")
            all_df.append(df)
            current_start = int(klines[-1][0]) + 1
            if len(klines) < 1000: break
            time.sleep(0.3)
        except Exception as e:
            print(f"    error: {e}"); break

    if not all_df: raise ValueError(f"No data for {symbol}")
    result = pd.concat(all_df)
    result = result[~result.index.duplicated(keep="first")]
    return result.sort_index()


# ──────────────────── Indicators ────────────────────
def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()


def calc_indicators(df):
    c = df["close"]; h = df["high"]; l = df["low"]; v = df["volume"]
    e9, e21, e50 = ema(c,9), ema(c,21), ema(c,50)
    ma50  = c.rolling(50).mean()
    ma200 = c.rolling(200).mean()
    d   = c.diff()
    g   = d.clip(lower=0).ewm(com=13, adjust=False).mean()
    ls  = (-d.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100/(1 + g/ls.replace(0, np.nan))
    ml  = ema(c,12) - ema(c,26)
    mh  = ml - ema(ml,9)
    s20 = c.rolling(20).mean()
    std = c.rolling(20).std()
    bb_pct = (c - (s20 - 2*std)) / ((4*std) + 1e-9) * 100
    bb_up  = s20 + 2*std
    bb_lo  = s20 - 2*std
    tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    vr  = v / v.rolling(20).mean()
    pc  = c.pct_change() * 100

    return pd.DataFrame({
        "close":c, "high":h, "low":l,
        "ema9":e9, "ema21":e21, "ema50":e50,
        "ma50":ma50, "ma200":ma200,
        "rsi":rsi, "macd":ml, "macd_signal":ema(ml,9),
        "macd_hist":mh, "bb_pct":bb_pct,
        "bb_upper":bb_up, "bb_lower":bb_lo, "bb_mid":s20,
        "atr":atr, "vol_ratio":vr, "price_change_pct":pc,
    }, index=df.index)


# ──────────────────── Mode 1: No Signal (Original logic) ────────────────────
def get_signal_original(row, min_conf=0.55):
    """Original signal — simple rule-based"""
    rsi = row["rsi"]; mh = row["macd_hist"]
    bb  = row["bb_pct"]; vr = row["vol_ratio"]
    e9  = row["ema9"]; e21 = row["ema21"]; e50 = row["ema50"]
    down = (e9 < e21) and (e21 < e50)

    if down:
        b = sum([rsi < 35, vr > 2.0, bb < 10, mh > 0])
        if b < 2: return "SKIP", 0
        thresh = 0.90
    else:
        thresh = min_conf

    sc   = sum([e9>e21, e21>e50, 40<rsi<65, rsi<40, mh>0, bb<40, vr>1.2]) / 7
    sell = sum([rsi>70, mh<0, bb>80]) / 3

    if sell >= 0.6: return "SELL", sell
    if sc >= thresh: return "BUY", sc
    return "HOLD", sc


# ──────────────────── Mode 2: With signals.py ────────────────────
def get_signal_enhanced(row, min_conf=0.55):
    """Enhanced signal — signals.py with 10 indicators"""
    if not USE_SIGNALS:
        return get_signal_original(row, min_conf)

    price  = row["close"]
    e9_21  = row["ema9"] > row["ema21"]
    e21_50 = row["ema21"] > row["ema50"]
    ma50   = row.get("ma50")
    ma200  = row.get("ma200")
    vr     = row["vol_ratio"]
    pc     = row.get("price_change_pct", 0)
    atr    = row["atr"]

    scores = [
        score_rsi(row["rsi"]),
        score_macd(row["macd"], row["macd_signal"], row["macd_hist"]),
        score_ma(price, ma50, ma200),
        score_bollinger(price, row["bb_upper"], row["bb_lower"], row["bb_mid"]),
        score_fear_greed(50),   # neutral fallback
        score_volume(vr),
        score_ema_trend(e9_21, e21_50, price, ma50),
        score_ma200_trend(price, ma200),
        score_atr_regime(atr, price),
        score_volume_spike(vr, pc),
    ]

    action, score, conf = aggregate_score(scores, DEFAULT_WEIGHTS)
    conf_normalized = conf / 100.0

    # Downtrend mode — requires strong signal
    down = not e9_21 and not e21_50
    if down:
        if conf_normalized < 0.90: return "HOLD", conf_normalized
        if action != "BUY": return "HOLD", conf_normalized

    if action == "BUY" and conf_normalized >= min_conf:
        return "BUY", conf_normalized
    if action == "SELL" and conf_normalized >= 0.60:
        return "SELL", conf_normalized
    return "HOLD", conf_normalized


# ──────────────────── Simulate ────────────────────
def simulate(inds, idx, atr_tp, atr_sl, min_conf,
             use_enhanced=False):
    cash = INITIAL_CASH
    pos  = {}
    cd   = {}
    trd  = []

    sig_fn = get_signal_enhanced if use_enhanced else get_signal_original

    for i, ts in enumerate(idx):
        if i < 50: continue

        # ──────────────────── TP/SL check ────────────────────
        to_close = []
        for pair, p in pos.items():
            row   = inds[pair].loc[ts]
            price = row["close"]
            high  = row["high"]
            low   = row["low"]

            # trailing SL — dynamic ATR
            if price > p["highest"]:
                p["highest"] = price
                atr = row["atr"]
                nsl = price - atr * atr_sl
                if nsl > p["sl"]: p["sl"] = nsl

            if high >= p["tp"]:   to_close.append((pair, "TP",  p["tp"]))
            elif low <= p["sl"]:  to_close.append((pair, "SL",  p["sl"]))

        for pair, reason, exit_price in to_close:
            p   = pos[pair]
            pct = (exit_price - p["entry"]) / p["entry"] * 100
            usd = (exit_price - p["entry"]) * p["qty"]
            cash += p["qty"] * exit_price
            trd.append({
                "pair":     pair,
                "entry":    round(p["entry"], 6),
                "exit":     round(exit_price, 6),
                "qty":      round(p["qty"], 6),
                "pnl_pct":  round(pct, 3),
                "pnl_usd":  round(usd, 2),
                "reason":   reason,
            })
            if reason == "SL": cd[pair] = i
            del pos[pair]

        # ──────────────────── Scan BUY ────────────────────
        for pair in PAIRS:
            if pair not in inds: continue
            if pair in pos: continue
            if len(pos) >= MAX_TRADES: continue
            if pair in cd and (i - cd[pair]) < CD_BARS: continue

            row = inds[pair].loc[ts]
            act, conf = sig_fn(row, min_conf)
            if act != "BUY": continue

            price = row["close"]
            amt   = min(cash * SIZE_PCT, cash * 0.95)
            if amt < 10 or cash < 10: continue
            qty   = amt / price
            atr   = row["atr"]
            cash -= amt
            pos[pair] = {
                "entry":   price,
                "qty":     qty,
                "tp":      price + atr * atr_tp,
                "sl":      price - atr * atr_sl,
                "highest": price,
            }

    # Close remaining positions
    last = idx[-1]
    for pair, p in pos.items():
        price = inds[pair].loc[last, "close"]
        pct   = (price - p["entry"]) / p["entry"] * 100
        usd   = (price - p["entry"]) * p["qty"]
        cash += p["qty"] * price
        trd.append({
            "pair":    pair,
            "entry":   round(p["entry"], 6),
            "exit":    round(price, 6),
            "qty":     round(p["qty"], 6),
            "pnl_pct": round(pct, 3),
            "pnl_usd": round(usd, 2),
            "reason":  "END",
        })

    return pd.DataFrame(trd), cash


# ──────────────────── Run ────────────────────
def run():
    print("=" * 65)
    print(f"  Backtest | 4h | {YEARS}Y | Cash=${INITIAL_CASH:,.0f}")
    print(f"  Modes: No Signal + {'With signals.py' if USE_SIGNALS else 'N/A'}")
    print("=" * 65)

    trader = BinanceTrader()
    inds   = {}

    print("\nFetching data from Binance...")
    for pair in PAIRS:
        try:
            df  = fetch(trader, pair)
            ind = calc_indicators(df).dropna()
            inds[pair] = ind
            print(f"  {pair}: {len(ind)} bars")
        except Exception as e:
            print(f"  {pair}: ERROR {e}")

    if not inds:
        print("No data."); return

    idx = None
    for ind in inds.values():
        idx = ind.index if idx is None else idx.intersection(ind.index)
    idx = sorted(idx)
    print(f"\nSimulating {len(idx)} bars × {len(inds)} pairs...\n")

    all_results = []

    # ──────────────────── Test all configs × 2 modes ────────────────────
    modes = [("NoSignal", False)]
    if USE_SIGNALS:
        modes.append(("WithSignal", True))

    for cfg in CONFIGS:
        for mode_name, use_enh in modes:
            name     = f"{cfg['name']}_{mode_name}"
            atr_tp   = cfg["ATR_TP"]
            atr_sl   = cfg["ATR_SL"]
            min_conf = cfg["MIN_CONF"]

            df, cash = simulate(inds, idx, atr_tp, atr_sl,
                                min_conf, use_enh)
            if df.empty:
                print(f"  [{name}] No trades"); continue

            wins   = df[df.pnl_pct > 0]
            losses = df[df.pnl_pct <= 0]
            wr     = len(wins)/len(df)*100
            roi    = (cash - INITIAL_CASH)/INITIAL_CASH*100
            tp_ct  = len(df[df.reason == "TP"])
            sl_ct  = len(df[df.reason == "SL"])

            all_results.append({
                "Config":   cfg["name"],
                "Mode":     mode_name,
                "ATR_TP":   atr_tp,
                "ATR_SL":   atr_sl,
                "CONF":     min_conf,
                "Trades":   len(df),
                "WR%":      round(wr, 1),
                "TP":       tp_ct,
                "SL":       sl_ct,
                "AvgWin":   round(wins.pnl_pct.mean(), 2) if len(wins) else 0,
                "AvgLoss":  round(losses.pnl_pct.mean(), 2) if len(losses) else 0,
                "PnL$":     round(df.pnl_usd.sum(), 2),
                "ROI%":     round(roi, 2),
                "Final$":   round(cash, 2),
            })

            icon = "✅" if roi > 0 else "❌"
            print(f"  {icon} [{name}]")
            print(f"     ATR {atr_tp}/{atr_sl} CONF={min_conf}")
            print(f"     Trades={len(df)} WR={wr:.1f}% "
                  f"TP={tp_ct} SL={sl_ct}")
            print(f"     ROI={roi:+.2f}% Final=${cash:,.2f}\n")

    # ──────────────────── Summary ────────────────────
    print("=" * 65)
    print("  COMPARISON SUMMARY")
    print("=" * 65)
    summary = pd.DataFrame(all_results)

    # Sort by ROI
    summary = summary.sort_values("ROI%", ascending=False)

    cols = ["Config","Mode","ATR_TP","ATR_SL","Trades",
            "WR%","TP","SL","AvgWin","ROI%","Final$"]
    print(summary[cols].to_string(index=False))

    summary.to_csv("backtest_comparison.csv", index=False)
    print(f"\n  Saved → backtest_comparison.csv")

    # Show winner
    if not summary.empty:
        best = summary.iloc[0]
        print(f"\n🏆 Best: {best['Config']} ({best['Mode']})")
        print(f"   ATR {best['ATR_TP']}/{best['ATR_SL']} "
              f"ROI={best['ROI%']:+.2f}% "
              f"WR={best['WR%']}%")
    print("=" * 65)
    return summary


if __name__ == "__main__":
    run()
