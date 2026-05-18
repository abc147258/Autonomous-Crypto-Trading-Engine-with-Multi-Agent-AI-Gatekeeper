# ============================================================
# scheduler.py — Run notifier lite every 1h / full 3 times per day
# Run: python scheduler.py
# ============================================================

import schedule
import time
import subprocess
import sys
import os
from datetime import datetime

from config import FULL_CHECK_HOURS

DIR = os.path.dirname(os.path.abspath(__file__))


def _run(mode: str):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] scheduler → notifier {mode}")
    result = subprocess.run(
        [sys.executable, os.path.join(DIR, "notifier.py"), f"--mode={mode}"],
        capture_output=True, text=True,
    )
    if result.stdout: print(result.stdout.strip())
    if result.stderr: print("[err]", result.stderr[:200])


def run_lite(): _run("lite")
def run_full(): _run("full")


# Lite every 1 hour
schedule.every().hour.at(":00").do(run_lite)

# Full at times set in config
for t in FULL_CHECK_HOURS:
    schedule.every().day.at(t).do(run_full)

if __name__ == "__main__":
    print("[*] Scheduler started")
    print(f"[*] Lite: every 1h | Full: {FULL_CHECK_HOURS}")
    print("[*] Ctrl+C to stop\n")
    run_full()   # Run full once immediately
    while True:
        schedule.run_pending()
        time.sleep(30)