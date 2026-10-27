#!/usr/bin/env python3
"""Tracks the daily BTC plan: live alerts and result recaps for the English channel.

    python plan_tracker.py check --state-dir state             # send alerts for new plan events
    python plan_tracker.py check --state-dir state --dry-run   # print them instead

Plans are saved by btc_daily_bot.py to <state-dir>/plans/YYYY-MM-DD.json when it posts;
the daily recap and the Monday weekly summary are sent from btc_daily_bot.py too.

Result model: 50% of the position is closed at TP1 and the stop moves to entry,
the other 50% is closed at TP2. A plan lives for 24h after it is posted.
If one M15 candle touches both the stop and a target, the stop is assumed first.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import btc_daily_bot as bot

WINDOW = 24 * 3600
FINALIZE_SLACK = 30 * 60  # the next morning's run may start a few minutes before 24h is up
HALF_TP1, HALF_TP2 = 0.5 * bot.TP_RR[0], 0.5 * bot.TP_RR[1]


# ---------------------------------------------------------------- state

def plans_dir(state_dir):
    return os.path.join(state_dir, "plans")


def load_plans(state_dir):
    d = plans_dir(state_dir)
    if not os.path.isdir(d):
        return []
    plans = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".json"):
            with open(os.path.join(d, name)) as f:
                plans.append(json.load(f))
    return plans


def save_plan(state_dir, plan):
    os.makedirs(plans_dir(state_dir), exist_ok=True)
    with open(os.path.join(plans_dir(state_dir), f"{plan['date']}.json"), "w") as f:
        json.dump(plan, f, indent=2)


def load_meta(state_dir):
    path = os.path.join(state_dir, "meta.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"weekly_sent": []}


def save_meta(state_dir, meta):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def new_plan(analysis, now, message_ids):
    p = analysis["primary"]
    return {
        "date": f"{now:%Y-%m-%d}", "posted_at": int(now.timestamp()), "direction": analysis["direction"],
        **{k: round(p[k], 2) for k in ("lo", "hi", "entry", "sl", "tp1", "tp2", "cancel")},
        "message_ids": message_ids, "alerts_sent": [], "recap_sent": False, "result": None,
    }


# --------------------------------------------------------------- replay

def replay(plan, m15, now_ts):
    """Walk the M15 candles after the post. Returns {status, r, events, final}."""
    side = 1 if plan["direction"] == "LONG" else -1
    entry, sl, tp1, tp2, cancel = (plan[k] for k in ("entry", "sl", "tp1", "tp2", "cancel"))
    risk = abs(entry - sl)
    start = plan["posted_at"] - plan["posted_at"] % 900
    end = min(now_ts, plan["posted_at"] + WINDOW)

    def against(c, level):  # price moved against the trade direction far enough to touch level
        return c["h"] >= level if side == -1 else c["l"] <= level

    def favor(c, level):
        return c["l"] <= level if side == -1 else c["h"] >= level

    def broken(close):
        return close > cancel if side == -1 else close < cancel

    def r_at(price):
        return side * (price - entry) / risk

    candles = [c for c in m15 if start <= c["t"] < end]
    if not candles or candles[0]["t"] > start + 900:
        return {"status": "unknown", "r": None, "events": [], "final": now_ts >= plan["posted_at"] + WINDOW}

    events, state, status, r = [], "waiting", None, None
    for c in candles:
        t_end = c["t"] + 900
        h1_close = t_end % 3600 == 0 and t_end <= now_ts  # last M15 of a finished hour = H1 close
        if state == "waiting":
            if against(c, entry):
                events.append({"t": c["t"], "kind": "entry", "price": entry})
                state = "open"
                if against(c, sl):
                    events.append({"t": c["t"], "kind": "sl", "price": sl})
                    status, r = "sl", -1.0
                    break
            elif favor(c, tp1):
                events.append({"t": c["t"], "kind": "skipped", "price": tp1})
                status = "skipped"
                break
            elif h1_close and broken(c["c"]):
                events.append({"t": t_end, "kind": "cancelled", "price": c["c"]})
                status = "cancelled"
                break
        elif state == "open":
            if against(c, sl):
                events.append({"t": c["t"], "kind": "sl", "price": sl})
                status, r = "sl", -1.0
                break
            if favor(c, tp1):
                events.append({"t": c["t"], "kind": "tp1", "price": tp1})
                state = "half"
                if favor(c, tp2):
                    events.append({"t": c["t"], "kind": "tp2", "price": tp2})
                    status, r = "tp2", HALF_TP1 + HALF_TP2
                    break
            elif h1_close and broken(c["c"]):
                r = r_at(c["c"])
                events.append({"t": t_end, "kind": "cancel_exit", "price": c["c"], "r": r})
                status = "cancel_exit"
                break
        elif state == "half":
            if against(c, entry):
                events.append({"t": c["t"], "kind": "be", "price": entry})
                status, r = "tp1_be", HALF_TP1
                break
            if favor(c, tp2):
                events.append({"t": c["t"], "kind": "tp2", "price": tp2})
                status, r = "tp2", HALF_TP1 + HALF_TP2
                break
            if h1_close and broken(c["c"]):
                r = HALF_TP1 + 0.5 * r_at(c["c"])
                events.append({"t": t_end, "kind": "cancel_exit", "price": c["c"], "r": r})
                status = "cancel_exit"
                break

    expired = now_ts >= plan["posted_at"] + WINDOW - FINALIZE_SLACK
    if status is None:
        if not expired:
            return {"status": "in_progress" if state != "waiting" else "waiting", "r": None,
                    "events": events, "final": False}
        last = candles[-1]["c"]
        if state == "waiting":
            status = "expired"
        elif state == "open":
            status, r = "time_exit", r_at(last)
        else:
            status, r = "time_exit", HALF_TP1 + 0.5 * r_at(last)
    return {"status": status, "r": r, "events": events, "final": True}


# --------------------------------------------------------------- format

def hhmm(ts):
    return datetime.fromtimestamp(ts, bot.TZ).strftime("%H:%M")


def alert_text(plan, ev):
    short = plan["direction"] == "SHORT"
    k, t = ev["kind"], hhmm(ev["t"])
    P = lambda key: bot.k_fmt(plan[key])  # noqa: E731
    word = "short" if short else "long"
    if k == "entry":
        return (f"🔔 <b>BTC {plan['direction']} — ENTRY ZONE REACHED</b>\n"
                f"Price hit {P('entry')} at {t}. Watch for {'bearish' if short else 'bullish'} rejection.\n"
                f"SL: {P('sl')} | TP1: {P('tp1')} | TP2: {P('tp2')}")
    if k == "tp1":
        return (f"✅ <b>TP1 HIT</b> — {P('tp1')} at {t}.\n"
                "Take partial profit and move the stop-loss to entry.")
    if k == "tp2":
        return f"🎯 <b>TP2 HIT</b> — {P('tp2')} at {t}. Plan completed."
    if k == "sl":
        return f"❌ <b>STOP-LOSS HIT</b> — {P('sl')} at {t}. Plan closed."
    if k == "be":
        return f"⚪ <b>BACK TO ENTRY</b> — {P('entry')} at {t} after TP1. Remaining position closed at breakeven."
    if k == "cancelled":
        return (f"🚫 <b>PLAN CANCELLED</b> — H1 closed {'above' if short else 'below'} {P('cancel')} at {t} "
                "before entry. No trade today.")
    if k == "cancel_exit":
        return (f"🚫 <b>STRUCTURE BROKEN</b> — H1 closed {'above' if short else 'below'} {P('cancel')} at {t}. "
                f"Exit the {word} at market.")
    if k == "skipped":
        return (f"⏭ <b>PLAN SKIPPED</b> — price reached {P('tp1')} at {t} before the zone. "
                "The move has played out: do not chase.")
    return ""


def result_line(res):
    st, r = res["status"], res["r"]
    if st in ("expired", "skipped", "cancelled"):
        why = {"expired": "price never reached the zone",
               "skipped": "price hit TP1 before the zone",
               "cancelled": "plan cancelled before entry"}[st]
        return f"🏁 <b>Result: No trade</b> ⚪ — {why}."
    if st == "unknown" or r is None:
        return "🏁 <b>Result: Not available</b> (missing market data)."
    mark = "✅" if r > 0.001 else ("❌" if r < -0.001 else "⚪")
    return f"🏁 <b>Result: {r:+.2f}R</b> {mark}"


EVENT_LABEL = {"entry": "Entry zone reached", "tp1": "TP1 hit", "tp2": "TP2 hit", "sl": "Stop-loss hit",
               "be": "Back to entry (breakeven)", "cancelled": "Cancelled (H1 close)",
               "cancel_exit": "Exited (H1 close broke structure)", "skipped": "TP1 reached before the zone"}


def recap_text(plan, res):
    day = datetime.strptime(plan["date"], "%Y-%m-%d")
    short = plan["direction"] == "SHORT"
    lines = [f"📋 <b>PLAN RESULT — {day:%B %d}</b>".upper().replace("<B>", "<b>").replace("</B>", "</b>"),
             f"{'🔴' if short else '🟢'} {plan['direction'].title()} {bot.k_fmt(plan['lo'], 50)}–{bot.k_fmt(plan['hi'], 50)}",
             f"Entry: {bot.k_fmt(plan['entry'])} | SL: {bot.k_fmt(plan['sl'])} | "
             f"TP1: {bot.k_fmt(plan['tp1'])} | TP2: {bot.k_fmt(plan['tp2'])}", ""]
    lines += [f"• {hhmm(e['t'])} {EVENT_LABEL[e['kind']]}" for e in res["events"]]
    if res["status"] == "time_exit":
        lines.append("• Closed at market when the plan expired")
    if res["events"] or res["status"] == "time_exit":
        lines.append("")
    lines.append(result_line(res))
    if res["r"] is not None and res["status"] != "sl":
        lines.append("<i>50% closed at TP1 with SL moved to entry, 50% at TP2.</i>")
    return "\n".join(lines)


def weekly_text(plans, monday):
    week_start = monday - timedelta(days=7)
    rows = [p for p in plans if p.get("result")
            and week_start.date() <= datetime.strptime(p["date"], "%Y-%m-%d").date() < monday.date()]
    if not rows:
        return None
    traded = [p for p in rows if p["result"]["r"] is not None]
    wins = [p for p in traded if p["result"]["r"] > 0.001]
    losses = [p for p in traded if p["result"]["r"] < -0.001]
    net = sum(p["result"]["r"] for p in traded)
    rate = f"{len(wins) / (len(wins) + len(losses)) * 100:.0f}%" if wins or losses else "—"
    last_day = monday - timedelta(days=1)
    lines = [f"📊 <b>WEEKLY TRACK RECORD — {week_start:%b %d} – {last_day:%b %d}</b>".upper()
             .replace("<B>", "<b>").replace("</B>", "</b>"),
             "",
             f"• Plans: {len(rows)} | Triggered: {len(traded)}",
             f"• Wins: {len(wins)} | Losses: {len(losses)} | Breakeven: {len(traded) - len(wins) - len(losses)}",
             f"• Win rate: {rate}",
             f"• Net result: <b>{net:+.2f}R</b>",
             ""]
    for p in rows:
        d = datetime.strptime(p["date"], "%Y-%m-%d")
        r = p["result"]["r"]
        res = "No trade" if r is None else f"{r:+.2f}R"
        lines.append(f"{d:%a} {'🔴' if p['direction'] == 'SHORT' else '🟢'} {p['direction'].title()} — {res}")
    lines += ["", f"<i>Every plan is counted, wins and losses. 1R = {bot.SL_PCT:g}% risk from entry.</i>"]
    return "\n".join(lines)


# ---------------------------------------------------------------- send

def send_text(token, chat_id, text, reply_to=None):
    fields = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if reply_to:
        fields["reply_parameters"] = json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})
    return bot.telegram_call(token, "sendMessage", fields)


def reply_target(plan):
    ids = plan.get("message_ids") or []
    return ids[-1] if ids else None


# ------------------------------------------------------------ workflows

def run_recaps(state_dir, m15, now, send):
    """Finalize finished plans; recap the latest one and, on Mondays, the past week.

    `send(text, reply_to)` posts a message (or prints it on a dry run) and returns True on success.
    """
    plans = load_plans(state_dir)
    now_ts = int(now.timestamp())
    finished = []
    for p in plans:
        if p.get("result") is None:
            res = replay(p, m15, now_ts)
            if not res["final"]:
                continue
            p["result"] = {"status": res["status"], "r": res["r"], "events": res["events"]}
        if not p.get("recap_sent"):
            finished.append(p)
    for p in finished[:-1]:  # older backlog: keep the result, skip the post
        p["recap_sent"] = True
    if finished:
        latest = finished[-1]
        if send(recap_text(latest, latest["result"]), reply_target(latest)):
            latest["recap_sent"] = True
    for p in plans:
        save_plan(state_dir, p)

    meta = load_meta(state_dir)
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.weekday() == 0 and f"{monday:%Y-%m-%d}" not in meta["weekly_sent"]:
        text = weekly_text(plans, monday)
        if text and send(text, None):
            meta["weekly_sent"].append(f"{monday:%Y-%m-%d}")
            save_meta(state_dir, meta)


def run_check(state_dir, m15, now, send):
    """Send alerts for new events of the plans that are still running."""
    now_ts = int(now.timestamp())
    for p in load_plans(state_dir):
        if p.get("result") is not None or now_ts > p["posted_at"] + WINDOW:
            continue
        res = replay(p, m15, now_ts)
        new = [e for e in res["events"] if f"{e['kind']}@{e['t']}" not in p["alerts_sent"]]
        if not new:
            continue
        text = "\n\n".join(alert_text(p, e) for e in new)
        if send(text, reply_target(p)):
            p["alerts_sent"] += [f"{e['kind']}@{e['t']}" for e in new]
            save_plan(state_dir, p)


def fetch_m15():
    errors = []
    for name, fetch, arg in (("Bitget", bot.fetch_bitget, "15m"), ("OKX", bot.fetch_okx, "15m")):
        try:
            return fetch(arg)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("All market data sources failed: " + "; ".join(errors))


def make_sender(dry_run):
    if dry_run:
        def send(text, reply_to):
            print(f"--- message (reply to {reply_to}) ---\n{text}\n")
            return True
        return send
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (English channel only).")

    def send(text, reply_to):
        try:
            send_text(token, chat_id, text, reply_to)
            return True
        except Exception as e:  # noqa: BLE001 - one failed message must not stop the run
            print(f"Telegram send failed: {e}", file=sys.stderr)
            return False
    return send


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["check"])
    p.add_argument("--state-dir", default="state")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not load_plans(args.state_dir):
        print("No saved plans yet.")
        return 0
    run_check(args.state_dir, fetch_m15(), datetime.now(bot.TZ), make_sender(args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
