```python
# ============================================================
# binance_client.py — Binance Global API Client (Clean Version)
# ============================================================

import math
import logging
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException

from config import (
    BINANCE_API_KEY, BINANCE_SECRET_KEY,
    BINANCE_TH_BASE_URL, USE_TESTNET,
    TRADE_AMOUNT_USDT, TAKE_PROFIT_PCT, STOP_LOSS_PCT,
    CANDLE_INTERVAL, CANDLE_LIMIT,
)

logger = logging.getLogger("TradingBot")


class BinanceTrader:
    def __init__(self):
        self.client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        if USE_TESTNET:
            self.client.API_URL = "https://testnet.binance.vision/api"
            logger.info("Binance connected (testnet=True)")
        else:
            self.client.API_URL = f"{BINANCE_TH_BASE_URL}/api"
            logger.info(f"Binance TH connected → {BINANCE_TH_BASE_URL}")

    def get_price(self, symbol: str) -> float:
        try:
            return float(self.client.get_symbol_ticker(symbol=symbol)["price"])
        except BinanceAPIException as e:
            logger.error(f"get_price {symbol}: {e}")
            return 0.0

    def get_candles(self, symbol: str, interval: str = None, limit: int = None) -> pd.DataFrame:
        klines = self.client.get_klines(
            symbol=symbol,
            interval=interval or CANDLE_INTERVAL,
            limit=limit or CANDLE_LIMIT,
        )
        df = pd.DataFrame(klines, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_buy_base",
            "taker_buy_quote","ignore",
        ])
        for col in ["open","high","low","close","volume"]:
            df[col] = pd.to_numeric(df[col])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        return df

    def get_candles_1h(self, symbol: str, limit: int = 200) -> pd.DataFrame:
        klines = self.client.get_klines(
            symbol=symbol, interval="1h", limit=limit,
        )
        df = pd.DataFrame(klines, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_buy_base",
            "taker_buy_quote","ignore",
        ])
        for col in ["open","high","low","close","volume"]:
            df[col] = pd.to_numeric(df[col])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        return df

    def get_symbol_info(self, symbol: str) -> dict:
        try:
            info   = self.client.get_symbol_info(symbol)
            result = {"step_size": 0.001, "tick_size": 0.01, "min_notional": 10.0}
            if info:
                for f in info.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        result["step_size"] = float(f["stepSize"])
                    elif f["filterType"] == "PRICE_FILTER":
                        result["tick_size"] = float(f["tickSize"])
                    elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                        result["min_notional"] = float(f.get("minNotional", 10.0))
            return result
        except Exception as e:
            logger.error(f"get_symbol_info {symbol}: {e}")
            return {"step_size": 0.001, "tick_size": 0.01, "min_notional": 10.0}

    def _round_qty(self, qty: float, step: float) -> float:
        """Always round qty to step_size"""
        if step <= 0:
            return qty
        precision = max(0, -int(math.log10(step))) if step < 1 else 0
        rounded   = round(int(qty / step) * step, precision)
        if rounded <= 0 and qty > 0:
            rounded = round(step, precision)
        return rounded

    def _calc_qty(self, symbol: str, price: float,
                  usdt_amount: float = None) -> float:
        if usdt_amount is None:
            usdt_amount = TRADE_AMOUNT_USDT
        info = self.get_symbol_info(symbol)
        raw  = usdt_amount / price
        return self._round_qty(raw, info["step_size"])

    def buy_limit(self, symbol: str, usdt_amount: float = None,
                  slippage_pct: float = 0.1,
                  timeout_s: int = 30) -> dict | None:
        """
        Try limit order first (lower than market slippage_pct%)
        If timeout → cancel → fallback market order
        Prevent slippage during volatile periods
        """
        import time as _time
        try:
            price       = self.get_price(symbol)
            if price <= 0: return None
            limit_price = round(price * (1 - slippage_pct/100), 8)
            info        = self.get_symbol_info(symbol)
            step        = info["step_size"]
            amount      = usdt_amount or TRADE_AMOUNT_USDT
            qty         = self._round_qty(amount / limit_price, step)

            if qty <= 0:
                return self.buy_market(symbol, amount)

            # Format price according to tick_size
            tick      = info["tick_size"]
            tick_prec = max(0, -int(math.log10(tick))) if tick < 1 else 0
            lp_str    = f"{limit_price:.{tick_prec}f}"

            logger.info(
                f"  [LIMIT] {symbol} qty={qty} @ ${limit_price:,.4f} "
                f"(market=${price:,.4f})"
            )
            order    = self.client.order_limit_buy(
                symbol=symbol, quantity=qty, price=lp_str
            )
            order_id = order.get("orderId")

            # Wait for fill
            start = _time.time()
            while _time.time() - start < timeout_s:
                _time.sleep(2)
                status = self.client.get_order(
```
```python
                    symbol=symbol, orderId=order_id)
                if status["status"] == "FILLED":
                    fills = status.get("fills", [])
                    if fills:
                        tc = sum(float(f["price"])*float(f["qty"]) for f in fills)
                        tq = sum(float(f["qty"]) for f in fills)
                        entry = tc/tq if tq > 0 else limit_price
                    else:
                        entry = limit_price
                    logger.info(f"  [LIMIT FILLED] {symbol} @ ${entry:,.4f}")
                    return {
                        "symbol":      symbol,
                        "qty":         self._round_qty(qty, step),
                        "entry_price": round(entry, 8),
                        "tp_price":    round(entry*(1+TAKE_PROFIT_PCT/100), 8),
                        "sl_price":    round(entry*(1-STOP_LOSS_PCT/100), 8),
                        "order_id":    order_id,
                    }
                elif status["status"] in ("CANCELED","REJECTED","EXPIRED"):
                    break

            # timeout → cancel
            try:
                self.client.cancel_order(symbol=symbol, orderId=order_id)
            except Exception:
                pass
            logger.warning(f"  [LIMIT TIMEOUT] {symbol} → market order")
            return self.buy_market(symbol, amount)

        except BinanceAPIException as e:
            logger.error(f"buy_limit {symbol}: {e}")
            return self.buy_market(symbol, usdt_amount)
        except Exception as e:
            logger.error(f"buy_limit {symbol} unexpected: {e}")
            return self.buy_market(symbol, usdt_amount)

    def buy_market(self, symbol: str, usdt_amount: float = None) -> dict | None:
        try:
            price = self.get_price(symbol)
            info  = self.get_symbol_info(symbol)
            step  = info["step_size"]
            qty   = self._round_qty(
                (usdt_amount or TRADE_AMOUNT_USDT) / price, step
            )

            if qty <= 0:
                logger.warning(f"buy_market {symbol}: qty={qty} too small")
                return None

            logger.info(f"BUY {symbol} qty={qty} @ ~${price:,.4f}")
            order = self.client.order_market_buy(symbol=symbol, quantity=qty)

            fills = order.get("fills", [])
            if fills:
                total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)
                total_qty  = sum(float(f["qty"]) for f in fills)
                entry      = total_cost / total_qty if total_qty > 0 else price
                real_qty   = self._round_qty(total_qty, step)
            else:
                entry    = price
                real_qty = qty

            tp = round(entry * (1 + TAKE_PROFIT_PCT / 100), 8)
            sl = round(entry * (1 - STOP_LOSS_PCT   / 100), 8)

            return {
                "symbol":      symbol,
                "qty":         real_qty,
                "entry_price": round(entry, 8),
                "tp_price":    tp,
                "sl_price":    sl,
                "order_id":    order.get("orderId"),
            }

        except BinanceAPIException as e:
            logger.error(f"buy_market {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"buy_market {symbol} unexpected: {e}")
            return None

    def sell_market(self, symbol: str, qty: float) -> dict | None:
        try:
            info  = self.get_symbol_info(symbol)
            step  = info["step_size"]

            # Get actual qty from Binance to handle BNB fee deductions
            asset = symbol.replace("USDT", "")
            try:
                bal      = self.client.get_asset_balance(asset=asset)
                real_bal = float(bal["free"]) if bal else qty
                # Use the smaller value between state qty and actual balance
                qty = min(qty, real_bal)
            except Exception:
                pass

            qty = self._round_qty(qty, step)

            if qty <= 0:
                logger.warning(f"sell_market {symbol}: qty={qty} too small")
                return None

            logger.info(f"SELL {symbol} qty={qty}")
            order = self.client.order_market_sell(symbol=symbol, quantity=qty)

            fills = order.get("fills", [])
            if fills:
                total_val  = sum(float(f["price"]) * float(f["qty"]) for f in fills)
                total_qty  = sum(float(f["qty"]) for f in fills)
                exit_price = total_val / total_qty if total_qty > 0 else 0
            else:
                exit_price = self.get_price(symbol)

            if exit_price == 0:
                exit_price = self.get_price(symbol)

            return {
                "exit_price": round(exit_price, 8),
                "order_id":   order.get("orderId"),
            }

        except BinanceAPIException as e:
            logger.error(f"sell_market {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"sell_market {symbol} unexpected: {e}")
            return None

    def get_usdt_balance(self) -> float:
        try:
            bal = self.client.get_asset_balance(asset="USDT")
            return float(bal["free"]) if bal else 0.0
        except Exception as e:
            logger.error(f"get_usdt_balance: {e}")
            return 0.0
```