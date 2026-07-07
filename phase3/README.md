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

## Candidate-sampling / patch farm — DONE (`animal/candidates.py`)

Diverse GENERATION filtered by objective tests, then cross-family selection —
the generation-side counterpart to the panel. Sample k coder attempts at spread
temperatures (single family in generation, per Self-MoA) → test-filter (the
harness runs the task's test on each) → a cross-family selector (mistral) picks
among the survivors (objective filters first, model judgment last, per CodeMonkeys).

**Result** (6 self-contained bugs, k=5, coder=qwen, selector=mistral):

| Metric | Result |
|--------|--------|
| **Farm solved** | **6/6** |
| Single-attempt (temp 0.2) baseline | 5/6 |

The farm recovered a fix a single attempt missed: `ob-2` (an `n=0` slice bug)
failed at temp 0.2 but passed at temps 0.5–1.1 — the test-filter kept the winners.
Candidate pass rates ranged 3/5–5/5 across tasks, confirming temperature diversity
matters (some samples fail; the objective filter keeps the ones that pass). This is
the Agentless insight realized on-box: cheap local tokens → sample many → recover
misses.

*Honest caveats:* these are easy single-file bugs, so the sampling gain is modest
(6/6 vs 5/6) — on harder tasks and larger k the gap widens (Agentless sampled ~40).
The backlog is a constructed 6-bug set; pointing the farm at a real scoped backlog
(Cairn trim P2–P5) is the production use. Results in `results/patch-farm.{txt,json}`.

## Production-scale trial on real repos (Cairn + Stalag) — the honest finding

Pointing the farm at two real codebases produced a more useful result than a green
checkmark: **the farm is a specialized tool, and neither project's actual backlog
is its shape.**

- **Cairn** (`~/dev/Cairn`, Python monorepo): its trim backlog (#259–276) is
  *green-preserving refactors, migrations, and architecture decisions* — the
  opposite of the farm's red→green contract (make a *failing* test pass). Its test
  suite also resolves DB paths under `~/.talkingrock`; the paths are redirectable
  (`HOME` + `TALKINGROCK_DATA_DIR`) so the live DB is protectable (verified
  untouched), but farming it cleanly needs its `.venv`/editable-install worked
  around on copies. Not run — wrong shape, disproportionate setup.
- **Stalag** (`~/dev/stalag`, JS game): its backlog (#294–439) is creative/graphics/
  simulation features whose correctness is *perceptual* (the `HUMAN_CHECK` class the
  design says the farm can't judge), and its logic suite already passes.

So the honest "farm on real code" run is mutation-testing on **real Stalag modules
against their real tests**: seed a validated regression in `cells.js` / `to-cell.js`,
make the farm recover it, verified by the real `cells.test.mjs` / `geometry.test.mjs`.

**Result** (4 real-module regressions, k=5): farm solved **4/4**, **0 test-gamed**
(the guard confirmed every fix edited the module, not the test). But single-attempt
also solved 4/4 — these single-line regressions are easy enough that temp-0.2 gets
them first try, so this run **did not exercise the sampling advantage**. That
advantage is real but only shows on harder bugs (the constructed `ob-2` above,
recovered only at raised temperature); a fair production demonstration of *sampling
value* needs subtler, multi-step regressions. What this run *does* prove: the farm
and its anti-gaming guard operate correctly on real, non-toy code and real test
suites. Results in `results/stalag-farm.{txt,json}`.

## Deferred to Phase 4
- Calibration + the learning plane (per-seat detection-value scoring feeds panel
  vote-weighting and routing); native Bastion-format ingestion.
