# 🤖 AI Crypto Trading Bot

An automated cryptocurrency trading system powered by Claude AI for market analysis and trade decisions. Supports 7 trading pairs on Binance with comprehensive risk management.

---

## ✨ Features

### Two-Stage AI Pipeline
- **Haiku** — Filters news from RSS feeds every 30 minutes, saving tokens
- **Sonnet** — Analyzes indicators + news and dynamically sets TP/SL/Trailing

### Smart Signal System
- Lite check every 1 hour — checks indicators without calling AI
- Full check 3 times per day (08:00, 16:00, 00:00) — comprehensive analysis
- Dead vol detection — automatically stops bot when market is inactive

### Comprehensive Risk Management
- **Position sizing by confidence** — Higher Sonnet confidence = larger position (0.5x–2.0x)
- **Dynamic TP/SL** — Calculated from ATR based on real market conditions
- **Dynamic trailing stop** — Sonnet determines activate/distance automatically
- **Daily loss limit** — Stops opening new positions if daily loss exceeds 5%
- **Portfolio stop loss** — Stops entire system if drawdown exceeds 15%
- **Fear & Greed filter** — No buying during Extreme Fear (F&G <= 15)

### Performance Tracking
- Records win rate by confidence band (55–64%, 65–74%, 75–84%, 85%+)
- Breakdown by market regime (BULL, BEAR, SIDEWAYS, HIGH_VOL)
- Breakdown by exit type (TP, SL, TRAIL_TP, TRAIL_SL, AI_SELL)

### Limit Order Protection
- Attempts limit order first (0.1% below market price)
- 30-second timeout → automatic fallback to market order

### AI Learning System
- Learns from losing trades using Haiku analysis
- Identifies patterns that caused losses
- Sends analytical context to Sonnet — learning, not avoiding
- Automatically adjusts signal weights based on loss history

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────┐
│              Signal System                   │
│  scheduler.py → notifier.py → signal.json   │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│              Orchestration                   │
│         bot_controller.py                    │
│         (start/stop bot.py)                  │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│              Trading Bot                     │
│  bot.py → ai_analyzer.py → binance_client   │
└─────────────────────────────────────────────┘
```

---

## 📁 File Structure

```
auto2/
├── bot.py              # Main trading loop
├── ai_analyzer.py      # Two-stage AI pipeline (Haiku + Sonnet)
├── signals.py          # Rule-based signal scoring (10 indicators)
├── lesson_engine.py    # AI learning system
├── indicators.py       # Technical indicators (RSI, MACD, BB, EMA, ATR)
├── binance_client.py   # Binance API wrapper
├── fear_greed.py       # Fear & Greed Index (1h cache)
├── notifier.py         # Signal analysis (lite/full mode)
├── crypto_notifier.py  # HTML email notifications
├── signal_writer.py    # Writes signal.json
├── bot_controller.py   # Start/stop bot automatically
├── scheduler.py        # Runs notifier on schedule
├── backtest.py         # Backtest script (No Signal vs With Signal)
├── config.py           # Reads config from .env
├── .env                # API keys (never commit!)
├── .env.example        # Template for setup
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🚀 Installation

### 1. Clone and install dependencies

```bash
git clone https://github.com/yourusername/auto2.git
cd auto2
pip install -r requirements.txt
```

### 2. Configure .env

```bash
cp .env.example .env
```

Edit `.env` with your real values:

```env
BINANCE_API_KEY=your_key_here
BINANCE_SECRET_KEY=your_secret_here
ANTHROPIC_API_KEY=sk-ant-...
EMAIL_SENDER=your@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECEIVER=your@gmail.com
```

### 3. Test configuration

```bash
python config.py
```

---

## ▶️ Running the Bot

Open 2 terminals simultaneously:

```bash
# Terminal 1 — Signal System
python scheduler.py

# Terminal 2 — Bot Controller
python bot_controller.py
```

`bot.py` will be automatically started/stopped based on signals from the notifier.

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| TRADING_PAIRS | 7 pairs | Coins to trade |
| CANDLE_INTERVAL | 4h | Primary timeframe |
| SCAN_INTERVAL_SECONDS | 900 | Scan frequency in seconds |
| TAKE_PROFIT_PCT | 8.0 | TP % (fallback) |
| STOP_LOSS_PCT | 4.0 | SL % (fallback) |
| MAX_OPEN_TRADES | 7 | Maximum simultaneous positions |
| MIN_BUY_CONFIDENCE | 65 | Minimum confidence to buy |
| PORTFOLIO_STOP_LOSS_PCT | 15.0 | Stop system if DD exceeds % |
| LIMIT_ORDER_SLIPPAGE_PCT | 0.1 | Limit order below market % |
| LIMIT_ORDER_TIMEOUT_S | 30 | Timeout before fallback |
| MAX_DAILY_LOSS_PCT | 5.0 | Stop new positions if loss exceeds % |

---

## 🔄 BUY Decision Flow

```
1. Portfolio DD > 15%?       → Stop entire system
2. Daily loss >= 5%?         → Check TP/SL only
3. Regime = BEAR?            → SKIP this pair
4. MTF 1h+4h = BEAR?         → SKIP this pair
5. Indicators interesting?   → If not → HOLD (skip Sonnet)
6. Sonnet analyzes           → BUY/SELL/HOLD + TP/SL/Trailing
7. conf >= 65%?              → Calculate position size
8. F&G > 15?                 → Send limit order
9. Limit order filled?       → Set dynamic TP/SL/Trailing
```

---

## 💰 Position Sizing

| Confidence | Multiplier | Example ($80 base) |
|-----------|-----------|-------------------|
| 55–64% | 0.5x | $40 |
| 65–74% | 1.0x | $80 |
| 75–84% | 1.5x | $120 |
| 85%+ | 2.0x | $160 |

Maximum cap: 30% of portfolio per trade

---

## 📊 Backtest Results

```bash
# Run backtest — compares No Signal vs With Signal modes
python backtest.py
```

Best result: **High_Conf_WithSignal**
- ATR_TP=4.2 | ATR_SL=2.8 | CONF=0.65
- ROI = +112.50% | Win Rate = 43.5% | Trades = 588

---

## 💸 Estimated API Cost

| Model | Usage | Cost/Month |
|-------|-------|------------|
| Haiku | News filtering (cached 30 min) | ~$0.04 |
| Sonnet | Trade decisions (4h interval) | ~$4.20 |
| **Total** | | **~$4.24/month** |

---

## 🔒 Security

- API keys stored in `.env` — never in code
- `.env` is in `.gitignore` — never push to GitHub
- IP whitelist configured in Binance dashboard
- API permission limited to Spot trading only (no withdrawal allowed)

---

## ⚠️ Disclaimer

This system is **experimental** and has not been tested in live markets long-term.

1. Start with minimum trade size (e.g. $11/trade) for at least 2 weeks
2. Monitor logs regularly
3. Never invest more than you can afford to lose
4. Cryptocurrency trading carries significant risk

---

## 📄 License

MIT License — Free to use and modify. No liability for any losses incurred from use of this software.

<img width="1891" height="878" alt="image" src="https://github.com/user-attachments/assets/2481432f-695f-46bc-926c-f83a27295b26" />

