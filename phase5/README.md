# Phase 5 — The Gated TDD Chain (M3)

The work lane grows the full agile discipline: a model authors the spec, a
tester authors a genuinely-failing test, the implementer makes it pass, and
three layers of distrust stand between "the model says done" and *done*.
Composed end-to-end as one call. **Exit criterion MET.**

## What's built (`animal/`)

| Piece | Story | Role |
|-------|-------|------|
| `product_owner.py` | #457 | A product-owner model call authors the Spec (user story / intent / out-of-scope / argv DoD) from plain language, with a corrective retry loop; the result faces the SAME grounding + authoring validation a hand-authored spec does. Gate 0 catches structural badness, so the approval summary shows every check's *body* and the cross-family premise panel defaults ON for model-authored specs. |
| `worklane.py` tester phase | #458 | Opt-in `tdd=True`: a tester role authors a test BEFORE the implementer runs. The harness — never the model's claim — confirms a genuine RED: scope gate (`tests/test_*.py`, directory anchored, raw-bytes changed-path list), the artifact actually exists and actually FAILS when the harness runs it, AND spec.dod independently still fails. The artifact is sha256-pinned *before* its RED run; GREEN re-runs the same bytes. Vacuous red → needs_human; scope violation → rejected. |
| `worklane.py` verifier gate | #459 | Claimed-vs-verified as DATA: a `verifier` GATE event + `Calibration.record(model, role, 'task_complete')` — only when the model actually claimed. The founding incident class (`model_claim_false`) lands in the Wilson-scored routing table, never in prose. Attribution ladder keeps the taxonomy honest: exit 126/127 → `env_mismatch`; the tester's own unmodified failing test → `other_actor_fault`; unstable evidence → `harness_fault`; none are charged. Crash-proof and purely observational: no store failure can change what state a task reaches. |
| `worklane.py` audit gate + `panel.audit_review` | #460 | Gate 3a (unconditional): every DoD check — and the tester's pinned files — re-run in a FRESH sandbox; any verify-vs-audit flip is unstable evidence: `harness_fault`, forced needs_human, typed `audit_halt` incident, nothing learned or charged from it. Gate 3b (default-on for model-authored specs): the cross-family panel attempts the adversarial construction ("a failure that passes every check but violates the story") and checks the diff is traceable to the story at all; `flagged` / `no_user_story` / all-abstain each halt a green run. |
| `worklane.run_tdd_work` | #461 | The composition: one call, plain-language story → authored spec → premise panel → human approval → TDD red → implement → GREEN → audit re-run → verifier calibration → audit panel → done \| needs_human \| rejected. Composition only — no gate logic duplicated. |

## Exit criteria — MET

**1. The composed chain reaches 'done' end-to-end** — the dogfood test
(`tests/test_phase5.py::test_run_tdd_work_end_to_end_dogfood`) drives
`run_tdd_work` on a toy repo with a deliberately-buggy `calc.add` (model calls
monkeypatched; every diff, check verdict, and gate computed by the real
harness): trajectory exactly
`['draft','grounded','approved','building','verifying','done']`, with the gate
sequence `grounding → dod_authoring → (premise_panel) → tester_scope →
tester_artifact → red_confirmed → dod_verify → audit_rerun → verifier →
audit_panel` in ledger order.

**1b. LIVE exit proof (2026-07-08, no mocks)** — the same `run_tdd_work` call
against the real llama-swap models on a toy broken-`calc.add` repo reached
`done` in 143 s: the product-owner authored the spec live, the tester CREATED
`tests/test_calc.py` with four module-level asserts (harness-run: exit 1, a
genuine red), the coder fixed the bug in 4 turns, GREEN passed with the
sha-pinned artifact unmodified, the fresh-sandbox audit re-run matched, the
verifier recorded a verified-TRUE claim, and the live cross-family audit
panel returned sound/traceable. All ten gates present in the live ledger with
those verdicts. It took three live iterations to get here, and the first two
FAILED SAFE — each stopped by the vacuous-red gate, each exposing a real
capability gap the mocked tests could not see: (1) the kernel's edit action
could not CREATE a file (the tester's first, correct instinct) → the #492
create form; (2) the tester wrote pytest-style `def test_...` that runs clean
as a script → the prompt now demands module-level asserts. The gates never
let a non-test through; the chain converged by fixing the *capability*, never
by weakening a gate.

**2. Every gate earns its place adversarially.** Each story shipped only after
a Gate-3 red-team (2–3 auditors + independent refute-verification of every
finding) demonstrated real failures — fixed, and almost all now regression
tests (two are code/config fixes without their own asserting test: the panel
prompt's injection clause, and the suite's `ANIMAL_HOME` redirects):
- #458: three rounds — no-op-stub/empty-diff reds; the implementer gutting the
  tester's test against a weak DoD (sha pinning); the quotePath and
  rename-collapse scope-gate bypasses; a self-rewriting test pinning its
  post-mutation bytes; an invalid-UTF-8 filename crashing the run.
- #459: an unguarded calibration write that killed the run *only when the
  model claimed*; the test suite fabricating `task_complete` rows in the
  production learning store; every failure mis-charged to the implementer.
- #460: the audit panel dark in every production path (the #449 precedent);
  the panel prompt exposed to injection via the diff under audit; test runs
  leaking ~60 synthetic ledgers into production `var/ledger` per suite run.

**3. No false 'done' on unstable or unowned evidence** — demonstrated paths:
verify-vs-audit mismatch (deterministic flip-flop check *and* a stateful
tester file) halts with a typed incident; a green `all_pass` is overridden by
`flagged` / `no_user_story` / all-abstain panel outcomes; a full test-suite
run writes **zero** rows to the production learning.db and **zero** files to
production `var/ledger` or the bastion feed (verified empirically by the #460
and #461 audits — the mechanism is the suite-wide `ANIMAL_HOME` redirect,
not an in-tree asserting test).

## Known residuals (named, tracked)
- **#490**: a byte-stable check/test gaming red↔green via *external state* it
  plants during its own run — the audit re-run narrows but cannot close it
  (same tree, no snapshot); quarantine of run-time side effects is the fix.
- Calibration's `model` key is the llama-swap seat alias; a roster remap
  merges histories (phase-4-wide trait).
- Under `tdd=True`, `ingest_ledger` attributes the whole shared ledger to the
  implementer role (documented in its docstring).
- Nondeterministic (`N=3`) checks get probabilistic-only mismatch coverage at
  the audit re-run.

## Run it

```
python3 tests/test_phase5.py          # 46 tests, no model server needed
                                      # (one is the live smoke, self-skips offline)
ANIMAL_LIVE_MODEL_TEST=1 python3 tests/test_phase5.py   # runs the live smoke for real
```

Live use: `worklane.run_tdd_work("story", repo, approver=...)` with llama-swap
up on :8890 (`phase0/llama-swap.roster.yaml`).

---

# M6 — The Timeboxed Sprint (the lifecycle animal is named for)

Given a review deadline, animal turns a prioritized, Fibonacci-pointed backlog
into real done/needs_human/rejected outcomes — iterating the M3 gated chain,
stopping *cleanly* at the deadline, and handing back one reviewable package.
**Exit criterion MET — proven live against real models.**

## What's built (`animal/`)

| Piece | Story | Role |
|-------|-------|------|
| `velocity.py` | #472 | How long a Fibonacci size ACTUALLY took, measured strictly from a run ledger's own `session_start`→`session_end` timestamps — never a caller-read clock (the 2026-04-20 flaky-timing incident was exactly an uninjected clock). `estimate_seconds` returns a NAMED, SPECULATED conservative default until real data exists, then the historical mean — more honest with every completion. A negative span (clock skew) is refused loudly, never a poisoned fact. |
| `scheduler.py` | #473 | `select_for_deadline(items, budget, estimate_fn)` — greedy by priority DESC, cheapest-first among equals (to land MORE items), a deterministic partition of the backlog. `estimate_fn` is injected, so the scheduler is pure arithmetic over harness-measured durations — no store, no model, no clock. `budget≤0` defers everything. |
| `sprint.py` | #474 | `run_sprint` iterates the REAL `worklane.run_work` chain over the scheduled queue. The budget is RE-CHECKED before each story: a started story runs to completion (never aborted mid-build); an unstarted story past the deadline is deferred. `now_fn` and `runner` are injected (the sprint's tests never touch a live model). Each story's state is written back exactly once; velocity is recorded only for stories that actually ran. |
| `review.py` | #475 | `assemble_review` + `to_markdown` — the package a maker reads in minutes instead of a ledger archaeology session. A real conservation check (no story in two buckets, none duplicated). Each needs_human/rejected story renders its failed DoD checks and ledger session id — the *why* and *where to look*, on the page. |
| `cli.py sprint` | #475 | `animal sprint --repo R --deadline (+Nm\|ISO8601) [--out D]` — runs the whole sprint and writes the JSON + markdown package. |

Named deviations from the pre-M2 story text (both are the roadmap's own
"extend M2, don't fork" correction): the sprint takes M2's `ProductStore`, not
a new `BacklogStore`/`var/backlog.db`; tests run directly (`python3 tests/…`),
not via pytest (not installed by design).

## Exit criterion — MET (live dogfood, real models, no mocks)

A backlog of **three genuinely-buggy `calc.py` functions** seeded with distinct
Fibonacci points/priority, run under a deadline whose conservative default
velocity forces a deferral:

```
$ printf 'y\ny\ny\n' | animal sprint --repo REPO --deadline +80m --out OUT

# Sprint review
**2 pts done** of 10 given (5 pts deferred); 54s used of 80.0m budget.
## finished
- story #1 — done (2 pts, 31s)
    - evidence: ledger session 32bdc00e9dff (3 turns)
- story #2 — needs_human (3 pts, 23s)
    - failed DoD: double
    - evidence: ledger session 10b6cc53d925 (3 turns)
## deferred
- story #3 — 5 pts — did not fit the deadline budget
```

The run is honest, not a happy path: **story #2 genuinely failed** — the coder
model *renamed* `double` to `multiply` instead of fixing it, so `calc.double`
vanished and the DoD check `assert calc.double(4)==8` failed. The harness
caught the wrong-thing-done and marked it `needs_human` with the failed check
named — the evidence-over-prose thesis, live: a model that "solved" the task
in a contract-breaking way does not get called done.

Velocity landed two real samples from the run's OWN ledger timestamps (not a
test fixture):

```
$ sqlite3 var/learning.db "SELECT spec_id, points, seconds, session_id FROM velocity"
spec-2387cb17|2|31.182315|32bdc00e9dff
spec-063b80a4|3|23.206029|10b6cc53d925
$ sqlite3 var/learning.db "SELECT COUNT(*) FROM velocity"
2
```

Backlog states written back exactly once (done / needs_human / deferred); the
review package's points conserve (2 done + 5 deferred, with the 3-pt
needs_human story surfaced in `points_attempted`, nothing hidden). The full
offline suite stayed green across the live run — no code was hand-patched to
make the dogfood pass.

## Run it

```
for f in tests/test_velocity.py tests/test_scheduler.py tests/test_sprint.py tests/test_review.py; do python3 $f; done
animal sprint --repo REPO --deadline +2h --out var/   # live, with llama-swap up on :8890
```
