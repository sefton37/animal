# Phase 0 — Measure

Phase 0 has one job: **replace the wall-clock model's guesses with measured
numbers, settle the grammar and decorrelation questions with data, and
pre-register the two experimental bets' thresholds** — before any kernel code is
written. See [`../docs/ARCHITECTURE.md` §Build phases](../docs/ARCHITECTURE.md#build-phases).

Nothing here is the harness. This is the instrument that tells us which numbers
in the plan were wishful.

## Workstreams

| # | Workstream | Status | Output |
|---|-----------|--------|--------|
| 1 | Real memory bandwidth (STREAM, not dmidecode nameplate) | ✅ **47.0 GB/s** (½ of assumed — 2/4 channels?) | `results/memory-bandwidth.txt` |
| 2 | Baseline the installed stack (Ollama) — the "installed zoo" column | ✅ done (14B 59 tok/s, gpt-oss:20b 23.7 tok/s / 34s swap) | `results/ollama-baseline.txt` |
| 3 | Install `llama-server` (CUDA) + `llama-swap` — the target backend | ✅ **built + validated** (CUDA sm89, tag 33ca0dc); llama-swap v235 phase-major swap **proven** (coder↔architect, one GPU seat at a time) | `results/backend-install.md`, `results/model-roster.md`, `llama-swap.roster.yaml` |
| 4 | Re-measure swap / batch-prefill(8k,32k) / tok-s / prefix-cache on llama.cpp | ✅ **4 GPU seats characterized** — coder/architect 37 t/s @2.8GB, judge(gpt-oss) **190 t/s** @11.4GB, auditor(Mistral-24B) 12 t/s @11.2GB (partial offload). Prefill 2k–10k t/s. **KEY: usable VRAM ~13.5GB (desktop eats 2.9GB) → dense-24B needs offload/headless.** jury+embedder pending. | `results/seat-characterization.md` |
| 5 | Multi-turn agentic soak per hybrid model (prompt-cache correctness, no CUDA faults) | ⛔ blocked on #3 | `results/hybrid-soak.md` |
| 6 | Grammar-constrained vs plain-text A/B (edit + tool-call fidelity) | ⛔ blocked on #3 | `results/grammar-ab.md` |
| 7 | Co-failure matrix across roster seats (decorrelation, measured) | ⛔ blocked on #3 + models | `results/cofailure-matrix.md` |
| 8 | Jury-on-CPU latency (3–4B, `num_gpu=0`) | ◐ Ollama 4B ≈ 15.6 tok/s CPU (~10s/verdict — usable) | `results/ollama-baseline.txt` |
| 9 | Time one full-chain dry run | ⛔ blocked on kernel bits | `results/fullchain-dryrun.md` |
| 10 | **Pre-register** panel thresholds (recall/FP) + interactive-latency ceiling | ⏳ proposed, awaiting ratification | `PREREGISTRATION.md` |

Legend: ▶ running · ◐ partial · ⏳ in progress · ⛔ blocked · ✅ done

## Exit criterion

Numbers replace the wall-clock model; roster seats have measured occupants; the
grammar and decorrelation questions are settled by data; the two experimental
bets (diversity, tiering) have **written** thresholds in `PREREGISTRATION.md`.

## Layout

```
phase0/
├── README.md              this file — plan + live status
├── PREREGISTRATION.md      the falsification thresholds (written before Phase 3)
├── bench/                  measurement scripts (reproducible)
│   ├── stream.c            memory-bandwidth ground-truth
│   └── ollama-baseline.sh  installed-stack baseline via /api/generate timings
└── results/               captured numbers (committed — they ARE the deliverable)
```

## Running the benches

```bash
# memory bandwidth
gcc -O3 -fopenmp -march=native bench/stream.c -o /tmp/stream
OMP_NUM_THREADS=24 OMP_PROC_BIND=spread OMP_PLACES=cores /tmp/stream

# installed-stack baseline (append :cpu to a model to pin num_gpu=0)
bash bench/ollama-baseline.sh qwen2.5-coder:14b qwen3:4b:cpu gpt-oss:20b
```

## Ground-truth hardware (recon 2026-07-07)

- GPU: RTX 4070 Ti SUPER, 16376 MiB, driver 580.159.03, Ada (cc 8.9). No CUDA
  toolkit (`nvcc`) or `cmake` installed → backend install must use prebuilt
  binaries, not a source build.
- CPU: AMD Threadripper 3960X, 24C/48T, single NUMA node.
- RAM: 251 GB DDR4 (quad-channel capable; real bandwidth measured in workstream 1).
- Disk: 2.9 TB free on `/` — ample for model downloads.
- Installed backend: Ollama 0.30.10 (`flash_attention=1`, `kv_cache_type=q8_0`,
  `max_loaded_models=3`). llama.cpp / llama-swap: **not present**.
- Local state (ledgers, DBs, downloaded models) is git-ignored; only scripts and
  curated results are committed.
