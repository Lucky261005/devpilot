#!/usr/bin/env bash
# Phase 3 experiment grid: prompt version x context mode on datasets v1 and v2, one model
# (qwen2.5-coder:3b via Ollama). Run from backend/. Runs one configuration at a time with a GPU
# cool-down between runs; never overwrites an existing run folder.
#   bash ../evaluation/scripts/run_phase3.sh [name ...]      (default: all)
set -u
OUT="${DEVPILOT_EVAL_OUT:-../evaluation/reports/experiments/phase3}"
mkdir -p "$OUT"
LOG="$OUT/runner.log"

# name dataset configs prompt context
GRID="
v2-static        v2 static   v1 changed
v2-ai-p1-changed v2 ai       v1 changed
v2-ai-p1-repo    v2 ai       v1 repo
v2-ai-p2-changed v2 ai       v2 changed
v2-ai-p2-repo    v2 ai       v2 repo
v1-ai-p1-repo    v1 ai       v1 repo
v1-ai-p2-changed v1 ai       v2 changed
v1-ai-p2-repo    v1 ai       v2 repo
"

cool_down() {
  sleep 60
  for _ in $(seq 1 30); do
    t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
    [ -z "$t" ] || [ "$t" -le 57 ] && return
    sleep 10
  done
}

echo "$GRID" | while read -r name dataset configs prompt context; do
  [ -z "$name" ] && continue
  if [ $# -gt 0 ] && ! printf '%s\n' "$@" | grep -qx "$name"; then continue; fi
  if [ -e "$OUT/$name" ]; then echo "$(date -u +%FT%TZ) $name: exists, skipped" >> "$LOG"; continue; fi
  echo "$(date -u +%FT%TZ) $name: start ($dataset $configs prompt=$prompt context=$context)" >> "$LOG"
  DEVPILOT_LLM_PROVIDER=ollama DEVPILOT_LLM_PROMPT_VERSION="$prompt" DEVPILOT_LLM_CONTEXT="$context" \
    uv run python ../evaluation/scripts/run_eval.py --configs "$configs" --dataset "$dataset" \
    --out "$OUT/$name" > "$OUT/$name-run.log" 2>&1
  echo "$(date -u +%FT%TZ) $name: end (exit $?)" >> "$LOG"
  [ "$configs" = "static" ] || cool_down
done
