"""Story #469 -- durable panel-estimate records. Deterministic, temp-db.
Run: python3 tests/test_estimates.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

import sqlite3
from animal.estimates import record_panel_run, query_by_story


def _db():
    return os.path.join(tempfile.mkdtemp(prefix="animal-est-"), "learning.db")


def test_record_and_query_round_trip():
    db = _db()
    run_id = record_panel_run("story-42", {"gpt-oss": 5, "mistral": 5, "qwen": 8},
                              aggregate_points=5, disagreement=1, escalated=False, db_path=db)
    rows = query_by_story("story-42", db_path=db)
    assert len(rows) == 3, rows
    assert all(r["run_id"] == run_id for r in rows)
    assert [r["seat"] for r in rows] == ["gpt-oss", "mistral", "qwen"]
    assert rows[0]["model"] == "judge" and rows[2]["model"] == "coder"   # joinable to calibration keys
    assert all(r["aggregate_points"] == 5 and r["disagreement"] == 1 and not r["escalated"]
               for r in rows)


def test_run_panel_dict_shape_and_abstains_record():
    """run_panel's {points, reasoning} shape lands directly; an abstain (None)
    is a REAL observation, stored as NULL, never dropped or invented."""
    db = _db()
    record_panel_run("s2", {"gpt-oss": {"points": None, "reasoning": "abstain"},
                            "mistral": {"points": 13, "reasoning": "big"}},
                     aggregate_points=13, disagreement=0, escalated=True, db_path=db)
    rows = query_by_story("s2", db_path=db)
    assert len(rows) == 2
    assert rows[0]["points"] is None and rows[1]["points"] == 13
    assert all(r["escalated"] for r in rows)


def test_multiple_runs_accumulate_never_overwrite():
    """Estimate HISTORY is the product: re-sizing a story appends a new run,
    the old record survives (estimate-vs-actual needs the trail)."""
    db = _db()
    r1 = record_panel_run("s3", {"mistral": 3}, 3, 0, False, db_path=db)
    r2 = record_panel_run("s3", {"mistral": 8}, 8, 0, False, db_path=db)
    rows = query_by_story("s3", db_path=db)
    assert len(rows) == 2 and rows[0]["run_id"] == r1 and rows[1]["run_id"] == r2
    assert [r["points"] for r in rows] == [3, 8]


def test_escalated_human_pick_round_trips_distinct_from_median():
    """Audit #469 minor: aggregate_points is the FINAL converged size (the
    human's pick when escalated) -- and the panel's own median stays
    recomputable from the per-seat votes, so #480 can tell 'panel said 3,
    human said 13'."""
    from animal.poker import aggregate_votes
    db = _db()
    # votes 1/3/21 (index-median 3), human escalated to 13
    record_panel_run("s-esc", {"gpt-oss": 1, "mistral": 3, "qwen": 21},
                     aggregate_points=13, disagreement=6, escalated=True, db_path=db)
    rows = query_by_story("s-esc", db_path=db)
    assert all(r["aggregate_points"] == 13 and r["escalated"] for r in rows)   # human's pick
    panel_median = aggregate_votes([r["points"] for r in rows])["median"]
    assert panel_median == 3, panel_median                                     # panel's own view survives


def test_model_travels_with_the_vote_unknown_seat_is_null_not_guessed():
    """Audit #469 major: model identity comes from the vote dict (run_panel's
    shape); an unknown seat records model NULL, never a silent identity guess."""
    db = _db()
    record_panel_run("s-model", {"gpt-oss": {"points": 5, "model": "judge"},
                                 "custom-seat": {"points": 8}},   # not in the roster, no model
                     aggregate_points=5, disagreement=1, escalated=False, db_path=db)
    rows = {r["seat"]: r for r in query_by_story("s-model", db_path=db)}
    assert rows["gpt-oss"]["model"] == "judge"
    assert rows["custom-seat"]["model"] is None, rows["custom-seat"]


def test_plain_sqlite_inspectable():
    """The AC's sovereignty check: the table reads with plain sqlite3."""
    db = _db()
    record_panel_run("s1", {"gpt-oss": 5, "mistral": 5, "qwen": 8}, 5, 1, False, db_path=db)
    n = sqlite3.connect(db).execute("select count(*) from story_estimates").fetchone()[0]
    assert n == 3, n


def test_no_calibration_coupling():
    """The AC's scope pin, at its exact letter: recording, not verifying --
    no verified outcome exists at estimation time, so the word 'calibration'
    must not appear in estimates.py at all (grep -c == 0)."""
    src = Path(__file__).resolve().parent.parent.joinpath("animal", "estimates.py").read_text()
    assert "calibration" not in src.lower(), "estimates.py must not reference calibration"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
