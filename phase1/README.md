# Phase 1 — The Kernel

The evidence-native kernel: the smallest thing that does real work while making
the founding-incident class impossible. **Exit criterion MET.** Language: Python 3.

> The model never gets to assert what happened. The kernel executes, observes,
> and records; the model only proposes and reads results.

## What's built (`animal/`)

| Module | Role |
|--------|------|
| `types.py` | Contracts: `Event` (append-only record), typed `Action`s (argv-only — a shell *string* is unrepresentable), `Envelope` (the harness-COMPUTED result = the truth), closed `ErrorClass` taxonomy + round-trip codec |
| `ledger.py` | Append-only NDJSON (source of truth) + SQLite index; harness-stamped `ts`/`seq`; replay + seq-resume |
| `workspace.py` | The evidence core: shadow-git snapshot/diff/restore; read-before-edit + staleness invariants; computed-diff envelopes; non-persistence detection; disproportionate-match guard; workspace containment |
| `model.py` | llama-swap client; context-integrity guard (no silent truncation); single-typed-action-per-turn via constrained JSON |
| `sandbox.py` | Capability-probing bwrap wrapper (`full` / `fs_only` / `degraded`) — records the mode honestly; argv-only execution |
| `loop.py` | The single agentic loop + tool dispatch + the harness-run check runner |
| `cli.py` | `python3 -m animal.cli run "<task>" --repo <path> --check "<cmd>"` |
| `bastion.py` | Security-tap adapter — exports each session so the operator is audited |
| `config.py` | Roster/paths from Phase 0 |

## Exit criteria — MET

| Criterion | Evidence |
|-----------|----------|
| Real trivial-lane work on a live repo, standing alone | CLI + live coder (Qwen3-Coder-30B-A3B) fixed a real bug in 3 turns; harness-run check passed (exit 0) |
| Replayable ledger of computed envelopes | full event sequence reconstructs from NDJSON; edit envelope carries the real computed diff |
| Security tap sees animal sessions | per-session AI-activity record written to the Bastion feed |
| Seeded non-persistence + fabricated-check-pass caught | `tests/test_seeded_attack.py` — both flagged as tool errors, deterministically |

`tests/test_kernel.py` (9) + `tests/test_seeded_attack.py` (2) — all green.

## Running it

```bash
# 1. backend up (Phase 0): the roster behind llama-swap
~/llm/swap/llama-swap --listen 127.0.0.1:8890 --config phase0/llama-swap.roster.yaml &

# 2. run a task
python3 -m animal.cli run "Fix add() in calc.py to return a+b" \
    --repo /path/to/repo --check "python3 check.py"

# 3. tests
python3 tests/test_kernel.py && python3 tests/test_seeded_attack.py
```

## Sandbox note (honest)

The sandbox capability-probes at startup and records the mode. On the real
Corellia box (unprivileged userns enabled) it is `full` — root read-only,
workspace writable, network off. Inside a nested container (e.g. the environment
this was built in) userns/netns are blocked and it degrades to `degraded`
(cwd=workspace, scrubbed env; control-plane protection falls to the tool layer,
which enforces read-before-edit + workspace containment regardless). The mode is
in every session summary and the Bastion feed — never silently weaker.

## Deferred to later phases (deliberately not in the kernel)
- **Phase 2**: spec/DoD state machine, full lane manifests, the real human-channel
  service (phone flow), rejected-artifact registry, delivery receipts, egress proxy.
- **Phase 3**: the model plane arbiter, the panels + candidate-sampling, native
  per-model dialect adapters beyond the JSON protocol.
- **Phase 4**: calibration + the learning plane; native Bastion-format ingestion;
  the full-chain dry run.

The kernel stands alone and is worth building even if those never shipped — it
already makes agent work auditable and honest.
