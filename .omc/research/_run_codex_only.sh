#!/bin/zsh
set -euo pipefail
export OMG_ALLOW_EXTERNAL_CLI=1
REPO="/Users/iml1s/Documents/mine/resume-skills"
SAFE="$REPO/.omc/research/dual-review-brief-safe.md"
OUT="$REPO/.omc/research/dual-review-codex.md"
LOG="$REPO/.omc/research/dual-review-codex.stdout.log"
# Do not attach stdin to avoid "Reading additional input from stdin..." hang.
# Prompt is a single argv; no workflow keywords.
exec codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  -s workspace-write \
  -m gpt-5.6-sol \
  -c model_reasoning_effort=max \
  --cd "$REPO" \
  "Read ONLY ${SAFE} and perform the requested READ-ONLY review. Write the complete Traditional Chinese report to ${OUT}. Also print a short summary to stdout. Do not edit product source under src/ or tests/. No workflow modes." \
  >"$LOG" 2>&1
