"""Story #472 -- the velocity tracker (M6).

How long a Fibonacci size ACTUALLY takes, measured from the harness's own
ledger timestamps -- never a model's claim, never a wall-clock the caller
read (this project's 2026-04-20 flaky-timing incident was exactly an
uninjected clock). record_completion computes elapsed seconds strictly from a
run ledger's session_start -> session_end `ts` gap (the same harness-stamped
`ts` ledger.py writes), so a completion's duration is a REPLAYABLE fact.

estimate_seconds(points) converts a size into a time budget for the scheduler
(#473): the historical mean of recorded completions at that size once any
exist, and a NAMED, SPECULATED default before real data does -- honestly
flagged, never a confident guess. Lives in var/learning.db beside the other
measurement-plane tables (the one-sqlite-file convention).
"""
from __future__ import annotations
import sqlite3
from datetime import datetime
from pathlib import Path
from . import config

# SPECULATED / placeholder -- the seed velocity the scheduler uses before a
# single real completion exists at a given size. Deliberately conservative
# (over-estimating time is fail-safe: it schedules FEWER stories, so the
# sprint never starts work it can't finish). Replaced by the historical mean
# the instant one completion is recorded. Not measured -- a starting guess,
# marked as one, per the design's "seeded with a conservative default
# velocity on the very first loop, before any is measured".
DEFAULT_SECONDS_PER_POINT = 900.0    # 15 min/point, SPECULATED until data exists


def _connect(db_path=None) -> sqlite3.Connection:
    path = db_path or str(config.VAR / "learning.db")
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS velocity(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, spec_id TEXT NOT NULL,
        points INTEGER NOT NULL, seconds REAL NOT NULL, session_id TEXT)""")
    db.commit()
    return db


def _session_span_seconds(ledger) -> tuple[float, str]:
    """Elapsed seconds between a run ledger's OWN session_start and
    session_end `ts` fields (harness-stamped, never re-measured here).
    Returns (seconds, session_id). Raises ValueError if the ledger lacks a
    paired start/end -- an unmeasurable run is a loud failure, not a zero."""
    evs = ledger.replay()
    start = next((e for e in evs if e.type == "session_start"), None)
    end = next((e for e in reversed(evs) if e.type == "session_end"), None)
    if start is None or end is None:
        raise ValueError("ledger has no paired session_start/session_end -- cannot measure duration")
    t0 = datetime.fromisoformat(start.ts)
    t1 = datetime.fromisoformat(end.ts)
    seconds = (t1 - t0).total_seconds()
    # A negative span (end before start -- clock skew, a corrupted ts) is a
    # physically-impossible duration; storing it would push the scheduler
    # toward OVERCOMMIT (a negative estimate makes anything "fit"). Refuse it
    # exactly like an unmeasurable run -- fail loud, never a poisoned fact.
    if seconds < 0:
        raise ValueError(f"ledger span is negative ({seconds}s: end {end.ts} before start {start.ts})")
    return seconds, start.session_id


def record_completion(ledger, spec_id, points: int, db_path=None) -> float:
    """Record how long the run in `ledger` actually took, computed from that
    ledger's own session_start/session_end ts gap. Returns the elapsed
    seconds. The duration is the harness's, not the caller's -- velocity.py
    never calls time.time() itself."""
    seconds, session_id = _session_span_seconds(ledger)
    db = _connect(db_path)
    try:
        db.execute(
            "INSERT INTO velocity(ts, spec_id, points, seconds, session_id) VALUES (?,?,?,?,?)",
            (_now_from_ledger(ledger), str(spec_id), int(points), float(seconds), session_id))
        db.commit()
    finally:
        db.close()
    return seconds


def _now_from_ledger(ledger) -> str:
    """The completion's timestamp is the run's OWN session_end ts (harness-
    stamped) -- not a fresh clock read, so a recorded row carries no
    caller-measured time at all."""
    end = next((e for e in reversed(ledger.replay()) if e.type == "session_end"), None)
    return end.ts if end else next(e.ts for e in ledger.replay())


def estimate_seconds(points: int, db_path=None) -> float:
    """Estimated seconds for a story of this size: the historical MEAN of
    recorded completions at this exact points value once any exist, else the
    SPECULATED DEFAULT_SECONDS_PER_POINT * points. The estimate gets more
    honest with every completion (#472's user story)."""
    db = _connect(db_path)
    try:
        row = db.execute("SELECT AVG(seconds), COUNT(*) FROM velocity WHERE points=?",
                         (int(points),)).fetchone()
    finally:
        db.close()
    avg, n = row
    if n and avg is not None:
        return float(avg)
    return DEFAULT_SECONDS_PER_POINT * float(points)


def recent(limit: int = 20, db_path=None) -> list[dict]:
    """Read-only inspection: the most recent completions, newest first."""
    db = _connect(db_path)
    try:
        rows = db.execute(
            "SELECT ts, spec_id, points, seconds, session_id FROM velocity"
            " ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    finally:
        db.close()
    return [{"ts": r[0], "spec_id": r[1], "points": r[2], "seconds": r[3], "session_id": r[4]}
            for r in rows]
