# Phase 2 — The Work-Lane State Machine

The gated work lane on top of the kernel: a task moves through a state machine
where **write capability follows state** and **only a human-channel grant reaches
the build state**. Gate 0 rejects vacuous/lint-bad DoD checks *before* the human
is asked. **Exit criterion MET.**

## What's built (`animal/`)

| Module | Role |
|--------|------|
| `spec.py` | `Spec` + `DoDCheck` typed objects (schema-constrained; argv-only checks; typed comparator grammar); `SpecState` enum = the state machine |
| `grounding.py` | resolve the files a spec references against the repo; record hash/existence + **misses** (a ref to a nonexistent file is caught before any work) |
| `dod.py` | the DoD executor (harness runs checks, N=3 for nondeterministic) + **authoring validation**: the negative-control (a check that passes pre-work is vacuous → rejected) and lints (grep BRE-alternation without `-E`, missing helper scripts, always-exit-0 shapes) |
| `task.py` | the work-lane state machine (`draft→grounded→approved→building→verifying→needs_human→done`); `can_write()` is true **only while building**; the `approved` transition requires a human grant |
| `human.py` | the approval service — approvals arrive over a channel no model output can write to (TUI keypress interactively; programmatic grant in tests). A model has no action that flips approval |
| `worklane.py` | orchestrates the full chain into one replayable ledger |

## Exit criteria — MET

| Criterion | Evidence |
|-----------|----------|
| A full-chain task lands with human gates over a real channel | live coder built through `draft → grounded → approved → building → verifying → done`; the approval came through the channel (not model output); the harness verified the DoD (passed) |
| A seeded vacuous check is rejected at authoring | `dod.validate_check` rejects it; the work lane rejects at `dod_authoring` **before the human is asked** |

Plus, by construction: a model **cannot self-approve** (no approval action exists),
capability follows state (`can_write` only while building), the reject path makes
**zero edits**, and a grounding miss is caught before approval.

`tests/test_phase2.py` — 13 tests, all green (+ Phase 1's 11 still green).

## The full chain

```
spec ─▶ ground ─▶ validate DoD (authoring: vacuous/lint REJECTED here)
     ─▶ HUMAN approval (real channel; model can't forge)
     ─▶ build   (write capability granted ONLY now — runs the kernel loop)
     ─▶ verify  (harness runs the DoD; real verdicts)
     ─▶ done | needs_human | rejected
```

## Running it

```python
from animal.spec import Spec, DoDCheck
from animal.worklane import run_work
spec = Spec("add() in calc.py must return a+b",
            dod=[DoDCheck("sums", ["python3","-c","import calc; assert calc.add(2,3)==5"], "exit_zero")])
run_work(spec, "/path/to/repo", approver=None)   # approver=None -> interactive TUI approval
```

## Deferred (within Phase 2 — the state machine + gates + human channel are done)
- **Model spec-author role**: specs are currently caller-provided/hand-authored; wiring
  the architect model to emit a `Spec` from a user story is next (the validate/ground/execute
  machinery is all in place).
- **Phone transport** for approvals (the `human.py` channel abstraction already supports it —
  it just needs the Tailnet endpoint); **rejected-artifact registry**; **delivery receipts**
  (reachable-history diff at push); **egress proxy** (per-task host allowlist).

## Deferred to later phases
- **Phase 3**: the model-plane arbiter + the decorrelated-family panels (premise review,
  audit) + candidate sampling — the diversity thesis Phase 0 validated.
- **Phase 4**: calibration + the learning plane; native Bastion-format ingestion.
