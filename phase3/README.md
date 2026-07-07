# Phase 3 — The Cross-Family Panel

The diversity thesis Phase 0 validated (co-failure φ = −0.07), turned into running
machinery and measured against the pre-registered bar. **Exit criterion MET.**

## What's built (`animal/panel.py`)

- Runs a premise-review battery through 3 capable **distinct-lineage** judge seats
  (gpt-oss / OpenAI, mistral / Mistral, qwen / Qwen — via llama-swap), collecting
  **independent verdicts, one round, no debate**.
- Aggregates: `any` (flag if any seat flags) vs `majority` (≥ half of voters; a tie
  flags — a split panel surfaces doubt rather than passing silently). Abstains
  don't vote.
- Guards the Phase-0 traps: per-seat **abstain + degeneracy** computed; a degenerate
  seat (one-class answers, or > 20% abstain) is excluded and flagged.
- `review_spec`: the premise panel as a real **Gate-0 step**, wired into the work
  lane (opt-in) — surfaces gameable/misaligned checks to the human at approval.
- `measure_shared_prior`: **interpretation-enumeration** — a different task shape
  for the ambiguities no construct-a-failure panel can catch (it only asks the
  model to *name* the choice, which is robust to a shared prior).

## Exit measurement (40 cases: 20 unsound / 20 clean; results in `results/`)

**Panel — GATE PASS.**

| Seat | Lineage | Individual acc | Notes |
|------|---------|---------------:|-------|
| mistral | Mistral | **98%** | balanced, 0 abstain |
| qwen | Qwen | **92%** | balanced, 0 abstain |
| gpt-oss | OpenAI | 68% | the weak seat here — 7 abstains (reasoning truncation on hard cases) + over-flagging bias |

| Aggregation | Recall (unsound) | FP (clean) | Meets bar (≥80% / ≤10%) |
|-------------|-----------------:|-----------:|-------------------------|
| any | 100% | 30% | ✗ (gpt-oss over-flagging inflates FP) |
| **majority** | **95%** | **0%** | ✅ |

The panel catches **19/20 subtle bad premises and never false-flags a clean spec**,
and majority voting is **robust to a noisy seat** — mistral + qwen carry the
majority while gpt-oss's flakiness doesn't flip a clean verdict. Majority is the
operating rule; `any` fails on false-positives. The panel is both stronger and
safer than any single judge, which is the whole diversity claim.

**Shared-prior sub-exit — 6/6 (100%).** Interpretation-enumeration surfaced the
planted ambiguity (UTC-vs-local day, round-half-even, GB vs GiB, ISO-week, …) in
every case. *Honest note:* the first run scored 0/6 — a **measurement artifact**,
not a result: `measure_shared_prior` defaulted to gpt-oss, whose reasoning channel
returns empty content on the nested-enumeration schema. Re-run with a reliable
seat (qwen) → 6/6. The code now defaults enumeration to a non-reasoning seat, and
this is exactly the Phase-0 discipline: scrutinize a clean-looking number (a 0/6
"failure") for artifacts before trusting it.

## Verdict

The diversity bet (O4) **holds on this box**: a majority vote of three
decorrelated lineages catches subtle premise defects at 95% recall / 0% FP, and
interpretation-enumeration handles the shared-prior blind spot. The pre-registered
fallback (single-judge + human) is not triggered.

## Tests
`tests/test_phase3.py` — 4 offline tests (aggregation rules, abstain/degeneracy
guards, recall/FP arithmetic). Total suite: 28 green across Phases 1–3.

## Deferred (the one Phase-3 lane not built here)
- **Candidate-sampling / patch farm**: sample k patches from the resident coder,
  filter by harness-run tests, cross-family selector picks the winner. Most
  meaningful against a real scoped backlog (Cairn trim P2–P5) and a substantial
  GPU-heavy build — noted as the next Phase-3 increment.

## Deferred to Phase 4
- Calibration + the learning plane (per-seat detection-value scoring feeds panel
  vote-weighting and routing); native Bastion-format ingestion.
