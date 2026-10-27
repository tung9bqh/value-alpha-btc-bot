#!/usr/bin/env bash
# Load or save the bot's plan history, kept on the 'state' branch of this repo.
#   bash .github/scripts/state.sh load    # -> ./state
#   bash .github/scripts/state.sh save    # ./state -> 'state' branch (needs GH_TOKEN)
set -euo pipefail
dir=state
case "${1:-}" in
  load)
    mkdir -p "$dir"
    if git ls-remote --exit-code --heads origin state >/dev/null 2>&1; then
      git fetch -q --depth 1 origin state
      git archive FETCH_HEAD | tar -x -C "$dir"
    fi
    ;;
  save)
    [ -n "$(ls -A "$dir" 2>/dev/null)" ] || exit 0
    cd "$dir"
    rm -rf .git
    git init -q -b state
    git add -A
    git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      commit -q -m "Bot state $(date -u +%Y-%m-%dT%H:%MZ)"
    git push -q -f "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}" state
    ;;
  *)
    echo "usage: $0 load|save" >&2
    exit 2
    ;;
esac
