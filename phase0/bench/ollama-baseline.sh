#!/usr/bin/env bash
# Baseline the CURRENTLY-installed stack (Ollama 0.30.10) — the "installed zoo"
# column of the wall-clock model in docs/ARCHITECTURE.md. Not the target stack
# (that is llama.cpp, measured after Phase 0 installs it), but a real,
# reproducible floor and the sanity check that our numbers match the prior
# research pass.
#
# Uses /api/generate timing fields (nanoseconds): load_duration (swap-in),
# prompt_eval_count/duration (prefill), eval_count/duration (generation).
# Append ":cpu" to a model name to pin num_gpu=0 (measures the CPU jury tier).
set -euo pipefail
OLLAMA=${OLLAMA:-http://127.0.0.1:11434}
PROMPT=${PROMPT:-"Write a Python function that returns the nth Fibonacci number. Return only code."}
NUMCTX=${NUMCTX:-8192}

bench() {  # $1=model  $2=ngpu(-1 default / 0 CPU)
  local model="$1" ngpu="${2:--1}" opts proc="GPU" rf
  if [[ "$ngpu" == "0" ]]; then
    opts=$(jq -n --argjson c "$NUMCTX" '{num_ctx:$c,num_gpu:0}'); proc="CPU"
  else
    opts=$(jq -n --argjson c "$NUMCTX" '{num_ctx:$c}')
  fi
  # cold: unload first so load_duration reflects a real swap-in
  curl -s "${OLLAMA}/api/generate" -d "{\"model\":\"${model}\",\"keep_alive\":0}" >/dev/null 2>&1 || true
  sleep 1
  rf=$(mktemp)
  jq -n --arg m "$model" --arg p "$PROMPT" --argjson o "$opts" \
     '{model:$m,prompt:$p,stream:false,options:$o}' \
    | curl -s "${OLLAMA}/api/generate" -d @- > "$rf"
  if ! jq -e .eval_count "$rf" >/dev/null 2>&1; then
    printf '%-30s %s  ERROR: %s\n' "$model" "$proc" "$(head -c 160 "$rf")"; rm -f "$rf"; return
  fi
  local fields
  fields=$(jq -r '[(.load_duration//0),(.prompt_eval_count//0),(.prompt_eval_duration//1),(.eval_count//0),(.eval_duration//1)]|@tsv' "$rf")
  rm -f "$rf"
  echo "$fields" | awk -v m="$model" -v proc="$proc" '{
    printf "%-30s %s  load=%6.2fs  prefill=%7.1f tok/s (%d tok)  gen=%6.1f tok/s (%d tok)\n",
      m, proc, $1/1e9, ($3>0?$2/($3/1e9):0), $2, ($5>0?$4/($5/1e9):0), $4 }'
}

echo "# Ollama baseline @ $(date -u +%FT%TZ)  num_ctx=${NUMCTX}"
echo "# (model, processor, load/swap latency, prefill tok/s, gen tok/s)"
for m in "$@"; do
  case "$m" in
    *:cpu) bench "${m%:cpu}" 0 ;;
    *)     bench "$m" -1 ;;
  esac
done
