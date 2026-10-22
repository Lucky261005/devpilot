#!/usr/bin/env bash
# Repeat the v3 two-step benchmark: 3 AI-only and 3 combined runs, one output folder each.
# Samples the GPU every 10 s and aborts a run if it is throttled (busy but <= 400 MHz for 3
# consecutive samples) or if 2 Ollama HTTP 500 errors appear. Run from backend/.
set -u
OUT=../evaluation/reports/experiments/v3-two-step/repeats
mkdir -p "$OUT"
RUNS="${*:-ai-1 ai-2 ai-3 combined-1 combined-2 combined-3}"
for run in $RUNS; do
  cfg=${run%-*}
  dir="$OUT/$run"
  if [ -e "$dir" ]; then echo "$run: $dir exists, skipping (never overwrite)"; continue; fi
  mkdir -p "$dir"
  echo "$run: start $(date -u +%FT%TZ)" | tee -a "$OUT/runner.log"
  before=$(ls -d "$TEMP"/devpilot-eval-* 2>/dev/null | sort)
  DEVPILOT_LLM_PROVIDER=ollama uv run python ../evaluation/scripts/run_eval.py \
    --configs "$cfg" --strategy two-step --out "$dir" > "$dir/run.log" 2>&1 &
  pid=$!
  low=0; aborted=""
  echo "utc,util_pct,sm_mhz,power_w" > "$dir/gpu.csv"
  while kill -0 "$pid" 2>/dev/null; do
    sample=$(nvidia-smi --query-gpu=utilization.gpu,clocks.sm,power.draw --format=csv,noheader,nounits | tr -d ' ')
    echo "$(date -u +%T),$sample" >> "$dir/gpu.csv"
    util=${sample%%,*}; rest=${sample#*,}; mhz=${rest%%,*}
    if [ "${util:-0}" -ge 90 ] && [ "${mhz:-9999}" -le 400 ]; then low=$((low+1)); else low=0; fi
    tmp=$(ls -td "$TEMP"/devpilot-eval-* 2>/dev/null | head -1)
    n500=$(cd "$tmp" 2>/dev/null && uv run --project "$OLDPWD" python -c "
import sqlite3,json
c=sqlite3.connect('eval.db')
print(sum('HTTP 500' in (json.loads(s).get('ai',{}).get('reason') or '') or 'error 500' in (json.loads(s).get('ai',{}).get('reason') or '') for (s,) in c.execute('select stats from review_jobs')))" 2>/dev/null || echo 0)
    if [ "$low" -ge 3 ]; then aborted="gpu throttled (<=400 MHz at >=90% util for 30 s)"; fi
    if [ "${n500:-0}" -ge 2 ]; then aborted="repeated Ollama HTTP 500 errors ($n500)"; fi
    if [ -n "$aborted" ]; then
      powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*run_eval.py*$run*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
      kill "$pid" 2>/dev/null
      echo "ABORTED: $aborted" | tee -a "$dir/ABORTED.txt" "$OUT/runner.log"
      break
    fi
    sleep 10
  done
  wait "$pid" 2>/dev/null; echo "exit=$?" >> "$dir/run.log"
  tmp=$(ls -td "$TEMP"/devpilot-eval-* | head -1)
  if ! echo "$before" | grep -qx "$tmp"; then cp "$tmp/eval.db" "$dir/eval.db"; fi
  echo "$run: end $(date -u +%FT%TZ) ${aborted:+(aborted)}" | tee -a "$OUT/runner.log"
  if [ -n "$aborted" ]; then echo "stopping all remaining runs" | tee -a "$OUT/runner.log"; break; fi
done
