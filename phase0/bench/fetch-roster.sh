#!/usr/bin/env bash
# Fetch the must-have Phase-0 model roster (GGUF) into var/models/ (git-ignored).
# Tolerant: verifies each repo exists (HF API) before pulling, uses --include
# quant patterns so exact filenames (incl. split parts) don't need to be known,
# and continues past any single failure. Logs to results/downloads.log.
#
# Usage: bash fetch-roster.sh
set -uo pipefail
DEST=${DEST:-/home/kellogg/dev/animal/var/models}
LOG=/home/kellogg/dev/animal/phase0/results/downloads.log
mkdir -p "$DEST"
: > "$LOG"

# repo | include-glob | nickname   (unsloth mirrors the standard GGUF quants)
ROSTER=(
  "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF|*Q4_K_M*|coder-qwen3-30b-a3b"
  "unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF|*Q4_K_M*|architect-qwen3-30b-thinking"
  "unsloth/gpt-oss-20b-GGUF|*Q4_K_M*|judge-gpt-oss-20b"
  "unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF|*Q4_K_M*|auditor-mistral-24b"
  "unsloth/Qwen3-4B-Instruct-2507-GGUF|*Q4_K_M*|jury-qwen3-4b"
  "unsloth/gemma-3-4b-it-GGUF|*Q4_K_M*|jury-gemma3-4b"
  "unsloth/Llama-3.2-3B-Instruct-GGUF|*Q4_K_M*|jury-llama32-3b"
  "Qwen/Qwen3-Embedding-0.6B-GGUF|*Q8_0*|embedder-qwen3-0.6b"
)

log(){ echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

for entry in "${ROSTER[@]}"; do
  IFS='|' read -r repo glob nick <<< "$entry"
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://huggingface.co/api/models/${repo}")
  if [ "$code" != "200" ]; then
    log "SKIP  $nick  ($repo -> HTTP $code; repo name needs fixing)"; continue
  fi
  log "PULL  $nick  <- $repo  (include $glob)"
  if hf download "$repo" --include "$glob" --local-dir "$DEST/$nick" >>"$LOG" 2>&1; then
    sz=$(du -sh "$DEST/$nick" 2>/dev/null | cut -f1)
    log "DONE  $nick  ($sz)"
  else
    log "FAIL  $nick  (see log)"
  fi
done
log "roster fetch complete"
du -sh "$DEST"/* 2>/dev/null | tee -a "$LOG"
