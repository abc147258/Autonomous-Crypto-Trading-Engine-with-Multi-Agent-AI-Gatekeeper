```python
"""
Crypto Market Notifier
Send email with crypto market summary every time it runs
Uses all free APIs - no Claude tokens consumed
"""

import smtplib
import requests
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import json
import os
from config import EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER, WHALE_ALERT_API_KEY


def get_crypto_prices():
    """Fetch BTC/ETH prices from CoinGecko (free, no API key required)"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true"
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return {
            "btc": {
                "price": data["bitcoin"]["usd"],
                "change_24h": data["bitcoin"]["usd_24h_change"],
                "volume": data["bitcoin"]["usd_24h_vol"],
                "market_cap": data["bitcoin"]["usd_market_cap"]
            },
            "eth": {
                "price": data["ethereum"]["usd"],
                "change_24h": data["ethereum"]["usd_24h_change"],
                "volume": data["ethereum"]["usd_24h_vol"],
                "market_cap": data["ethereum"]["usd_market_cap"]
            }
        }
    except Exception as e:
        print(f"[!] CoinGecko error: {e}")
        return None


def get_fear_greed():
    """Fetch Fear & Greed Index from alternative.me (free)"""
    try:
        url = "https://api.alternative.me/fng/?limit=2"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()["data"]
        today = data[0]
        yesterday = data[1]
        return {
            "value": int(today["value"]),
            "label": today["value_classification"],
            "yesterday": int(yesterday["value"]),
            "yesterday_label": yesterday["value_classification"]
        }
    except Exception as e:
        print(f"[!] Fear & Greed error: {e}")
        return None


def get_crypto_news(max_items=5):
    """Fetch crypto news from CryptoPanic RSS (free)"""
    feeds = [
        "https://cryptopanic.com/news/rss/",
        "https://cointelegraph.com/rss",
    ]
    news = []
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_items]:
                news.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", "Crypto News"),
                    "published": entry.get("published", "")
                })
        except Exception as e:
            print(f"[!] RSS feed error ({feed_url}): {e}")
    return news[:max_items]


def get_whale_alerts():
    """Fetch whale transactions from Whale Alert API (free tier: 10 req/min)"""
    if not WHALE_ALERT_API_KEY or WHALE_ALERT_API_KEY == "YOUR_WHALE_ALERT_API_KEY":
        return []
    try:
        import time
        min_value = 1_000_000  # $1M and above
        url = "https://api.whale-alert.io/v1/transactions"
        params = {
            "api_key": WHALE_ALERT_API_KEY,
            "min_value": min_value,
            "start": int(time.time()) - 3600,  # Past 1 hour
            "limit": 5
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        txs = r.json().get("transactions", [])
        results = []
        for tx in txs[:5]:
            results.append({
                "amount": tx.get("amount", 0),
                "symbol": tx.get("symbol", "").upper(),
                "amount_usd": tx.get("amount_usd", 0),
                "from": tx.get("from", {}).get("owner_type", "unknown"),
                "to": tx.get("to", {}).get("owner_type", "unknown"),
                "blockchain": tx.get("blockchain", "")
            })
        return results
    except Exception as e:
        print(f"[!] Whale Alert error: {e}")
        return []


def format_number(n):
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"${n:,.0f}"
    return f"${n:.2f}"


def build_email_html(prices, fg, news, whales):
    """Build beautiful HTML email"""
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    # BTC/ETH section
    def price_block(symbol, data, color):
        chg = data["change_24h"]
        arrow = "▲" if chg >= 0 else "▼"
        chg_color = "#10b981" if chg >= 0 else "#ef4444"
        return f"""
        <td style="width:50%; padding:0 8px;">
          <div style="background:#1a1a2e; border:1px solid #2d2d4e; border-radius:12px; padding:20px; text-align:center;">
            <div style="color:#8888aa; font-size:12px; letter-spacing:2px; margin-bottom:6px;">{symbol}</div>
            <div style="color:#ffffff; font-size:28px; font-weight:700; margin-bottom:4px;">{format_number(data['price'])}</div>
            <div style="color:{chg_color}; font-size:14px; font-weight:600;">{arrow} {abs(chg):.2f}% (24h)</div>
            <div style="color:#666688; font-size:11px; margin-top:8px;">Vol: {format_number(data['volume'])}</div>
          </div>
        </td>"""

    price_html = ""
    if prices:
        price_html = f"""
        <table style="width:100%; border-collapse:collapse; margin-bottom:24px;">
          <tr>
            {price_block("₿ BTC", prices['btc'], "#f7931a")}
            {price_block("Ξ ETH", prices['eth'], "#627eea")}
```
```python
          </tr>
        </table>"""

    # Fear & Greed
    fg_html = ""
    if fg:
        v = fg["value"]
        if v <= 25:
            fg_color, fg_bg = "#ef4444", "#2d1a1a"
        elif v <= 45:
            fg_color, fg_bg = "#f97316", "#2d1e10"
        elif v <= 55:
            fg_color, fg_bg = "#eab308", "#2a2210"
        elif v <= 75:
            fg_color, fg_bg = "#84cc16", "#1a2510"
        else:
            fg_color, fg_bg = "#10b981", "#0f2520"

        delta = fg["value"] - fg["yesterday"]
        delta_str = f"{'▲' if delta >= 0 else '▼'} {abs(delta)} from yesterday ({fg['yesterday']} - {fg['yesterday_label']})"

        fg_html = f"""
        <div style="background:{fg_bg}; border:1px solid {fg_color}33; border-radius:12px; padding:20px; margin-bottom:24px; display:flex; align-items:center;">
          <div style="text-align:center; margin-right:24px; min-width:80px;">
            <div style="color:{fg_color}; font-size:42px; font-weight:800; line-height:1;">{v}</div>
            <div style="color:{fg_color}; font-size:12px; font-weight:600; margin-top:4px;">/100</div>
          </div>
          <div>
            <div style="color:#ffffff; font-size:16px; font-weight:600; margin-bottom:4px;">Fear & Greed: {fg['label']}</div>
            <div style="color:#8888aa; font-size:12px;">{delta_str}</div>
          </div>
        </div>"""

    # News
    news_html = ""
    if news:
        items = ""
        for n in news:
            items += f"""
            <tr>
              <td style="padding:10px 0; border-bottom:1px solid #2d2d4e;">
                <a href="{n['link']}" style="color:#a78bfa; text-decoration:none; font-size:13px; font-weight:500; display:block; margin-bottom:4px;">{n['title']}</a>
                <span style="color:#666688; font-size:11px;">{n['source']}</span>
              </td>
            </tr>"""
        news_html = f"""
        <div style="background:#16162a; border:1px solid #2d2d4e; border-radius:12px; padding:20px; margin-bottom:24px;">
          <div style="color:#8888aa; font-size:11px; letter-spacing:2px; margin-bottom:16px; font-weight:600;">📰 Latest News</div>
          <table style="width:100%; border-collapse:collapse;">{items}</table>
        </div>"""

    # Whale alerts
    whale_html = ""
    if whales:
        items = ""
        for w in whales:
            items += f"""
            <tr>
              <td style="padding:8px 0; border-bottom:1px solid #2d2d4e;">
                <span style="color:#fbbf24; font-weight:700;">{w['symbol']}</span>
                <span style="color:#ffffff; font-size:13px;"> {format_number(w['amount_usd'])} </span>
                <span style="color:#8888aa; font-size:12px;">{w['from']} → {w['to']} ({w['blockchain']})</span>
              </td>
            </tr>"""
        whale_html = f"""
        <div style="background:#16162a; border:1px solid #2d2d4e; border-radius:12px; padding:20px; margin-bottom:24px;">
          <div style="color:#8888aa; font-size:11px; letter-spacing:2px; margin-bottom:16px; font-weight:600;">🐋 WHALE MOVEMENTS (1h)</div>
          <table style="width:100%; border-collapse:collapse;">{items}</table>
        </div>"""
    elif WHALE_ALERT_API_KEY == "YOUR_WHALE_ALERT_API_KEY":
        whale_html = """
        <div style="background:#16162a; border:1px solid #2d2d4e; border-radius:12px; padding:16px; margin-bottom:24px; text-align:center;">
          <div style="color:#666688; font-size:12px;">🐋 Add Whale Alert API key in config.py to view whale movements</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#0d0d1a; font-family:'Segoe UI', Arial, sans-serif;">
  <div style="max-width:600px; margin:0 auto; padding:24px 16px;">

    <div style="text-align:center; margin-bottom:28px;">
      <div style="color:#a78bfa; font-size:11px; letter-spacing:3px; margin-bottom:8px; font-weight:600;">CRYPTO MARKET BRIEF</div>
      <div style="color:#666688; font-size:12px;">{now}</div>
    </div>

    {price_html}
    {fg_html}
    {news_html}
    {whale_html}

    <div style="text-align:center; color:#444466; font-size:11px; margin-top:16px;">
      Data: CoinGecko · Alternative.me · CryptoPanic · CoinTelegraph · Whale Alert<br>
      ⚠️ Not investment advice
    </div>
  </div>
</body>
</html>"""


def send_email(subject, html_body):
    """Send email via Gmail SMTP"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print(f"[✓] Email sent to {EMAIL_RECEIVER}")


def main():
    print("[*] Fetching market data...")

    prices = get_crypto_prices()
    fg = get_fear_greed()
    news = get_crypto_news()
    whales = get_whale_alerts()

    # Create subject
    subject_parts = ["🔔 Crypto Brief"]
    if prices:
        btc_chg = prices["btc"]["change_24h"]
        eth_chg = prices["eth"]["change_24h"]
        subject_parts.append(f"BTC {'▲' if btc_chg >= 0 else '▼'}{abs(btc_chg):.1f}%")
        subject_parts.append(f"ETH {'▲' if eth_chg >= 0 else '▼'}{abs(eth_chg):.1f}%")
    if fg:
        subject_parts.append(f"F&G: {fg['value']} ({fg['label']})")

    subject = " | ".join(subject_parts)

    html = build_email_html(prices, fg, news, whales)
    send_email(subject, html)
    print("[✓] Done!")


if __name__ == "__main__":
    main()
```