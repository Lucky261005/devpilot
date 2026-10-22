#!/usr/bin/env bash
# Corrected, label-blind benchmark: static once, then each AI configuration three times.
# Run from backend/. One new folder per run; never overwrites. Between runs it waits for the GPU
# to cool (<= 57 C and at least 90 s). During a run it samples the GPU about every 10 s and stops
# ONLY that run if the GPU throttles (>= 90% busy at <= 400 MHz for 3 samples), if no case finishes
# for 6 minutes (stall), or if 3 Ollama HTTP 500s appear; then it continues with the next run.
set -u
OUT="${DEVPILOT_EVAL_OUT:-../evaluation/reports/experiments/label-blind}"
mkdir -p "$OUT"
RUNS="${*:-static ai-single-1 ai-single-2 ai-single-3 ai-two-1 ai-two-2 ai-two-3 combined-single-1 combined-single-2 combined-single-3 combined-two-1 combined-two-2 combined-two-3}"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/runner.log"; }

cooldown() {
  local start; start=$(date +%s)
  until [ "$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits)" -le 57 ] \
        && [ $(( $(date +%s) - start )) -ge 90 ]; do sleep 10; done
}

finished_cases() {  # number of finished jobs in the newest eval DB
  local tmp; tmp=$(ls -td "$TEMP"/devpilot-eval-* 2>/dev/null | head -1)
  uv run python -c "
import sqlite3,json,sys
c=sqlite3.connect(sys.argv[1]+'/eval.db')
rows=c.execute('select status,stats from review_jobs').fetchall()
done=sum(r[0] in ('completed','failed') for r in rows)
e500=sum('500' in (json.loads(s).get('ai',{}).get('reason') or '') for _,s in rows)
print(done, e500)" "$tmp" 2>/dev/null || echo "0 0"
}

for run in $RUNS; do
  dir="$OUT/$run"
  if [ -e "$dir" ]; then log "$run: exists, skipped (never overwrite)"; continue; fi
  case "$run" in
    static) cfg=static; strategy=single ;;
    ai-single-*) cfg=ai; strategy=single ;;
    ai-two-*) cfg=ai; strategy=two-step ;;
    combined-single-*) cfg=combined; strategy=single ;;
    combined-two-*) cfg=combined; strategy=two-step ;;
    *) log "$run: unknown run name"; continue ;;
  esac
  [ "$run" != static ] && cooldown
  mkdir -p "$dir"
  log "$run: start (config=$cfg strategy=$strategy)"
  before=$(ls -d "$TEMP"/devpilot-eval-* 2>/dev/null | sort)
  DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py \
    --configs "$cfg" --strategy "$strategy" --out "$dir" > "$dir/run.log" 2>&1 &
  pid=$!
  echo "utc,temp_c,util_pct,sm_mhz,power_w" > "$dir/gpu.csv"
  low=0; last_done=0; last_change=$(date +%s); aborted=""
  while kill -0 "$pid" 2>/dev/null; do
    s=$(nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,clocks.sm,power.draw --format=csv,noheader,nounits | tr -d ' ')
    echo "$(date -u +%T),$s" >> "$dir/gpu.csv"
    IFS=, read -r temp util mhz _ <<< "$s"
    if [ "${util:-0}" -ge 90 ] && [ "${mhz:-9999}" -le 400 ]; then low=$((low+1)); else low=0; fi
    read -r done e500 <<< "$(finished_cases)"
    if [ "${done:-0}" != "$last_done" ]; then last_done=$done; last_change=$(date +%s); fi
    [ "$low" -ge 3 ] && aborted="GPU throttled (<=400 MHz at >=90% busy for 3 samples)"
    [ "$cfg" != static ] && [ $(( $(date +%s) - last_change )) -ge 360 ] && aborted="stalled: no case finished for 6 minutes"
    [ "${e500:-0}" -ge 3 ] && aborted="repeated Ollama HTTP 500 errors ($e500)"
    if [ -n "$aborted" ]; then
      powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*run_eval.py*label-blind/$run*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
      kill "$pid" 2>/dev/null
      echo "$aborted" > "$dir/ABORTED.txt"
      break
    fi
    sleep 10
  done
  wait "$pid" 2>/dev/null; echo "exit=$?" >> "$dir/run.log"
  tmp=$(ls -td "$TEMP"/devpilot-eval-* | head -1)
  if ! echo "$before" | grep -qx "$tmp"; then cp "$tmp/eval.db" "$dir/eval.db"; fi
  log "$run: end ${aborted:+ABORTED: $aborted}"
done
log "all requested runs processed"
