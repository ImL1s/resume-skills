#!/bin/zsh
# Dual-review launcher — short prompts, PID files only, no pkill -f
set -euo pipefail
export OMG_ALLOW_EXTERNAL_CLI=1

REPO="/Users/iml1s/Documents/mine/resume-skills"
RESEARCH="$REPO/.omc/research"
SAFE="$RESEARCH/dual-review-brief-safe.md"
PID_DIR="/tmp/dual-review-pids"
mkdir -p "$PID_DIR"
cd "$REPO"

# empty MCP for fable
echo '{"mcpServers":{}}' > /tmp/empty-mcp.json

# sanitize ensure (already on disk)
python3 - <<'PY'
from pathlib import Path
import re
src_path = Path("/Users/iml1s/Documents/mine/resume-skills/.omc/research/dual-review-brief-full.md")
out_path = Path("/Users/iml1s/Documents/mine/resume-skills/.omc/research/dual-review-brief-safe.md")
src = src_path.read_text(encoding="utf-8")
for pat, rep in [
    (r"(?i)ultrawork", "ULTRA_WORK_SKILL"),
    (r"(?i)ultragoal", "ULTRA_GOAL_SKILL"),
    (r"(?i)autopilot", "AUTO_PILOT_SKILL"),
    (r"(?i)ralplan", "RAL_PLAN_SKILL"),
    (r"(?i)\bralph\b", "RALPH_SKILL"),
    (r"(?i)\bulw\b", "ULW_ALIAS"),
]:
    src = re.sub(pat, rep, src)
header = (
    "# SANITIZED REVIEW BRIEF\n"
    "DO NOT activate orchestration workflow modes.\n"
    "Map: ULW_ALIAS=parallel, ULTRA_WORK_SKILL=parallel-engine, "
    "RALPH_SKILL=persist-loop, RAL_PLAN_SKILL=plan-consensus, "
    "AUTO_PILOT_SKILL=full-pipeline, ULTRA_GOAL_SKILL=durable-goals.\n\n"
)
out_path.write_text(header + src, encoding="utf-8")
print(f"wrote {out_path} bytes={out_path.stat().st_size}")
PY

OUT_CODEX="$RESEARCH/dual-review-codex.md"
OUT_FABLE="$RESEARCH/dual-review-fable.md"
OUT_GROK="$RESEARCH/dual-review-grok.md"
OUT_AGY="$RESEARCH/dual-review-agy.md"

META="$RESEARCH/dual-review-launch-meta.txt"
: > "$META"

# 1 Codex
if command -v codex >/dev/null 2>&1; then
  (
    codex exec \
      --dangerously-bypass-approvals-and-sandbox \
      --skip-git-repo-check \
      -s workspace-write \
      -m gpt-5.6-sol \
      -c model_reasoning_effort=max \
      --cd "$REPO" \
      "Read ONLY $SAFE and perform the requested READ-ONLY review. Write the complete Traditional Chinese report to $OUT_CODEX and print it to stdout. No code changes. No workflow modes." \
      </dev/null \
      > "$RESEARCH/dual-review-codex.stdout.log" 2>&1
    echo CODEX_DONE >> "$RESEARCH/dual-review-codex.stdout.log"
  ) &
  echo $! > "$PID_DIR/codex.pid"
  echo "codex: running pid=$(cat $PID_DIR/codex.pid)" | tee -a "$META"
else
  echo "codex: BLOCKED (not found)" | tee -a "$META"
  printf '%s\n' "# BLOCKED" "" "codex CLI not found" "Verdict: BLOCKED" > "$OUT_CODEX"
fi

# 2 Fable — options first, prompt last
if command -v claude >/dev/null 2>&1; then
  (
    claude -p \
      --model claude-fable-5 \
      --effort xhigh \
      --dangerously-skip-permissions \
      --strict-mcp-config \
      --mcp-config /tmp/empty-mcp.json \
      --no-session-persistence \
      "Read ONLY $SAFE and perform the requested READ-ONLY review. Write the complete Traditional Chinese report to $OUT_FABLE and print it to stdout. No code changes. No workflow modes." \
      </dev/null \
      > "$RESEARCH/dual-review-fable.stdout.log" 2>&1
    echo FABLE_DONE >> "$RESEARCH/dual-review-fable.stdout.log"
  ) &
  echo $! > "$PID_DIR/fable.pid"
  echo "fable: running pid=$(cat $PID_DIR/fable.pid)" | tee -a "$META"
else
  echo "fable: BLOCKED (claude not found)" | tee -a "$META"
  printf '%s\n' "# BLOCKED" "" "claude CLI not found" "Verdict: BLOCKED" > "$OUT_FABLE"
fi

# 3 Grok optional
if command -v grok >/dev/null 2>&1; then
  (
    grok -p \
      "Read ONLY $SAFE and perform the requested READ-ONLY review. Write the complete Traditional Chinese report to $OUT_GROK and print it to stdout. No code changes. No workflow modes." \
      </dev/null \
      > "$RESEARCH/dual-review-grok.stdout.log" 2>&1
    echo GROK_DONE >> "$RESEARCH/dual-review-grok.stdout.log"
  ) &
  echo $! > "$PID_DIR/grok.pid"
  echo "grok: running pid=$(cat $PID_DIR/grok.pid)" | tee -a "$META"
else
  echo "grok: SKIPPED (not found)" | tee -a "$META"
fi

# 4 agy optional
if command -v agy >/dev/null 2>&1; then
  (
    agy -p \
      "Read ONLY $SAFE and perform the requested READ-ONLY review. Write the complete Traditional Chinese report to $OUT_AGY and print it to stdout. No code changes. No workflow modes." \
      </dev/null \
      > "$RESEARCH/dual-review-agy.stdout.log" 2>&1
    echo AGY_DONE >> "$RESEARCH/dual-review-agy.stdout.log"
  ) &
  echo $! > "$PID_DIR/agy.pid"
  echo "agy: running pid=$(cat $PID_DIR/agy.pid)" | tee -a "$META"
else
  echo "agy: SKIPPED (not found)" | tee -a "$META"
fi

echo "launch complete" | tee -a "$META"
cat "$META"
