#!/usr/bin/env python3
"""Value Alpha Crypto - BTC daily multi-timeframe plan poster (English channel).

Pulls BTCUSDT.P (USDT-margined perpetual) candles for M15, M30, H1 and H4 from
Bitget (fallback: OKX BTC-USDT-SWAP), decides the day's direction (LONG or
SHORT), writes a short analysis, draws a 4-panel chart with the plan on it and
posts chart + text to ONE Telegram channel: TELEGRAM_CHAT_ID.

The script only calls Telegram's sendPhoto/sendMessage. It never calls
getUpdates or setWebhook, so a bot that already serves another (e.g.
Vietnamese) community with the same token keeps working untouched.

Usage:
    python btc_daily_bot.py --dry-run             # print post + save chart, send nothing
    python btc_daily_bot.py                       # post to TELEGRAM_CHAT_ID
    python btc_daily_bot.py --wait-until 08:30    # sleep until 08:30 local time first

Requires matplotlib (for the chart); everything else is standard library.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=int(os.environ.get("POST_TZ_OFFSET_HOURS", "7"))))  # Vietnam = UTC+7
CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "Value Alpha Crypto")
USER_AGENT = "ValueAlphaBTCBot/2.0"

# Display name -> (Bitget granularity, OKX bar, weight in the daily decision)
TIMEFRAMES = {
    "H4": ("4H", "4H", 0.40),
    "H1": ("1H", "1H", 0.30),
    "M30": ("30m", "30m", 0.17),
    "M15": ("15m", "15m", 0.13),
}
CAPTION_LIMIT = 1024  # Telegram limit for photo captions (visible characters)


# ---------------------------------------------------------------- data

def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def to_candles(rows):
    out = [{"t": int(r[0]) // 1000, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]),
            "c": float(r[4]), "v": float(r[5])} for r in rows]
    return sorted(out, key=lambda c: c["t"])


def fetch_bitget(granularity):
    url = ("https://api.bitget.com/api/v2/mix/market/candles?"
           + urllib.parse.urlencode({"symbol": "BTCUSDT", "productType": "USDT-FUTURES",
                                     "granularity": granularity, "limit": 300}))
    body = http_get_json(url)
    if body.get("code") != "00000" or not body.get("data"):
        raise RuntimeError(f"bad response: {str(body)[:200]}")
    return to_candles(body["data"])


def fetch_okx(bar):
    url = ("https://www.okx.com/api/v5/market/candles?"
           + urllib.parse.urlencode({"instId": "BTC-USDT-SWAP", "bar": bar, "limit": 300}))
    body = http_get_json(url)
    if body.get("code") != "0" or not body.get("data"):
        raise RuntimeError(f"bad response: {str(body)[:200]}")
    return to_candles(body["data"])


def fetch_market():
    """Return ({tf: candles}, source label). All timeframes come from one exchange."""
    errors = []
    for name, fetch, idx in (("Bitget", fetch_bitget, 0), ("OKX", fetch_okx, 1)):
        try:
            return {tf: fetch(spec[idx]) for tf, spec in TIMEFRAMES.items()}, name
        except Exception as e:  # noqa: BLE001 - fall through to the next exchange
            errors.append(f"{name}: {e}")
    raise RuntimeError("All market data sources failed: " + "; ".join(errors))


# ---------------------------------------------------------- indicators

def ema_series(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    out[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(closes, period=14):
    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        gains.append(max(cur - prev, 0.0))
        losses.append(max(prev - cur, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    return 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)


def atr(candles, period=14):
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
           for p, c in zip(candles, candles[1:])]
    out = sum(trs[:period]) / period
    for tr in trs[period:]:
        out = (out * (period - 1) + tr) / period
    return out


def macd_hist(closes):
    fast, slow = ema_series(closes, 12), ema_series(closes, 26)
    line = [f - s for f, s in zip(fast[25:], slow[25:])]
    signal = ema_series(line, 9)
    return [m - s for m, s in zip(line[8:], signal[8:])]


# ------------------------------------------------------------ analysis

def analyze_tf(candles):
    closes = [c["c"] for c in candles]
    e20, e50 = ema_series(closes, 20), ema_series(closes, 50)
    hist = macd_hist(closes)
    price = closes[-1]
    r = rsi(closes)
    score = (1 if price > e20[-1] else -1) + (1 if e20[-1] > e50[-1] else -1)
    score += 1 if r > 55 else (-1 if r < 45 else 0)
    score += 1 if hist[-1] > 0 else -1
    trend = "Bullish" if score >= 2 else ("Bearish" if score <= -2 else "Neutral")
    if price > e20[-1] > e50[-1]:
        stack = "above a bullish EMA20/50 stack"
    elif price < e20[-1] < e50[-1]:
        stack = "below a bearish EMA20/50 stack"
    else:
        stack = "between the EMA20 and EMA50"
    return {"score": score, "trend": trend, "rsi": r, "e20": e20, "e50": e50,
            "macd_rising": hist[-1] > hist[-2], "stack": stack, "atr": atr(candles)}


def key_levels(data, sig):
    h1, h4, m15 = data["H1"], data["H4"], data["M15"]
    yday = (datetime.fromtimestamp(h1[-1]["t"], timezone.utc) - timedelta(days=1)).date()
    prev_day = [c for c in h1 if datetime.fromtimestamp(c["t"], timezone.utc).date() == yday]
    levels = [
        ("H1 EMA20", sig["H1"]["e20"][-1]), ("H1 EMA50", sig["H1"]["e50"][-1]),
        ("H4 EMA20", sig["H4"]["e20"][-1]), ("H4 EMA50", sig["H4"]["e50"][-1]),
        ("24h high", max(c["h"] for c in h1[-24:])), ("24h low", min(c["l"] for c in h1[-24:])),
        ("3D high", max(c["h"] for c in h4[-18:])), ("3D low", min(c["l"] for c in h4[-18:])),
        ("M15 swing high", max(c["h"] for c in m15[-32:])), ("M15 swing low", min(c["l"] for c in m15[-32:])),
    ]
    if prev_day:
        levels += [("PDH", max(c["h"] for c in prev_day)), ("PDL", min(c["l"] for c in prev_day))]
    return levels


def build_plan(direction, price, levels, atr1h, atr4h):
    side = 1 if direction == "LONG" else -1
    gap = 0.2 * atr1h
    # Nearest level on the "entry" side of price (support for longs, resistance for shorts).
    entry_side = sorted([lv for lv in levels if side * (price - lv[1]) > gap], key=lambda lv: side * (price - lv[1]))
    target_side = sorted([lv for lv in levels if side * (lv[1] - price) > gap], key=lambda lv: side * (lv[1] - price))

    if entry_side and side * (price - entry_side[0][1]) <= 1.5 * atr4h:
        ref, edge = entry_side[0]
        far = edge
        near = edge + side * 0.3 * atr1h
        if side * (near - price) > 0:  # zone reaches current price
            near = price
    else:
        ref = "pullback"
        near, far = price - side * 0.3 * atr1h, price - side * 0.8 * atr1h
    sl = far - side * 0.6 * atr1h
    mid = (near + far) / 2
    risk = abs(mid - sl)

    targets = [lv for lv in target_side if side * (lv[1] - mid) >= 1.0 * risk]
    tp1 = targets[0][1] if targets else mid + side * 1.5 * risk
    more = [lv[1] for lv in targets if side * (lv[1] - tp1) >= 0.5 * risk]
    tp2 = more[0] if more else tp1 + side * max(risk, side * (mid + side * 2.5 * risk - tp1))
    lo, hi = sorted((near, far))
    return {"direction": direction, "entry_lo": lo, "entry_hi": hi, "entry_ref": ref, "sl": sl,
            "tp1": tp1, "tp2": tp2, "rr1": abs(tp1 - mid) / risk, "rr2": abs(tp2 - mid) / risk}


def analyze(data):
    sig = {tf: analyze_tf(c) for tf, c in data.items()}
    price = data["M15"][-1]["c"]
    h1 = data["H1"]
    change_24h = (price / h1[-25]["c"] - 1) * 100 if len(h1) > 25 else 0.0

    total = sum(TIMEFRAMES[tf][2] * sig[tf]["score"] / 4 for tf in TIMEFRAMES)  # -1 .. +1
    if total == 0:
        total = 0.01 if price > sig["H4"]["e50"][-1] else -0.01
    direction = "LONG" if total > 0 else "SHORT"
    confidence = "High" if abs(total) >= 0.6 else ("Medium" if abs(total) >= 0.3 else "Low")

    plan = build_plan(direction, price, key_levels(data, sig), sig["H1"]["atr"], sig["H4"]["atr"])
    return {"price": price, "change_24h": change_24h, "sig": sig, "total": total,
            "direction": direction, "confidence": confidence, "plan": plan}


def commentary(a):
    sig, long_ = a["sig"], a["direction"] == "LONG"
    h4, h1 = sig["H4"], sig["H1"]
    trend_word = {"Bullish": "bullish", "Bearish": "bearish", "Neutral": "undecided"}
    stack_agrees = ("bullish" in h4["stack"] and h4["trend"] == "Bullish") or \
                   ("bearish" in h4["stack"] and h4["trend"] == "Bearish")
    if stack_agrees or "between" in h4["stack"]:
        parts = [f"On H4, BTC trades {h4['stack']} with RSI {h4['rsi']:.0f}, "
                 f"so the higher-timeframe trend is {trend_word[h4['trend']]}."]
    else:
        parts = [f"On H4, BTC trades {h4['stack']}, but RSI {h4['rsi']:.0f} and MACD don't confirm, "
                 f"leaving the higher-timeframe trend {trend_word[h4['trend']]}."]

    if h1["trend"] == h4["trend"] and h1["trend"] != "Neutral":
        parts.append(f"H1 confirms it, with MACD momentum {'building' if h1['macd_rising'] == (h1['trend'] == 'Bullish') else 'cooling'}.")
    else:
        parts.append(f"H1 reads {trend_word[h1['trend']]} (RSI {h1['rsi']:.0f}), "
                     f"so the intraday picture is {'mixed' if h1['trend'] == 'Neutral' else 'diverging from H4'}.")

    want = "Bullish" if long_ else "Bearish"
    ltf = [sig["M30"]["trend"], sig["M15"]["trend"]]
    if all(t == want for t in ltf):
        parts.append("M30/M15 are aligned, so " + ("dips should be bought quickly." if long_ else "bounces should be sold quickly."))
    elif all(t not in (want, "Neutral") for t in ltf):
        parts.append("M30/M15 are still " + ("pulling back" if long_ else "bouncing")
                     + ", so wait for price to reach the entry zone instead of chasing.")
    else:
        parts.append("M30/M15 are mixed, so patience at the entry zone is key.")
    if a["confidence"] == "Low":
        parts.append("Signals are weak today: trade smaller.")
    return " ".join(parts)


# -------------------------------------------------------------- format

def usd(x, step=10):
    return f"{round(x / step) * step:,.0f}"


def build_post(a, source, now):
    p, sig = a["plan"], a["sig"]
    dot = {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "🟡"}
    arrow = "▲" if a["change_24h"] >= 0 else "▼"
    long_ = a["direction"] == "LONG"
    tf_lines = [f"{dot[sig[tf]['trend']]} {tf:<3} {sig[tf]['trend']} · RSI {sig[tf]['rsi']:.0f}" for tf in TIMEFRAMES]
    offset = now.utcoffset().total_seconds() / 3600
    return "\n".join([
        f"📊 <b>{html.escape(CHANNEL_NAME)} | BTC Daily Plan</b>",
        f"📅 {now:%a, %b %d, %Y} • {now:%H:%M} (UTC{offset:+g})",
        f"💰 <b>BTCUSDT.P:</b> ${usd(a['price'], 1)} ({arrow} {a['change_24h']:+.2f}% 24h)",
        "",
        "<b>🔎 Multi-timeframe</b>",
        *tf_lines,
        "",
        "<b>🧠 Analysis</b>",
        html.escape(commentary(a)),
        "",
        f"<b>🎯 TODAY: {a['direction']} {'🟢' if long_ else '🔴'}</b> (confidence: {a['confidence']})",
        f"• Entry: {usd(p['entry_lo'])} – {usd(p['entry_hi'])}",
        f"• SL: {usd(p['sl'])}",
        f"• TP1: {usd(p['tp1'])} ({p['rr1']:.1f}R) | TP2: {usd(p['tp2'])} ({p['rr2']:.1f}R)",
        f"• Invalid if H1 closes {'below' if long_ else 'above'} {usd(p['sl'])}",
        "",
        "🛡 Risk 1–2%/trade · Move SL to entry at TP1",
        f"<i>Data: {source} BTCUSDT.P. Not financial advice. DYOR.</i>",
    ])


def visible_len(text):
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


# --------------------------------------------------------------- chart

def draw_chart(data, a, source, now, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401 - used via matplotlib.ticker below

    bg, panel, grid, fg = "#0b0e11", "#12161c", "#1f2630", "#c9d1d9"
    up, down = "#2ebd85", "#f6465d"
    p = a["plan"]
    long_ = a["direction"] == "LONG"
    bars = {"H4": 42, "H1": 72, "M30": 80, "M15": 96}

    fig, axes = plt.subplots(2, 2, figsize=(16, 10), dpi=100, facecolor=bg)
    for ax, tf in zip(axes.flat, TIMEFRAMES):
        candles = data[tf][-bars[tf]:]
        n = len(candles)
        sig = a["sig"][tf]
        ax.set_facecolor(panel)
        for i, c in enumerate(candles):
            col = up if c["c"] >= c["o"] else down
            ax.vlines(i, c["l"], c["h"], color=col, linewidth=1)
            ax.bar(i, max(abs(c["c"] - c["o"]), 1e-6), bottom=min(c["o"], c["c"]), color=col, width=0.65)
        xs = range(n)
        ax.plot(xs, sig["e20"][-n:], color="#f0b90b", linewidth=1.2, label="EMA20")
        ax.plot(xs, sig["e50"][-n:], color="#3d8bfd", linewidth=1.2, label="EMA50")

        ax.axhspan(p["entry_lo"], p["entry_hi"], color="#3d8bfd", alpha=0.18)
        lines = [("ENTRY", (p["entry_lo"] + p["entry_hi"]) / 2, "#3d8bfd"), ("SL", p["sl"], down),
                 ("TP1", p["tp1"], up), ("TP2", p["tp2"], up)]
        ys = [c["l"] for c in candles] + [c["h"] for c in candles] + [y for _, y, _ in lines]
        pad = (max(ys) - min(ys)) * 0.05
        ymin, ymax = min(ys) - pad, max(ys) + pad
        ax.set_ylim(ymin, ymax)

        # Spread the labels so they never overlap, even when the levels are close.
        min_gap = (ymax - ymin) * 0.045
        placed = []
        for name, y, col in sorted(lines, key=lambda x: x[1]):
            ty = max(y, placed[-1] + min_gap) if placed else y
            placed.append(ty)
            ax.axhline(y, color=col, linestyle="--", linewidth=1)
            ax.text(n + 0.5, ty, f" {name} {usd(y)}", color=col, va="center", fontsize=9, fontweight="bold")
        ax.set_xlim(-1, n + max(12, int(n * 0.24)))  # room for the level labels
        ticks = list(range(0, n, max(1, n // 6)))
        fmt = "%d/%m" if tf == "H4" else "%H:%M"
        ax.set_xticks(ticks)
        ax.set_xticklabels([datetime.fromtimestamp(candles[i]["t"], TZ).strftime(fmt) for i in ticks])
        tcol = {"Bullish": up, "Bearish": down, "Neutral": "#f0b90b"}[sig["trend"]]
        ax.set_title(f"{tf}  •  {sig['trend']}  •  RSI {sig['rsi']:.0f}", color=tcol, loc="left",
                     fontsize=12, fontweight="bold")
        ax.tick_params(colors=fg, labelsize=8)
        ax.yaxis.tick_right()
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.grid(color=grid, linewidth=0.6)
        for s in ax.spines.values():
            s.set_color(grid)
        ax.legend(loc="best", fontsize=8, facecolor=panel, edgecolor=grid, labelcolor=fg, framealpha=0.85)
        ax.text(0.5, 0.5, CHANNEL_NAME, transform=ax.transAxes, ha="center", va="center",
                fontsize=26, color=fg, alpha=0.06, fontweight="bold")

    fig.suptitle(f"BTCUSDT.P ({source})  •  {now:%d %b %Y %H:%M} (UTC{now.utcoffset().total_seconds() / 3600:+g})"
                 f"   |   TODAY: {a['direction']}  ({a['confidence']} confidence)",
                 color=up if long_ else down, fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, facecolor=bg)
    plt.close(fig)
    return path


# --------------------------------------------------------------- send

def telegram_call(token, method, fields, files=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        for k, (fname, content, ctype) in files.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n").encode() + content + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    else:
        body = urllib.parse.urlencode(fields).encode()
        headers = {}
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Never echo the URL: it contains the bot token.
        raise RuntimeError(f"Telegram API error {e.code}: {e.read().decode(errors='replace')}") from None
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result["result"]["message_id"]


def send_post(token, chat_id, text, chart_path):
    with open(chart_path, "rb") as f:
        photo = ("btc_plan.png", f.read(), "image/png")
    if visible_len(text) <= CAPTION_LIMIT:
        return [telegram_call(token, "sendPhoto", {"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                              {"photo": photo})]
    # Too long for a caption: chart first, full text right after.
    first = telegram_call(token, "sendPhoto", {"chat_id": chat_id}, {"photo": photo})
    second = telegram_call(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                                  "disable_web_page_preview": "true"})
    return [first, second]


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
    p.add_argument("--dry-run", action="store_true", help="print the post and save the chart, send nothing")
    p.add_argument("--wait-until", metavar="HH:MM", help="sleep until this local time before posting")
    p.add_argument("--chart-out", default="btc_plan.png", help="where to save the chart image")
    args = p.parse_args()

    if args.wait_until:
        wait_until(args.wait_until)

    data, source = fetch_market()
    analysis = analyze(data)
    now = datetime.now(TZ)
    text = build_post(analysis, source, now)
    draw_chart(data, analysis, source, now, args.chart_out)

    if args.dry_run:
        print(text)
        print(f"\n[caption length {visible_len(text)}/{CAPTION_LIMIT}; chart saved to {args.chart_out}]")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (English channel only).", file=sys.stderr)
        return 2
    ids = send_post(token, chat_id, text, args.chart_out)
    print(f"Posted message(s) {ids} to {chat_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
