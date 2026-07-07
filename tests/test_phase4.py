"""Phase 4 learning-plane tests — deterministic, offline. Prove the two exits
(routing reads calibration; a compiled lesson blocks a regression on a real diff)
plus the store mechanics. Run: python3 tests/test_phase4.py
"""
import sys, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from animal.calibration import Calibration
from animal.lessons import Lessons
from animal.incidents import Incidents
from animal.spec import DoDCheck
from animal import watchdogs


def _db():
    return os.path.join(tempfile.mkdtemp(), "learning.db")


# --- EXIT 1: routing reads calibration ---

def test_routing_reads_calibration():
    cal = Calibration(_db())
    for _ in range(9): cal.record("A", "coder", "edit", True)
    cal.record("A", "coder", "edit", False)          # 9/10
    for _ in range(3): cal.record("B", "coder", "edit", True)
    for _ in range(7): cal.record("B", "coder", "edit", False)   # 3/10
    r = cal.route("coder", "edit", ["A", "B"])
    assert r["chosen"] == "A"
    assert cal.rate("A", "coder", "edit")["lo"] > cal.rate("B", "coder", "edit")["lo"]


def test_error_taxonomy_excludes_harness_fault():
    cal = Calibration(_db())
    cal.record("A", "coder", "edit", True)
    cal.record("A", "coder", "edit", False, error_class="harness_fault")   # not the model's fault
    cal.record("A", "coder", "edit", False, error_class="env_mismatch")    # nor this
    assert cal.rate("A", "coder", "edit")["n"] == 1                        # only the real one counted


def test_panel_weight_from_verdicts():
    cal = Calibration(_db())
    cal.ingest_panel_verdicts("mistral", {"c1": "unsound", "c2": "sound", "c3": "unsound"},
                              {"c1": "unsound", "c2": "sound", "c3": "sound"})   # 2/3
    w = cal.weight("mistral", "judge", "premise_verdict")
    assert 0.0 < w < 1.0 and cal.weight("unseen", "judge", "premise_verdict") == 0.5


# --- EXIT 2: a compiled lesson blocks a regression on a real diff ---

def test_lesson_compiles_and_blocks_regression():
    les = Lessons(_db())
    repo = Path(tempfile.mkdtemp()); (repo / "calc.py").write_text("def add(a,b):\n    return a + b\n")
    chk = DoDCheck("add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")
    les.upsert("k", "add must sum", paths=["calc.py"], check=chk, verified_good=True)
    L = les.upsert("k", "add must sum", paths=["calc.py"], check=chk, verified_good=True)  # 2nd -> compiles
    assert L["compiled"]
    assert not les.run_compiled(repo, ["calc.py"])["blocked"]           # correct code passes
    (repo / "calc.py").write_text("def add(a,b):\n    return a - b\n")  # REGRESSION
    res = les.run_compiled(repo, ["calc.py"])
    assert res["blocked"] and "k" in res["regressions"]


def test_lesson_upsert_reinforces_not_duplicates():
    les = Lessons(_db())
    les.upsert("k", "t"); L = les.upsert("k", "t")
    assert L["pos"] == 2 and les.db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 1


def test_lesson_contradict_lowers_confidence():
    les = Lessons(_db())
    les.upsert("k", "t"); les.upsert("k", "t")
    c1 = les.get("k")["confidence"]
    les.contradict("k")
    assert les.get("k")["confidence"] < c1


def test_lesson_needs_check_and_support_to_compile():
    les = Lessons(_db())
    L = les.upsert("noc", "no check attached")            # no check -> never compiles
    assert not L["compiled"]
    chk = DoDCheck("c", ["true"], "exit_zero")
    L = les.upsert("one", "one obs", check=chk)           # 1 obs < threshold -> not yet
    assert not L["compiled"]


# --- incidents + watchdogs ---

def test_incidents_supersede_tombstones():
    inc = Incidents(_db())
    old = inc.add("stale", claim="phone is always reachable")
    inc.add("corrected", claim="phone VPN drops on update", supersedes=old)
    active = inc.active()
    assert len(active) == 1 and active[0]["class"] == "corrected"


def test_watchdog_flags_empty_plane():
    empty = _db()
    Calibration(empty).close()   # create empty tables
    h = watchdogs.health(db_path=empty, ledger_dir=tempfile.mkdtemp())
    assert not h["healthy"] and any(not c["ok"] for c in h["checks"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
