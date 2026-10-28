// TradingView -> Telegram relay (Cloudflare Worker).
//
// TradingView webhooks are fire-and-forget, so they cannot learn the
// message_id of the entry post. This worker posts each alert to Telegram,
// remembers the entry message_id per trade id in KV, and sends the
// TP1 / TP2 / SL alerts of that trade as replies to the entry post.
//
// Entry alerts are posted as a chart image (candles, EMAs, SL/TP zones) with
// the alert text as caption; if the chart cannot be made, as plain text.
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

// Candles up to and including the signal bar, from Bitget (fallback OKX).
async function fetchCandles(symbol, tf, signalTime) {
  const [bitgetTf, okxBar] = TIMEFRAMES[tf];
  const errors = [];
  try {
    const body = await getJson("https://api.bitget.com/api/v2/mix/market/candles?" + new URLSearchParams({
      symbol, productType: "USDT-FUTURES", granularity: bitgetTf, limit: "600",
    }));
    if (body.code !== "00000" || !body.data?.length) throw new Error(`Bitget: ${body.msg || body.code}`);
    return { candles: toCandles(body.data).filter((c) => c.t <= signalTime), exchange: "Bitget" };
  } catch (e) {
    errors.push(String(e.message || e));
  }
  try {
    const instId = symbol.replace(/USDT$/, "-USDT-SWAP");
    const body = await getJson("https://www.okx.com/api/v5/market/candles?" + new URLSearchParams({
      instId, bar: okxBar, limit: "300",
    }));
    if (body.code !== "0" || !body.data?.length) throw new Error(`OKX: ${body.msg || body.code}`);
    return { candles: toCandles(body.data).filter((c) => c.t <= signalTime), exchange: "OKX" };
  } catch (e) {
    errors.push(String(e.message || e));
  }
  throw new Error(errors.join("; "));
}

// HTML -> PNG with the Cloudflare Browser Rendering REST API.
async function screenshot(env, html) {
  const resp = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${env.CF_ACCOUNT_ID}/browser-rendering/screenshot`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${env.BROWSER_TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify({
        html,
        viewport: { width: CHART_WIDTH, height: CHART_HEIGHT, deviceScaleFactor: 2 },
        screenshotOptions: { type: "png" },
      }),
      signal: AbortSignal.timeout(20000),
    },
  );
  const type = resp.headers.get("content-type") || "";
  if (!resp.ok || !type.startsWith("image/")) {
    throw new Error(`Browser Rendering HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
  }
  return resp.arrayBuffer();
}

async function signalChart(env, body) {
  if (!env.BROWSER_TOKEN || !env.CF_ACCOUNT_ID) throw new Error("chart disabled (no BROWSER_TOKEN)");
  const tf = TIMEFRAMES[body.tf] ? String(body.tf) : "5";
  const ticker = String(body.ticker || String(body.id || "").split("-")[0]);
  const symbol = ticker.replace(/\.P$/i, "").replace(/[^A-Z0-9]/gi, "").toUpperCase();
  // "yyyy-MM-dd HH:mm" (UTC, bar open) from the indicator; else the last closed bar.
  const step = TIMEFRAMES[tf][2];
  let signalTime = Date.parse(String(body.time || "").replace(" ", "T") + ":00Z") / 1000;
  if (!Number.isFinite(signalTime)) signalTime = Math.floor(Date.now() / 1000 / step) * step - step;

  const levels = ["entry", "sl", "tp1", "tp2"].map((k) => Number(body[k]));
  if (!levels.every((v) => Number.isFinite(v) && v > 0)) throw new Error("missing entry/sl/tp levels");
  const decimals = Math.max(...["entry", "sl", "tp1", "tp2"].map((k) => (String(body[k]).split(".")[1] || "").length));

  const { candles, exchange } = await fetchCandles(symbol, tf, signalTime);
  if (candles.length < 30) throw new Error(`only ${candles.length} candles`);
  const [entry, sl, tp1, tp2] = levels;
  const html = chartHtml(candles, {
    side: String(body.side || (tp1 > entry ? "LONG" : "SHORT")).toUpperCase(),
    ticker, tfLabel: TIMEFRAMES[tf][3], entry, sl, tp1, tp2,
    lev: body.lev ? String(body.lev) : "", decimals, exchange,
  });
  return screenshot(env, html);
}

async function relay(body, env) {
  const event = String(body.event || "entry").toLowerCase();
  const text = String(body.text || "").trim();
  const chatId = String(body.chat_id || env.CHAT_ID || "").trim();
  const tradeId = String(body.id || "").trim();
  const key = `${chatId}|${tradeId}`;

  let result, chartError = null;
  if (event === "entry") {
    try {
      const png = await signalChart(env, body);
      const form = new FormData();
      form.append("chat_id", chatId);
      form.append("caption", text.slice(0, 1024));
      form.append("photo", new Blob([png], { type: "image/png" }), "signal.png");
      result = await telegram(env, "sendPhoto", form);
      if (!result?.ok) chartError = `sendPhoto: ${result?.description}`;
    } catch (e) {
      chartError = String(e.message || e);
    }
    if (chartError) console.log("chart failed, sending text", tradeId, chartError);
  }

  const payload = { chat_id: chatId, text, disable_web_page_preview: true };
  if (!result?.ok) {
    if (event !== "entry" && tradeId) {
      const entryMessageId = await env.TRADES.get(key);
      if (entryMessageId) {
        payload.reply_parameters = { message_id: Number(entryMessageId), allow_sending_without_reply: true };
      }
    }
    result = await telegram(env, "sendMessage", payload);
  }
  if (!result?.ok) {
    console.log("telegram error", event, tradeId, result?.description);
    return { ok: false, error: result?.description || "telegram", chart_error: chartError };
  }

  const messageId = result.result.message_id;
  if (event === "entry" && tradeId) {
    await env.TRADES.put(key, String(messageId), { expirationTtl: TRADE_TTL_SECONDS });
  }
  return {
    ok: true, event, id: tradeId, message_id: messageId,
    photo: Boolean(result.result.photo), chart_error: chartError,
    reply_to: payload.reply_parameters?.message_id ?? null,
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
