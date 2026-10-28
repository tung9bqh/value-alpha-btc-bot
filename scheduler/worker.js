// Cloudflare Worker: on-time scheduler for the GitHub Actions bot.
//
// GitHub's own `schedule:` trigger is best-effort and was hours late (or skipped)
// for this repo, so this worker's Cron Triggers start the workflows instead via
// workflow_dispatch. The GitHub schedules stay as a backup; every workflow is
// idempotent (once-per-day guards, de-duplicated alerts), so a double start is harmless.

const REPO = "tung9bqh/value-alpha-btc-bot";

// cron (UTC, must match wrangler.toml) -> workflows to start.
// The retry slots re-run a job that failed (exchange/feed hiccup, runner error); both
// workflows post at most once per day, so a retry after a successful post does nothing.
const JOBS = {
  "29 1 * * *": [["btc-daily.yml", { dry_run: "false" }]],      // 08:30 Vietnam: daily plan + recap
  "40,55 1 * * *": [["btc-daily.yml", { dry_run: "false" }]],   // retries at 08:40 and 08:55
  "59 4 * * *": [["econ-calendar.yml", { dry_run: "false" }]],  // 12:00 Vietnam: economic calendar
  "10,25 5 * * *": [["econ-calendar.yml", { dry_run: "false" }]], // retries at 12:10 and 12:25
  "*/5 * * * *": [["plan-alerts.yml", { dry_run: "false" }]],   // plan alerts every 5 minutes
};

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
    for (const [workflow, inputs] of JOBS[event.cron] || []) {
      ctx.waitUntil(dispatch(env, workflow, inputs));
    }
  },
  async fetch() {
    return new Response("va-scheduler ok\n");
  },
};
