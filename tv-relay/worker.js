// TradingView -> Telegram relay (Cloudflare Worker).
//
// TradingView webhooks are fire-and-forget, so they cannot learn the
// message_id of the entry post. This worker posts each alert to Telegram,
// remembers the entry message_id per trade id in KV, and sends the
// TP1 / TP2 / SL alerts of that trade as replies to the entry post.
//
// Request body (JSON, sent by the Pine indicator):
//   {"secret": "...", "chat_id": "@channel", "event": "entry|tp1|tp2|sl",
//    "id": "DOTUSDT.P-S-202610281435", "text": "..."}

const TRADE_TTL_SECONDS = 30 * 24 * 3600;
const EVENTS = new Set(["entry", "tp1", "tp2", "sl"]);

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
    const resp = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({ ok: false, description: `HTTP ${resp.status}` }));
    const wait = data?.parameters?.retry_after;
    if (data.ok || !wait || attempt === 1) return data;
    await new Promise((r) => setTimeout(r, Math.min(wait, 5) * 1000));
  }
}

export async function handle(request, env) {
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
  const text = String(body.text || "").trim();
  const chatId = String(body.chat_id || env.CHAT_ID || "").trim();
  const tradeId = String(body.id || "").trim();
  if (!EVENTS.has(event) || !text || !chatId) {
    return json({ ok: false, error: "need event, text and chat_id" }, 400);
  }

  const key = `${chatId}|${tradeId}`;
  const payload = { chat_id: chatId, text, disable_web_page_preview: true };

  if (event !== "entry" && tradeId) {
    const entryMessageId = await env.TRADES.get(key);
    if (entryMessageId) {
      payload.reply_parameters = {
        message_id: Number(entryMessageId),
        allow_sending_without_reply: true,
      };
    }
  }

  const result = await telegram(env, "sendMessage", payload);
  if (!result?.ok) {
    console.log("telegram error", event, tradeId, result?.description);
    return json({ ok: false, error: result?.description || "telegram" }, 502);
  }

  const messageId = result.result.message_id;
  if (event === "entry" && tradeId) {
    await env.TRADES.put(key, String(messageId), { expirationTtl: TRADE_TTL_SECONDS });
  }
  return json({ ok: true, event, id: tradeId, message_id: messageId, reply_to: payload.reply_parameters?.message_id ?? null });
}

export default {
  fetch: (request, env) => handle(request, env),
};
