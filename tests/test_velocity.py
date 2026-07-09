"""Story #472 -- velocity tracker: durations from ledger ts, honest estimates.
Deterministic, temp-db, no model calls. (AC's `pytest -k` letter maps to this
repo's direct runner: the -k names are the test function names below.)
Run: python3 tests/test_velocity.py
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

import animal.velocity as velocity
from animal.velocity import record_completion, estimate_seconds, DEFAULT_SECONDS_PER_POINT
from animal.ledger import Ledger


def _db():
    return os.path.join(tempfile.mkdtemp(prefix="animal-vel-"), "learning.db")


def _ledger_with_span(start_ts: str, end_ts: str) -> Ledger:
    """A ledger whose OWN session_start/session_end carry controlled ts --
    written straight to the NDJSON truth replay() reads, so record_completion
    measures exactly this gap and nothing the test process's clock added."""
    d = tempfile.mkdtemp(prefix="animal-vel-led-")
    L = Ledger(ledger_dir=d)
    sid = L.session_id
    lines = [
        {"id": "e1", "session_id": sid, "seq": 1, "schema_version": 1,
         "type": "session_start", "ts": start_ts, "payload": {"lane": "work"}},
        {"id": "e2", "session_id": sid, "seq": 2, "schema_version": 1,
         "type": "session_end", "ts": end_ts, "payload": {"final_state": "done"}},
    ]
    (Path(d) / f"{sid}.ndjson").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return L


def test_derives_from_ledger_ts():
    """Elapsed is the ledger's OWN session_start->session_end gap -- exactly
    1830s here -- never a clock velocity.py read itself."""
    db = _db()
    L = _ledger_with_span("2026-07-08T10:00:00+00:00", "2026-07-08T10:30:30+00:00")
    secs = record_completion(L, "spec-1", 5, db_path=db)
    assert secs == 1830.0, secs
    import sqlite3
    stored = sqlite3.connect(db).execute(
        "SELECT seconds, points, spec_id FROM velocity").fetchone()
    assert stored == (1830.0, 5, "spec-1"), stored


def test_derives_from_ledger_ts_missing_pair_raises():
    """An unmeasurable run (no paired start/end) is a LOUD failure, never a
    silent zero-duration row."""
    d = tempfile.mkdtemp(prefix="animal-vel-led-")
    L = Ledger(ledger_dir=d)
    sid = L.session_id
    (Path(d) / f"{sid}.ndjson").write_text(
        json.dumps({"id": "e1", "session_id": sid, "seq": 1, "schema_version": 1,
                    "type": "session_start", "ts": "2026-07-08T10:00:00+00:00", "payload": {}}) + "\n")
    try:
        record_completion(L, "s", 3, db_path=_db())
        assert False, "expected ValueError for an unmeasurable run"
    except ValueError:
        pass


def test_negative_span_raises_never_stored():
    """Audit major: end<start (clock skew) is physically impossible -- a
    negative duration would push the scheduler toward overcommit. Refused
    loudly, exactly like an unmeasurable run, never a stored fact."""
    db = _db()
    L = _ledger_with_span("2026-07-08T10:30:00+00:00", "2026-07-08T10:00:00+00:00")  # end<start
    try:
        record_completion(L, "skew", 5, db_path=db)
        assert False, "expected ValueError for a negative span"
    except ValueError:
        pass
    # the guard fires BEFORE any db write; nothing was stored (recent() reads
    # via the module's own connect, creating the table empty)
    assert velocity.recent(db_path=db) == []


def test_estimate_seconds_n0_fallback_and_n1_historical():
    """n=0 -> the SPECULATED default (points * DEFAULT_SECONDS_PER_POINT);
    once completions exist at that size -> their historical mean."""
    db = _db()
    # n=0 for size 5 -> speculated default
    assert estimate_seconds(5, db_path=db) == DEFAULT_SECONDS_PER_POINT * 5
    # record two real 5-point completions: 1000s and 2000s -> mean 1500
    record_completion(_ledger_with_span("2026-07-08T00:00:00+00:00", "2026-07-08T00:16:40+00:00"),
                      "a", 5, db_path=db)   # 1000s
    record_completion(_ledger_with_span("2026-07-08T00:00:00+00:00", "2026-07-08T00:33:20+00:00"),
                      "b", 5, db_path=db)   # 2000s
    assert estimate_seconds(5, db_path=db) == 1500.0, estimate_seconds(5, db_path=db)
    # a DIFFERENT size still has no data -> its own speculated default
    assert estimate_seconds(8, db_path=db) == DEFAULT_SECONDS_PER_POINT * 8


def test_default_is_named_and_conservative():
    """The seed velocity is a documented module constant, not a magic literal,
    and over-estimates (fail-safe: schedules fewer stories)."""
    assert isinstance(DEFAULT_SECONDS_PER_POINT, float) and DEFAULT_SECONDS_PER_POINT > 0
    src = Path(velocity.__file__).read_text()
    assert "SPECULATED" in src and "DEFAULT_SECONDS_PER_POINT" in src


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
