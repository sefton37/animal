"""Phase 2 tests: Gate-0 (spec/DoD authoring validation) + the work-lane state
machine (capability-follows-state, human-gated). Deterministic — no model needed
(the live approve path is demonstrated separately; see phase2/README.md).
Run: `python3 tests/test_phase2.py` or under pytest.
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (a #460 audit found suite runs depositing synthetic
# work-lane ledgers into the PRODUCTION var/ledger).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal.spec import Spec, DoDCheck, SpecError, SpecState
from animal.dod import validate_check, run_check
from animal.sandbox import Sandbox
from animal.task import Task, TransitionError
from animal.worklane import run_work


def _repo(src="def add(a,b):\n    return a - b\n"):
    r = Path(tempfile.mkdtemp(prefix="animal-p2-"))
    (r / "calc.py").write_text(src)
    return r


def _good():
    return DoDCheck("add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")


# --- Gate 0: DoD authoring validation ---

def test_negative_control_rejects_vacuous():
    sb = Sandbox()
    v = validate_check(DoDCheck("vac", ["python3", "-c", "print(1)"], "exit_zero"), sb, _repo())
    assert not v["ok"] and v["vacuous"]


def test_good_check_accepted():
    v = validate_check(_good(), Sandbox(), _repo())      # fails pre-work (calc broken) -> not vacuous
    assert v["ok"], v


def test_lint_bre_alternation():
    v = validate_check(DoDCheck("bre", ["grep", "-n", "add|sum", "calc.py"], "exit_zero"), Sandbox(), _repo())
    assert not v["ok"] and any("BRE alternation" in r for r in v["reasons"])


def test_lint_missing_helper():
    v = validate_check(DoDCheck("m", ["python3", "nope.py"], "exit_zero"), Sandbox(), _repo())
    assert not v["ok"] and any("does not exist" in r for r in v["reasons"])


def test_executor_runs_check_real_result():
    r = _repo("def add(a,b):\n    return a + b\n")        # fixed
    res = run_check(_good(), Sandbox(), r)
    assert res["passed"] and res["exit_code"] == 0


def test_nondeterministic_runs_n3():
    flaky = DoDCheck("f", ["python3", "-c", "import random,sys; sys.exit(0 if random.random()<0.5 else 1)"],
                     "exit_zero", nondeterministic=True)
    assert run_check(flaky, Sandbox(), _repo())["runs"] == 3


def test_dodcheck_argv_only():
    try:
        DoDCheck("x", "python3 -c print(1)", "exit_zero"); assert False
    except SpecError:
        pass


def test_spec_roundtrip():
    s = Spec.from_dict({"user_story": "u", "dod": [_good().to_dict()]})
    assert s.dod[0].name == "add-sums" and s.state == SpecState.DRAFT.value


# --- work-lane state machine ---

def test_capability_follows_state():
    t = Task(Spec("u", dod=[_good()]))
    assert not t.can_write()                 # draft
    t.spec.state = SpecState.BUILDING.value
    assert t.can_write()                     # only building grants writes


def test_model_cannot_self_approve():
    t = Task(Spec("u", dod=[_good()])); t.spec.state = "grounded"
    try:
        t.transition("approved"); assert False, "self-approved without a grant"
    except TransitionError:
        pass
    t.transition("approved", approval="approve")   # only a human-channel grant works
    assert t.state == "approved"


def test_vacuous_spec_rejected_before_approval():
    seen = {"n": 0}
    def watch(k, s): seen["n"] += 1; return "approve"
    r = run_work(Spec("noop", dod=[DoDCheck("v", ["python3", "-c", "print(1)"], "exit_zero")]),
                 str(_repo()), approver=watch, max_turns=2)
    assert r["final_state"] == "rejected" and r["rejected_at"] == "dod_authoring"
    assert seen["n"] == 0, "human must not be asked to approve a vacuous spec"


def test_reject_path_makes_no_edits():
    repo = _repo()
    r = run_work(Spec("add must sum", dod=[_good()]), str(repo), approver=lambda k, s: "reject", max_turns=2)
    assert r["final_state"] == "rejected" and r["rejected_at"] == "approval"
    assert "a - b" in (repo / "calc.py").read_text()


def test_grounding_miss_rejected():
    r = run_work(Spec("x", dod=[DoDCheck("g", ["python3", "ghost.py"], "exit_zero")]),
                 str(_repo()), approver=lambda k, s: "approve", max_turns=2)
    assert r["final_state"] == "rejected" and r["rejected_at"] == "grounding"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
