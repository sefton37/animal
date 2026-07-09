"""Story #469 -- persist panel estimates for future estimate-vs-actual matching.

Every sizing run is recorded DURABLY: one row per SEAT per run (the per-seat
vote is the record M7's estimate-vs-actual story (#480) will score each
model's estimation track record from), grouped by a run id and carrying the
converged aggregate alongside. Lives in learning.db beside the other
measurement-plane tables (the one-sqlite-file convention): an estimate is a
MEASUREMENT-IN-WAITING, not backlog state -- the converged story_points
themselves land on the story row in the product store (#471), never here.

Deliberately NOT here (the AC pins this to keep the scope honest): no write
into any verified-track-record table -- no verified outcome exists at
estimation time. Recording, not verifying; #480 closes the loop later.
"""
from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from . import config


def _connect(db_path=None) -> sqlite3.Connection:
    path = db_path or str(config.VAR / "learning.db")
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS story_estimates(
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts TEXT NOT NULL,
        story_id TEXT NOT NULL, seat TEXT NOT NULL, model TEXT,
        points INTEGER, aggregate_points INTEGER, disagreement INTEGER,
        escalated INTEGER DEFAULT 0)""")
    db.commit()
    return db


def record_panel_run(story_id, per_seat_votes: dict, aggregate_points, disagreement,
                     escalated: bool, db_path=None) -> str:
    """Record one panel run: a row per seat (vote may be None -- an abstain is
    a real observation), each carrying the run's converged aggregate.

    THE CONTRACT (audit-pinned): aggregate_points is the FINAL converged size
    -- converge()['points'], i.e. the HUMAN's pick when escalated=True, the
    harness median otherwise. The panel's own median stays recomputable from
    the stored per-seat votes, so 'the panel said 3, the human said 13' is
    always reconstructible.

    Model identity travels WITH the vote: per_seat values in run_panel's
    {points, reasoning, model} shape carry their own model name (a roster
    lookup at record time could misattribute a renamed/custom seat); bare
    points fall back to the poker roster, and an UNKNOWN seat records model
    NULL -- loud in the data, never a silent identity guess. Join keys: the
    `seat` column matches the measurement plane's panel-verdict keying; the
    `model` column matches ROLES/ledger keying. Returns the run id."""
    from .poker import ESTIMATOR_SEATS
    seat_models = {s["name"]: s["model"] for s in ESTIMATOR_SEATS}
    run_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).isoformat()
    db = _connect(db_path)
    try:
        for seat, vote in per_seat_votes.items():
            if isinstance(vote, dict):
                points = vote.get("points")
                model = vote.get("model") or seat_models.get(seat)
            else:
                points = vote
                model = seat_models.get(seat)
            db.execute(
                "INSERT INTO story_estimates(run_id, ts, story_id, seat, model, points,"
                " aggregate_points, disagreement, escalated) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, ts, str(story_id), str(seat), model,
                 points, aggregate_points, disagreement, int(bool(escalated))))
        db.commit()
    finally:
        db.close()
    return run_id


def query_by_story(story_id, db_path=None) -> list[dict]:
    """Every recorded estimate row for a story, newest run last, seat order
    preserved within a run."""
    db = _connect(db_path)
    try:
        rows = db.execute(
            "SELECT run_id, ts, seat, model, points, aggregate_points, disagreement, escalated"
            " FROM story_estimates WHERE story_id=? ORDER BY id", (str(story_id),)).fetchall()
    finally:
        db.close()
    return [{"run_id": r[0], "ts": r[1], "seat": r[2], "model": r[3], "points": r[4],
             "aggregate_points": r[5], "disagreement": r[6], "escalated": bool(r[7])}
            for r in rows]
