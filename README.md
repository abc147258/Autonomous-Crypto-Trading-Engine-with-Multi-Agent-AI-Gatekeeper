# 🤖 AI Crypto Trading Bot

ระบบเทรด cryptocurrency อัตโนมัติที่ใช้ Claude AI วิเคราะห์ตลาดและตัดสินใจซื้อขาย รองรับ 7 คู่เหรียญบน Binance พร้อมระบบ risk management ครบถ้วน

---

## ✨ Features

### Two-Stage AI Pipeline
- **Haiku** — กรองข่าวจาก RSS feeds ทุก 30 นาที ประหยัด token
- **Sonnet** — วิเคราะห์ indicators + ข่าว และกำหนด TP/SL/Trailing แบบ dynamic

### Smart Signal System
- Lite check ทุก 1 ชั่วโมง — ตรวจ indicators ไม่เรียก AI
- Full check วันละ 3 ครั้ง (08:00, 16:00, 00:00) — วิเคราะห์ครบทุกด้าน
- Dead vol detection — หยุด bot อัตโนมัติเมื่อตลาดนิ่ง

### Risk Management ครบถ้วน
- **Position sizing by confidence** — Sonnet มั่นใจมากลงเงินมาก (0.5x–2.0x)
- **Dynamic TP/SL** — คำนวณจาก ATR ตามสภาพตลาดจริง
- **Dynamic trailing stop** — Sonnet กำหนด activate/distance เอง
- **Daily loss limit** — หยุดเปิดใหม่ถ้าขาดทุนเกิน 5%/วัน
- **Portfolio stop loss** — หยุดทั้งระบบถ้า drawdown เกิน 15%
- **Fear & Greed filter** — ไม่ซื้อตอน Extreme Fear (F&G <= 15)

### Performance Tracking
- บันทึก win rate แยกตาม confidence band (55–64%, 65–74%, 75–84%, 85%+)
- แยกตาม market regime (BULL, BEAR, SIDEWAYS, HIGH_VOL)
- แยกตาม exit type (TP, SL, TRAIL_TP, TRAIL_SL, AI_SELL)

### Limit Order Protection
- พยายามซื้อด้วย limit order ก่อน (ต่ำกว่าตลาด 0.1%)
- timeout 30 วินาที → fallback market order อัตโนมัติ

---

## 🏗️ สถาปัตยกรรมระบบ

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

## 📁 โครงสร้างไฟล์

```
autob/
├── bot.py              # Main trading loop
├── ai_analyzer.py      # Two-stage AI pipeline (Haiku + Sonnet)
├── indicators.py       # Technical indicators (RSI, MACD, BB, EMA, ATR)
├── binance_client.py   # Binance API wrapper
├── fear_greed.py       # Fear & Greed Index (cache 1h)
├── notifier.py         # Signal analysis (lite/full mode)
├── signal_writer.py    # เขียน signal.json
├── bot_controller.py   # Start/stop bot อัตโนมัติ
├── scheduler.py        # รัน notifier ตาม schedule
├── backtest.py         # Backtest script
├── config.py           # อ่าน config จาก .env
├── .env                # API keys (ห้าม commit!)
├── .env.example        # Template สำหรับ setup
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🚀 การติดตั้ง

### 1. Clone และติดตั้ง dependencies

```bash
git clone https://github.com/yourusername/autob.git
cd autob
pip install -r requirements.txt
```

### 2. ตั้งค่า .env

```bash
cp .env.example .env
```

แก้ไขไฟล์ `.env` ใส่ค่าจริง:

```env
BINANCE_API_KEY=your_key_here
BINANCE_SECRET_KEY=your_secret_here
ANTHROPIC_API_KEY=sk-ant-...
EMAIL_SENDER=your@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECEIVER=your@gmail.com
```

### 3. ทดสอบ config

```bash
python config.py
```

ถ้าขึ้น `✅ config โหลดสำเร็จ` แสดงว่าพร้อมใช้งาน

---

## ▶️ วิธีรัน

เปิด 2 terminal พร้อมกัน:

```bash
# Terminal 1 — Signal System
python scheduler.py

# Terminal 2 — Bot Controller
python bot_controller.py
```

bot.py จะถูก start/stop อัตโนมัติตาม signal จาก notifier

---

## ⚙️ การตั้งค่า

ค่าทั้งหมดตั้งได้ใน `.env`:

| ตัวแปร | ค่าเริ่มต้น | คำอธิบาย |
|--------|------------|---------|
| `TRADING_PAIRS` | 7 pairs | เหรียญที่เทรด |
| `CANDLE_INTERVAL` | 4h | timeframe หลัก |
| `SCAN_INTERVAL_SECONDS` | 900 | scan ทุกกี่วินาที |
| `TAKE_PROFIT_PCT` | 8.0 | TP % (fallback) |
| `STOP_LOSS_PCT` | 4.0 | SL % (fallback) |
| `MAX_OPEN_TRADES` | 7 | position สูงสุดพร้อมกัน |
| `MIN_BUY_CONFIDENCE` | 55 | confidence ขั้นต่ำ |
| `PORTFOLIO_STOP_LOSS_PCT` | 15.0 | หยุดระบบถ้า DD เกิน % |
| `LIMIT_ORDER_SLIPPAGE_PCT` | 0.1 | limit order ต่ำกว่าตลาด % |
| `LIMIT_ORDER_TIMEOUT_S` | 30 | timeout ก่อน fallback |
| `MAX_DAILY_LOSS_PCT` | 5.0 | หยุดเปิดใหม่ถ้าขาดทุน % |

---

## 🔄 Flow การตัดสินใจ BUY

```
1. Portfolio DD > 15%?     → หยุดระบบ
2. Daily loss >= 5%?       → เช็ค TP/SL เท่านั้น
3. Regime = BEAR?          → SKIP pair นั้น
4. MTF 1h+4h = BEAR?       → SKIP pair นั้น
5. Indicators น่าสนใจ?     → ถ้าไม่ → HOLD (ไม่เรียก Sonnet)
6. Sonnet วิเคราะห์        → BUY/SELL/HOLD + TP/SL/Trailing
7. conf >= 55%?            → คำนวณ position size
8. F&G > 15?               → ส่ง limit order
9. Limit order fill?       → ตั้ง TP/SL/Trailing dynamic
```

---

## 💰 Position Sizing

| Confidence | Multiplier | ตัวอย่าง ($80 base) |
|-----------|-----------|-------------------|
| 55–64% | 0.5x | $40 |
| 65–74% | 1.0x | $80 |
| 75–84% | 1.5x | $120 |
| 85%+ | 2.0x | $160 |

cap สูงสุด 30% ของ portfolio ต่อ trade

---

## 📊 Backtest

```bash
# รันกับข้อมูลจริงจาก Binance
python backtest.py --start 2023-01-01 --interval 4h

# เฉพาะบาง pair
python backtest.py --pairs BTCUSDT ETHUSDT --cash 5000

# ได้ไฟล์ผลลัพธ์
# backtest_results.json
# equity_curve.csv
```

---

## 💸 ค่าใช้จ่าย API (ประมาณ)

| Model | การใช้งาน | ค่าใช้จ่าย/เดือน |
|-------|---------|----------------|
| Haiku | ดึงข่าว cache 30 นาที | ~$0.04 |
| Sonnet | ตัดสินใจ trade (4h interval) | ~$4.20 |
| **รวม** | | **~$4.24/เดือน** |

---

## 🔒 Security

- API keys เก็บใน `.env` ไม่มีใน code
- `.env` อยู่ใน `.gitignore` ห้าม push เด็ดขาด
- ตั้ง IP whitelist ใน Binance dashboard
- จำกัด permission ให้แค่ Spot trading (ไม่ต้องให้ withdraw)

---

## ⚠️ คำเตือน

ระบบนี้เป็น **experimental** ยังไม่ผ่านการทดสอบในตลาดจริงระยะยาว แนะนำให้:

1. ทดสอบด้วย `TRADE_AMOUNT_USDT=11` (ขั้นต่ำ Binance) ก่อน 2 สัปดาห์
2. ดู log อย่างสม่ำเสมอ
3. ไม่ใส่เงินมากกว่าที่รับความเสี่ยงได้
4. Crypto มีความเสี่ยงสูง ราคาผันผวนมาก

---

## 📄 License

MIT License — ใช้ได้ฟรี ดัดแปลงได้ แต่ไม่รับผิดชอบต่อความเสียหายที่เกิดจากการใช้งาน
