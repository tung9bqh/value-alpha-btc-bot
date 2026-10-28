#!/usr/bin/env bash
# Daily check of GH_DISPATCH_TOKEN (used by the Cloudflare scheduler to start the workflows).
# Opens a GitHub issue that @mentions the owner (-> email) when the token is missing, invalid,
# or expires within WARN_DAYS; closes it once the token is renewed.
# Env: TOKEN (the token), GH_TOKEN (workflow token for issues), OWNER, WARN_DAYS, GITHUB_REPOSITORY.
set -uo pipefail
WARN_DAYS=${WARN_DAYS:-14}
status=ok expires="" days=""

if [ -z "${TOKEN:-}" ]; then
  status=missing
else
  code=$(curl -sS -o /dev/null -D /tmp/token-headers -w '%{http_code}' \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GITHUB_REPOSITORY")
  expires=$(grep -i '^github-authentication-token-expiration:' /tmp/token-headers | cut -d' ' -f2- | tr -d '\r')
  if [ "$code" = "401" ] || [ "$code" = "403" ]; then
    status=invalid
  elif [ -n "$expires" ]; then
    days=$(( ($(date -d "$expires" +%s) - $(date +%s)) / 86400 ))
    [ "$days" -le "$WARN_DAYS" ] && status=expiring
  fi
fi

mkdir -p state/checks
prev=$(jq -r '.status // empty' state/checks/gh_dispatch_token.json 2>/dev/null)
printf '{"checked_at": "%s", "status": "%s", "expires": "%s", "days_left": "%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%MZ)" "$status" "$expires" "$days" > state/checks/gh_dispatch_token.json
echo "GH_DISPATCH_TOKEN: status=$status expires=${expires:-never} days_left=${days:--}"
echo "GH_DISPATCH_TOKEN: **$status**, expires: ${expires:-never}, days left: ${days:--}" >> "$GITHUB_STEP_SUMMARY"

title="⚠️ GH_DISPATCH_TOKEN cần gia hạn"
issue=$(gh issue list --state open --search "GH_DISPATCH_TOKEN in:title" --json number --jq '.[0].number // empty')

if [ "$status" = ok ]; then
  if [ -n "$issue" ]; then
    gh issue close "$issue" --comment "✅ Token đã được gia hạn (hết hạn: ${expires:-không bao giờ}). Đóng issue."
  fi
  exit 0
fi

case $status in
  missing)  what="Secret \`GH_DISPATCH_TOKEN\` **không còn** trong repo." ;;
  invalid)  what="Token \`GH_DISPATCH_TOKEN\` **đã hết hạn hoặc bị thu hồi** (GitHub từ chối token)." ;;
  expiring) what="Token \`GH_DISPATCH_TOKEN\` sẽ **hết hạn sau $days ngày** (${expires})." ;;
esac
body="@$OWNER $what

Khi token hết hạn, bộ hẹn giờ Cloudflare không kích hoạt được bot nữa → bài 08:30, lịch kinh tế 12:00 và cảnh báo
sẽ phụ thuộc lịch GitHub (hay trễ hàng giờ).

**Cách gia hạn (2 phút):**
1. Mở https://github.com/settings/personal-access-tokens → chọn token \`va-scheduler\` → **Regenerate token**
   (giữ nguyên quyền: repo \`value-alpha-btc-bot\`, *Actions: Read and write*) → copy token mới.
2. Mở https://github.com/$GITHUB_REPOSITORY/settings/secrets/actions → \`GH_DISPATCH_TOKEN\` → **Update** → dán token mới.
3. Mở https://github.com/$GITHUB_REPOSITORY/actions/workflows/scheduler-deploy.yml → **Run workflow**.

Issue này tự đóng sau khi token được gia hạn."

if [ -z "$issue" ]; then
  gh issue create --title "$title" --body "$body"
elif [ "$status" != "$prev" ] || [[ "$status:$days" =~ ^expiring:(7|3|1|0|-.*)$ ]]; then
  gh issue comment "$issue" --body "$body"  # remind on a status change and at 7, 3, 1, 0 days left
fi
exit 1  # failed run = extra email from GitHub
