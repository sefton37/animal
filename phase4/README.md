# Phase 4 — The Learning Plane (Resonance's successor)

The plane that makes animal *improve*. Everything here is the Resonance necropsy
turned into design: learn from **verified outcomes**, never prose; upsert, don't
duplicate; confidence is a running posterior, not a birth certificate; compile
lessons into enforcement; and never die quiet. **Exit criterion MET.**

## What's built (`animal/`)

| Module | Role |
|--------|------|
| `calibration.py` | (model × role × claim-type) → claimed vs **verified-true**. The routing function AND the panel vote-weight. Wilson lower bound (1/1 doesn't outrank 90/100). The error taxonomy excludes harness/env faults so a model isn't charged for infrastructure noise. Fed by ledger + seeded-verdict projections. |
| `lessons.py` | lessons **upserted** by key (re-observation reinforces, never duplicates — Resonance made "Scope Drift" 35×); confidence a Beta posterior that reinforces / contradicts / decays; and the distinctive **compilation** — a lesson that earns support mints a standing DoD check that the harness runs on relevant diffs. |
| `incidents.py` | typed incident ledger (class / claim / reality / detection / root-cause / countermeasure), de-duplicated by **supersession** (a correction tombstones the stale record at write time). Seeded from `hallucinations.md`. |
| `watchdogs.py` | standing invariant checks over the plane — an empty or stale learning plane is a *finding*, not a silent nothing (Resonance's daemon died quiet for two weeks). |
| `cli.py learn` | read-only inspection of calibration / lessons / incidents / health. |
| `worklane.py` | opt-in `learn=` hook: after a verified run, ingest calibration + upsert the passed DoD checks as lessons (re-observation compiles them into regression guards). |

## Exit criteria — MET

**1. Routing reads calibration** — demonstrated on the *real* Phase-3 judge outcomes:

| Judge (seat) | verified rate | Wilson-lower vote-weight |
|--------------|--------------:|-------------------------:|
| mistral | 39/40 | **0.871** |
| qwen | 37/40 | 0.801 |
| gpt-oss | 27/40 | 0.520 |

`route("judge","premise_verdict",[…])` reads this table and picks **mistral** — the
best-verified judge. The calibration is a projection of verified outcomes (the
seeded panel verdicts), and reading it *is* the routing/weighting decision.

**2. A compiled lesson blocks a regression on a real diff** — a lesson carrying a
verified DoD check, once it earns support (≥2 verified observations), compiles into
a standing check. On correct code it passes; when the diff **regresses** (`add`
reverts to `a - b`) the compiled check fails → the regression is **blocked**. That
is "warned in memory" turned into "the harness won't let it happen again."

## The plane, seeded from real data
- **21 incidents** ingested from `hallucinations.md` (the corpus becomes typed,
  queryable context instead of 45 KB of prose to re-read).
- **3 judges calibrated** from the Phase-3 measurement (their real detection rates).

## Tests
`tests/test_phase4.py` — 9 offline tests (routing, error-taxonomy exclusion, panel
weight, lesson compile-and-block, upsert-not-duplicate, contradict/decay, incident
supersession, watchdog health). **Full suite: 38 green across Phases 1–4.**

## Deferred (the plane is complete; these are enrichments)
- Wire the calibration vote-weights into `panel.aggregate` as *weighted* majority
  (the weights exist and are read; the panel currently uses unweighted majority).
- Embedding-similarity lesson matching (currently keyed); native Bastion-format
  ingestion of the ledger; the full-chain dry run at production scale.

---

With Phase 4, **animal is functionally complete across the planned build**: it
measures its own hardware, runs an evidence-native kernel, gates work behind a
human-approved state machine that rejects vacuous checks, uses decorrelated model
families to both judge premises and generate fixes, and now learns from verified
outcomes — routing on measured track records and compiling earned lessons into
regression guards.
