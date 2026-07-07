"""Phase 1 kernel tests. Runnable directly (`python3 tests/test_kernel.py`) or
under pytest. These are the evidence the kernel's invariants hold — the same
"evidence over prose" discipline the kernel enforces on its agents."""
import sys, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal.ledger import Ledger
from animal.types import (EventType, action_from_dict, ActionParseError,
                          ShellAction, EditAction)
from animal.workspace import Workspace
from animal.types import ErrorClass


def test_ledger_append_replay_resume():
    d = tempfile.mkdtemp(prefix="animal-led-")
    L = Ledger(session_id="s", ledger_dir=d)
    L.append(EventType.SESSION_START, {"task": "t"})
    L.append(EventType.ACTION, {"kind": "edit"})
    L.append(EventType.ENVELOPE, {"ok": True})
    evs = L.replay()
    assert [e.type for e in evs] == ["session_start", "action", "envelope"]
    assert [e.seq for e in evs] == [0, 1, 2]
    assert all(e.ts for e in evs), "ts must be harness-stamped"
    # reopening resumes seq -> append-only survives restart
    assert Ledger(session_id="s", ledger_dir=d).append(EventType.SESSION_END).seq == 3


def test_action_codec_rejects_bad_shapes():
    assert isinstance(action_from_dict(
        {"kind": "edit", "path": "p", "old_string": "a", "new_string": "b"}), EditAction)
    assert isinstance(action_from_dict({"kind": "shell", "argv": ["ls", "-a"]}), ShellAction)
    for bad in [{"kind": "shell", "argv": "one big shell string"},  # argv must be a list
                {"kind": "nope"}, {"kind": "edit", "path": "p"}]:
        try:
            action_from_dict(bad); assert False, f"accepted bad action {bad}"
        except ActionParseError:
            pass


def _ws():
    repo = Path(tempfile.mkdtemp(prefix="animal-ws-"))
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    return repo, Workspace(repo, session_id="t", shadow_root=tempfile.mkdtemp())


def test_read_before_edit_enforced():
    _, ws = _ws()
    e = ws.edit("calc.py", "return a + b", "return a - b")
    assert not e.ok and e.error_class == ErrorClass.INVARIANT_VIOLATION.value


def test_real_edit_produces_computed_diff():
    repo, ws = _ws()
    ws.read("calc.py")
    e = ws.edit("calc.py", "return a + b", "return a - b")
    assert e.ok and "return a - b" in e.computed["diff"]
    assert (repo / "calc.py").read_text().find("a - b") >= 0


def test_non_persistence_caught():
    _, ws = _ws()
    ws.read("calc.py")
    e = ws.edit("calc.py", "return a + b", "return a + b")   # no change
    assert not e.ok and e.error_class == ErrorClass.NON_PERSISTENCE.value


def test_false_anchor_caught():
    _, ws = _ws()
    ws.read("calc.py")
    e = ws.edit("calc.py", "text that is absent", "x")
    assert not e.ok and e.error_class == ErrorClass.MODEL_CLAIM_FALSE.value


def test_staleness_caught():
    repo, ws = _ws()
    ws.read("calc.py")
    (repo / "calc.py").write_text((repo / "calc.py").read_text() + "\n# external\n")
    e = ws.edit("calc.py", "return a + b", "return a + b + 0")
    assert not e.ok and "stale" in e.note


def test_shadow_git_snapshot_diff_restore():
    repo, ws = _ws()
    t0 = ws.snapshot()
    ws.read("calc.py"); ws.edit("calc.py", "return a + b", "return a - b")
    t1 = ws.snapshot()
    assert t0 != t1 and "a - b" in ws.diff_trees(t0, t1)
    ws.restore(t0)
    assert "a + b" in (repo / "calc.py").read_text()


def test_workspace_containment():
    _, ws = _ws()
    e = ws.edit("../../etc/hosts", "x", "y")
    assert not e.ok and e.error_class == ErrorClass.INVARIANT_VIOLATION.value


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
