// Cloudflare Worker: on-time scheduler for the GitHub Actions bot.
//
// GitHub's own `schedule:` trigger is best-effort and was hours late (or skipped)
// for this repo, so this worker starts the workflows instead via workflow_dispatch.
// One Cron Trigger fires every 5 minutes and the slot table below decides what runs,
// so new times never need another trigger (the free plan allows only a few).
// Every workflow is idempotent (once-per-day guards per session, de-duplicated alerts),
// so the retry slots and GitHub's backup schedules can never cause a double post.

const REPO = "tung9bqh/value-alpha-btc-bot";

const DAILY = ["btc-daily.yml", { dry_run: "false", session: "asia" }];
const US = ["btc-daily.yml", { dry_run: "false", session: "us" }];
const ECON = ["econ-calendar.yml", { dry_run: "false" }];
const ALERTS = ["plan-alerts.yml", { dry_run: "false" }];

// "HH:MM" in UTC -> workflows. Vietnam time = UTC+7.
const SLOTS = {
  "01:30": [DAILY], "01:40": [DAILY], "01:55": [DAILY], // 08:30 plan (+ retries 08:40, 08:55)
  "05:00": [ECON], "05:10": [ECON], "05:25": [ECON],    // 12:00 economic calendar (+ retries)
  "12:00": [US], "12:10": [US], "12:25": [US],          // 19:00 US-session outlook (+ retries)
};

export function jobsAt(date) {
  const hhmm = date.toISOString().slice(11, 16);
  return [...(SLOTS[hhmm] || []), ALERTS];
}

async function dispatch(env, workflow, inputs) {
  const resp = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "value-alpha-scheduler",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  if (resp.status !== 204) {
    console.log(`dispatch ${workflow} failed: HTTP ${resp.status} ${await resp.text()}`);
  }
  return resp.status;
}

export default {
  async scheduled(event, env, ctx) {
    for (const [workflow, inputs] of jobsAt(new Date(event.scheduledTime))) {
      ctx.waitUntil(dispatch(env, workflow, inputs));
    }
  },
  async fetch() {
    return new Response("va-scheduler ok\n");
  },
};
