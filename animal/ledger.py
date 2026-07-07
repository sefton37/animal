"""The ledger: an append-only NDJSON log per session (the source of truth) plus a
SQLite index (a rebuildable projection for queries). Everything the kernel does
lands here; nothing else is authoritative. Replay reads the NDJSON, not the DB.

The harness stamps `ts` and `seq` here — never a model. (Resonance's newest
"moment" was model-dated three years into the past; provenance is harness-owned.)
"""
from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from .types import Event, EventType, SCHEMA_VERSION
from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, session_id: str | None = None, ledger_dir=None):
        self.dir = Path(ledger_dir or config.LEDGER_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.path = self.dir / f"{self.session_id}.ndjson"
        self.db = sqlite3.connect(str(self.dir / "index.db"))
        self._init_db()
        self._seq = self._max_seq()

    def _init_db(self):
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events(
                 id TEXT PRIMARY KEY, session_id TEXT, seq INTEGER, type TEXT,
                 schema_version INTEGER, ts TEXT, payload TEXT)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_sess ON events(session_id, seq)")
        self.db.commit()

    def _max_seq(self) -> int:
        row = self.db.execute(
            "SELECT MAX(seq) FROM events WHERE session_id=?", (self.session_id,)).fetchone()
        return row[0] if row and row[0] is not None else -1

    def append(self, etype, payload: dict | None = None) -> Event:
        """Append one event. Returns the stamped Event. Append-only: never rewrites."""
        self._seq += 1
        ev = Event(
            session_id=self.session_id, seq=self._seq,
            type=(etype.value if isinstance(etype, EventType) else str(etype)),
            payload=payload or {}, ts=_now())
        with open(self.path, "a") as f:
            f.write(json.dumps(ev.to_dict()) + "\n")
        self.db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
            (ev.id, ev.session_id, ev.seq, ev.type, ev.schema_version, ev.ts, json.dumps(ev.payload)))
        self.db.commit()
        return ev

    def replay(self, session_id: str | None = None) -> list[Event]:
        """Reconstruct a session from the NDJSON truth (not the SQLite projection)."""
        sid = session_id or self.session_id
        p = self.dir / f"{sid}.ndjson"
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            if line.strip():
                out.append(Event.from_dict(json.loads(line)))
        return out

    def events_of(self, etype, session_id: str | None = None) -> list[Event]:
        t = etype.value if isinstance(etype, EventType) else str(etype)
        return [e for e in self.replay(session_id) if e.type == t]

    def close(self):
        self.db.close()
