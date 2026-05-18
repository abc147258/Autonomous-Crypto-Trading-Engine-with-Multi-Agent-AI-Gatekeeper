```python
# ============================================================
# bot_controller.py — Read signal.json and start/stop bot.py
# Run separately: python bot_controller.py
# ============================================================

import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BOT_SCRIPT     = Path("bot.py")
SIGNAL_FILE    = Path("signal.json")
STOP_FLAG_FILE = Path("bot.stop")
CHECK_INTERVAL = 60      # Check every 60 seconds
SIGNAL_MAX_AGE = 7200    # Signal older than 2h = not trusted

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CTRL] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_controller.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("BotController")


class BotController:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.last_action  = None
        self.start_count  = 0
        self.stop_count   = 0
        self.stopped_reason = ""

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_bot(self, reason: str = ""):
        if self.is_running():
            return
        if STOP_FLAG_FILE.exists():
            STOP_FLAG_FILE.unlink()
        logger.info(f"▶ START bot.py — {reason}")
        self.process = subprocess.Popen(
            [sys.executable, str(BOT_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.last_action = "started"
        self.start_count += 1
        logger.info(f"  PID={self.process.pid}")

    def stop_bot(self, reason: str = ""):
        if not self.is_running():
            if STOP_FLAG_FILE.exists():
                STOP_FLAG_FILE.unlink()
            return
        logger.info(f"⏹ STOP bot.py — {reason}")
        STOP_FLAG_FILE.write_text(
            json.dumps({"reason": reason, "ts": datetime.now().isoformat()}),
            encoding="utf-8",
        )
        # Wait up to 120 seconds for graceful stop
        for i in range(24):
            time.sleep(5)
            if not self.is_running():
                logger.info(f"  Graceful stop in {(i+1)*5}s ✓")
                break
        else:
            logger.warning("  Force terminate")
            self.process.terminate()
            time.sleep(3)
            if self.is_running():
                self.process.kill()

        self.process = None
        self.last_action    = "stopped"
        self.stopped_reason = reason
        self.stop_count    += 1
        if STOP_FLAG_FILE.exists():
            STOP_FLAG_FILE.unlink()

    def read_signal(self) -> dict | None:
        if not SIGNAL_FILE.exists():
            logger.warning("signal.json not found — wait for notifier to run")
            return None
        try:
            data = json.loads(SIGNAL_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Read signal.json: {e}"); return None
        try:
            age = (datetime.now() - datetime.fromisoformat(
                data.get("updated_at",""))).total_seconds()
            if age > SIGNAL_MAX_AGE:
                logger.warning(f"Signal is {age/3600:.1f}h old — skipping")
                return None
        except Exception:
            pass
        return data

    def run(self):
        logger.info("=" * 50)
        logger.info("  Bot Controller started")
        logger.info(f"  Check signal every {CHECK_INTERVAL}s")
        logger.info("=" * 50)

        while True:
            try:
                sig = self.read_signal()
                now = datetime.now().strftime("%H:%M:%S")

                if sig is None:
                    logger.info(f"[{now}] No signal | bot={'running' if self.is_running() else 'stopped'}")
                    time.sleep(CHECK_INTERVAL)
                    continue

                should_stop = sig.get("should_stop_bot", False)
                reasons     = sig.get("stop_reasons", [])
                buys        = sig.get("buy_signals", [])
                mode        = sig.get("mode", "?")

                decision = "🔴 STOP" if should_stop else "🟢 RUN"
                reason_str = ", ".join(reasons) if reasons else "market neutral"
                buy_str = ", ".join(buys) if buys else "no buy signal"

                logger.info(f"[{now}] {'='*55}")
                logger.info(f"[{now}] Decision: {decision}")
                logger.info(f"[{now}] Market status: dead_vol={sig.get('market_dead')} | extreme_fear={sig.get('extreme_fear')} | F&G={sig.get('fg_value')} ({sig.get('fg_label','?')})")
                logger.info(f"[{now}] AI Analysis: {sig.get('ai_sentiment','?')} (score={sig.get('ai_score','?')})")
                logger.info(f"[{now}] {'─'*55}")

                # Display all pairs
                all_sig = sig.get("all_signals", {})
                if all_sig:
                    for pair, s in all_sig.items():
                        short = s.get("short", {})
                        mid   = s.get("mid", {})
                        short_act = short.get("action", "?")
                        mid_act   = mid.get("action", "?")
                        short_col = "BUY " if short_act == "BUY" else ("SELL" if short_act == "SELL" else "HOLD")
                        mid_col   = "BUY " if mid_act   == "BUY" else ("SELL" if mid_act   == "SELL" else "HOLD")
                        flag = " ⚡" if short_act == "BUY" or mid_act == "BUY" else ""
                        logger.info(
                            f"[{now}] {pair:<10}: "
                            f"short={short_col}({short.get('confidence','?')}%) "
```
```python
                            f"mid={mid_col}({mid.get('confidence','?')}%){flag}"
                        )
                else:
                    # fallback BTC/ETH original
                    logger.info(f"[{now}] {'BTCUSDT':<10}: short={sig.get('btc_short',{}).get('action','?')}({sig.get('btc_short',{}).get('confidence','?')}%) mid={sig.get('btc_mid',{}).get('action','?')}({sig.get('btc_mid',{}).get('confidence','?')}%)")
                    logger.info(f"[{now}] {'ETHUSDT':<10}: short={sig.get('eth_short',{}).get('action','?')}({sig.get('eth_short',{}).get('confidence','?')}%) mid={sig.get('eth_mid',{}).get('action','?')}({sig.get('eth_mid',{}).get('confidence','?')}%)")

                logger.info(f"[{now}] {'─'*55}")
                logger.info(f"[{now}] Reason: {reason_str if should_stop else buy_str}")
                logger.info(f"[{now}] Bot status: {'🟡 RUNNING' if self.is_running() else '⚫ STOPPED'}")
                logger.info(f"[{now}] {'='*55}")

                if should_stop and self.is_running():
                    self.stop_bot(", ".join(reasons) or "signal:stop")

                elif not should_stop and not self.is_running():
                    self.start_bot(", ".join(buys) or "market:active")

                # Check if bot died on its own
                if self.process and self.process.poll() is not None:
                    code = self.process.returncode
                    logger.warning(f"Bot exited on its own (exit={code})")
                    self.process = None
                    if code != 0:
                        logger.error("Bot crashed — waiting for signal before restart")

            except KeyboardInterrupt:
                logger.info("Controller stopped by user")
                self.stop_bot("user_interrupt")
                break
            except Exception as e:
                logger.error(f"Controller error: {e}")

            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    BotController().run()
```