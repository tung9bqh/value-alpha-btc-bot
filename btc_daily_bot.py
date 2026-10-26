#!/usr/bin/env python3
"""Value Alpha Crypto - BTC daily trading strategy poster (English channel).

Fetches BTC market data, builds a rule-based daily plan (bias, key levels,
long/short setups) and posts it to ONE Telegram channel: TELEGRAM_CHAT_ID.

The script only calls Telegram's sendMessage. It never calls getUpdates or
setWebhook, so a bot that already serves another (e.g. Vietnamese) community
with the same token keeps working untouched.

Usage:
    python btc_daily_bot.py --dry-run      # print the post, send nothing
    python btc_daily_bot.py                # post to TELEGRAM_CHAT_ID
    python btc_daily_bot.py --wait-until 08:30   # sleep until 08:30 local time first

Only the standard library is used.
"""

import argparse
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=int(os.environ.get("POST_TZ_OFFSET_HOURS", "7"))))  # Vietnam = UTC+7
CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "Value Alpha Crypto")
USER_AGENT = "ValueAlphaBTCBot/1.0"


# ---------------------------------------------------------------- data

def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_binance(interval, limit):
    # data-api.binance.vision serves public market data and, unlike
    # api.binance.com, is reachable from US-hosted GitHub runners.
    url = ("https://data-api.binance.vision/api/v3/klines?"
           + urllib.parse.urlencode({"symbol": "BTCUSDT", "interval": interval, "limit": limit}))
    rows = http_get_json(url)
    return [{"t": r[0] // 1000, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
             "c": float(r[4]), "v": float(r[5])} for r in rows]


def fetch_coinbase(granularity):
    url = ("https://api.exchange.coinbase.com/products/BTC-USD/candles?"
           + urllib.parse.urlencode({"granularity": granularity}))
    rows = http_get_json(url)  # newest first: [time, low, high, open, close, volume]
    return [{"t": r[0], "o": float(r[3]), "h": float(r[2]), "l": float(r[1]),
             "c": float(r[4]), "v": float(r[5])} for r in reversed(rows)]


def fetch_market():
    """Return (daily candles, intraday candles, intraday label, source)."""
    errors = []
    try:
        return fetch_binance("1d", 300), fetch_binance("4h", 200), "4H", "Binance BTC/USDT"
    except Exception as e:  # noqa: BLE001 - fall through to the next source
        errors.append(f"binance: {e}")
    try:
        return fetch_coinbase(86400), fetch_coinbase(21600), "6H", "Coinbase BTC/USD"
    except Exception as e:  # noqa: BLE001
        errors.append(f"coinbase: {e}")
    raise RuntimeError("All market data sources failed: " + "; ".join(errors))


# ---------------------------------------------------------- indicators

def ema(values, period):
    k = 2 / (period + 1)
    out = sum(values[:period]) / period
    for v in values[period:]:
        out = v * k + out * (1 - k)
    return out


def rsi(closes, period=14):
    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        d = cur - prev
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def atr(candles, period=14):
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
           for p, c in zip(candles, candles[1:])]
    out = sum(trs[:period]) / period
    for tr in trs[period:]:
        out = (out * (period - 1) + tr) / period
    return out


# ------------------------------------------------------------ analysis

def analyze(daily, intraday):
    price = intraday[-1]["c"]
    closes = [c["c"] for c in daily]
    y = daily[-2]  # last completed daily candle (UTC)

    pivot = (y["h"] + y["l"] + y["c"]) / 3
    levels = {
        "R2": pivot + (y["h"] - y["l"]),
        "R1": 2 * pivot - y["l"],
        "P": pivot,
        "S1": 2 * pivot - y["h"],
        "S2": pivot - (y["h"] - y["l"]),
    }
    week = intraday[-42:] if len(intraday) >= 42 else intraday  # ~7 days of 4H
    swing_high = max(c["h"] for c in week)
    swing_low = min(c["l"] for c in week)

    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    d_atr = atr(daily)
    rsi_d = rsi(closes)
    rsi_i = rsi([c["c"] for c in intraday])

    # 24h change measured on intraday candles so it is a true rolling 24h.
    bars_24h = max(1, round(86400 / (intraday[-1]["t"] - intraday[-2]["t"])))
    ref = intraday[-1 - bars_24h]["c"] if len(intraday) > bars_24h else intraday[0]["c"]
    change_24h = (price / ref - 1) * 100

    score = 0
    score += 1 if price > e20 else -1
    score += 1 if price > e50 else -1
    score += 1 if e20 > e50 else -1
    score += 1 if price > e200 else -1
    score += 1 if rsi_i > 55 else (-1 if rsi_i < 45 else 0)
    if score >= 3:
        bias = "BULLISH"
    elif score <= -3:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL / RANGE"

    # Candidate supports/resistances relative to the live price.
    cands = [("S1", levels["S1"]), ("S2", levels["S2"]), ("Pivot", levels["P"]),
             ("R1", levels["R1"]), ("R2", levels["R2"]), ("EMA20", e20), ("EMA50", e50),
             ("EMA200", e200), ("7D high", swing_high), ("7D low", swing_low)]
    min_gap = 0.15 * d_atr  # ignore levels practically at the current price
    supports = sorted([c for c in cands if c[1] < price - min_gap], key=lambda c: -c[1])
    resists = sorted([c for c in cands if c[1] > price + min_gap], key=lambda c: c[1])
    sup1 = supports[0] if supports else ("ATR support", price - d_atr)
    sup2 = next((s for s in supports[1:] if s[1] < sup1[1] - 0.3 * d_atr), ("ATR support", sup1[1] - d_atr))
    res1 = resists[0] if resists else ("ATR resistance", price + d_atr)
    res2 = next((r for r in resists[1:] if r[1] > res1[1] + 0.3 * d_atr), ("ATR resistance", res1[1] + d_atr))

    long_setup = {
        "entry_lo": sup1[1], "entry_hi": sup1[1] + 0.2 * d_atr, "entry_ref": sup1[0],
        "sl": sup1[1] - 0.6 * d_atr, "tp1": res1[1], "tp2": res2[1],
    }
    short_setup = {
        "entry_lo": res1[1] - 0.2 * d_atr, "entry_hi": res1[1], "entry_ref": res1[0],
        "sl": res1[1] + 0.6 * d_atr, "tp1": sup1[1], "tp2": sup2[1],
    }
    for s, side in ((long_setup, 1), (short_setup, -1)):
        mid = (s["entry_lo"] + s["entry_hi"]) / 2
        risk = abs(mid - s["sl"])
        s["rr1"] = abs(s["tp1"] - mid) / risk if risk else 0
        s["rr2"] = abs(s["tp2"] - mid) / risk if risk else 0

    return {
        "price": price, "change_24h": change_24h, "bias": bias, "score": score,
        "levels": levels, "e20": e20, "e50": e50, "e200": e200, "atr": d_atr,
        "rsi_d": rsi_d, "rsi_i": rsi_i, "swing_high": swing_high, "swing_low": swing_low,
        "sup1": sup1, "sup2": sup2, "res1": res1, "res2": res2,
        "long": long_setup, "short": short_setup,
    }


# -------------------------------------------------------------- format

def usd(x):
    return f"${round(x / 10) * 10:,.0f}"


def rsi_label(v):
    if v >= 70:
        return "overbought"
    if v <= 30:
        return "oversold"
    if v >= 55:
        return "bullish momentum"
    if v <= 45:
        return "bearish momentum"
    return "neutral"


def setup_block(title, s, side):
    verb = "Buy" if side == "long" else "Sell"
    return (
        f"<b>{title}</b>\n"
        f"• Entry: {verb} zone {usd(s['entry_lo'])} – {usd(s['entry_hi'])} ({html.escape(s['entry_ref'])})\n"
        f"• Stop-loss: {usd(s['sl'])}\n"
        f"• TP1: {usd(s['tp1'])} (R:R {s['rr1']:.1f}) | TP2: {usd(s['tp2'])} (R:R {s['rr2']:.1f})"
    )


def build_post(a, intraday_label, source, now):
    emoji = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(a["bias"], "🟡")
    arrow = "▲" if a["change_24h"] >= 0 else "▼"
    lv = a["levels"]

    if a["bias"] == "BULLISH":
        primary = setup_block("✅ Primary plan – LONG on pullback", a["long"], "long")
        alt = (f"<b>⚠️ Alternative</b>\n"
               f"A {intraday_label} close below {usd(a['long']['sl'])} invalidates the long idea; "
               f"expect a move toward {usd(a['sup2'][1])}. Breakout traders: a {intraday_label} close above "
               f"{usd(a['res1'][1])} opens {usd(a['res2'][1])}.")
        view = ("Trend structure favours buyers. Don't chase green candles – "
                "let price come back to support and buy with a defined stop.")
    elif a["bias"] == "BEARISH":
        primary = setup_block("✅ Primary plan – SHORT on rally", a["short"], "short")
        alt = (f"<b>⚠️ Alternative</b>\n"
               f"A {intraday_label} close above {usd(a['short']['sl'])} invalidates the short idea; "
               f"expect a squeeze toward {usd(a['res2'][1])}. Breakdown traders: a {intraday_label} close below "
               f"{usd(a['sup1'][1])} opens {usd(a['sup2'][1])}.")
        view = ("Sellers control the structure. Avoid catching knives – "
                "sell strength into resistance and keep size small.")
    else:
        primary = (setup_block("✅ Range plan – LONG near support", a["long"], "long") + "\n\n"
                   + setup_block("✅ Range plan – SHORT near resistance", a["short"], "short"))
        alt = (f"<b>⚠️ Breakout watch</b>\n"
               f"A {intraday_label} close above {usd(a['res1'][1])} → momentum long toward {usd(a['res2'][1])}. "
               f"A {intraday_label} close below {usd(a['sup1'][1])} → momentum short toward {usd(a['sup2'][1])}.")
        view = ("Mixed signals – BTC is ranging. Trade the edges, not the middle, "
                "and cut quickly if the range breaks.")

    return "\n".join([
        f"☀️ <b>{html.escape(CHANNEL_NAME)} | BTC Daily Strategy</b>",
        f"📅 {now:%a, %b %d, %Y} • {now:%H:%M} (UTC{now.utcoffset().total_seconds() / 3600:+g})",
        "",
        f"💰 <b>Price:</b> {usd(a['price'])} ({arrow} {a['change_24h']:+.2f}% 24h)",
        f"{emoji} <b>Bias:</b> {a['bias']}",
        "",
        "<b>📊 Market snapshot</b>",
        f"• EMA20 / EMA50 / EMA200 (D1): {usd(a['e20'])} / {usd(a['e50'])} / {usd(a['e200'])}",
        f"• RSI D1: {a['rsi_d']:.0f} ({rsi_label(a['rsi_d'])}) | RSI {intraday_label}: {a['rsi_i']:.0f} ({rsi_label(a['rsi_i'])})",
        f"• Daily ATR: {usd(a['atr'])} (expected daily range)",
        f"• 7D range: {usd(a['swing_low'])} – {usd(a['swing_high'])}",
        "",
        "<b>🎯 Key levels</b>",
        f"• Resistance: {usd(lv['R1'])} (R1) | {usd(lv['R2'])} (R2)",
        f"• Pivot: {usd(lv['P'])}",
        f"• Support: {usd(lv['S1'])} (S1) | {usd(lv['S2'])} (S2)",
        "",
        primary,
        "",
        alt,
        "",
        f"🧠 <b>Takeaway:</b> {view}",
        "",
        "🛡 Risk max 1–2% of capital per trade. Move SL to entry after TP1.",
        f"<i>Data: {html.escape(source)}. Educational content, not financial advice. DYOR.</i>",
    ])


# --------------------------------------------------------------- send

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Never echo the URL: it contains the bot token.
        raise RuntimeError(f"Telegram API error {e.code}: {e.read().decode(errors='replace')}") from None
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body}")
    return body["result"]["message_id"]


def wait_until(hhmm):
    h, m = map(int, hhmm.split(":"))
    now = datetime.now(TZ)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    delay = (target - now).total_seconds()
    if 0 < delay <= 3600:  # only wait if we started early (GitHub cron jitter)
        print(f"Waiting {delay:.0f}s until {hhmm} (UTC{now:%z})")
        time.sleep(delay)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="print the post instead of sending it")
    p.add_argument("--wait-until", metavar="HH:MM", help="sleep until this local time before posting")
    args = p.parse_args()

    if args.wait_until:
        wait_until(args.wait_until)

    daily, intraday, label, source = fetch_market()
    analysis = analyze(daily, intraday)

    text = build_post(analysis, label, source, datetime.now(TZ))
    if args.dry_run:
        print(text)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (English channel only).", file=sys.stderr)
        return 2
    message_id = send_telegram(token, chat_id, text)
    print(f"Posted message {message_id} to {chat_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
