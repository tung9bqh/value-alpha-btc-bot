// TradingView -> Telegram relay (Cloudflare Worker).
//
// TradingView webhooks are fire-and-forget, so they cannot learn the
// message_id of the entry post. This worker posts each alert to Telegram,
// remembers the entry message_id per trade id in KV, and sends the
// TP1 / TP2 / SL alerts of that trade as replies to the entry post.
//
// Entry alerts are posted as a chart image (candles, EMAs, SL/TP zones) with
// the alert text as caption, TP1 / TP2 as a chart of the target being reached
// with the profit on RESULT_MARGIN, and SL as a short "HIT SL" text. When a
// chart cannot be made, the alert text is posted instead.
//
// Request body (JSON, sent by the Pine indicator):
//   {"secret": "...", "chat_id": "@channel", "event": "entry|tp1|tp2|sl",
//    "id": "DOTUSDT.P-S-202610281435", "text": "...",
//    entry only: "side", "entry", "sl", "tp1", "tp2", "lev", "tf", "time"}

import { chartHtml, CHART_WIDTH, CHART_HEIGHT } from "./chart.js";

const TRADE_TTL_SECONDS = 30 * 24 * 3600;
const EVENTS = new Set(["entry", "tp1", "tp2", "sl"]);

// TradingView timeframe.period -> [Bitget granularity, OKX bar, seconds, label]
const TIMEFRAMES = {
  "1": ["1m", "1m", 60, "1m"], "3": ["3m", "3m", 180, "3m"], "5": ["5m", "5m", 300, "5m"],
  "15": ["15m", "15m", 900, "15m"], "30": ["30m", "30m", 1800, "30m"],
  "60": ["1H", "1H", 3600, "1h"], "240": ["4H", "4H", 14400, "4h"], "D": ["1D", "1D", 86400, "1D"],
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function telegram(env, method, payload) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`;
  for (let attempt = 0; attempt < 2; attempt++) {
    const init = payload instanceof FormData
      ? { method: "POST", body: payload }
      : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) };
    const resp = await fetch(url, init);
    const data = await resp.json().catch(() => ({ ok: false, description: `HTTP ${resp.status}` }));
    const wait = data?.parameters?.retry_after;
    if (data.ok || !wait || attempt === 1) return data;
    await new Promise((r) => setTimeout(r, Math.min(wait, 5) * 1000));
  }
}

async function getJson(url) {
  const resp = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} from ${new URL(url).host}`);
  return resp.json();
}

const toCandles = (rows) => rows
  .map((r) => ({ t: Math.floor(Number(r[0]) / 1000), o: +r[1], h: +r[2], l: +r[3], c: +r[4] }))
  .sort((a, b) => a.t - b.t);

// Candles up to and including the bar starting at upTo, from Bitget (fallback OKX).
async function fetchCandles(symbol, tf, upTo) {
  const [bitgetTf, okxBar] = TIMEFRAMES[tf];
  const errors = [];
  try {
    const body = await getJson("https://api.bitget.com/api/v2/mix/market/candles?" + new URLSearchParams({
      symbol, productType: "USDT-FUTURES", granularity: bitgetTf, limit: "1000",
    }));
    if (body.code !== "00000" || !body.data?.length) throw new Error(`Bitget: ${body.msg || body.code}`);
    return { candles: toCandles(body.data).filter((c) => c.t <= upTo), exchange: "Bitget" };
  } catch (e) {
    errors.push(String(e.message || e));
  }
  try {
    const instId = symbol.replace(/USDT$/, "-USDT-SWAP");
    const body = await getJson("https://www.okx.com/api/v5/market/candles?" + new URLSearchParams({
      instId, bar: okxBar, limit: "300",
    }));
    if (body.code !== "0" || !body.data?.length) throw new Error(`OKX: ${body.msg || body.code}`);
    return { candles: toCandles(body.data).filter((c) => c.t <= upTo), exchange: "OKX" };
  } catch (e) {
    errors.push(String(e.message || e));
  }
  throw new Error(errors.join("; "));
}

// HTML -> PNG with the Cloudflare Browser Run (formerly Browser Rendering)
// REST API. The product was renamed in 2026; try the new path, then the old one.
async function screenshot(env, html) {
  const body = JSON.stringify({
    html,
    viewport: { width: CHART_WIDTH, height: CHART_HEIGHT, deviceScaleFactor: 2 },
    screenshotOptions: { type: "png" },
  });
  let error;
  for (const path of ["browser-run", "browser-rendering"]) {
    const resp = await fetch(
      `https://api.cloudflare.com/client/v4/accounts/${env.CF_ACCOUNT_ID}/${path}/screenshot`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${env.BROWSER_TOKEN}`, "content-type": "application/json" },
        body,
        signal: AbortSignal.timeout(20000),
      },
    );
    const type = resp.headers.get("content-type") || "";
    if (resp.ok && type.startsWith("image/")) return resp.arrayBuffer();
    error = `Browser Run (${path}) HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`;
    if (resp.status !== 404) break;
  }
  throw new Error(error);
}

// Trade details from the indicator's entry alert, kept in KV for the TP replies.
function tradeFromEntry(body) {
  const keys = ["entry", "sl", "tp1", "tp2"];
  const [entry, sl, tp1, tp2] = keys.map((k) => Number(body[k]));
  if (![entry, sl, tp1, tp2].every((v) => Number.isFinite(v) && v > 0)) return null;
  const ticker = String(body.ticker || String(body.id || "").split("-")[0]);
  const tf = TIMEFRAMES[body.tf] ? String(body.tf) : "5";
  // "yyyy-MM-dd HH:mm" (UTC, bar open) from the indicator; else the last closed bar.
  const step = TIMEFRAMES[tf][2];
  let time = Date.parse(String(body.time || "").replace(" ", "T") + ":00Z") / 1000;
  if (!Number.isFinite(time)) time = Math.floor(Date.now() / 1000 / step) * step - step;
  return {
    ticker, tf, time, entry, sl, tp1, tp2,
    side: String(body.side || (tp1 > entry ? "LONG" : "SHORT")).toUpperCase(),
    lev: body.lev ? String(body.lev) : "",
    decimals: Math.max(...keys.map((k) => (String(body[k]).split(".")[1] || "").length)),
  };
}

// Entry chart, or with `hit` the chart up to now with the target reached and the profit.
async function signalChart(env, trade, hit) {
  if (!env.BROWSER_TOKEN || !env.CF_ACCOUNT_ID) throw new Error("chart disabled (no BROWSER_TOKEN)");
  const symbol = trade.ticker.replace(/\.P$/i, "").replace(/[^A-Z0-9]/gi, "").toUpperCase();
  const upTo = hit ? Math.floor(Date.now() / 1000) : trade.time;
  const { candles, exchange } = await fetchCandles(symbol, trade.tf, upTo);
  if (candles.length < 30) throw new Error(`only ${candles.length} candles`);
  const html = chartHtml(candles, {
    ...trade, tfLabel: TIMEFRAMES[trade.tf][3], exchange, signalTime: trade.time, hit,
  });
  return screenshot(env, html);
}

async function sendPhoto(env, chatId, png, caption, replyTo) {
  const form = new FormData();
  form.append("chat_id", chatId);
  form.append("caption", caption.slice(0, 1024));
  if (replyTo) form.append("reply_parameters", JSON.stringify({ message_id: replyTo, allow_sending_without_reply: true }));
  form.append("photo", new Blob([png], { type: "image/png" }), "signal.png");
  const result = await telegram(env, "sendPhoto", form);
  if (!result?.ok) throw new Error(`sendPhoto: ${result?.description}`);
  return result;
}

// KV value: the entry post's message_id, with the trade details (JSON) since
// chart replies; older entries hold only the message_id.
async function loadTrade(env, key) {
  const raw = await env.TRADES.get(key);
  if (!raw) return {};
  if (/^\d+$/.test(raw)) return { messageId: Number(raw) };
  try {
    const v = JSON.parse(raw);
    return { messageId: Number(v.m) || null, trade: v.trade || null };
  } catch {
    return {};
  }
}

async function relay(body, env) {
  const event = String(body.event || "entry").toLowerCase();
  let text = String(body.text || "").trim();
  const chatId = String(body.chat_id || env.CHAT_ID || "").trim();
  const tradeId = String(body.id || "").trim();
  const key = `${chatId}|${tradeId}`;
  const margin = Number(env.RESULT_MARGIN) || 2500;

  let trade = null, replyTo = null;
  if (event === "entry") {
    trade = tradeFromEntry(body);
  } else if (tradeId) {
    ({ messageId: replyTo, trade } = await loadTrade(env, key));
  }
  if (event === "sl") {
    const ticker = trade?.ticker || tradeId.split("-")[0] || "";
    text = `❌ HIT SL${ticker ? ` | ${ticker}` : ""}`;
  }

  let result = null, chartError = null;
  if (trade && (event === "entry" || event === "tp1" || event === "tp2")) {
    try {
      const hit = event === "entry" ? null : { label: event.toUpperCase(), price: trade[event], margin };
      const png = await signalChart(env, trade, hit);
      result = await sendPhoto(env, chatId, png, text, replyTo);
    } catch (e) {
      chartError = String(e.message || e);
      console.log("chart failed, sending text", event, tradeId, chartError);
    }
  }

  if (!result) {
    const payload = { chat_id: chatId, text, disable_web_page_preview: true };
    if (replyTo) payload.reply_parameters = { message_id: replyTo, allow_sending_without_reply: true };
    result = await telegram(env, "sendMessage", payload);
  }
  if (!result?.ok) {
    console.log("telegram error", event, tradeId, result?.description);
    return { ok: false, error: result?.description || "telegram", chart_error: chartError };
  }

  const messageId = result.result.message_id;
  if (event === "entry" && tradeId) {
    await env.TRADES.put(key, JSON.stringify({ m: messageId, trade }), { expirationTtl: TRADE_TTL_SECONDS });
  }
  return {
    ok: true, event, id: tradeId, message_id: messageId,
    photo: Boolean(result.result.photo), chart_error: chartError, reply_to: replyTo,
  };
}

export async function handle(request, env, ctx) {
  if (request.method === "GET") return new Response("tv-relay ok\n");
  if (request.method !== "POST") return json({ ok: false, error: "method" }, 405);

  let body;
  try {
    body = JSON.parse(await request.text());
  } catch {
    return json({ ok: false, error: "body is not JSON" }, 400);
  }
  if (!env.WEBHOOK_SECRET || !safeEqual(body.secret, env.WEBHOOK_SECRET)) {
    return json({ ok: false, error: "forbidden" }, 403);
  }
  const event = String(body.event || "entry").toLowerCase();
  if (!EVENTS.has(event) || !String(body.text || "").trim() || !String(body.chat_id || env.CHAT_ID || "").trim()) {
    return json({ ok: false, error: "need event, text and chat_id" }, 400);
  }

  // TradingView gives up after ~3 s, and the chart takes longer: answer now and
  // finish in the background. {"wait": true} (deploy test) waits for the result.
  if (body.wait || !ctx) {
    const result = await relay(body, env);
    return json(result, result.ok ? 200 : 502);
  }
  ctx.waitUntil(relay(body, env));
  return json({ ok: true, queued: true }, 202);
}

export default {
  fetch: (request, env, ctx) => handle(request, env, ctx),
};
