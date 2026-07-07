# Workstream 4 — Seat characterization on the llama.cpp stack (2026-07-07)

All seats measured on the built llama.cpp+CUDA stack (`llamacpp-bench.sh`).
Numbers are gen tok/s / batch-prefill tok/s / load / VRAM.

| Seat | Model (Q4_K_M unless noted) | Config | VRAM | load | prefill tok/s | gen tok/s | verdict |
|------|------------------------------|--------|-----:|-----:|---------------|----------:|---------|
| **Coder** | Qwen3-Coder-30B-A3B | `--n-cpu-moe 48` (all experts→CPU) | 2.8 GB | 5.1 s | 2,000–2,861 | **37** | sweet spot; partial GPU offload was *slower* |
| **Architect** | Qwen3-30B-A3B-Thinking-2507 | `--n-cpu-moe 48` | 2.8 GB | 8.1 s | 1,943–2,829 | **37–38** | same arch as coder; thinking model |
| **Judge** | gpt-oss-20b | full GPU `-ngl 999` | 11.4 GB | 5.1 s | 6,610–10,381 | **183–192** | blazing (MoE fully on GPU); ideal panel seat |
| **Auditor** | Mistral-Small-3.2-24B | `-ngl 30` (10 dense layers→CPU) | 11.2 GB | 3.9 s | 1,011 | **12** | does NOT fit full (see VRAM finding); partial offload works, slow but audits are infrequent |
| Jury ×3 | Qwen3-4B / Gemma-3-4B / Llama-3.2-3B | CPU `-ngl 0` | 0 (RAM) | — | — | ~15 (Ollama baseline) | llama.cpp CPU confirm pending |
| Embedder | Qwen3-Embedding-0.6B | GPU | ~0.7 GB | — | — | — | pending |

Context integrity: **no truncation** on any seat (server-reported prompt_n == sent) — the hard-fail gate passes across the board.

## KEY FINDING — usable VRAM is ~13.5 GB, not 15.5 GB

`nvidia-smi` compute-apps account for only ~221 MiB, but `memory.used` sits at
**~2,892 MiB** — the **desktop/display environment** (gnome-remote-desktop, the
compositor, Steam GUI) reserves ~2.9 GB of VRAM that never shows as a "compute"
process. So a model gets **~13.5 GB usable**, not the ~15.5 GB the roster planned
against. Consequences, measured:

- MoE seats (coder/architect, 2.8 GB) and gpt-oss judge (11.4 GB) fit comfortably.
- **The dense Mistral-24B auditor (13.3 GB weight buffer) does NOT fit fully** —
  OOM at `-ngl 999` even with a clean GPU. Options: (a) partial offload `-ngl 30`
  → 12 tok/s (chosen — audits are infrequent); (b) a smaller quant (Mistral Q3 ~11
  GB); (c) an MoE or ≤12 GB auditor of a distinct lineage; (d) **run the box
  headless for big-seat work** — the 2.9 GB desktop overhead returns and the dense
  24B fits. animal's unattended/overnight profile favors (d).

## Implications for the wall-clock model (O7 bet)

- **Prefill on GPU seats is 2,000–10,400 tok/s** — the wall-clock model feared
  ~160. A 10k-token panel bundle prefills in **~1–5 s**, not ~60 s. The dominant
  unknown resolves strongly favorably; full-chain estimates come down.
- **The judge seat is ~190 tok/s** — panel verdicts are near-instant on gen; the
  cost is the swap (load ~5 s) not the inference.
- Swap/load is 4–8 s for every seat (mmap + small GPU resident set), far under
  the 34 s gpt-oss swap seen on Ollama — llama.cpp's load path is much better.

## Adoption-gate status
- ✅ MoE-offload worth it (37 ≫ 12 floor)
- ✅ Context integrity (no silent truncation)
- ✅ Backend not a regression (prefill + load far exceed Ollama; gen competitive)
- ⏳ Grammar A/B — next (run on coder)
- ⏳ Decorrelation φ — next (co-failure matrix across judge-lineage seats)
