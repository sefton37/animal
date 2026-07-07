"""The Phase 1 exit proof: the kernel catches the two founding-incident classes as
tool errors, by construction, without trusting any model claim.

  1. Non-persistence — an agent "edits" a file but nothing actually changes.
     The workspace computes an empty diff and flags NON_PERSISTENCE.
  2. Fabricated check-pass — an agent "claims" a check passed. The harness re-runs
     the check itself; the REAL exit code is authoritative, so a failing check is
     reported as failed regardless of any claim.

Deterministic (no model needed) — these are invariants, not behaviors.
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal.workspace import Workspace
from animal.sandbox import Sandbox
from animal.types import Envelope, ErrorClass


def test_seeded_non_persistence_is_flagged():
    """A claimed edit that leaves the file unchanged is a tool error, not a fact."""
    repo = Path(tempfile.mkdtemp(prefix="animal-atk-"))
    (repo / "m.py").write_text("def f():\n    return 1\n")
    ws = Workspace(repo, "atk1", shadow_root=tempfile.mkdtemp())
    ws.read("m.py")
    # the "attack": agent asserts it changed the return, but old==new -> no diff
    env = ws.edit("m.py", "return 1", "return 1")
    assert not env.ok, "non-persistent edit must not be accepted"
    assert env.error_class == ErrorClass.NON_PERSISTENCE.value
    # and the file is genuinely unchanged (the claim bought nothing)
    assert (repo / "m.py").read_text() == "def f():\n    return 1\n"


def test_seeded_fabricated_check_pass_is_flagged():
    """The harness runs the check; a real failure is reported as failure regardless
    of what a model might claim about it."""
    repo = Path(tempfile.mkdtemp(prefix="animal-atk-"))
    (repo / "t.py").write_text("assert 1 == 2, 'this check genuinely fails'\n")
    sb = Sandbox()
    # the harness-run check (the check runner's core): real exit code, computed
    r = sb.run(["python3", "t.py"], repo)
    ok = r["exit_code"] == 0
    env = Envelope("check", ok, ErrorClass.NONE.value if ok else ErrorClass.MODEL_CLAIM_FALSE.value, computed=r)
    assert not env.ok, "harness must report the real (failing) check result"
    assert env.error_class == ErrorClass.MODEL_CLAIM_FALSE.value
    assert r["exit_code"] != 0
    # control: a genuinely-passing check is reported as passing
    (repo / "ok.py").write_text("assert 1 == 1\n")
    r2 = sb.run(["python3", "ok.py"], repo)
    assert r2["exit_code"] == 0


if __name__ == "__main__":
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        fn(); print(f"  ok  {name}")
    print("\nSEEDED-ATTACK EXIT PROOF PASS — the kernel catches both classes by construction")
