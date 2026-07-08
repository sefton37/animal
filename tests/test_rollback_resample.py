"""Story #448 -- rollback-and-resample after repeated failed edits on a target.
config.MAX_EDIT_RETRIES (the retry budget) had zero call sites before this story.
This proves the loop actually uses it: after MAX_EDIT_RETRIES consecutive failed
edit envelopes (ok=False) on the SAME path, run_task reverts ONLY that path
(Workspace.restore_path) to the checkpoint taken right before that failure
streak began and records an EventType.GATE ledger event -- but the session
does NOT terminate, it keeps consuming turns (a fresh resample) up to
max_turns. The failure counter is scoped PER PATH, not global, and the
revert itself is scoped PER PATH too: a successful edit to a DIFFERENT file
that landed in between must survive the gate (see
test_interleaved_success_on_other_path_survives_gate_rollback).

Deterministic: a scripted stand-in replaces the live llama-swap ModelPlane call,
so no model server is required. Run: python3 tests/test_rollback_resample.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes (ledgers, bastion feed) for this test process
# BEFORE any animal import resolves config.VAR (a #461 audit found suite runs
# appending records to the production var/bastion-feed.jsonl).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

import animal.loop as loop
from animal.ledger import Ledger
from animal.types import EventType
from animal import config


class _ScriptedModelPlane:
    """Deterministic stand-in for ModelPlane: replays a fixed list of actions,
    one per call, repeating the last one once the script runs out (so a task
    that never finishes still has something to propose every remaining turn)."""
    def __init__(self, actions):
        self.actions = list(actions)
        self.i = 0
        self.temps = []              # temperature seen on each call (proves resample varies it)

    def call(self, role, messages, temperature=None):
        self.temps.append(temperature)
        action = self.actions[min(self.i, len(self.actions) - 1)]
        self.i += 1
        return {"thought": "scripted", "action": action}, {"context_overflow": False}


def _repo_with(name: str, content: str) -> Path:
    repo = Path(tempfile.mkdtemp(prefix="animal-rollback-"))
    (repo / name).write_text(content)
    return repo


def _run_scripted(actions, repo, max_turns=10):
    """Runs loop.run_task with ModelPlane monkeypatched to a scripted plane, in the
    same save/replace/restore-in-finally style test_phase3.py uses for panel.run_seat."""
    orig = loop.ModelPlane
    plane = _ScriptedModelPlane(actions)
    loop.ModelPlane = lambda *a, **kw: plane
    ledger_dir = tempfile.mkdtemp(prefix="animal-rollback-ledger-")
    L = Ledger(ledger_dir=ledger_dir)
    try:
        summary = loop.run_task("rollback-resample test", str(repo), ledger=L, max_turns=max_turns)
    finally:
        loop.ModelPlane = orig
    return summary, L


def test_rollback_ceiling_stops_the_run_instead_of_burning_the_budget():
    # #448 red-team: rollback-and-resample must NOT loop to max_turns (the shipped
    # test used to assert turns==max_turns as CORRECT -- the exact anti-pattern the
    # user story forbids). After MAX_EDIT_RETRIES full rollback CYCLES on one path,
    # the run stops (stuck), well before the turn budget is exhausted.
    original = "def f():\n    return 1\n"
    repo = _repo_with("target.py", original)
    actions = [
        {"kind": "read", "path": "target.py"},
        {"kind": "edit", "path": "target.py",
         "old_string": "this text is never in the file", "new_string": "x"},
    ]
    summary, L = _run_scripted(actions, repo, max_turns=30)

    assert (repo / "target.py").read_text() == original      # never corrupted
    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    cycles = [g for g in gates if g["reason"] == "max_edit_retries_exceeded"]
    stuck = [g for g in gates if g["reason"] == "stuck_rollback_ceiling"]
    assert len(cycles) == config.MAX_EDIT_RETRIES            # a bounded number of rollback cycles
    assert cycles[0]["path"] == "target.py"
    assert cycles[0]["attempts"] == config.MAX_EDIT_RETRIES
    assert len(stuck) == 1 and stuck[0]["path"] == "target.py"
    # the crux: it STOPPED on the ceiling and did NOT exhaust the 30-turn budget
    assert summary["stop_reason"] == "stuck:target.py"
    assert summary["turns"] < 30
    assert not summary["finished"]


def test_interleaved_success_on_other_path_survives_gate_rollback():
    """Red-team fix: a whole-tree Workspace.restore() would silently wipe out
    a DIFFERENT file's successful, already-landed edit if it happened between
    the 1st and 3rd consecutive failures on the gated path -- with zero ledger
    trace, since the GATE payload only records the failing path. This drives
    exactly that interleaving (success on b.py sandwiched between failures on
    a.py) and asserts b.py's landed edit survives the a.py rollback."""
    original_a = "value = 1\n"
    repo = _repo_with("a.py", original_a)
    (repo / "b.py").write_text("value = 2\n")
    actions = [
        {"kind": "read", "path": "a.py"},
        {"kind": "edit", "path": "a.py",
         "old_string": "not in a.py", "new_string": "x"},        # fail 1/3 on a.py
        {"kind": "read", "path": "b.py"},
        {"kind": "edit", "path": "b.py",
         "old_string": "value = 2", "new_string": "value = 999"},  # success on b.py -- lands
        {"kind": "edit", "path": "a.py",
         "old_string": "not in a.py", "new_string": "x"},        # fail 2/3 on a.py
        {"kind": "edit", "path": "a.py",
         "old_string": "not in a.py", "new_string": "x"},        # fail 3/3 -> gate fires on a.py ONLY
        {"kind": "finish", "message": "done"},
    ]
    summary, L = _run_scripted(actions, repo, max_turns=10)

    # a.py's failed streak reverted it to its pre-streak content (failed edits
    # never write, so this was already true; the gate must not have broken it)
    assert (repo / "a.py").read_text() == original_a

    # b.py's SUCCESSFUL edit -- landed on a DIFFERENT path -- must survive the
    # gate that fired on a.py. A whole-tree restore() would wipe this silently.
    assert (repo / "b.py").read_text() == "value = 999\n"

    gates = [e for e in L.replay() if e.type == EventType.GATE.value]
    assert len(gates) == 1, "exactly one gate event, scoped to a.py"
    assert gates[0].payload["path"] == "a.py"
    assert summary["finished"]


def test_per_path_failure_counter_is_scoped_not_global():
    repo = _repo_with("a.py", "value = 1\n")
    (repo / "b.py").write_text("value = 2\n")
    actions = [
        {"kind": "read", "path": "a.py"},
        {"kind": "edit", "path": "a.py", "old_string": "not in a.py", "new_string": "x"},
        {"kind": "edit", "path": "a.py", "old_string": "not in a.py", "new_string": "x"},  # 2 fails on a.py
        {"kind": "read", "path": "b.py"},
        {"kind": "edit", "path": "b.py", "old_string": "not in b.py", "new_string": "x"},  # 1 fail on b.py
        {"kind": "finish", "message": "done"},
    ]
    summary, L = _run_scripted(actions, repo, max_turns=10)
    gates = [e for e in L.replay() if e.type == EventType.GATE.value]
    assert not gates, "2 failures on a.py + 1 on b.py must never accumulate into a rollback"
    assert summary["finished"]


def test_resample_raises_temperature_after_rollback():
    # #448 red-team: a "resample" must be a genuinely DIFFERENT sample, not the same
    # greedy decode replayed. The rollback gate raises the temperature for later
    # turns; assert a raised temperature is actually passed to the model plane.
    repo = _repo_with("target.py", "def f():\n    return 1\n")
    actions = [
        {"kind": "read", "path": "target.py"},
        {"kind": "edit", "path": "target.py", "old_string": "never here", "new_string": "x"},
    ]
    orig = loop.ModelPlane
    plane = _ScriptedModelPlane(actions)
    loop.ModelPlane = lambda *a, **kw: plane
    try:
        loop.run_task("t", str(repo), ledger=Ledger(ledger_dir=tempfile.mkdtemp()), max_turns=30)
    finally:
        loop.ModelPlane = orig
    raised = [t for t in plane.temps if isinstance(t, float)]
    assert raised, f"no float temperature was ever passed on resample: {plane.temps}"
    assert max(raised) > config.ROLES["coder"]["temperature"], \
        f"resample never raised temperature above the base: {plane.temps}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
