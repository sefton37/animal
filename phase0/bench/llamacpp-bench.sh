#!/usr/bin/env bash
# Measure a model on the llama.cpp llama-server stack — the numbers Phase 0 exists
# to get and the wall-clock model depends on: load/swap latency, BATCH-PREFILL
# tok/s at several context depths (the dominant per-turn cost), generation tok/s,
# and a CONTEXT-INTEGRITY check (server-reported prompt tokens must match what we
# sent — silent truncation is the local twin of the founding hallucination).
#
# Usage:  bash llamacpp-bench.sh /path/to/model.gguf "label" [-- extra llama-server flags]
# Env:    PORT(8081) NGL(999) CTX(32768) PREFILLS("2048 8192 32768") SERVER(~/llm/llama.cpp/build/bin/llama-server)
#
# Examples:
#   bash llamacpp-bench.sh var/models/coder-qwen3-30b-a3b/*.gguf coder-full-gpu
#   NGL=999 bash llamacpp-bench.sh .../coder.gguf coder-moe -- --n-cpu-moe 48
set -uo pipefail
MODEL="${1:?model gguf path required}"; LABEL="${2:-model}"; shift 2 || true
[ "${1:-}" = "--" ] && shift
EXTRA=("$@")
SERVER="${SERVER:-/home/kellogg/llm/llama.cpp/build/bin/llama-server}"
PORT="${PORT:-8081}"; NGL="${NGL:-999}"; CTX="${CTX:-32768}"
PREFILLS="${PREFILLS:-2048 8192 32768}"
BASE="http://127.0.0.1:${PORT}"

[ -x "$SERVER" ] || { echo "no llama-server at $SERVER (build not done?)"; exit 1; }
[ -f "$MODEL" ] || { echo "no model at $MODEL"; exit 1; }

echo "== $LABEL =="; echo "model: $(basename "$MODEL")  ngl=$NGL ctx=$CTX flags='${EXTRA[*]:-}'"

# start server, time to healthy = load/swap latency
t0=$(date +%s.%N)
"$SERVER" -m "$MODEL" -ngl "$NGL" -c "$CTX" -fa on --host 127.0.0.1 --port "$PORT" \
  "${EXTRA[@]}" >/tmp/lls-$LABEL.log 2>&1 &
SPID=$!
trap 'kill $SPID 2>/dev/null' EXIT
ready=""
for _ in $(seq 1 120); do
  if curl -sf "$BASE/health" >/dev/null 2>&1; then ready=1; break; fi
  kill -0 $SPID 2>/dev/null || { echo "server died — tail:"; tail -8 /tmp/lls-$LABEL.log; exit 1; }
  sleep 1
done
[ -n "$ready" ] || { echo "server not healthy in 120s — tail:"; tail -8 /tmp/lls-$LABEL.log; exit 1; }
load=$(awk -v a="$t0" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
# confirm the model is actually on the GPU
gpu=$(nvidia-smi --query-compute-apps=process_name,used_memory --format=csv,noheader 2>/dev/null | grep -i llama-server | head -1)
echo "load/swap: ${load}s   GPU: ${gpu:-<<NOT ON GPU>>}"

printf '%-9s %-12s %-12s %-10s %s\n' "prefill" "prefill_t/s" "gen_t/s" "prompt_n" "integrity"
for want in $PREFILLS; do
  [ "$want" -gt "$CTX" ] && continue
  # ~1 token per "w " repetition; overshoot then the server reports the true count
  prompt=$(yes "w" | head -n "$want" | tr '\n' ' ')
  resp=$(jq -n --arg p "$prompt" '{prompt:$p,n_predict:64,cache_prompt:false,temperature:0}' \
    | curl -sf "$BASE/completion" -d @- 2>/dev/null)
  [ -z "$resp" ] && { printf '%-9s server-error\n' "$want"; continue; }
  echo "$resp" | jq -r --arg want "$want" '
    .timings as $t |
    "\($want)|\($t.prompt_per_second|floor)|\($t.predicted_per_second|floor)|\($t.prompt_n)|" +
    (if ($t.prompt_n|tonumber) >= ($want|tonumber)*0.5 then "ok(no-trunc)" else "TRUNCATED?" end)' \
    | awk -F'|' '{printf "%-9s %-12s %-12s %-10s %s\n",$1,$2,$3,$4,$5}'
done
kill $SPID 2>/dev/null; trap - EXIT; wait $SPID 2>/dev/null || true
