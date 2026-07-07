# Workstream 3 — Backend install path (researched 2026-07-07)

Target backend is llama.cpp `llama-server` + `llama-swap` (per ARCHITECTURE §The
model plane). Research verified against live GitHub release APIs; every
load-bearing claim carries a source. **Not yet installed — awaiting a path
decision (sovereignty vs. effort trade-off; see below).**

## Critical finding

**Official llama.cpp ships NO Linux x64 CUDA binary.** The current release
(tag `b9895`) publishes Linux assets for CPU, **Vulkan**, ROCm, SYCL, OpenVINO
only; the CUDA + `cudart` companions are **Windows-only**. Verified via
`gh api repos/ggml-org/llama.cpp/releases/latest`. So "download the official CUDA
binary" is not an option; three real paths remain.

## The three paths

| Path | What | CUDA? | sudo? | First-party? | Notes |
|------|------|-------|-------|--------------|-------|
| **A — keypaa/llamaup** | third-party rebuild of the same upstream tag as `llama-b<tag>-linux-cuda12.4-sm89-x64.tar.gz`; **bundles cudart** (driver-only, no toolkit); `sm89` = our exact Ada GPU | ✅ native | ❌ none | ❌ **third-party** | fastest to running; supply-chain trust hole for a sovereignty-first project |
| **B — official Vulkan** | official `llama-b<tag>-bin-ubuntu-vulkan-x64.tar.gz`; NVIDIA Vulkan ICD already present on box | ⚠️ via Vulkan | ❌ none | ✅ yes | first-party, no sudo, GPU works — but Vulkan is slower than CUDA and **MoE/flash-attn coverage lags CUDA**, so it under-measures the very CUDA features Phase 0 must test |
| **C — source build (CUDA)** | build official source with `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89` | ✅ native | ✅ **needs sudo** | ✅ yes | most sovereignty-aligned + native CUDA; needs `cmake` + minimal CUDA components (`cuda-nvcc-12-x` + `libcublas-dev-12-x`, NOT the full toolkit) via NVIDIA apt repo, then a ~10–20 min build |

## Recommendation

**Path C (build from official source, CUDA).** Rationale: Phase 0's job is to
measure the CUDA-specific capabilities the design bets on — `--n-cpu-moe` expert
offload, GBNF/JSON-schema grammars, `--cache-reuse`/`--cache-ram` prefix caching.
Vulkan (Path B) under-measures exactly those, so it would give misleading Phase-0
numbers. Path A gives native CUDA but asks a sovereignty-first project to trust an
unaudited third-party binary that bundles its own cudart — off-brand for O1.
Path C is first-party source + native CUDA; the only cost is a few `sudo apt`
commands (which need the human) and build time. The minimal component set avoids
the multi-GB full toolkit.

If getting numbers *today* matters more than first-party purity, **Path B** is a
fine bridge (no sudo, running in minutes) for the backend-agnostic measurements
(tok/s, grammars are GBNF and work on any backend), with Path C to follow for the
MoE/CUDA-specific numbers.

## Verified flags (current server README)

- `-ngl all` / `--n-gpu-layers` (now accepts `auto`/`all`) — full GPU offload.
- `--n-cpu-moe N` — keep MoE weights of first N layers on CPU. ✅ exists.
- `--jinja` — **default-on** now (`--no-jinja` to disable).
- `--cache-reuse N` — KV-shift prompt-cache reuse. ✅
- `--cache-ram N` — host-RAM KV cache, **default 8192 MiB**, -1 = unlimited. ✅
- `--parallel N` / `-np` + `GET /slots` — server slots.
- `--grammar` / `--grammar-file` (GBNF), `--json-schema`/`-j` + request `json_schema`. ✅
- `-fa on|off|auto` — **changed**: flash-attn now takes a value (default `auto`);
  q8_0 KV needs `-fa on --cache-type-k q8_0 --cache-type-v q8_0`.
- logprobs via request `n_probs` + `post_sampling_probs`. ✅
- `/props`, `/v1/chat/completions`, `/v1/completions`, `/v1/models`. ✅

## llama-swap

Release **v235**; asset `llama-swap_235_linux_amd64.tar.gz` (the bare-binary URL
in blog posts is stale — use the tarball). Config: per-model `cmd` (with
`${PORT}`), `ttl` (idle-unload), `aliases`, `env`, `checkEndpoint`; `groups` with
`swap: true` (one member loaded at a time — this is our phase-major GPU
scheduler), `exclusive`, `persistent`. Run: `llama-swap --listen ADDR --config
config.yaml`. This fronts N llama-server instances behind one OpenAI-compatible
endpoint and is the concrete implementation of the plan's VRAM arbiter / phase
scheduler.

Sources: ggml-org/llama.cpp releases + build.md + server README; keypaa/llamaup;
mostlygeek/llama-swap + configuration.md; NVIDIA CUDA compatibility.
