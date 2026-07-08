"""M2: the sovereign product store — epics -> stories -> specs -> DoD checks ->
commit links, so a maker's backlog CAN live on this machine in the harness
rather than an external tracker. #451 laid the schema; #452 (this story) adds
CRUD for epics + stories (with Fibonacci-validated story points) and wires a
write path onto the `animal` CLI, so the schema #451's own red-team flagged as
"defined but no callers" is now reachable. #453 (spec/DoD persistence) is next.
Same var/*.db pattern already used in the Phase-4 learning plane (calibration.py).

Cardinality: 1 story : 1 spec : 1 DoD : N checks (spec_checks), enforced here
by specs.story_id UNIQUE. commit_links carries N commits per story (many
commits per issue is fine — the DoD is what's singular, not the history).
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from . import config

# Scrum-standard Fibonacci-ish sequence; a story's points must land on one of
# these or the estimate is meaningless noise (the whole point of the scale).
FIBONACCI_POINTS = {1, 2, 3, 5, 8, 13, 21}


class ProductError(ValueError):
    """Raised when a product-store write violates a domain rule -- e.g. a
    story_points value outside the Fibonacci set."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductStore:
    def __init__(self, db_path=None):
        path = db_path or str(config.VAR / "product.db")
        # A fresh clone/CI checkout has no var/ yet (it's gitignored, never
        # committed) -- create the parent dir before connecting so the default
        # constructor doesn't crash with sqlite3.OperationalError('unable to
        # open database file'). Same pattern as ledger.py/bastion.py/workspace.py.
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS epics(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT DEFAULT 'backlog',
            priority INTEGER DEFAULT 0, created TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS stories(
            id INTEGER PRIMARY KEY, epic_id INTEGER, title TEXT NOT NULL,
            user_story TEXT, story_points INTEGER, priority INTEGER DEFAULT 0,
            status TEXT DEFAULT 'backlog', created TEXT,
            FOREIGN KEY(epic_id) REFERENCES epics(id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS specs(
            id INTEGER PRIMARY KEY, story_id INTEGER UNIQUE NOT NULL, title TEXT,
            body TEXT, status TEXT DEFAULT 'draft', created TEXT,
            FOREIGN KEY(story_id) REFERENCES stories(id))""")
        # spec_checks mirrors animal/spec.py's DoDCheck 1:1 so #453 can round-trip
        # it with NO schema migration: argv is a JSON list[str] (never a shell
        # string -- the ambiguity DoDCheck was built to avoid), plus the comparator
        # enum and the stdout needle / nondeterministic flag it carries.
        self.db.execute("""CREATE TABLE IF NOT EXISTS spec_checks(
            id INTEGER PRIMARY KEY, spec_id INTEGER NOT NULL, name TEXT NOT NULL,
            argv TEXT NOT NULL, comparator TEXT NOT NULL DEFAULT 'exit_zero',
            stdout_needle TEXT, nondeterministic INTEGER DEFAULT 0, created TEXT,
            FOREIGN KEY(spec_id) REFERENCES specs(id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS commit_links(
            id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL, sha TEXT NOT NULL,
            message TEXT, created TEXT,
            FOREIGN KEY(story_id) REFERENCES stories(id))""")
        # A pre-#452 var/product.db already has epics/stories WITHOUT the new
        # columns below (CREATE TABLE IF NOT EXISTS is a no-op on an existing
        # table) -- migrate it in place so an existing local backlog isn't
        # silently stuck on the old schema.
        self._ensure_column("epics", "priority", "INTEGER DEFAULT 0")
        self._ensure_column("stories", "user_story", "TEXT")
        self._ensure_column("stories", "story_points", "INTEGER")
        self._ensure_column("stories", "priority", "INTEGER DEFAULT 0")
        self.db.commit()

    def _ensure_column(self, table: str, column: str, coltype: str) -> None:
        cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    def close(self):
        self.db.close()

    # ------------------------------------------------------------------
    # epics
    # ------------------------------------------------------------------

    def create_epic(self, title: str, priority: int = 0, status: str = "backlog") -> int:
        cur = self.db.execute(
            "INSERT INTO epics(name, status, priority, created) VALUES (?,?,?,?)",
            (title, status, priority, _now()))
        self.db.commit()
        return cur.lastrowid

    def get_epic(self, epic_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT id, name, status, priority, created FROM epics WHERE id=?", (epic_id,)).fetchone()
        return self._epic_row(row) if row else None

    def update_epic(self, epic_id: int, **fields) -> None:
        if "title" in fields:                    # alias -> the `name` column
            fields["name"] = fields.pop("title")
        allowed = {"name", "status", "priority"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        clause = ", ".join(f"{k}=?" for k in sets)
        self.db.execute(f"UPDATE epics SET {clause} WHERE id=?", (*sets.values(), epic_id))
        self.db.commit()

    def list_epics(self, status: str | None = None) -> list[dict]:
        query = "SELECT id, name, status, priority, created FROM epics"
        params: list = []
        if status is not None:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY priority ASC, created ASC"
        rows = self.db.execute(query, params).fetchall()
        return [self._epic_row(r) for r in rows]

    @staticmethod
    def _epic_row(row) -> dict:
        return {"id": row[0], "title": row[1], "status": row[2], "priority": row[3], "created": row[4]}

    # ------------------------------------------------------------------
    # stories
    # ------------------------------------------------------------------

    def create_story(self, epic_id: int, title: str, user_story: str | None = None,
                      story_points: int | None = None, priority: int = 0,
                      status: str = "backlog") -> int:
        self._validate_points(story_points)
        cur = self.db.execute(
            "INSERT INTO stories(epic_id, title, user_story, story_points, priority, status, created)"
            " VALUES (?,?,?,?,?,?,?)",
            (epic_id, title, user_story, story_points, priority, status, _now()))
        self.db.commit()
        return cur.lastrowid

    def get_story(self, story_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT id, epic_id, title, user_story, story_points, priority, status, created"
            " FROM stories WHERE id=?", (story_id,)).fetchone()
        return self._story_row(row) if row else None

    def update_story(self, story_id: int, **fields) -> None:
        if "story_points" in fields:
            self._validate_points(fields["story_points"])
        allowed = {"epic_id", "title", "user_story", "story_points", "priority", "status"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        clause = ", ".join(f"{k}=?" for k in sets)
        self.db.execute(f"UPDATE stories SET {clause} WHERE id=?", (*sets.values(), story_id))
        self.db.commit()

    def list_backlog(self, epic_id: int | None = None, status: str | None = None) -> list[dict]:
        query = ("SELECT id, epic_id, title, user_story, story_points, priority, status, created"
                 " FROM stories")
        clauses, params = [], []
        if epic_id is not None:
            clauses.append("epic_id=?"); params.append(epic_id)
        if status is not None:
            clauses.append("status=?"); params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY priority ASC, created ASC"
        rows = self.db.execute(query, params).fetchall()
        return [self._story_row(r) for r in rows]

    @staticmethod
    def _validate_points(story_points) -> None:
        if story_points is not None and story_points not in FIBONACCI_POINTS:
            raise ProductError(
                f"story_points={story_points!r} is not in the Fibonacci set {sorted(FIBONACCI_POINTS)}")

    @staticmethod
    def _story_row(row) -> dict:
        return {"id": row[0], "epic_id": row[1], "title": row[2], "user_story": row[3],
                "story_points": row[4], "priority": row[5], "status": row[6], "created": row[7]}
