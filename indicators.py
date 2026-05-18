```python
"""
indicators.py — Calculate technical indicators from Binance OHLCV
No heavy libraries needed, all calculated manually
"""
import requests


def get_ohlcv(symbol="BTCUSDT", interval="1d", limit=200):
    """Fetch OHLCV from Binance public API (no key required)"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    candles = r.json()
    closes = [float(c[4]) for c in candles]
    highs  = [float(c[2]) for c in candles]
    lows   = [float(c[3]) for c in candles]
    volumes= [float(c[5]) for c in candles]
    return closes, highs, lows, volumes


def calc_rsi(closes, period=14):
    """RSI 14"""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def calc_ema(closes, period):
    """EMA"""
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)


def calc_sma(closes, period):
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def calc_macd(closes):
    """MACD (12, 26, 9) — returns macd, signal, histogram"""
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if ema12 is None or ema26 is None:
        return None, None, None
    macd_line = ema12 - ema26
    # approximate signal using last 9 MACD values
    macd_vals = []
    for i in range(max(26, len(closes)-20), len(closes)):
        e12 = calc_ema(closes[:i+1], 12)
        e26 = calc_ema(closes[:i+1], 26)
        if e12 and e26:
            macd_vals.append(e12 - e26)
    signal = calc_ema(macd_vals, 9) if len(macd_vals) >= 9 else None
    histogram = round(macd_line - signal, 2) if signal else None
    return round(macd_line, 2), signal, histogram


def calc_bollinger(closes, period=20, std_mult=2):
    """Bollinger Bands — returns upper, middle, lower"""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = variance ** 0.5
    return round(mid + std_mult * std, 2), round(mid, 2), round(mid - std_mult * std, 2)


def calc_volume_signal(volumes):
    """Compare 24h volume vs 20-day average"""
    if len(volumes) < 20:
        return None, None
    avg20 = sum(volumes[-20:]) / 20
    current = volumes[-1]
    ratio = round(current / avg20, 2)
    return round(current, 0), round(avg20, 0), ratio


def get_all_indicators(symbol="BTCUSDT"):
    """Combine all indicators for 1 coin"""
    try:
        # Daily candles for mid-term
        closes_d, highs_d, lows_d, vols_d = get_ohlcv(symbol, "1d", 200)
        # 4h candles for short-term
        closes_4h, _, _, vols_4h = get_ohlcv(symbol, "4h", 100)

        current_price = closes_d[-1]

        # Short-term (4h)
        rsi_short  = calc_rsi(closes_4h, 14)
        macd_s, macd_sig_s, macd_h_s = calc_macd(closes_4h)
        bb_up_s, bb_mid_s, bb_low_s  = calc_bollinger(closes_4h)

        # Mid-term (daily)
        rsi_mid    = calc_rsi(closes_d, 14)
        ma50       = calc_sma(closes_d, 50)
        ma200      = calc_sma(closes_d, 200)
        macd_m, macd_sig_m, macd_h_m = calc_macd(closes_d)
        bb_up_m, bb_mid_m, bb_low_m  = calc_bollinger(closes_d)
        vol_cur, vol_avg, vol_ratio   = calc_volume_signal(vols_d)

        return {
            "symbol": symbol,
            "price": current_price,
            "short": {
                "rsi": rsi_short,
                "macd": macd_s,
                "macd_signal": macd_sig_s,
                "macd_hist": macd_h_s,
                "bb_upper": bb_up_s,
                "bb_lower": bb_low_s,
                "bb_mid": bb_mid_s,
            },
            "mid": {
                "rsi": rsi_mid,
                "ma50": ma50,
                "ma200": ma200,
                "macd": macd_m,
                "macd_signal": macd_sig_m,
                "macd_hist": macd_h_m,
                "bb_upper": bb_up_m,
                "bb_lower": bb_low_m,
                "bb_mid": bb_mid_m,
                "volume_ratio": vol_ratio,
            }
        }
    except Exception as e:
        print(f"[!] Indicator error ({symbol}): {e}")
        return None
```