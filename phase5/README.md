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
