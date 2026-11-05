#!/bin/bash
# Commit and push the automatic test's files to the branch bench-auto, nothing else.
#   bash bench/auto_commit.sh "message"
# Stages only the allowed paths, refuses on anything that looks like a key, never touches main.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(git branch --show-current)" = "bench-auto" ] || { echo "not on bench-auto"; exit 1; }
git add -- bench/*.py bench/*.sh bench/reports bench/prompts notes/bench_control.md notes/bench_runbook_2026-11-05.md notes/speech_test_design_2026-11-05.md
if git diff --cached | grep -E '^\+' | grep -Eq 'sk-or-|OPENROUTER_API_KEY=|sk-ant-|BEGIN [A-Z ]*PRIVATE KEY'; then
  git reset -q; echo "possible key in the staged changes: nothing committed"; exit 1
fi
if git diff --cached --quiet; then echo "nothing to commit"; else
  git commit -q -m "$1

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
  git log --oneline -1
fi
git pull -q --rebase origin bench-auto 2>/dev/null || true
git push -q origin bench-auto && echo "pushed bench-auto"
