"""Phase 4: the typed incident ledger — successor to Resonance's moment schema,
made forensic (class / claim / reality / detection / root_cause / countermeasure)
and de-duplicated by SUPERSESSION: a corrected record tombstones the old one at
write time. That closes the exact Resonance failure where a correction lived in a
new record while the stale assertion persisted unmarked.

Seeded from the existing hallucinations.md corpus — the most valuable file on the
machine becomes queryable, typed context instead of 45 KB of prose to re-read.
"""
from __future__ import annotations
import sqlite3, re
from datetime import datetime, timezone
from pathlib import Path
from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Incidents:
    def __init__(self, db_path=None):
        self.db = sqlite3.connect(db_path or str(config.VAR / "learning.db"))
        self.db.execute("""CREATE TABLE IF NOT EXISTS incidents(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, date TEXT, klass TEXT,
            claim TEXT, reality TEXT, detection TEXT, root_cause TEXT, countermeasure TEXT,
            supersedes INTEGER, tombstoned INTEGER DEFAULT 0)""")
        self.db.commit()

    def add(self, klass: str, claim: str, reality: str = "", detection: str = "",
            root_cause: str = "", countermeasure: str = "", date: str = "", supersedes: int | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO incidents(ts,date,klass,claim,reality,detection,root_cause,countermeasure,supersedes)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (_now(), date, klass, claim, reality, detection, root_cause, countermeasure, supersedes))
        if supersedes is not None:          # tombstone the corrected record at write time
            self.db.execute("UPDATE incidents SET tombstoned=1 WHERE id=?", (supersedes,))
        self.db.commit()
        return cur.lastrowid

    def active(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT id,date,klass,claim,reality,countermeasure FROM incidents WHERE tombstoned=0 ORDER BY id").fetchall()
        return [{"id": r[0], "date": r[1], "class": r[2], "claim": r[3], "reality": r[4],
                 "countermeasure": r[5]} for r in rows]

    def ingest_hallucinations(self, path=None) -> int:
        """Best-effort seed: split the corpus on dated headers, store each block as
        an incident record (class='seed'). A typed container for the prose, not a
        perfect parse — later incidents are written structured at session-end."""
        p = Path(path or (Path.home() / ".claude/projects/-home-kellogg/memory/hallucinations.md"))
        if not p.exists():
            return 0
        text = p.read_text(errors="replace")
        # split on lines beginning with a date (2026-..) or a '## <date>' header
        blocks = re.split(r"\n(?=#{0,3}\s*20\d\d-\d\d-\d\d)", text)
        n = 0
        for b in blocks:
            b = b.strip()
            if len(b) < 40:
                continue
            m = re.search(r"(20\d\d-\d\d-\d\d)", b)
            date = m.group(1) if m else ""
            first = b.splitlines()[0][:200]
            self.add("seed", claim=first, reality=b[:1200], date=date)
            n += 1
        return n

    def close(self):
        self.db.close()
