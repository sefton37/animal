"""M2: the sovereign product store — epics -> stories -> specs -> DoD checks ->
commit links, so a maker's backlog CAN live on this machine in the harness
rather than an external tracker. #451 laid the schema; #452 added CRUD for
epics + stories (Fibonacci-validated story points) and wired a write path onto
the `animal` CLI. #453 (this story) adds attach_spec()/load_spec(), round-
tripping animal/spec.py's Spec + DoDCheck dataclasses through specs/spec_checks
with no lossy conversion (argv stays list[str], never a shell string) -- so a
maker's definition of done lives with the backlog and the work lane can
execute it. Same var/*.db pattern already used in the Phase-4 learning plane
(calibration.py).

Cardinality: 1 story : 1 spec (ACTIVE) : 1 DoD : N checks (spec_checks). Unlike
#451's original design, specs.story_id is NOT a DB-level UNIQUE constraint --
a rejected spec's story must be re-attachable, producing spec HISTORY (a new
specs row), not an overwrite. The "only one ACTIVE spec per story" rule is
therefore enforced at the application layer in attach_spec(), by inspecting
the CURRENT (most recent) specs row's status before inserting a new one.
commit_links carries N commits per story (many commits per issue is fine —
the DoD is what's singular, not the history).
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from . import config
from .spec import Spec

# Cardinality gate (#453): a story's CURRENT spec in any of these states already
# has an ACTIVE definition of done -- attach_spec() must not silently replace it.
# 'rejected' (and 'draft'/'grounded'/'needs_human') are NOT in this set: re-attaching
# over those creates a new specs row (spec history), same as a first attach.
_SPEC_ACTIVE_STATES = {"approved", "building", "verifying", "done"}

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
        # story_id is NOT UNIQUE (see module docstring): #453 needs a story to be
        # re-attachable after a rejected spec, producing spec HISTORY.
        self.db.execute("""CREATE TABLE IF NOT EXISTS specs(
            id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL, title TEXT,
            body TEXT, status TEXT DEFAULT 'draft', created TEXT,
            FOREIGN KEY(story_id) REFERENCES stories(id))""")
        # spec_checks mirrors animal/spec.py's DoDCheck 1:1 so #453 round-trips
        # it with no lossy conversion: argv is a JSON list[str] (never a shell
        # string -- the ambiguity DoDCheck was built to avoid), plus the comparator
        # enum, the stdout needle, the nondeterministic flag, and (added by #453;
        # #451 named only argv/comparator/stdout_needle/nondeterministic as
        # mirrored) the regression flag -- also a real DoDCheck field, needed for
        # exact Spec round-trip equality.
        self.db.execute("""CREATE TABLE IF NOT EXISTS spec_checks(
            id INTEGER PRIMARY KEY, spec_id INTEGER NOT NULL, name TEXT NOT NULL,
            argv TEXT NOT NULL, comparator TEXT NOT NULL DEFAULT 'exit_zero',
            stdout_needle TEXT, nondeterministic INTEGER DEFAULT 0,
            regression INTEGER DEFAULT 0, created TEXT,
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
        self._ensure_column("spec_checks", "regression", "INTEGER DEFAULT 0")
        self._ensure_column("spec_checks", "expected_new", "INTEGER DEFAULT 0")
        # #463: the idempotency key for ledger-projected ingests (a discovery
        # session re-ingested must never duplicate its epic -- the store is a
        # PROJECTION of the ledger, calibration.py's framing)
        self._ensure_column("epics", "source_key", "TEXT")
        self._ensure_specs_story_id_not_unique()
        self._ensure_spec_checks_fk_target()
        self.db.commit()

    def _ensure_column(self, table: str, column: str, coltype: str) -> None:
        cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    def _ensure_specs_story_id_not_unique(self) -> None:
        """A pre-#453 var/product.db has `specs.story_id UNIQUE NOT NULL` (#451's
        original schema), which forbids the spec-history behavior this story
        requires (a rejected spec's story gets a NEW specs row, not an overwrite).
        SQLite can't drop a column-level UNIQUE via ALTER TABLE -- detect the old
        auto-index and rebuild the table without it, preserving existing rows.

        Fix-forward note (red-team, 2nd pass): the FIRST version of this method
        did `ALTER TABLE specs RENAME TO specs_pre453` *before* recreating a
        fresh `specs` table. SQLite's rename-table logic (default since 3.25,
        i.e. `legacy_alter_table=OFF`) rewrites the declared FOREIGN KEY clause
        text of every OTHER table that references the renamed table, so
        spec_checks' FK permanently became `REFERENCES "specs_pre453"(id)` --
        a table this method then DROPs, leaving a dangling reference forever
        (`PRAGMA foreign_key_check` flags it even though enforcement defaults
        off). The fix is ORDER: build the replacement under a throwaway name
        FIRST (nothing references that throwaway name, so the final rename's
        auto-fixup has nothing to touch), copy the data, DROP the OLD `specs`
        table (a plain drop never rewrites other tables' schema text), THEN
        rename the replacement into the `specs` name. spec_checks' FK clause
        is never touched by any of these four statements -- it says
        `REFERENCES specs(id)` before, during, and after, and by the time we're
        done a table actually named `specs` exists again, so it resolves."""
        idx = self.db.execute("PRAGMA index_list(specs)").fetchall()
        has_unique = any(row[1].startswith("sqlite_autoindex_specs") and row[2] for row in idx)
        if not has_unique:
            return
        self.db.execute("""CREATE TABLE specs_new453(
            id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL, title TEXT,
            body TEXT, status TEXT DEFAULT 'draft', created TEXT,
            FOREIGN KEY(story_id) REFERENCES stories(id))""")
        self.db.execute(
            "INSERT INTO specs_new453(id, story_id, title, body, status, created)"
            " SELECT id, story_id, title, body, status, created FROM specs")
        self.db.execute("DROP TABLE specs")
        self.db.execute("ALTER TABLE specs_new453 RENAME TO specs")

    def _ensure_spec_checks_fk_target(self) -> None:
        """Self-heal a DB whose spec_checks.spec_id FK clause was corrupted by
        the OLD (buggy) rename-first version of `_ensure_specs_story_id_not_unique`
        above, run against this same DB before the fix-forward landed. That bug
        left spec_checks' declared FK permanently reading
        `REFERENCES "specs_pre453"(id)` -- a table long since DROPped -- with no
        error ever surfacing because sqlite3's Python driver defaults FK
        enforcement OFF. `PRAGMA foreign_key_list` resolves purely from the
        declared schema text (it does not require the referenced table to
        exist), so this detects the corruption even on a silent connection.
        Rebuilds spec_checks with a corrected FK, preserving every row and
        column value by name (immune to any physical column-order drift from
        earlier `ALTER TABLE ... ADD COLUMN` migrations)."""
        fk_rows = self.db.execute("PRAGMA foreign_key_list(spec_checks)").fetchall()
        bad = any(row[2] != "specs" for row in fk_rows)
        if not bad:
            return
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(spec_checks)").fetchall()]
        col_list = ", ".join(cols)
        self.db.execute("""CREATE TABLE spec_checks_new453(
            id INTEGER PRIMARY KEY, spec_id INTEGER NOT NULL, name TEXT NOT NULL,
            argv TEXT NOT NULL, comparator TEXT NOT NULL DEFAULT 'exit_zero',
            stdout_needle TEXT, nondeterministic INTEGER DEFAULT 0,
            regression INTEGER DEFAULT 0, expected_new INTEGER DEFAULT 0, created TEXT,
            FOREIGN KEY(spec_id) REFERENCES specs(id))""")
        self.db.execute(
            f"INSERT INTO spec_checks_new453({col_list}) SELECT {col_list} FROM spec_checks")
        self.db.execute("DROP TABLE spec_checks")
        self.db.execute("ALTER TABLE spec_checks_new453 RENAME TO spec_checks")

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

    # ------------------------------------------------------------------
    # spec + DoD persistence (#453) -- round-trips animal/spec.py's Spec/
    # DoDCheck dataclasses through specs/spec_checks with no lossy conversion.
    # ------------------------------------------------------------------

    def attach_spec(self, story_id: int, spec: Spec) -> int:
        """Persist `spec` as the story's spec: 1 specs row + 1 spec_checks row per
        DoDCheck (1:1:N). Raises ProductError if the story's CURRENT spec is
        already ACTIVE (state in _SPEC_ACTIVE_STATES) -- attach_spec never
        silently replaces a live definition of done. Re-attaching over a
        'rejected' (or draft/grounded/needs_human) current spec succeeds and
        inserts a NEW specs row: spec history, not an overwrite. Returns the
        new specs row id."""
        current = self._current_spec_row(story_id)
        if current is not None and current["status"] in _SPEC_ACTIVE_STATES:
            raise ProductError("story already has an active spec")
        envelope = spec.to_dict()
        del envelope["dod"]     # dod lives in spec_checks (1:N), not duplicated in body
        cur = self.db.execute(
            "INSERT INTO specs(story_id, title, body, status, created) VALUES (?,?,?,?,?)",
            (story_id, spec.user_story, json.dumps(envelope), spec.state, _now()))
        spec_row_id = cur.lastrowid
        for check in spec.dod:
            self.db.execute(
                "INSERT INTO spec_checks(spec_id, name, argv, comparator, stdout_needle,"
                " nondeterministic, regression, expected_new, created) VALUES (?,?,?,?,?,?,?,?,?)",
                (spec_row_id, check.name, json.dumps(check.argv), check.comparator,
                 check.expected, int(check.nondeterministic), int(check.regression),
                 int(check.expected_new), _now()))
        self.db.commit()
        return spec_row_id

    def load_spec(self, story_id: int) -> Spec | None:
        """Load the story's CURRENT spec (most recently attached) back as a real
        Spec, with its dod list rebuilt from spec_checks in attach order. None
        if the story has no spec. Built entirely on Spec.from_dict()."""
        row = self._current_spec_row(story_id)
        if row is None:
            return None
        envelope = json.loads(row["body"])
        checks = self.db.execute(
            "SELECT name, argv, comparator, stdout_needle, nondeterministic, regression,"
            " expected_new FROM spec_checks WHERE spec_id=? ORDER BY id ASC", (row["id"],)).fetchall()
        envelope["dod"] = [
            {"name": c[0], "argv": json.loads(c[1]), "comparator": c[2],
             "expected": c[3] or "", "nondeterministic": bool(c[4]), "regression": bool(c[5]),
             "expected_new": bool(c[6])}
            for c in checks]
        return Spec.from_dict(envelope)

    def set_spec_status(self, story_id: int, status: str) -> None:
        """Transition the story's CURRENT spec to a new lifecycle status. Without
        this, attach_spec()'s one-active-spec gate is a ONE-WAY TRAP: a spec that
        reached an ACTIVE state (approved/building/verifying/done) could never be
        superseded, so a corrected spec after an auditor rejection was blocked
        forever (#453 red-team). Move the current spec aside (e.g. -> 'rejected')
        and the story is free to accept a re-authored spec as a new history row."""
        row = self._current_spec_row(story_id)
        if row is None:
            raise ProductError(f"story {story_id} has no spec to transition")
        self.db.execute("UPDATE specs SET status=? WHERE id=?", (status, row["id"]))
        self.db.commit()

    def _current_spec_row(self, story_id: int) -> dict | None:
        row = self.db.execute(
            "SELECT id, story_id, title, body, status, created FROM specs"
            " WHERE story_id=? ORDER BY id DESC LIMIT 1", (story_id,)).fetchone()
        if row is None:
            return None
        return {"id": row[0], "story_id": row[1], "title": row[2], "body": row[3],
                "status": row[4], "created": row[5]}
