"""Phase 4: plane watchdogs. Resonance's daemon died cleanly one day and the whole
learning loop stopped for two weeks with nobody noticing. So the learning plane
carries standing invariant checks over its own state — an empty or stale plane is
a finding, surfaced in the readout, not a silent nothing.
"""
from __future__ import annotations
import sqlite3, time
from pathlib import Path
from . import config


def _count(db, table, where="") -> int:
    try:
        return db.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def health(db_path=None, ledger_dir=None, max_ledger_age_days: float = 7.0) -> dict:
    db = sqlite3.connect(db_path or str(config.VAR / "learning.db"))
    cal = _count(db, "calibration")
    les = _count(db, "lessons", "WHERE retired=0")
    compiled = _count(db, "lessons", "WHERE compiled=1 AND retired=0")
    inc = _count(db, "incidents", "WHERE tombstoned=0")
    db.close()

    ld = Path(ledger_dir or config.LEDGER_DIR)
    newest_age = None
    recent = 0
    if ld.exists():
        files = sorted(ld.glob("*.ndjson"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            newest_age = (time.time() - files[0].stat().st_mtime) / 86400.0
            recent = sum(1 for f in files if (time.time() - f.stat().st_mtime) / 86400.0 < max_ledger_age_days)

    checks = [
        {"name": "calibration_nonempty", "ok": cal > 0, "detail": f"{cal} (model x role x claim) cells"},
        {"name": "lessons_present", "ok": les > 0, "detail": f"{les} active, {compiled} compiled"},
        {"name": "incidents_seeded", "ok": inc > 0, "detail": f"{inc} active incidents"},
        {"name": "ledgers_recent", "ok": recent > 0,
         "detail": (f"{recent} within {max_ledger_age_days:g}d, newest {newest_age:.1f}d ago"
                    if newest_age is not None else "NO run ledgers — plane may be dead")},
    ]
    return {"healthy": all(c["ok"] for c in checks), "checks": checks}
