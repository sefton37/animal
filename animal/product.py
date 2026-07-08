"""M2: the sovereign product store — the SCHEMA for animal's own local backlog
(epics -> stories -> specs -> DoD checks -> commit links), so a maker's backlog
CAN live on this machine in the harness rather than an external tracker. #451 lays
the schema (this file); #452 (CRUD) and #453 (spec/DoD persistence) populate and
WIRE it — until they land the store is DEFINED, not yet the maker's live backlog.
Same var/*.db pattern already used in the Phase-4 learning plane (calibration.py).

Cardinality: 1 story : 1 spec : 1 DoD : N checks (spec_checks), enforced here
by specs.story_id UNIQUE. commit_links carries N commits per story (many
commits per issue is fine — the DoD is what's singular, not the history).

Story #451 lays only the schema (this file). CRUD (#452) and spec/DoD
persistence (#453) build on it — deliberately no read/write methods beyond
the tables themselves yet.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import config


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
            created TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS stories(
            id INTEGER PRIMARY KEY, epic_id INTEGER, title TEXT NOT NULL,
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
        self.db.commit()

    def close(self):
        self.db.close()
