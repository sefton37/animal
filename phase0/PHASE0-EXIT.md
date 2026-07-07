# Phase 0 — Exit summary

**Status: exit criterion MET.** Numbers replace the wall-clock model; roster seats
have measured occupants; the grammar and decorrelation questions are settled by
data; the pre-registration is ratified and frozen. One workstream (full-chain dry
run) is deferred by dependency, not skipped — it genuinely needs Phase-1 kernel
pieces to exist, so it belongs at the Phase 0→1 boundary.

**Verdict: PROCEED TO PHASE 1.** The kernel bet is de-risked — backend built and
validated, scheduler working, every seat characterized, all adoption gates
passed, and the diversity thesis has clean directional support. No Phase-0
finding blocks Phase 1; the plan absorbs the corrections below.

## Measured corrections the architectural plan must absorb

| Assumption in the plan | Measured | Consequence |
|---|---|---|
| Memory bandwidth ~75–85 GB/s | **47 GB/s** | A3B MoE still fine (3B active); big *dense* CPU-offload is halved. Populating the other 2 DDR4 channels would ~2× it. |
| Usable VRAM ~15.5 GB | **~13.5 GB** (desktop reserves ~2.9 GB) | Dense-24B doesn't fit resident → partial offload or headless. MoE seats (2.8 GB) + gpt-oss (11.4 GB) comfortable. |
| Batch prefill ~160 tok/s (feared) | **2,000–10,400 tok/s** | The wall-clock model's dominant unknown resolves strongly favorably. Full-chain estimates drop; the real cost is model swaps (~5 s), not prefill. |
| MoE offload tuning unknown | **full expert offload (`--n-cpu-moe 48`) is the sweet spot** — 37 tok/s @ 2.8 GB | Partial GPU offload was *slower* (CPU↔GPU sync). Simplest config wins; leaves ~11 GB free. |
| Swap/load cost (34 s on Ollama) | **4–8 s** on llama.cpp | mmap + small GPU-resident set; swap-heavy panel scheduling is cheaper than feared. |
| "weak models + grammars beat prompts" | small models **100% valid free-form** even on nested schemas | Constrained decoding is cheap *insurance*, not load-bearing. Keep plain-text for edit bodies (Aider). |
| (new) premise review is a judgment task | **3–4B models degenerate** (all-"unsound"); ≥20B judges hit 88–94% | The tiny jury is for cheap classification only. Gate-0 premise review needs the big seats. |

## Adoption gates — all passed

| Gate | Bar | Result |
|---|---|---|
| MoE-offload worth it | ≥12 tok/s | ✅ 37 tok/s |
| Context integrity | no silent truncation | ✅ prompt_n == sent, every seat |
| Backend not a regression | ≥ Ollama | ✅ prefill + load far exceed Ollama |
| Grammar constrains without wrecking quality | validity ↑, edits not worse | ✅ neutral (100% both) → insurance, not necessity |
| Decorrelation | pairwise φ < 0.5 | ✅ **max φ = −0.07** (all pairs φ<0) |

## The decorrelation result (the diversity thesis test)

16-case seeded premise-review battery (8 sound / 8 unsound — the "checks pass but
the story is violated" shape, e.g. buoyancy "crate never dips below surface",
auth "lock out the legitimate owner"). Three capable distinct-lineage judges:

| Judge | Lineage | Accuracy | Bad premises caught |
|---|---|---|---|
| gpt-oss-20b | OpenAI | 94% | 8/8 |
| Mistral-Small-3.2-24B | Mistral | 94% | 7/8 |
| Qwen3-Coder-30B-A3B | Qwen | 88% | 6/8 |

Pairwise co-failure φ: −0.07, −0.10, −0.10 — all negative, and **both-wrong = 0 for
every pair**. On this box, diverse-lineage judges fail on *different* cases; where
one errs the others are right. A 3-family panel would have caught all 8 seeded bad
premises. Strong directional support for O4.

**Honest caveats.** n=16 (φ is noisy at this size); one battery; the Phase-3 gate
is the fuller test (bigger battery, more lineages incl. Gemma/DeepSeek). And the
measurement itself took 4 iterations — the first three produced plausible-looking
"FAIL" results that were pure artifacts (abstaining models, degenerate all-"unsound"
3–4B responders, gpt-oss reasoning truncated by a tight token budget). Only the
built-in degeneracy/abstain guard prevented reporting a fiction. That is the
project's founding lesson reproduced live: distrust a clean-looking number until
the thing producing it is verified to have actually functioned.

## Recommended seat operating configs (carry into Phase 1)

| Seat | Model | Config | Perf |
|---|---|---|---|
| Coder | Qwen3-Coder-30B-A3B Q4 | `-ngl 999 --n-cpu-moe 48 -fa on` | 37 tok/s, 2.8 GB |
| Architect | Qwen3-30B-A3B-Thinking Q4 | `-ngl 999 --n-cpu-moe 48 -fa on` | 37 tok/s, 2.8 GB |
| Judge | gpt-oss-20b Q4 | `-ngl 999 -fa on --jinja`, **generous max_tokens (≥1024, reasoning)** | 190 tok/s, 11.4 GB |
| Auditor | Mistral-Small-3.2-24B Q4 | `-ngl 30` (interactive) or full GPU headless | 12 tok/s partial, 11.2 GB; 94% on premise review |
| Jury (classification only) | Qwen3-4B / Gemma-3-4B / Llama-3.2-3B | `-ngl 0` (CPU) | ~15 tok/s; **not** for premise review |
| Scheduler | llama-swap phase-major group | `swap:true exclusive:true` | validated |

## Deferred / follow-ups
- **Full-chain dry run** → Phase 0/1 boundary (needs kernel).
- **gpt-oss** needs a generous token budget (≥1024) in any harness role — its reasoning trace precedes the content.
- **Auditor VRAM**: partial offload for interactive; headless for full-GPU (the unattended/overnight profile favors headless).
- **Phase-3 decorrelation**: bigger battery + Gemma/DeepSeek lineages; per-seat calibration over time.
- **Cleanup**: ~115 GB of orphaned gpt-oss quant bloat in `var/models/judge-gpt-oss-20b/` (see README; user `rm`).
