#!/usr/bin/env python3
"""Value Alpha Crypto - daily high-impact USD economic calendar (English channel).

Reads ForexFactory's calendar export feed (same data as forexfactory.com/calendar),
keeps only USD events with High impact (red folder) in the next 24 hours, draws the
"ECONOMIC CALENDAR TODAY" image and posts it with a short caption to TELEGRAM_CHAT_ID.
Nothing is posted on days without such events.

Usage:
    python econ_calendar.py --dry-run             # print caption + save image, send nothing
    python econ_calendar.py --wait-until 12:00    # sleep until 12:00 local time, then post
"""

import argparse
import html
import json
import os
import sys
import textwrap
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import btc_daily_bot as bot

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
MAX_ROWS = 8

# (match in title, table subtitle, impact if higher/hawkish, impact if lower/dovish,
#  explanation title, explanation, icon). First match wins, so specific names come first.
HAWKISH_UP = ("Higher than forecast:", "Lower than forecast:")
EVENT_RULES = [
    ("Core Retail Sales", "(excl. autos, main sales)", HAWKISH_UP, "Core Retail Sales",
     "Excludes volatile items (autos, gas). A better view of underlying consumer demand.", "$"),
    ("Retail Sales", "(total sales)", HAWKISH_UP, "Retail Sales",
     "Measures the total spending of consumers. Stronger data shows a strong economy → Fed may keep rates higher.", "$"),
    ("Federal Funds Rate", "(interest rate decision)", ("Rate hike / more hawkish:", "Rate hold / cut:"),
     "Federal Funds Rate",
     "The interest rate set by the Fed. A higher rate can reduce market liquidity and put pressure on BTC.", "%"),
    ("Economic Projections", "(Fed's outlook)", ("More hawkish outlook:", "More dovish outlook:"), "FOMC Projections",
     "Fed's outlook on growth, inflation and interest rates. Provides clues about future policy direction.", "☰"),
    ("FOMC Statement", "(official statement)", ("Hawkish tone:", "Dovish tone:"), "FOMC Statement",
     "Official statement after the meeting. Market looks for changes in tone and guidance.", "✎"),
    ("Press Conference", "(Chair's briefing)", ("Hawkish remarks:", "Dovish remarks:"), "FOMC Press Conference",
     "Fed Chair's Q&A session. Often the most volatile part of the day.", "✉"),
    ("Minutes", "(last meeting details)", ("Hawkish tone:", "Dovish tone:"), "FOMC Minutes",
     "Detailed record of the last Fed meeting. Shows how hawkish or dovish members were.", "✎"),
    ("Speaks", "(speech)", ("Hawkish remarks:", "Dovish remarks:"), "Fed Speeches",
     "Comments from Fed officials can quickly shift rate expectations.", "✉"),
    ("Testif", "(testimony)", ("Hawkish remarks:", "Dovish remarks:"), "Fed Testimony",
     "Fed Chair answers lawmakers' questions. Can move rate expectations.", "✉"),
    ("Core CPI", "(excl. food & energy)", HAWKISH_UP, "Core CPI",
     "Inflation excluding food and energy, the Fed's key gauge of sticky inflation.", "%"),
    ("CPI", "(consumer inflation)", HAWKISH_UP, "CPI",
     "Measures changes in consumer prices. Hotter inflation → Fed may keep rates higher.", "%"),
    ("Core PCE", "(Fed's preferred inflation)", HAWKISH_UP, "Core PCE",
     "The Fed's preferred inflation measure. Hotter readings support tighter policy.", "%"),
    ("PPI", "(producer inflation)", HAWKISH_UP, "PPI",
     "Prices received by producers. An early signal for consumer inflation.", "%"),
    ("Non-Farm", "(jobs added)", HAWKISH_UP, "Non-Farm Payrolls",
     "Jobs added outside farming. Strong hiring → Fed may keep rates higher.", "$"),
    ("Unemployment Rate", "(jobless rate)", ("Lower than forecast:", "Higher than forecast:"), "Unemployment Rate",
     "Share of the labor force without a job. Rising unemployment raises the odds of rate cuts.", "%"),
    ("Unemployment Claims", "(weekly jobless claims)", ("Lower than forecast:", "Higher than forecast:"),
     "Unemployment Claims", "Weekly first-time jobless claims. A fast read on the labor market.", "☰"),
    ("Average Hourly Earnings", "(wage growth)", HAWKISH_UP, "Average Hourly Earnings",
     "Wage growth, a key driver of services inflation.", "$"),
    ("JOLTS", "(job openings)", HAWKISH_UP, "JOLTS Job Openings",
     "Measures labor demand. Fewer openings point to a cooling job market.", "☰"),
    ("GDP", "(economic growth)", HAWKISH_UP, "GDP",
     "Total output of the economy. Strong growth means less need for rate cuts.", "$"),
    ("ISM Manufacturing", "(factory activity)", HAWKISH_UP, "ISM Manufacturing PMI",
     "Survey of factory activity. Above 50 = expansion, below 50 = contraction.", "☰"),
    ("ISM Services", "(services activity)", HAWKISH_UP, "ISM Services PMI",
     "Survey of the services sector, the largest part of the US economy.", "☰"),
    ("Inflation Expectations", "(consumer expectations)", HAWKISH_UP, "Inflation Expectations",
     "What consumers expect inflation to be. Watched closely by the Fed.", "%"),
    ("Consumer", "(consumer mood)", HAWKISH_UP, "Consumer Confidence",
     "How consumers feel about the economy. A lead indicator for spending.", "$"),
    ("Durable Goods", "(long-lasting goods orders)", HAWKISH_UP, "Durable Goods Orders",
     "Orders for long-lasting goods, a signal of business investment.", "$"),
]
FALLBACK_RULE = ("", "", HAWKISH_UP, "Other high-impact data",
                 "High-impact US data that can move the dollar and risk assets like BTC.", "$")


# ---------------------------------------------------------------- data

def fetch_feed():
    last = None
    for attempt in range(3):
        try:
            return bot.http_get_json(FEED_URL, timeout=30)
        except Exception as e:  # noqa: BLE001 - the feed is rate limited; retry gently
            last = e
            time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Economic calendar feed failed: {last}")


def rule_for(title):
    return next((r for r in EVENT_RULES if r[0].lower() in title.lower()), FALLBACK_RULE)


def display_name(title):
    for short, full in ((" m/m", " (MoM)"), (" y/y", " (YoY)"), (" q/q", " (QoQ)")):
        title = title.replace(short, full)
    return title


def todays_events(feed, now_utc):
    """High-impact USD events from now until 24h later, sorted by time."""
    end = now_utc + timedelta(hours=24)
    out = []
    for e in feed:
        if e.get("country") != "USD" or e.get("impact") != "High":
            continue
        t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        if now_utc <= t < end:
            rule = rule_for(e["title"])
            out.append({"time": t, "title": display_name(e["title"]), "sub": rule[1],
                        "forecast": (e.get("forecast") or "").strip() or "—",
                        "previous": (e.get("previous") or "").strip() or "—", "rule": rule})
    return sorted(out, key=lambda x: x["time"])[:MAX_ROWS]


# -------------------------------------------------------------- caption

def build_caption(events, day, tz):
    offset = tz.utcoffset(None).total_seconds() / 3600
    lines = [f"🗓 <b>ECONOMIC CALENDAR — {day:%a, %b %d, %Y}</b>".upper().replace("<B>", "<b>").replace("</B>", "</b>"),
             "🔴 High-impact USD news today:", ""]
    for e in events:
        local = e["time"].astimezone(tz)
        lines.append(f"• <b>{e['time']:%H:%M} UTC</b> ({local:%H:%M} UTC{offset:+g}) — {html.escape(e['title'])}")
        if e["forecast"] != "—" or e["previous"] != "—":
            lines.append(f"   Forecast: {html.escape(e['forecast'])} | Previous: {html.escape(e['previous'])}")
    lines += ["", "⚠️ Expect high volatility around the releases. Avoid over-leveraging, don't chase the "
              "first move and wait for confirmation.",
              "<i>Data: ForexFactory. Not financial advice.</i>"]
    return "\n".join(lines)


# ---------------------------------------------------------------- image

def draw_calendar(events, day, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib import font_manager
    from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon, Rectangle
    import matplotlib.patheffects as pe

    fonts = {}
    for key, fname in (("display", "Anton-Regular.ttf"), ("script", "GreatVibes-Regular.ttf"),
                       ("caps", "BebasNeue-Regular.ttf")):
        fpath = os.path.join(FONT_DIR, fname)
        if os.path.exists(fpath):
            font_manager.fontManager.addfont(fpath)
            fonts[key] = font_manager.FontProperties(fname=fpath).get_name()
    display = fonts.get("display", "DejaVu Sans")
    script = fonts.get("script", "DejaVu Serif")
    caps = fonts.get("caps", "DejaVu Sans")

    gold, gold_dim, gold_line = "#f2c14e", "#b8860b", "#8a6a1f"
    white, muted, red, green = "#f5f5f5", "#a8a8a8", "#ff4d4d", "#2ee06e"
    W, H = 16, 9
    A = W / H  # aspect: 1 unit of x is A units of y in screen space

    fig = plt.figure(figsize=(W, H), dpi=120, facecolor="#050505")
    bgax = fig.add_axes([0, 0, 1, 1])
    bgax.axis("off")
    # dark background with warm glows (top centre and behind the coin)
    yy, xx = np.mgrid[0:1:270j, 0:1:480j]
    glow = 0.55 * np.exp(-(((xx - 0.5) / 0.35) ** 2 + ((yy - 0.05) / 0.25) ** 2))
    glow += 0.8 * np.exp(-(((xx - 0.88) / 0.16) ** 2 + ((yy - 0.45) / 0.3) ** 2))
    img = np.zeros((270, 480, 3))
    img[..., 0], img[..., 1], img[..., 2] = 0.02 + 0.22 * glow, 0.02 + 0.15 * glow, 0.02 + 0.03 * glow
    bgax.imshow(img, extent=(0, 1, 0, 1), aspect="auto", zorder=0)

    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.patch.set_alpha(0)
    renderer = fig.canvas.get_renderer()

    def box(x, y, w, h, edge=gold_dim, face="#0b0b0b", lw=1.6, r=0.012, alpha=0.92, z=2):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", linewidth=lw,
                                    edgecolor=edge, facecolor=face, alpha=alpha, mutation_aspect=A, zorder=z))

    def text(x, y, s, size, color=white, weight="normal", family="DejaVu Sans", **kw):
        kw.setdefault("va", "center")
        return ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, family=family, zorder=5, **kw)

    def rich(x, y, parts, size):
        """Left-aligned run of differently coloured text pieces."""
        for s, color, weight in parts:
            t = text(x, y, s, size, color, weight)
            x += t.get_window_extent(renderer).width / fig.bbox.width

    def flag(x, y, w):
        h = w * A * 0.55
        for i in range(7):
            ax.add_patch(Rectangle((x, y + i * h / 7), w, h / 7, color="#b22234" if i % 2 == 0 else "white", zorder=4))
        ax.add_patch(Rectangle((x, y + h * 3 / 7), w * 0.42, h * 4 / 7, color="#3c3b6e", zorder=5))

    # ---- background candles + coin (right side)
    rng = np.random.default_rng(7)
    level = 0.45
    for i in range(14):
        x = 0.80 + i * 0.013
        o = level
        level = level + rng.normal(0.012, 0.02)
        hi, lo = max(o, level) + 0.02, min(o, level) - 0.02
        ax.plot([x, x], [lo, hi], color=gold_dim, alpha=0.25, lw=1, zorder=1)
        ax.add_patch(Rectangle((x - 0.0035, min(o, level)), 0.007, abs(level - o) + 0.004,
                               color=gold if level > o else gold_dim, alpha=0.2, zorder=1))
    cx, cy, cr = 0.885, 0.585, 0.085
    for k, col in enumerate(["#5c430d", "#a87b16", "#e2b13c", "#c99a2e", "#f5cf63", "#d9a93a"]):
        rr = cr * (1 - k * 0.07)
        ax.add_patch(Ellipse((cx, cy), 2 * rr, 2 * rr * A, color=col, zorder=3))
    ax.add_patch(Ellipse((cx, cy), 2 * cr * 0.62, 2 * cr * 0.62 * A, fill=False, edgecolor="#8a6414", lw=2, zorder=3))
    text(cx, cy - 0.005, "B", 95, "#7a5510", family=display, ha="center",
         path_effects=[pe.withStroke(linewidth=3, foreground="#f7d774")])
    for dx in (-0.011, 0.009):
        ax.plot([cx + dx, cx + dx], [cy + 0.098, cy + 0.12], color="#7a5510", lw=6, zorder=6, solid_capstyle="butt")
        ax.plot([cx + dx, cx + dx], [cy - 0.13, cy - 0.108], color="#7a5510", lw=6, zorder=6, solid_capstyle="butt")
    text(0.873, 0.368, "Macro Drives Crypto", 21, gold, family=script, ha="center", rotation=5)

    # ---- header
    lx, ly = 0.03, 0.935
    ax.add_patch(Polygon([(lx, ly - 0.03), (lx + 0.02, ly + 0.03), (lx + 0.04, ly - 0.03)], color=gold, zorder=5))
    ax.add_patch(Polygon([(lx + 0.02, ly - 0.03), (lx + 0.037, ly + 0.018), (lx + 0.054, ly - 0.03)],
                         color=gold_dim, zorder=5))
    text(0.09, 0.947, "VALUE ALPHA", 24, gold, family=caps)
    text(0.137, 0.912, "C R Y P T O", 9, gold, ha="center")
    text(0.03, 0.877, "KNOWLEDGE  ·  DISCIPLINE  ·  LONG-TERM WEALTH", 7.5, white)
    title_fx = [pe.withStroke(linewidth=4, foreground="#5a3d00"), pe.withSimplePatchShadow(offset=(3, -3), alpha=0.6)]
    text(0.485, 0.935, "ECONOMIC CALENDAR", 58, gold, family=display, ha="center", path_effects=title_fx)
    text(0.485, 0.845, "TODAY", 66, "#e9e9e9", family=display, ha="center",
         path_effects=[pe.withStroke(linewidth=4, foreground="#4a4a4a"), pe.withSimplePatchShadow(offset=(3, -3))])
    text(0.485, 0.775, "TRACK THE MARKET     |     MANAGE RISK     |     TRADE SMART", 9.5, white, ha="center")
    text(0.715, 0.835, "Big News\n   Bigger Moves", 24, gold, family=script, ha="left", rotation=10, linespacing=0.9)
    text(0.975, 0.935, "TRADE\nSMARTER\nGROW\nTOGETHER", 8, white, ha="right", linespacing=1.6)
    box(0.03, 0.765, 0.245, 0.06, edge=gold, lw=2, r=0.01)
    ax.add_patch(Rectangle((0.045, 0.78), 0.022, 0.03, fill=False, edgecolor=gold, lw=1.8, zorder=5))
    ax.add_patch(Rectangle((0.045, 0.80), 0.022, 0.01, color=gold, zorder=5))
    text(0.168, 0.795, f"{day:%a, %b %d, %Y}".upper(), 21, gold, family=caps, ha="center")

    # ---- events table
    cols = [0.03, 0.105, 0.19, 0.38, 0.47, 0.56, 0.775]
    top, head_h = 0.745, 0.065
    row_h = min(0.058, (top - head_h - 0.375) / max(len(events), 1))
    bottom = top - head_h - row_h * len(events)
    box(cols[0], bottom, cols[-1] - cols[0], top - bottom, edge=gold_dim, lw=1.6, r=0.01)
    ax.add_patch(Rectangle((cols[0] + 0.002, top - head_h), cols[-1] - cols[0] - 0.004, head_h - 0.004,
                           color="#1a1408", zorder=3))
    for x in cols[1:-1]:
        ax.plot([x, x], [bottom, top], color=gold_line, lw=0.8, zorder=4)
    heads = ["TIME\n(UTC)", "CURRENCY", "EVENT", "FORECAST", "PREVIOUS", "POTENTIAL IMPACT ON BTC"]
    for i, h in enumerate(heads):
        text((cols[i] + cols[i + 1]) / 2, top - head_h / 2, h, 11, gold, "bold", ha="center", linespacing=1.1)
    for r, e in enumerate(events):
        y0 = top - head_h - (r + 1) * row_h
        ym = y0 + row_h / 2
        if r:
            ax.plot([cols[0], cols[-1]], [y0 + row_h, y0 + row_h], color=gold_line, lw=0.6, zorder=4)
        text((cols[0] + cols[1]) / 2, ym, f"{e['time']:%H:%M}", 15, white, "bold", ha="center")
        flag((cols[1] + cols[2]) / 2 - 0.0165, ym - 0.0165 * A * 0.55, 0.033)
        name_size = 11.5 if len(e["title"]) <= 30 else 10
        text(cols[2] + 0.008, ym + row_h * 0.17, e["title"], name_size, white, "bold")
        text(cols[2] + 0.008, ym - row_h * 0.2, e["sub"], 8.5, muted)
        text((cols[3] + cols[4]) / 2, ym, e["forecast"], 14, white, "bold", ha="center")
        text((cols[4] + cols[5]) / 2, ym, e["previous"], 14, white, "bold", ha="center")
        up_txt, down_txt = e["rule"][2]
        rich(cols[5] + 0.008, ym + row_h * 0.2, [("▼ ", red, "bold"), (up_txt + " ", white, "normal"),
                                                ("Bearish", red, "bold")], 9.5)
        rich(cols[5] + 0.008, ym - row_h * 0.2, [("▲ ", green, "bold"), (down_txt + " ", white, "normal"),
                                                ("Bullish", green, "bold")], 9.5)

    # ---- what these events mean
    bx, by, bw, bh = 0.03, 0.075, 0.475, 0.285
    box(bx, by, bw, bh, edge=gold_dim)
    for i, hgt in enumerate((0.012, 0.02, 0.028)):
        ax.add_patch(Rectangle((bx + 0.015 + i * 0.007, by + bh - 0.045), 0.005, hgt, color=gold, zorder=5))
    text(bx + 0.045, by + bh - 0.033, "WHAT THESE EVENTS MEAN", 13, gold, "bold")
    seen, items = set(), []
    for e in events:
        if e["rule"][3] not in seen:
            seen.add(e["rule"][3])
            items.append(e["rule"])
    items = items[:6]
    col_w = bw / 2
    for k, rule in enumerate(items):
        cxi = bx + 0.015 + (k // 3) * col_w
        cyi = by + bh - 0.085 - (k % 3) * 0.067
        if k // 3 == 1 and k % 3 == 0:
            ax.plot([bx + col_w, bx + col_w], [by + 0.015, by + bh - 0.06], color=gold_line, lw=0.6, zorder=4)
        ax.add_patch(Ellipse((cxi + 0.011, cyi - 0.006), 0.022, 0.022 * A, color=gold, zorder=5))
        text(cxi + 0.011, cyi - 0.006, rule[5], 10, "#1a1208", "bold", ha="center")
        text(cxi + 0.028, cyi + 0.004, rule[3], 9.5, gold, "bold")
        desc = textwrap.fill(rule[4], 57)
        text(cxi + 0.028, cyi - 0.008, desc, 7.6, white, va="top", linespacing=1.3)

    # ---- overall impact
    ox, ow = 0.515, 0.245
    box(ox, by, ow, bh, edge=gold_dim)
    ax.add_patch(Ellipse((ox + 0.022, by + bh - 0.033), 0.022, 0.022 * A, fill=False, edgecolor=gold, lw=2, zorder=5))
    ax.add_patch(Ellipse((ox + 0.022, by + bh - 0.033), 0.008, 0.008 * A, color=gold, zorder=5))
    text(ox + 0.04, by + bh - 0.033, "OVERALL IMPACT ON BTC", 12, gold, "bold")
    scen = [
        (red, "IF DATA IS HIGHER THAN FORECAST\n(Hawkish)", ["Stronger economy", "Fed may keep rates higher",
                                                            "USD and bond yields could rise", "Risk assets under pressure"],
         "Potentially\nBearish\nfor BTC", True),
        (green, "IF DATA IS LOWER THAN FORECAST\n(Dovish)", ["Weaker economic data", "Higher chance of rate cuts",
                                                           "USD and bond yields could drop", "Risk-on sentiment may return"],
         "Potentially\nBullish\nfor BTC", False),
    ]
    for j, (col, head, bullets, verdict, is_up) in enumerate(scen):
        sy = by + bh - 0.065 - (j + 1) * 0.105
        box(ox + 0.008, sy, ow - 0.016, 0.098, edge=col, face="#140808" if is_up else "#07140b", lw=1.4, r=0.008)
        ax.annotate("", xy=(ox + 0.03, sy + (0.085 if is_up else 0.012)), xytext=(ox + 0.03, sy + (0.012 if is_up else 0.085)),
                    arrowprops=dict(arrowstyle="-|>,head_width=0.9,head_length=1.2", color=col, lw=6), zorder=6)
        text(ox + 0.055, sy + 0.08, head, 6.8, col, "bold", linespacing=1.1)
        for b, line in enumerate(bullets):
            text(ox + 0.058, sy + 0.054 - b * 0.0135, f"▸ {line}", 6.5, white)
        box(ox + ow - 0.072, sy + 0.025, 0.056, 0.05, edge=col, face="#000000", lw=1.2, r=0.006, z=4)
        text(ox + ow - 0.044, sy + 0.05, verdict, 7.2, col, "bold", ha="center", linespacing=1.05)

    # ---- reminders
    rx, rw, rh = 0.772, 0.203, 0.25
    box(rx, by, rw, rh, edge=gold_dim)
    text(rx + 0.02, by + rh - 0.035, "⚠", 22, gold, ha="center")
    text(rx + 0.038, by + rh - 0.035, "IMPORTANT REMINDERS", 11.5, white, "bold")
    tips = ["Expect high volatility around\nthe news release.", "Avoid over-leveraging.", "Don't chase the first move.",
            "Wait for confirmation and watch\nthe overall market reaction.", "Manage your capital and risk\nat all times."]
    yt = by + rh - 0.068
    for tip in tips:
        text(rx + 0.015, yt, "▶", 7, gold, va="top")
        text(rx + 0.028, yt, tip, 8, white, va="top", linespacing=1.25)
        yt -= 0.0165 * (tip.count("\n") + 1) + 0.0075

    # ---- footer
    text(0.5, 0.045, "V A L U E    A L P H A    C R Y P T O", 12, gold, "bold", ha="center")
    text(0.5, 0.018, "KNOWLEDGE  ·  DISCIPLINE  ·  LONG-TERM WEALTH", 7.5, white, ha="center")
    text(0.03, 0.03, "BETTER TRADERS\nA BRIGHTER TOMORROW", 7, white, linespacing=1.5)
    text(0.975, 0.03, "DISCIPLINE\nCREATES FREEDOM", 7, white, ha="right", linespacing=1.5)

    fig.savefig(path, facecolor="#050505")
    plt.close(fig)
    return path


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="print the caption and save the image, send nothing")
    p.add_argument("--wait-until", metavar="HH:MM", help="sleep until this local time before posting")
    p.add_argument("--out", default="econ_calendar.png", help="where to save the image")
    p.add_argument("--as-of", metavar="ISO_TIME", help="preview as if run at this time, e.g. 2026-10-28T05:00Z")
    args = p.parse_args()

    if args.wait_until:
        bot.wait_until(args.wait_until)
    now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if args.as_of:
        now_utc = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(timezone.utc)
    feed = fetch_feed()
    events = todays_events(feed, now_utc)
    if args.dry_run:  # show what the feed contains, to make quiet days easy to verify
        dates = sorted(e["date"] for e in feed)
        print(f"[feed: {len(feed)} events, {dates[0][:10] if dates else '-'} → {dates[-1][:10] if dates else '-'}]")
        for e in feed:
            if e.get("country") == "USD" and e.get("impact") == "High":
                t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
                print(f"[USD high this week: {t:%a %d %b %H:%M} UTC  {e['title']}]")
        print()
    if not events:
        print("No high-impact USD events in the next 24 hours - nothing to post.")
        return 0

    caption = build_caption(events, now_utc, bot.TZ)
    draw_calendar(events, now_utc, args.out)
    if args.dry_run:
        print(caption)
        print(f"\n[{len(events)} events; {bot.visible_len(caption)} chars; image saved to {args.out}]")
        return 0

    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (English channel only).", file=sys.stderr)
        return 2
    with open(args.out, "rb") as f:
        photo = ("econ_calendar.png", f.read(), "image/png")
    if bot.visible_len(caption) <= bot.CAPTION_LIMIT:
        ids = [bot.telegram_call(token, "sendPhoto", {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                                 {"photo": photo})]
    else:
        ids = [bot.telegram_call(token, "sendPhoto", {"chat_id": chat_id}, {"photo": photo}),
               bot.telegram_call(token, "sendMessage", {"chat_id": chat_id, "text": caption, "parse_mode": "HTML",
                                                        "disable_web_page_preview": "true"})]
    print(f"Posted message(s) {ids} to {chat_id}: {len(events)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
