#!/usr/bin/env python3
"""Value Alpha Crypto - BTC daily multi-timeframe plan poster (English channel).

Pulls BTCUSDT.P (USDT-margined perpetual) candles for M15, M30, H1 and H4 from
Bitget (fallback: OKX BTC-USDT-SWAP), decides the day's primary bias (LONG or
SHORT), writes the multi-timeframe analysis with a primary and a
breakdown/breakout setup (fixed % stop-loss, TP1/TP2 by R:R), draws an M15
plan image and posts image + text to ONE Telegram channel: TELEGRAM_CHAT_ID.

The script only calls Telegram's sendPhoto/sendMessage. It never calls
getUpdates or setWebhook, so a bot that already serves another (e.g.
Vietnamese) community with the same token keeps working untouched.

Usage:
    python btc_daily_bot.py --dry-run             # print post + save image, send nothing
    python btc_daily_bot.py                       # post to TELEGRAM_CHAT_ID
    python btc_daily_bot.py --wait-until 08:30    # sleep until 08:30 local time first

Requires matplotlib (for the image); everything else is standard library.
"""

import argparse
import html
import json
import os
import random
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
ALTCOIN_POOL = [c.strip() for c in os.environ.get(
    "ALTCOIN_POOL", "ETH,SOL,XAUT,BNB,LTC,SUI,XRP,LINK,AVAX,DOT,NEAR,ADA,DOGE,UNI,ZEC").split(",") if c.strip()]
ALTCOIN_PICKS = 5
SL_PCT = float(os.environ.get("SL_PCT", "1.25"))  # stop-loss distance from entry, in %
TP_PCTS = (float(os.environ.get("TP1_PCT", "1.0")), float(os.environ.get("TP2_PCT", "1.6")))  # from entry, in %
ENTRY_DIST_PCT = 0.35  # entry this far from the current price, inside the analysed zone
ZONE_HALF_PCT = 0.10   # zone = entry +/- this
SR_NEAR_PCT = 0.40     # price within this of a support/resistance level counts as "at" the level
USER_AGENT = "ValueAlphaBTCBot/3.0"

# Display name -> (Bitget granularity, OKX bar, weight in the daily decision)
TIMEFRAMES = {
    "H4": ("4H", "4H", 0.20),
    "H1": ("1H", "1H", 0.35),
    "M30": ("30m", "30m", 0.25),
    "M15": ("15m", "15m", 0.20),
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
                                     "granularity": granularity, "limit": 600}))
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


def pivots(candles, k=3, key="h"):
    """Swing highs (key='h') or lows (key='l'): bars more extreme than k bars on each side."""
    pick = max if key == "h" else min
    return [candles[i][key] for i in range(k, len(candles) - k)
            if candles[i][key] == pick(c[key] for c in candles[i - k:i + k + 1])]


# ------------------------------------------------------------ analysis

def analyze_tf(candles):
    """Trend score of one timeframe from -6 to +6: price vs EMA20/50/200, EMA20 vs EMA50, RSI, MACD."""
    closes = [c["c"] for c in candles]
    e20, e50, e200 = ema_series(closes, 20), ema_series(closes, 50), ema_series(closes, 200)
    hist = macd_hist(closes)
    price = closes[-1]
    r = rsi(closes)
    above = {n: (price > e[-1]) for n, e in ((20, e20), (50, e50), (200, e200)) if e[-1] is not None}
    score = sum(1 if up else -1 for up in above.values())
    score += 1 if e20[-1] > e50[-1] else -1
    score += 1 if r > 55 else (-1 if r < 45 else 0)
    score += 1 if hist[-1] > 0 else -1
    trend = "Bullish" if score >= 3 else ("Bearish" if score <= -3 else "Neutral")
    return {"score": score, "trend": trend, "rsi": r, "e20": e20, "e50": e50, "e200": e200, "above": above,
            "macd": hist[-1], "macd_rising": hist[-1] > hist[-2], "atr": atr(candles),
            "e20_slope": (e20[-1] - e20[-4]) / price}


def nearest_sr(data, sig, price):
    """Nearest resistance above and support below price, from swing points, yesterday's range and EMA200s."""
    h4, h1 = data["H4"], data["H1"]
    levels = [(f"H4 swing high", v) for v in pivots(h4[-90:], 3, "h")[-5:]]
    levels += [(f"H4 swing low", v) for v in pivots(h4[-90:], 3, "l")[-5:]]
    levels += [(f"H1 swing high", v) for v in pivots(h1[-72:], 3, "h")[-5:]]
    levels += [(f"H1 swing low", v) for v in pivots(h1[-72:], 3, "l")[-5:]]
    yday = (datetime.fromtimestamp(h1[-1]["t"], TZ) - timedelta(days=1)).date()
    prev_day = [c for c in h1 if datetime.fromtimestamp(c["t"], TZ).date() == yday]
    if prev_day:
        levels += [("yesterday's high", max(c["h"] for c in prev_day)), ("yesterday's low", min(c["l"] for c in prev_day))]
    for tf in ("H4", "H1"):
        if sig[tf]["e200"][-1] is not None:
            levels.append((f"{tf} EMA200", sig[tf]["e200"][-1]))
    above = sorted((lv for lv in levels if lv[1] > price), key=lambda lv: lv[1])
    below = sorted((lv for lv in levels if lv[1] < price), key=lambda lv: -lv[1])
    return (above[0] if above else None), (below[0] if below else None)


def analyze(data):
    sig = {tf: analyze_tf(c) for tf, c in data.items()}
    price = data["M15"][-1]["c"]
    total = sum(TIMEFRAMES[tf][2] * sig[tf]["score"] / 6 for tf in TIMEFRAMES)  # -1 .. +1
    if total == 0:
        total = 0.01 if price > sig["H4"]["e50"][-1] else -0.01
    res, sup = nearest_sr(data, sig, price)
    at_res = res is not None and (res[1] - price) / price * 100 <= SR_NEAR_PCT
    at_sup = sup is not None and (price - sup[1]) / price * 100 <= SR_NEAR_PCT
    m15, h1, h4 = sig["M15"], sig["H1"], sig["H4"]
    strong_up = h4["score"] >= 4 and h1["score"] >= 4
    strong_down = h4["score"] <= -4 and h1["score"] <= -4

    # Default: trade with the multi-timeframe trend. At a key level with stretched RSI and
    # fading momentum, fade the level instead - unless H4 and H1 both trend hard through it.
    setup, direction = "trend", ("LONG" if total > 0 else "SHORT")
    if at_res and max(m15["rsi"], h1["rsi"]) >= 60 and not m15["macd_rising"] and not strong_up:
        setup, direction = "resistance", "SHORT"
    elif at_sup and min(m15["rsi"], h1["rsi"]) <= 40 and m15["macd_rising"] and not strong_down:
        setup, direction = "support", "LONG"
    agree = abs(total) if (total > 0) == (direction == "LONG") else 0
    confidence = "High" if agree >= 0.6 else ("Medium" if agree >= 0.3 or setup != "trend" else "Low")
    a = {"price": price, "sig": sig, "total": total, "direction": direction, "setup": setup,
         "confidence": confidence, "res": res, "sup": sup, "at_res": at_res, "at_sup": at_sup}
    a["primary"] = build_setup(data, sig, price, direction)
    return a


def candidate_levels(data, sig):
    h1, m15 = data["H1"], data["M15"]
    yday = (datetime.fromtimestamp(h1[-1]["t"], TZ) - timedelta(days=1)).date()
    prev_day = [c for c in h1 if datetime.fromtimestamp(c["t"], TZ).date() == yday]
    levels = []
    for tf in ("H4", "H1", "M15"):
        for n in (20, 50, 200):
            v = sig[tf][f"e{n}"][-1]
            if v is not None:
                levels.append((f"{tf} EMA{n}", v))
    levels += [(f"the {k_fmt(v, 100)} H4 swing high", v) for v in pivots(data["H4"][-90:], 3, "h")[-4:]]
    levels += [(f"the {k_fmt(v, 100)} H4 swing low", v) for v in pivots(data["H4"][-90:], 3, "l")[-4:]]
    levels += [(f"the {k_fmt(v, 100)} swing high", v) for v in pivots(h1[-72:], 3, "h")[-4:]]
    levels += [(f"the {k_fmt(v, 100)} swing low", v) for v in pivots(h1[-72:], 3, "l")[-4:]]
    levels += [(f"the {k_fmt(v, 100)} M15 swing high", v) for v in pivots(m15[-96:], 4, "h")[-3:]]
    levels += [(f"the {k_fmt(v, 100)} M15 swing low", v) for v in pivots(m15[-96:], 4, "l")[-3:]]
    if prev_day:
        levels += [("yesterday's high", max(c["h"] for c in prev_day)),
                   ("yesterday's low", min(c["l"] for c in prev_day))]
    return levels


def build_setup(data, sig, price, direction):
    """Entry ~0.35% from price inside the analysed zone; fixed % stop and targets; structural cancel level."""
    side = 1 if direction == "LONG" else -1
    levels = candidate_levels(data, sig)
    target = price * (1 - side * ENTRY_DIST_PCT / 100)
    # Snap the entry to a confluence level when one sits close to the 0.35% mark.
    near = [lv for lv in levels if 0.25 <= side * (price - lv[1]) / price * 100 <= 0.45]
    entry = min(near, key=lambda lv: abs(lv[1] - target))[1] if near else target
    half = entry * ZONE_HALF_PCT / 100
    lo, hi = round_to(entry - half, 10), round_to(entry + half, 10)
    entry = (lo + hi) / 2
    reasons = [name for name, v in levels if lo - 2 * half <= v <= hi + 2 * half]

    sl = entry * (1 - side * SL_PCT / 100)
    st = {"direction": direction, "lo": lo, "hi": hi, "entry": entry, "sl": sl,
          "tp1": entry * (1 + side * TP_PCTS[0] / 100), "tp2": entry * (1 + side * TP_PCTS[1] / 100),
          "reasons": list(dict.fromkeys(reasons))[:3]}
    recent = data["H1"][-24:]
    st["guard"] = max(c["h"] for c in recent) if side == -1 else min(c["l"] for c in recent)

    # Cancel: the nearest structure level beyond the zone (but before the stop). An H1 close
    # through it means BTC is moving against the analysis, so the plan is dropped early.
    beyond = [lv for lv in levels if side * (lv[1] - (lo if side == 1 else hi)) < 0
              and abs(lv[1] - entry) / entry * 100 >= 0.4 and side * (lv[1] - sl) > 0]
    if beyond:
        ref = min(beyond, key=lambda lv: abs(lv[1] - entry))
        st["cancel"], st["cancel_ref"] = ref[1], ref[0]
    else:
        st["cancel"], st["cancel_ref"] = entry * (1 - side * 0.6 * SL_PCT / 100), None
    return st


# -------------------------------------------------------------- format

def round_to(x, step):
    return round(x / step) * step


def k_fmt(x, step=10):
    """82000 -> '82K', 80450 -> '80.45K', 80800 -> '80.8K'."""
    v = round_to(x, step) / 1000
    return f"{v:,.2f}".rstrip("0").rstrip(".") + "K"


def join_words(items):
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def ema_position(sg):
    """'below EMA20/50/200', 'above EMA20/50/200' or 'above EMA20, below EMA50/200'."""
    ups = [str(n) for n, up in sg["above"].items() if up]
    downs = [str(n) for n, up in sg["above"].items() if not up]
    parts = ([f"above EMA{'/'.join(ups)}"] if ups else []) + ([f"below EMA{'/'.join(downs)}"] if downs else [])
    return ", ".join(parts)


def momentum(sg):
    if sg["macd"] > 0:
        return "bullish momentum building" if sg["macd_rising"] else "bullish momentum fading"
    return "bearish momentum fading" if sg["macd_rising"] else "bearish momentum building"


def mtf_summary(a, data):
    """One chained paragraph H4 -> H1 -> M30/M15 (EMA20/50/200, RSI, momentum, S/R) plus a conclusion."""
    sig, price, short = a["sig"], a["price"], a["direction"] == "SHORT"
    h4, h1, m30, m15 = (sig[tf] for tf in ("H4", "H1", "M30", "M15"))
    swings = pivots(data["H4"][-90:], 3, "h" if short else "l")[-4:]
    trending = len(swings) >= 2 and all((b < x) if short else (b > x) for x, b in zip(swings, swings[1:]))
    structure = ""
    if trending:
        structure = f" with {'lower highs' if short else 'higher lows'} ({k_fmt(swings[0], 100)} → {k_fmt(swings[-1], 100)})"
    chain = (f"H4 trades {ema_position(h4)}{structure} (RSI {h4['rsi']:.0f}, {momentum(h4)}); "
             f"H1 is {ema_position(h1)} (RSI {h1['rsi']:.0f}); "
             + (f"M30/M15 are {ema_position(m15)}" if ema_position(m30) == ema_position(m15)
                else f"M30 is {ema_position(m30)} and M15 {ema_position(m15)}")
             + f" (RSI {m15['rsi']:.0f}, {momentum(m15)}).")
    res, sup = a["res"], a["sup"]
    if a["at_res"]:
        chain += f" Price is testing resistance at {k_fmt(res[1], 100)} ({res[0]})."
    elif a["at_sup"]:
        chain += f" Price is testing support at {k_fmt(sup[1], 100)} ({sup[0]})."
    elif res and sup:
        chain += f" Nearest resistance {k_fmt(res[1], 100)}, support {k_fmt(sup[1], 100)}."

    want = "Bearish" if short else "Bullish"
    aligned = sum(sig[tf]["trend"] == want for tf in TIMEFRAMES)
    if a["setup"] == "resistance":
        conclusion = (f"Price is at resistance with stretched RSI and fading momentum — favour a SHORT from this "
                      f"level, with tight risk as the higher-timeframe trend is {h4['trend'].lower()}.")
    elif a["setup"] == "support":
        conclusion = (f"Price is at support with stretched RSI and recovering momentum — favour a LONG from this "
                      f"level, with tight risk as the higher-timeframe trend is {h4['trend'].lower()}.")
    elif h4["trend"] == want and aligned >= 3:
        conclusion = (f"Timeframes are aligned to the {'downside' if short else 'upside'} — "
                      f"{'sell the rebound into the zone' if short else 'buy the dip into the zone'} rather than chasing.")
    elif h4["trend"] == want:
        conclusion = (f"The H4 {'downtrend' if short else 'uptrend'} is intact while lower timeframes are mixed — "
                      f"wait for the {'rebound' if short else 'pullback'} to stall at the zone before entering.")
    else:
        conclusion = "Signals are mixed and the bias is weak — trade smaller and only on clear confirmation."
    if a["setup"] == "trend" and ((a["at_res"] and not short) or (a["at_sup"] and short)):
        lvl = res if a["at_res"] else sup
        conclusion += f" Price is pressing into {k_fmt(lvl[1], 100)}: let it {'pull back' if not short else 'bounce'} first."
    return chain, conclusion


def setup_lines(st):
    return [f"• Entry: {k_fmt(st['entry'])} | SL: {k_fmt(st['sl'])} | "
            f"TP1: {k_fmt(st['tp1'])} | TP2: {k_fmt(st['tp2'])}"]


def pick_altcoins(now):
    """Five random coins from the pool; seeded by date so every run on the same day agrees."""
    return random.Random(now.strftime("%Y-%m-%d")).sample(ALTCOIN_POOL, min(ALTCOIN_PICKS, len(ALTCOIN_POOL)))


def build_post(a, data, now):
    short = a["direction"] == "SHORT"
    p = a["primary"]
    word = "Short" if short else "Long"
    zone = f"{k_fmt(p['lo'])}–{k_fmt(p['hi'])}"
    if p["reasons"]:
        why = f"This area aligns with {join_words(p['reasons'])}"
    else:
        why = "This area marks the nearest " + ("rebound" if short else "pullback") + " zone from current price"
    g = p["guard"]
    if short and g > p["hi"]:
        why += f", while remaining below the recent {k_fmt(g, 100)} high"
    elif not short and g < p["lo"]:
        why += f", while holding above the recent {k_fmt(g, 100)} low"
    alts = join_words([f"${c}" for c in pick_altcoins(now)])
    chain, conclusion = mtf_summary(a, data)

    lines = [
        f"{'📉' if short else '📈'} <b>BTCUSDT UPDATE — {now:%B %d, %Y}</b>".upper().replace("<B>", "<b>").replace("</B>", "</b>"),
        "",
        f"{'🔴' if short else '🟢'} <b>PRIMARY BIAS: {a['direction']}</b>",
        "",
        "🔎 <b>MULTI-TIMEFRAME ANALYSIS</b>",
        html.escape(chain),
        "",
        f"👉 <b>Conclusion:</b> {html.escape(conclusion)}",
        "",
        f"🎯 <b>KEY {a['direction']} ZONE</b>",
        "",
        f"{'🔴' if short else '🟢'} <b>Primary {word}: {zone}</b>",
        f"Wait for price to {'rebound' if short else 'pull back'} into this zone (~{ENTRY_DIST_PCT:g}% from current "
        f"price) and show {'bearish' if short else 'bullish'} rejection. {html.escape(why)}.",
        *setup_lines(p),
        "",
        f"🚫 <b>Cancel {word} Scenario</b>",
        f"• An H1 candle closes {'above' if short else 'below'} {k_fmt(p['cancel'])}"
        + (f" ({html.escape(p['cancel_ref'])})" if p.get("cancel_ref") else "")
        + " — BTC is moving against the analysis: exit or stand aside.",
        f"• Price {'drops' if short else 'rallies'} to {k_fmt(p['tp1'])} before reaching the zone — "
        "the move has played out: do not chase.",
        "• The zone is not reached by the end of the day — the plan expires.",
        "",
        "📊 <b>ALTCOIN WATCHLIST</b>",
        f"Keep an eye on {alts}. Combine our trading indicators with technical analysis and wait for "
        "confirmation before entering any trade.",
        "",
        "⚠️ <i>This analysis is for reference only, not financial advice. Always manage your risk and "
        "trade according to your plan.</i>",
    ]
    return "\n".join(lines)


def morning_status(state_dir, data, now):
    """One sentence on how this morning's plan has played out so far (None if unknown)."""
    if not state_dir:
        return None
    path = os.path.join(state_dir, "plans", f"{now:%Y-%m-%d}.json")
    if not os.path.exists(path):
        return None
    import plan_tracker
    with open(path) as f:
        plan = json.load(f)
    res = plan_tracker.replay(plan, data["M15"], int(now.timestamp()))
    word = plan["direction"].title()
    kinds = [e["kind"] for e in res["events"]]
    if res["status"] == "unknown":
        return None
    if not kinds:
        return f"The morning {word} plan has not been triggered yet."
    last = kinds[-1]
    return {
        "entry": f"The morning {word} is open from {k_fmt(plan['entry'])}.",
        "tp1": f"The morning {word} has hit TP1 ({k_fmt(plan['tp1'])}); the rest runs with the stop at entry.",
        "tp2": f"The morning {word} has reached TP2 ({k_fmt(plan['tp2'])}).",
        "sl": f"The morning {word} was stopped out at {k_fmt(plan['sl'])}.",
        "be": f"The morning {word} took TP1, then closed the rest at entry.",
        "cancelled": f"The morning {word} plan was cancelled before entry.",
        "cancel_exit": f"The morning {word} was closed early as price broke the cancel level.",
        "skipped": f"The morning {word} played out without a retrace (TP1 hit before entry).",
    }.get(last)


def tonight_news(now):
    """High-impact USD events between now and 08:30 tomorrow, as a short phrase (None if none/unavailable)."""
    try:
        import econ_calendar
        feed = http_get_json(econ_calendar.FEED_URL, timeout=20)
        events = econ_calendar.todays_events(feed, now.astimezone(timezone.utc).replace(second=0, microsecond=0))
    except Exception:  # noqa: BLE001 - the outlook is still useful without the news line
        return None
    end = (now + timedelta(days=1)).replace(hour=8, minute=30)
    items = [f"{e['title']} ({'time TBD' if e['tentative'] else e['time'].astimezone(TZ).strftime('%H:%M')})"
             for e in events if e["time"] < end]
    return join_words(items[:4]) if items else None


def build_us_post(a, data, now, state_dir=None):
    """Short evening outlook for the US session: context since the morning + bias + levels."""
    short = a["direction"] == "SHORT"
    p, sig, price = a["primary"], a["sig"], a["price"]
    start = now.replace(hour=8, minute=30, second=0, microsecond=0).timestamp()
    since = [c for c in data["M15"] if c["t"] >= start] or data["M15"][-40:]
    chg = (price / since[0]["o"] - 1) * 100
    lo, hi = min(c["l"] for c in since), max(c["h"] for c in since)
    h1, m15 = sig["H1"], sig["M15"]

    context = [f"Since this morning BTC has moved {chg:+.1f}% to {k_fmt(price, 100)}, "
               f"trading in a {k_fmt(lo, 100)}–{k_fmt(hi, 100)} range."]
    status = morning_status(state_dir, data, now)
    if status:
        context.append(status)
    context.append(f"H1 is {ema_position(h1)} (RSI {h1['rsi']:.0f}) and M15 is {ema_position(m15)} "
                   f"with {momentum(m15)}.")
    res, sup = a["res"], a["sup"]
    if a["at_res"]:
        context.append(f"Price is testing resistance at {k_fmt(res[1], 100)}.")
    elif a["at_sup"]:
        context.append(f"Price is testing support at {k_fmt(sup[1], 100)}.")
    elif res and sup:
        context.append(f"Key levels: resistance {k_fmt(res[1], 100)}, support {k_fmt(sup[1], 100)}.")

    zone = f"{k_fmt(p['lo'])}–{k_fmt(p['hi'])}"
    if a["setup"] == "resistance":
        plan = f"For the US session, favour a SHORT from resistance at {zone} once price shows rejection."
    elif a["setup"] == "support":
        plan = f"For the US session, favour a LONG from support at {zone} once price shows a bounce."
    else:
        plan = (f"For the US session, favour {'SHORT' if short else 'LONG'}: "
                f"{'sell a rebound into' if short else 'buy a pullback into'} {zone} rather than chasing the move.")
    plan += (f" Cancel the idea if an H1 candle closes {'above' if short else 'below'} {k_fmt(p['cancel'])}.")
    news = tonight_news(now)

    lines = [
        f"🌙 <b>BTC — US SESSION OUTLOOK | {now:%b %d}</b>".upper().replace("<B>", "<b>").replace("</B>", "</b>"),
        f"{'🔴' if short else '🟢'} <b>BIAS: {a['direction']}</b>",
        "",
        html.escape(" ".join(context)),
        "",
        html.escape(plan),
        *setup_lines(p),
    ]
    if news:
        lines += ["", f"⚠️ <b>Tonight:</b> {html.escape(news)} — expect volatility, avoid entries right before releases."]
    lines += ["", "<i>Not financial advice. Manage your risk.</i>"]
    return "\n".join(lines)


def visible_len(text):
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


# --------------------------------------------------------------- image

def draw_plan_image(data, a, now, path, session=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401 - used as matplotlib.ticker below
    from matplotlib.patches import Ellipse, FancyBboxPatch
    from matplotlib.transforms import blended_transform_factory

    bg, fg, muted, grid = "#07090d", "#f5f5f5", "#9aa4b2", "#161b22"
    gold, up, down, cyan = "#f0b429", "#22c55e", "#ff3b4e", "#22d3ee"
    short = a["direction"] == "SHORT"
    accent = down if short else up
    p = a["primary"]

    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=bg)
    ov = fig.add_axes([0, 0, 1, 1])
    ov.set_xlim(0, 1)
    ov.set_ylim(0, 1)
    ov.axis("off")
    ov.set_zorder(2)
    ov.patch.set_alpha(0)

    def box(x, y, w, h, edge, face="#0d1117", lw=2, r=0.012):
        ov.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                    linewidth=lw, edgecolor=edge, facecolor=face, mutation_aspect=16 / 9))

    # ---- header
    ov.add_patch(Ellipse((0.048, 0.915), 0.066, 0.066 * 16 / 9, color="#f7931a"))
    ov.text(0.048, 0.912, "B", color="white", fontsize=40, fontweight="bold", ha="center", va="center")
    for dx in (-0.006, 0.004):
        ov.plot([0.048 + dx, 0.048 + dx], [0.955, 0.968], color="white", lw=3, solid_capstyle="butt")
        ov.plot([0.048 + dx, 0.048 + dx], [0.856, 0.869], color="white", lw=3, solid_capstyle="butt")
    ov.text(0.094, 0.918, "BTCUSDT", color=fg, fontsize=50, fontweight="bold", va="center")
    ov.plot([0.345, 0.345], [0.875, 0.96], color="#5b6270", lw=1.5)
    box(0.36, 0.868, 0.50, 0.10, accent, face="#1a0b0e" if short else "#0b1a10")
    ov.text(0.385, 0.918, "PRIMARY SCENARIO:", color=fg, fontsize=30, fontweight="bold", va="center")
    ov.text(0.71, 0.918, a["direction"], color=accent, fontsize=36, fontweight="bold", va="center")
    box(0.094, 0.79, 0.13, 0.055, gold, face=bg, lw=1.6, r=0.008)
    ov.text(0.159, 0.817, f"{now:%d/%m/%Y}", color=fg, fontsize=17, fontweight="bold", ha="center", va="center")
    box(0.237, 0.79, 0.055, 0.055, gold, face=bg, lw=1.6, r=0.008)
    ov.text(0.2645, 0.817, "M15", color=gold, fontsize=17, fontweight="bold", ha="center", va="center")
    if session:
        box(0.305, 0.79, 0.135, 0.055, accent, face=bg, lw=1.6, r=0.008)
        ov.text(0.3725, 0.817, session, color=accent, fontsize=15, fontweight="bold", ha="center", va="center")

    # ---- M15 chart
    candles = data["M15"][-260:]
    n = len(candles)
    sig = a["sig"]["M15"]
    ax = fig.add_axes([0.012, 0.06, 0.60, 0.70], facecolor=bg)
    for i, c in enumerate(candles):
        col = up if c["c"] >= c["o"] else down
        ax.vlines(i, c["l"], c["h"], color=col, linewidth=0.8)
        ax.bar(i, max(abs(c["c"] - c["o"]), 1e-6), bottom=min(c["o"], c["c"]), color=col, width=0.7)
    for key, col in (("e20", "#facc15"), ("e50", "#3b82f6"), ("e200", "#a855f7")):
        ys = sig[key][-n:]
        pts = [(i, y) for i, y in enumerate(ys) if y is not None]
        if pts:
            ax.plot(*zip(*pts), color=col, linewidth=1.3)

    price = a["price"]
    zone_mid = (p["lo"] + p["hi"]) / 2
    warn = "#f59e0b"
    levels = [p["sl"], p["tp1"], p["tp2"], p["lo"], p["hi"], p["cancel"]]
    ys = [c["l"] for c in candles] + [c["h"] for c in candles] + levels
    span = max(ys) - min(ys)
    ymin, ymax = min(ys) - span * 0.06, max(ys) + span * 0.14
    xmax = n + 50  # room on the right for the scenario arrows and the level labels
    ax.set_xlim(-2, xmax)
    ax.set_ylim(ymin, ymax)

    # plan zone + SL/TP + cancel level; labels are spread so they never overlap
    zx0 = n - 70
    ax.fill_between([zx0, xmax], p["lo"], p["hi"], color=accent, alpha=0.32, linewidth=0)
    ax.hlines([p["lo"], p["hi"]], zx0, xmax, color=accent, linewidth=1, alpha=0.8)
    marks = [("SL", p["sl"], down, (0, (5, 4))), ("TP1", p["tp1"], up, (0, (5, 4))),
             ("TP2", p["tp2"], up, (0, (5, 4))), ("CANCEL", p["cancel"], warn, (0, (8, 3, 2, 3)))]
    last_y = None
    for name, y, col, style in sorted(marks, key=lambda m: m[1]):
        ax.hlines(y, n - 62, xmax, color=col, linestyle=style, linewidth=1.2, zorder=4)
        ty = y if last_y is None else max(y, last_y + span * 0.045)
        last_y = ty
        ax.text(xmax - 0.5, ty + span * 0.008, f"{name} {k_fmt(y)}", color=col, fontsize=10, fontweight="bold",
                ha="right", va="bottom", zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", facecolor=bg, edgecolor="none", alpha=0.85))

    # scenario arrow: retrace into the zone, then continue in the bias direction
    x0, x1, x2 = n + 1, n + 9, n + 21
    y_end = zone_mid - (zone_mid - price) * 2.0
    y_end = max(y_end, ymin + span * 0.05) if short else min(y_end, ymax - span * 0.05)
    ax.plot([x0, x1], [price, zone_mid], color=accent, linewidth=3, solid_capstyle="round", zorder=5)
    ax.annotate("", xy=(x2, y_end), xytext=(x1, zone_mid), zorder=5,
                arrowprops=dict(arrowstyle="-|>,head_width=0.6,head_length=1.0", color=accent, linewidth=3))

    # cancel illustration: BTC pushes through the cancel level instead -> plan dropped
    c_end = p["cancel"] + (span * 0.06 if short else -span * 0.06)
    c_end = min(max(c_end, ymin + span * 0.03), ymax - span * 0.03)
    ax.annotate("", xy=(n + 20, c_end), xytext=(x0, price), zorder=4,
                arrowprops=dict(arrowstyle="-|>,head_width=0.45,head_length=0.8", color=warn, linewidth=1.8,
                                linestyle=(0, (4, 3)), alpha=0.9))
    cross_x = x0 + (n + 20 - x0) * (p["cancel"] - price) / (c_end - price)
    ax.plot([cross_x], [p["cancel"]], marker="X", markersize=13, color=warn, markeredgecolor=bg, zorder=6)
    ax.text(n + 20, c_end + (span * 0.015 if short else -span * 0.015), "PLAN CANCELLED", color=warn,
            fontsize=9, fontweight="bold", ha="center", va="bottom" if short else "top", zorder=6,
            bbox=dict(boxstyle="round,pad=0.2", facecolor=bg, edgecolor="none", alpha=0.85))

    # callout: first spot near the zone that clears the level lines and the recent candles
    cx = n - 48
    win = candles[max(0, cx - 14):cx + 14]
    c_lo, c_hi = min(c["l"] for c in win), max(c["h"] for c in win)
    half = span * 0.075
    marks_y = [m[1] for m in marks]
    away = 1 if short else -1  # zone side first
    options = [p["hi"] + span * 0.16, p["hi"] + span * 0.3, p["lo"] - span * 0.16, p["lo"] - span * 0.3,
               ymax - span * 0.1, ymin + span * 0.1]
    if away == -1:
        options = options[2:4] + options[:2] + options[4:]
    options = [y for y in options if ymin + span * 0.08 <= y <= ymax - span * 0.08] or [(ymin + ymax) / 2]

    def clash(y):
        return (sum(abs(y - m) < half for m in marks_y) + (p["lo"] - half < y < p["hi"] + half) * 2
                + (not (y + half < c_lo or y - half > c_hi)))
    cy = min(options, key=clash)
    ax.text(cx, cy, f"{a['direction']} ZONE:\n{k_fmt(p['lo'])} – {k_fmt(p['hi'])}",
            color=fg, fontsize=15, fontweight="bold", ha="center", va="center", linespacing=1.4, zorder=7,
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#1a0b0e" if short else "#0b1a10",
                      edgecolor=accent, linewidth=2))

    # current price
    ax.axhline(price, color=cyan, linestyle=(0, (2, 2)), linewidth=1)
    tr = blended_transform_factory(ax.transAxes, ax.transData)
    ax.text(1.012, price, f"Current price\n~{k_fmt(price, 100)}", transform=tr, color="#001018", fontsize=11,
            fontweight="bold", ha="left", va="center", linespacing=1.2,
            bbox=dict(boxstyle="round,pad=0.35", facecolor=cyan, edgecolor=cyan))

    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.tick_params(colors=muted, labelsize=11, length=0)
    ticks, labels = [], []
    for i, c in enumerate(candles):
        t = datetime.fromtimestamp(c["t"], TZ)
        if t.minute == 0 and t.hour in (0, 12):
            ticks.append(i)
            labels.append(f"{t:%d}" if t.hour == 0 else "12:00")
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.grid(color=grid, linewidth=0.6)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.text(0.5, 0.5, CHANNEL_NAME, transform=ax.transAxes, ha="center", va="center", fontsize=40,
            color=fg, alpha=0.05, fontweight="bold")

    # ---- right panel: entry conditions
    box(0.705, 0.30, 0.282, 0.555, gold, face="#0d0f14")
    ov.text(0.728, 0.80, "◎", color=gold, fontsize=30, va="center", ha="center")
    ov.text(0.75, 0.80, "ENTRY CONDITIONS", color=gold, fontsize=22, fontweight="bold", va="center")
    zone_txt = f"{k_fmt(p['lo'])} – {k_fmt(p['hi'])}"
    items = [
        (f"Price {'rebounds' if short else 'pulls back'} into", zone_txt),
        (f"{'Bearish' if short else 'Bullish'} rejection /\nreversal candle appears", None),
        (f"M15 confirms the {'failed bounce' if short else 'bounce holds'},\nideally aligned with M30 – H1", None),
    ]
    for k, (txt, hl) in enumerate(items):
        y = 0.685 - k * 0.135
        ov.add_patch(Ellipse((0.737, y), 0.036, 0.036 * 16 / 9, facecolor="#0d0f14", edgecolor=gold, linewidth=2))
        ov.text(0.737, y, str(k + 1), color=gold, fontsize=20, fontweight="bold", ha="center", va="center")
        if hl:
            ov.text(0.768, y + 0.022, txt, color=fg, fontsize=15, va="center")
            ov.text(0.768, y - 0.022, hl, color=gold, fontsize=16, fontweight="bold", va="center")
        else:
            ov.text(0.768, y, txt, color=fg, fontsize=15, va="center", linespacing=1.35)
        if k < 2:
            ov.plot([0.72, 0.972], [y - 0.068, y - 0.068], color="#2a2f3a", linewidth=1)

    # ---- warning box
    box(0.705, 0.06, 0.282, 0.20, accent, face="#1a0b0e" if short else "#0b1a10")
    ov.text(0.745, 0.16, "⚠", color=accent, fontsize=48, ha="center", va="center")
    ov.text(0.79, 0.195, f"Don't FOMO {a['direction']}", color=accent, fontsize=17, fontweight="bold", va="center")
    ov.text(0.79, 0.13, f"after a big {'red' if short else 'green'} candle —\nwait for confirmation.",
            color=fg, fontsize=14, va="center", linespacing=1.35)

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


def send_post(token, chat_id, text, image_path):
    with open(image_path, "rb") as f:
        photo = ("btc_plan.png", f.read(), "image/png")
    if visible_len(text) <= CAPTION_LIMIT:
        return [telegram_call(token, "sendPhoto", {"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                              {"photo": photo})]
    # Too long for a caption: plan image first, full text right after.
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
    p.add_argument("--dry-run", action="store_true", help="print the post and save the image, send nothing")
    p.add_argument("--wait-until", metavar="HH:MM", help="sleep until this local time before posting")
    p.add_argument("--chart-out", default="btc_plan.png", help="where to save the plan image")
    p.add_argument("--state-dir", help="plan history folder: enables the recap of the previous plan "
                                       "and saves today's plan for the alert tracker")
    p.add_argument("--session", choices=["asia", "us"], default="asia",
                   help="asia = full 08:30 plan; us = short 19:00 outlook for the US session")
    p.add_argument("--once-per-day", action="store_true",
                   help="skip if today's plan is already in --state-dir (guards against late/duplicate triggers)")
    args = p.parse_args()

    def already_posted():
        today = f"{datetime.now(TZ):%Y-%m-%d}"
        return bool(args.state_dir) and os.path.exists(os.path.join(args.state_dir, "plans", f"{today}.json"))

    if args.once_per_day and not args.dry_run and already_posted():
        print("Today's plan was already posted - skipping.")
        return 0
    if args.wait_until:
        wait_until(args.wait_until)

    data, source = fetch_market()
    analysis = analyze(data)
    now = datetime.now(TZ)
    if args.session == "us":
        text = build_us_post(analysis, data, now, args.state_dir)
        draw_plan_image(data, analysis, now, args.chart_out, session="US SESSION")
    else:
        text = build_post(analysis, data, now)
        draw_plan_image(data, analysis, now, args.chart_out)

    if args.dry_run and args.session == "us":
        print(text)
        words = len(re.sub(r"<[^>]+>", "", text).split())
        print(f"\n[source {source}; {words} words; {visible_len(text)} chars; image saved to {args.chart_out}]")
        return 0
    if args.dry_run:
        if args.state_dir:
            import plan_tracker
            plan_tracker.run_recaps(args.state_dir, data["M15"], now, plan_tracker.make_sender(True))
        print(text)
        print(f"\n[source {source}; {visible_len(text)} chars; image saved to {args.chart_out}]")
        return 0

    if args.session == "us":
        print("US-session posting is preview-only for now (use --dry-run).", file=sys.stderr)
        return 2
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (English channel only).", file=sys.stderr)
        return 2
    if args.state_dir:
        import plan_tracker
        try:  # a failed recap must never block the morning plan
            plan_tracker.run_recaps(args.state_dir, data["M15"], now, plan_tracker.make_sender(False))
        except Exception as e:  # noqa: BLE001
            print(f"Recap failed: {e}", file=sys.stderr)
    ids = send_post(token, chat_id, text, args.chart_out)
    print(f"Posted message(s) {ids} to {chat_id} (data: {source})")
    if args.state_dir:
        plan_tracker.save_plan(args.state_dir, plan_tracker.new_plan(analysis, now, ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
