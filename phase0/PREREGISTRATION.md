# Pre-registration — the falsification thresholds

Written at Phase 0, **before** the code that would let us rationalize a miss.
The whole point (ARCHITECTURE §What this experiment tests): the evidence-native
kernel (O2/O3) is a **verified invariant** — no threshold, it either enforces or
it is a bug — while O4 (diversity) and O7 (tiering) are **bets** that must be
falsifiable with numbers set in advance.

**Status: RATIFIED 2026-07-07** (Kel: "all looking good"). **Frozen** — Phase 3 is
graded against these numbers verbatim. Changing a threshold after this point
requires a dated amendment note below, not a silent edit.

---

## Bet 1 — Diversity (O4)

*Hypothesis:* a decorrelated-family panel is a cheaper, more honest reliability
lever than a single larger model, where judgment (not measurement) is required.

| Parameter | Proposed bar | Rationale |
|-----------|-------------|-----------|
| Seeded bad-premise battery size | **≥ 20** premises, hand-authored across ≥ 4 subsystems | enough to make a rate meaningful; small enough to author honestly |
| Clean-control set | **≥ 20** known-good specs, interleaved | measures the false-positive rate, not just recall |
| **Recall bar** (must catch) | **≥ 80%** of seeded bad premises | below this the panel misses too much to trust |
| **False-positive ceiling** | **≤ 10%** on clean controls | above this the panel cries wolf and burns the attention it exists to protect |
| Shared-prior sub-exit | separate: ≥ 5 ambiguities every family resolves identically (e.g. UTC-vs-local day boundary); measure whether interpretation-enumeration + data-receipt surface them | this class is *expected* to evade a construct-a-failure panel; graded separately, not folded into the 80% |

**Consequence if missed:** fall back to a single strong judge + human review; move
the diversity budget to candidate selection (where the evidence is already solid).
Graded at **Phase 3**.

## Bet 2 — Tiering (O7)

*Hypothesis:* the chain is usable at local-model speeds. Grounded in the Phase-0
baseline (14B ≈ 59 tok/s, gpt-oss:20b swap 34 s, CPU 4B ≈ 15.6 tok/s, memory
47 GB/s) — these are **installed-Ollama** numbers; re-set against the llama.cpp
stack once measured.

| Tier | Interactive claim | Proposed ceiling (p50, representative repo task) |
|------|-------------------|--------------------------------------------------|
| Trivial | interactive | **≤ 3 min** |
| Short chain | interactive | **≤ 25 min**; **declared non-interactive if > 40 min** → background-only |
| Full chain | **none** — supervised/overnight by design | no interactive falsifier; measured for planning only |
| Patch farm | overnight | validation-bound; no ceiling, just completes a batch |

**Consequence if missed:** the tier is reassigned to background/overnight (a real
conclusion about *where* animal is useful), not gate removal. Overnight slowness
is free by design and is **not** a falsifier.

## Phase-0 adoption gates (set now that we have data — pass/fail, not bets)

These decide whether we adopt the llama.cpp backend and the MoE-offload strategy
at all; measured in workstreams 4–7 as models land.

| Gate | Bar | Why |
|------|-----|-----|
| Backend not a regression | llama.cpp gen tok/s **≥** Ollama baseline for the same model (14B ≥ ~59, gpt-oss:20b ≥ ~24) | no point switching to a slower backend |
| Context integrity | server-reported prompt token count **==** tokens sent, every call; overflow **errors**, never silently truncates | silent truncation is the local twin of the founding hallucination — hard fail |
| MoE-offload worth it | 30B-A3B via `--n-cpu-moe` achieves **≥ 12 tok/s** gen | below ~12, a dense 14B (59 tok/s) is the better coder seat and the "big MoE" story is off for this box until the other 2 DDR4 channels are populated |
| Grammar constrains without wrecking quality | GBNF/JSON-schema tool-call validity **↑** vs plain-text, with edit-format correctness **not** worse (the Aider caveat) | settles the grammar-vs-plain-text A/B honestly |
| Decorrelation is real | pairwise co-failure φ across the three judge-lineage seats **< 0.5** on the seeded battery | if the "diverse" seats fail together, the roster is monoculture regardless of brand labels |

## What "settled by data" means for the Phase 0 exit

Phase 0 exits when: workstreams 1–9 have measured numbers in `results/`, the
roster seats have real occupants, the grammar and decorrelation questions have
data, and **this file is ratified and frozen**. The bets above are then graded at
Phase 3 against these exact numbers.
