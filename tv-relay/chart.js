// Signal chart: candles + EMA20/50/200 + SL/TP zones, drawn as an SVG page
// that Cloudflare Browser Run turns into a PNG. Used for the entry post and,
// with `hit`, for the TP1 / TP2 replies (price reaching the zone + profit).

export const CHART_WIDTH = 1280;
export const CHART_HEIGHT = 820;

const BARS_BEFORE = 72;  // candles shown up to and including the signal bar
const MIN_BEFORE = 24;   // ...shrunk to this when the trade ran long
const MAX_BARS = 150;    // visible candles at most
const BARS_AFTER = 22;   // empty space right of the last candle (entry chart)
const HIT_AFTER = 16;    // ...and on TP replies, where the zone labels move into it
const ZONE_BARS = 15;    // same length as the indicator's SL/TP boxes

const C = {
  bg: "#0d111c", grid: "#1b2130", axis: "#8a93a6", text: "#d7dce6",
  up: "#26a69a", down: "#ef5350",
  ema20: "#f5d430", ema50: "#2f6fea", ema200: "#9b3fc4",
  sl: "#ef5350", tp: "#26a69a", entry: "#c9ced8", win: "#16d38a",
};

export function ema(values, period) {
  const k = 2 / (period + 1);
  const out = [];
  let prev;
  for (const v of values) {
    prev = prev === undefined ? v : v * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const money = (n, d) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (n, d) => (n < 0 ? "-" : "+") + money(Math.abs(n), d);

function niceStep(range, ticks) {
  const raw = range / ticks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}

function hhmm(sec) {
  const d = new Date(sec * 1000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

// Qty = Margin × Leverage ÷ Entry; PnL = Qty × (Exit − Entry), sign flipped
// for shorts; ROI = PnL ÷ Margin. No fees.
export function profit({ side, entry, exit, lev, margin }) {
  const dir = side === "SHORT" ? -1 : 1;
  const pnl = margin * lev / entry * (exit - entry) * dir;
  return { pnl, roi: pnl / margin * 100, move: (exit - entry) / entry * 100 * dir };
}

// candles: [{t (sec), o, h, l, c}] ascending.
// sig: {side, ticker, tfLabel, entry, sl, tp1, tp2, lev, decimals, exchange,
//       signalTime (sec, default: last candle),
//       hit: {label: "TP1"|"TP2", price, margin} for a TP reply}
export function chartHtml(candles, sig) {
  const closes = candles.map((c) => c.c);
  const emas = [ema(closes, 20), ema(closes, 50), ema(closes, 200)];
  let sigAt = candles.length - 1;
  if (sig.signalTime) {
    const i = candles.findIndex((c) => c.t >= sig.signalTime);
    if (i >= 0) sigAt = i;
  }
  const last = candles.length - 1;
  const before = Math.max(MIN_BEFORE, Math.min(BARS_BEFORE, MAX_BARS - (last - sigAt)));
  const start = Math.max(0, sigAt - before + 1, last - MAX_BARS + 1);
  const bars = candles.slice(start);
  const lines = emas.map((e) => e.slice(start));
  const n = bars.length;
  const sigIdx = sigAt - start;
  const hit = sig.hit;
  const slots = n + (hit ? HIT_AFTER : BARS_AFTER);
  const fmt = (v) => v.toFixed(sig.decimals);
  const pct = (v) => `${(Math.abs(v - sig.entry) / sig.entry * 100).toFixed(2)}%`;
  const isLong = sig.side === "LONG";

  const W = CHART_WIDTH, H = CHART_HEIGHT;
  const L = 24, R = W - 104, T = 92, B = H - 64;
  const xStep = (R - L) / slots;
  const x = (i) => L + xStep * (i + 0.5);

  const levels = [sig.entry, sig.sl, sig.tp1, sig.tp2];
  const barLo = Math.min(...bars.map((b) => b.l), ...levels);
  const barHi = Math.max(...bars.map((b) => b.h), ...levels);
  // EMAs may widen the range, but not so far that EMA200 squashes the candles.
  let lo = Math.max(Math.min(barLo, ...lines.flat()), barLo - (barHi - barLo) * 0.25);
  let hi = Math.min(Math.max(barHi, ...lines.flat()), barHi + (barHi - barLo) * 0.25);
  const pad = (hi - lo) * 0.07;
  lo -= pad; hi += pad;
  const y = (v) => T + (hi - v) / (hi - lo) * (B - T);

  const s = [];
  s.push(`<rect width="${W}" height="${H}" fill="${C.bg}"/>`);

  // grid + price axis
  const step = niceStep(hi - lo, 8);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    s.push(`<line x1="${L}" x2="${R}" y1="${y(v)}" y2="${y(v)}" stroke="${C.grid}"/>`);
    // skip axis labels hidden behind the SL/TP/entry tags
    if (levels.every((lv) => Math.abs(y(lv) - y(v)) > 22)) {
      s.push(`<text x="${R + 12}" y="${y(v) + 5}" fill="${C.axis}" font-size="14">${fmt(v)}</text>`);
    }
  }
  // time axis: a label every hour (every 2 hours on long charts)
  const every = n > 100 ? 7200 : 3600;
  for (let i = 0; i < n; i++) {
    if (bars[i].t % every === 0) {
      s.push(`<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${B}" stroke="${C.grid}"/>`);
      s.push(`<text x="${x(i)}" y="${B + 24}" fill="${C.axis}" font-size="14" text-anchor="middle">${hhmm(bars[i].t)}</text>`);
    }
  }
  s.push(`<text x="${R}" y="${B + 24}" fill="${C.axis}" font-size="13" text-anchor="end">UTC</text>`);

  // zones (drawn under the candles), reaching past the last candle on TP replies
  const zx = x(sigIdx) - xStep / 2;
  const zw = hit ? x(n - 1 + HIT_AFTER - 1) - zx : xStep * ZONE_BARS;
  // labels sit in the empty space after the last candle on TP replies
  // (clear of the HIT badge under/over the last candle)
  const labelX = hit ? Math.min(zx + zw - 48, Math.max(x(n - 1 + HIT_AFTER / 2), x(n - 1) + 110)) : zx + zw / 2;
  const zone = (a, b, color, alpha, label, price, sign) => {
    const top = y(Math.max(a, b)), h = Math.abs(y(a) - y(b));
    const cx = labelX, cy = top + h / 2;
    s.push(`<rect x="${zx}" y="${top}" width="${zw}" height="${h}" fill="${color}" fill-opacity="${alpha}" stroke="${color}" stroke-opacity="0.55"/>`);
    s.push(`<text x="${cx}" text-anchor="middle" fill="#fff" fill-opacity="0.85" font-size="15" font-weight="600">` +
      `<tspan x="${cx}" y="${cy - 10}">${label}</tspan>` +
      `<tspan x="${cx}" y="${cy + 9}">${fmt(price)}</tspan>` +
      `<tspan x="${cx}" y="${cy + 28}" font-weight="400">(${sign}${pct(price)})</tspan></text>`);
  };
  zone(sig.entry, sig.sl, C.sl, 0.16, "SL", sig.sl, "-");
  zone(sig.entry, sig.tp1, C.tp, 0.14, "TP1", sig.tp1, "+");
  zone(sig.tp1, sig.tp2, C.tp, 0.26, "TP2", sig.tp2, "+");
  s.push(`<line x1="${zx}" x2="${R}" y1="${y(sig.entry)}" y2="${y(sig.entry)}" stroke="${C.entry}" stroke-dasharray="5 5" stroke-opacity="0.7"/>`);

  // EMAs
  [[lines[0], C.ema20], [lines[1], C.ema50], [lines[2], C.ema200]].forEach(([e, color]) => {
    const pts = e.map((v, i) => `${x(i).toFixed(1)},${y(Math.min(hi, Math.max(lo, v))).toFixed(1)}`).join(" ");
    s.push(`<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2.4" stroke-linejoin="round"/>`);
  });

  // candles
  const bw = Math.max(2.5, xStep * 0.64);
  bars.forEach((b, i) => {
    const color = b.c >= b.o ? C.up : C.down;
    const top = y(Math.max(b.o, b.c)), h = Math.max(1.2, Math.abs(y(b.o) - y(b.c)));
    s.push(`<line x1="${x(i)}" x2="${x(i)}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${color}" stroke-width="1.4"/>`);
    s.push(`<rect x="${x(i) - bw / 2}" y="${top}" width="${bw}" height="${h}" fill="${color}"/>`);
  });

  // signal label with a pointer to the signal candle, left of it so the zone labels stay readable
  const sb = bars[sigIdx];
  const lblW = 260, lblH = sig.lev ? 84 : 62;
  const lblColor = isLong ? C.up : C.down;
  const px = x(sigIdx);
  const lx = Math.max(L + 6, px - lblW + 24);
  const ly = isLong ? y(sb.l) + 16 : y(sb.h) - 16 - lblH;
  const tip = isLong ? `${px - 8},${ly} ${px + 8},${ly} ${px},${ly - 10}` : `${px - 8},${ly + lblH} ${px + 8},${ly + lblH} ${px},${ly + lblH + 10}`;
  s.push(`<polygon points="${tip}" fill="${lblColor}"/>`);
  s.push(`<rect x="${lx}" y="${ly}" width="${lblW}" height="${lblH}" rx="6" fill="${lblColor}"/>`);
  s.push(`<text x="${lx + lblW / 2}" text-anchor="middle" fill="#fff" font-size="16">` +
    `<tspan x="${lx + lblW / 2}" y="${ly + 25}" font-weight="700">${isLong ? "▲" : "▼"} ${sig.side} | ${esc(sig.ticker)}</tspan>` +
    `<tspan x="${lx + lblW / 2}" y="${ly + 48}">Entry: ${fmt(sig.entry)}</tspan>` +
    (sig.lev ? `<tspan x="${lx + lblW / 2}" y="${ly + 70}">Leverage: x${esc(sig.lev)}</tspan>` : "") + `</text>`);

  // price tags on the right axis
  const tag = (v, color, label) => {
    s.push(`<rect x="${R + 4}" y="${y(v) - 12}" width="96" height="24" rx="3" fill="${color}"/>`);
    s.push(`<text x="${R + 52}" y="${y(v) + 5}" fill="#fff" font-size="13" font-weight="700" text-anchor="middle">${label} ${fmt(v)}</text>`);
  };
  tag(sig.sl, C.sl, "SL");
  tag(sig.tp2, "#1d7d73", "TP2");
  tag(sig.tp1, C.tp, "TP1");
  tag(sig.entry, "#5d6577", "");

  // TP reply: mark where the target was reached and show the profit
  let headRight = `<text x="${W - 24}" y="66" fill="${lblColor}" font-size="17" font-weight="700" text-anchor="end">${sig.side} SIGNAL</text>`;
  if (hit) {
    const hx = x(n - 1), hy = y(hit.price);
    s.push(`<line x1="${zx}" x2="${hx}" y1="${hy}" y2="${hy}" stroke="${C.win}" stroke-width="2" stroke-dasharray="7 5"/>`);
    s.push(`<circle cx="${hx}" cy="${hy}" r="11" fill="none" stroke="${C.win}" stroke-width="3"/>`);
    s.push(`<circle cx="${hx}" cy="${hy}" r="4.5" fill="${C.win}"/>`);
    // badge on the side the price came from is busy; put it past the target
    const hl = `${hit.label} HIT`, hw = 112;
    const hlx = Math.max(L, hx - hw / 2), hly = isLong ? hy - 52 : hy + 22;
    s.push(`<rect x="${hlx}" y="${hly}" width="${hw}" height="30" rx="6" fill="${C.win}"/>`);
    s.push(`<text x="${hlx + hw / 2}" y="${hly + 21}" fill="#06231a" font-size="16" font-weight="800" text-anchor="middle">${hl}</text>`);

    const p = profit({ side: sig.side, entry: sig.entry, exit: hit.price, lev: Number(sig.lev) || 1, margin: hit.margin });
    // profit panel in the chart corner away from the price action
    const pw = 360, ph = 150;
    const startAbove = (bars[0].h + bars[0].l) / 2 < (hi + lo) / 2;
    const pX = L + 16, pY = startAbove ? B - ph - 16 : T + 16;
    s.push(`<rect x="${pX}" y="${pY}" width="${pw}" height="${ph}" rx="14" fill="#0b0f19" fill-opacity="0.9" stroke="${C.win}" stroke-opacity="0.55"/>`);
    s.push(`<text x="${pX + 22}" y="${pY + 34}" fill="${C.axis}" font-size="15" font-weight="600" letter-spacing="1">${hl} · ${esc(sig.side)} ${sig.lev ? esc(sig.lev) + "X" : ""}</text>`);
    s.push(`<text x="${pX + 20}" y="${pY + 92}" fill="${C.win}" font-size="56" font-weight="800">${signed(p.roi, 2)}%</text>`);
    s.push(`<text x="${pX + 22}" y="${pY + 127}" fill="${C.win}" font-size="22" font-weight="600">${signed(p.pnl, 2)} USDT` +
      `<tspan fill="${C.axis}" font-size="15" font-weight="400">  on ${money(hit.margin, 0)} USDT margin</tspan></text>`);
    headRight = `<text x="${W - 24}" y="66" fill="${C.win}" font-size="17" font-weight="700" text-anchor="end">${hl} · ${signed(p.move, 2)}%</text>`;
  }

  // header
  const time = new Date((hit ? bars[n - 1].t : sb.t) * 1000).toISOString().slice(0, 16).replace("T", " ");
  const hb = hit ? bars[n - 1] : sb;
  s.push(`<text x="${L}" y="40" fill="#fff" font-size="26" font-weight="700">${esc(sig.ticker)}` +
    `<tspan fill="${C.axis}" font-size="18" font-weight="400">  ·  ${esc(sig.tfLabel)}  ·  ${time} UTC</tspan></text>`);
  s.push(`<text x="${L}" y="70" font-size="15">` +
    `<tspan fill="${C.axis}">O</tspan><tspan fill="${C.text}"> ${fmt(hb.o)}  </tspan>` +
    `<tspan fill="${C.axis}">H</tspan><tspan fill="${C.text}"> ${fmt(hb.h)}  </tspan>` +
    `<tspan fill="${C.axis}">L</tspan><tspan fill="${C.text}"> ${fmt(hb.l)}  </tspan>` +
    `<tspan fill="${C.axis}">C</tspan><tspan fill="${C.text}"> ${fmt(hb.c)}     </tspan>` +
    `<tspan fill="${C.ema20}">EMA20</tspan><tspan fill="${C.ema50}">  EMA50</tspan><tspan fill="${C.ema200}">  EMA200</tspan></text>`);
  s.push(`<text x="${W - 24}" y="40" fill="#fff" font-size="22" font-weight="800" text-anchor="end" letter-spacing="1">VALUE ALPHA CRYPTO</text>`);
  s.push(headRight);
  s.push(`<text x="${L}" y="${H - 14}" fill="#5d6577" font-size="13">Chart data: ${esc(sig.exchange)} perpetual` +
    `${hit ? ` · PnL is the signal's result on ${money(hit.margin, 0)} USDT margin, no fees` : ""} · Not financial advice</text>`);

  return `<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:${C.bg}}
svg{display:block;font-family:"Inter","Segoe UI","Roboto","Helvetica Neue","Arial",sans-serif}
</style></head><body><svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${s.join("")}</svg></body></html>`;
}
