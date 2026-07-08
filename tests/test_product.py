"""Story #451/#452/#453 tests: the sovereign product-store schema (epics ->
stories -> specs -> spec_checks -> commit_links), epic/story CRUD, and
attach_spec()/load_spec() round-tripping animal/spec.py's Spec/DoDCheck
dataclasses 1:1:N. Deterministic, offline. Run:
`python3 tests/test_product.py` or under pytest.
"""
import sys, os, tempfile, sqlite3, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from animal.product import ProductStore, ProductError, FIBONACCI_POINTS
from animal.spec import Spec, DoDCheck, Comparator, SpecState

EXPECTED_TABLES = {"epics", "stories", "specs", "spec_checks", "commit_links"}
REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def _user_tables(db: sqlite3.Connection) -> set:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    return {r[0] for r in rows}


def test_schema_tables_exist():
    store = ProductStore(db_path=":memory:")
    assert _user_tables(store.db) == EXPECTED_TABLES
    store.close()


def test_schema_idempotent():
    path = os.path.join(tempfile.mkdtemp(prefix="animal-product-"), "product.db")
    s1 = ProductStore(db_path=path)
    s1.close()
    s2 = ProductStore(db_path=path)   # re-instantiate against the SAME file — must raise nothing
    tables = _user_tables(s2.db)
    assert tables == EXPECTED_TABLES and len(tables) == 5
    s2.close()


def test_default_constructor_creates_var_dir_if_missing():
    """Regression (red-team Audit 1.5): ProductStore() called with the DEFAULT
    db_path must not crash with sqlite3.OperationalError('unable to open database
    file') when var/ does not exist yet -- e.g. a fresh clone/CI checkout, before
    any other module has created it. var/ is gitignored, so it is NEVER present
    on a clean checkout. This spawns a real subprocess pointed at a fresh
    ANIMAL_HOME (no var/ subdir) and calls the bare default constructor -- the
    exact path a pre-created tempdir or ':memory:' test can't exercise."""
    fresh_home = tempfile.mkdtemp(prefix="animal-fresh-home-")
    assert not (Path(fresh_home) / "var").exists()
    env = dict(os.environ, ANIMAL_HOME=fresh_home, PYTHONPATH=REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c",
         "from animal.product import ProductStore; s = ProductStore(); s.close(); print('OK')"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
    assert (Path(fresh_home) / "var" / "product.db").exists()


def test_spec_checks_schema_mirrors_dodcheck():
    # #451 red-team: spec_checks must round-trip animal/spec.py's DoDCheck 1:1
    # (argv is a list[str], never a shell string), so #453 needs NO schema
    # migration. Assert argv/comparator columns, not a lossy single `command` TEXT.
    store = ProductStore(db_path=":memory:")
    cols = {r[1] for r in store.db.execute("PRAGMA table_info(spec_checks)").fetchall()}
    assert {"argv", "comparator"} <= cols
    assert "command" not in cols     # the lossy shell-string column is gone
    store.close()


def test_default_status_is_backlog():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("an epic")
    sid = store.create_story(eid, "a story")
    assert store.get_epic(eid)["status"] == "backlog"
    assert store.get_story(sid)["status"] == "backlog"
    store.close()


def test_epic_crud():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("harness epic", priority=2)
    got = store.get_epic(eid)
    assert got == {"id": eid, "title": "harness epic", "status": "backlog",
                    "priority": 2, "created": got["created"]}
    store.update_epic(eid, status="active", priority=9)
    updated = store.get_epic(eid)
    assert updated["status"] == "active" and updated["priority"] == 9
    assert store.get_epic(eid + 999) is None
    assert [e["id"] for e in store.list_epics()] == [eid]
    assert store.list_epics(status="active") == [updated]
    assert store.list_epics(status="backlog") == []
    store.close()


def test_story_crud():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    sid = store.create_story(eid, "a story", user_story="As a maker...", story_points=5, priority=1)
    got = store.get_story(sid)
    assert got["title"] == "a story" and got["user_story"] == "As a maker..."
    assert got["story_points"] == 5 and got["priority"] == 1 and got["epic_id"] == eid
    store.update_story(sid, status="in_progress", story_points=8)
    updated = store.get_story(sid)
    assert updated["status"] == "in_progress" and updated["story_points"] == 8
    assert store.get_story(sid + 999) is None
    store.close()


def test_story_points_fibonacci_only():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    try:
        store.create_story(eid, "bad story", story_points=4)
        assert False, "expected ProductError for story_points=4 (not Fibonacci)"
    except ProductError:
        pass
    sid = store.create_story(eid, "good story", story_points=8)
    assert store.get_story(sid)["story_points"] == 8
    assert 4 not in FIBONACCI_POINTS and 8 in FIBONACCI_POINTS
    # update_story enforces the same rule on an existing row
    try:
        store.update_story(sid, story_points=6)
        assert False, "expected ProductError for story_points=6 (not Fibonacci)"
    except ProductError:
        pass
    store.close()


def test_list_backlog_ordering():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    ids = {}
    for priority in (2, 0, 1):        # insertion order deliberately scrambled
        sid = store.create_story(eid, f"story-p{priority}", priority=priority)
        ids[priority] = sid
    backlog = store.list_backlog(epic_id=eid)
    assert [s["priority"] for s in backlog] == [0, 1, 2]
    assert [s["id"] for s in backlog] == [ids[0], ids[1], ids[2]]
    # status filter narrows the result set
    store.update_story(ids[1], status="done")
    assert [s["priority"] for s in store.list_backlog(epic_id=eid, status="backlog")] == [0, 2]
    store.close()


def test_cli_backlog_write_reachability():
    """#452 requires write reachability from a user-facing CLI path (the
    schema #451's own red-team flagged as 'defined but no callers'). Spawns a
    real subprocess against a fresh ANIMAL_HOME, exactly like the sibling
    default-constructor test above."""
    fresh_home = tempfile.mkdtemp(prefix="animal-cli-backlog-")
    env = dict(os.environ, ANIMAL_HOME=fresh_home, PYTHONPATH=REPO_ROOT)

    def run(*args):
        return subprocess.run([sys.executable, "-m", "animal.cli", "backlog", *args],
                               cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15)

    r1 = run("add-epic", "CLI epic", "--priority", "3")
    assert r1.returncode == 0, f"stdout={r1.stdout!r} stderr={r1.stderr!r}"
    assert "epic #1 created" in r1.stdout

    r2 = run("add-story", "1", "CLI story", "--points", "5")
    assert r2.returncode == 0, f"stdout={r2.stdout!r} stderr={r2.stderr!r}"
    assert "story #1 created" in r2.stdout

    r3 = run("add-story", "1", "bad story", "--points", "4")
    assert r3.returncode == 1, f"stdout={r3.stdout!r} stderr={r3.stderr!r}"
    assert "not in the Fibonacci set" in r3.stderr

    r4 = run("list", "--epic-id", "1")
    assert r4.returncode == 0
    assert "CLI story" in r4.stdout and "pts=5" in r4.stdout

    # #452 red-team: epics must be listable from the CLI too (list_epics existed
    # but had no caller), else a created epic is invisible once its line scrolls off
    r5 = run("list-epics")
    assert r5.returncode == 0
    assert "CLI epic" in r5.stdout and "epic #1" in r5.stdout


# ------------------------------------------------------------------
# #453: attach_spec()/load_spec() -- Spec/DoDCheck persistence, 1:1:N
# ------------------------------------------------------------------

def _two_check_spec(state=SpecState.DRAFT.value) -> Spec:
    checks = [
        DoDCheck(name="check-one", argv=["python3", "-c", "print(1)"],
                 comparator=Comparator.EXIT_ZERO.value),
        DoDCheck(name="check-two", argv=["grep", "-n", "needle", "file.txt"],
                 comparator=Comparator.STDOUT_CONTAINS.value, expected="needle",
                 nondeterministic=True, regression=True, expected_new=True),
    ]
    return Spec(user_story="As a maker, I want...", intent=["decompose", "ground"],
                out_of_scope=["unrelated thing"], dod=checks,
                groundings=[{"file": "animal/product.py", "symbol": "attach_spec"}],
                state=state)


def test_attach_spec_persists_dod_1_to_n():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    sid = store.create_story(eid, "a story")
    spec = _two_check_spec()
    spec_row_id = store.attach_spec(sid, spec)
    n_specs = store.db.execute("SELECT COUNT(*) FROM specs WHERE story_id=?", (sid,)).fetchone()[0]
    assert n_specs == 1
    n_checks = store.db.execute(
        "SELECT COUNT(*) FROM spec_checks WHERE spec_id=?", (spec_row_id,)).fetchone()[0]
    assert n_checks == 2
    store.close()


def test_spec_roundtrip_equality():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    sid = store.create_story(eid, "a story")
    spec = _two_check_spec(state=SpecState.GROUNDED.value)
    store.attach_spec(sid, spec)
    loaded = store.load_spec(sid)
    assert loaded is not None
    assert loaded.to_dict() == spec.to_dict()
    # argv MUST stay a real list[str], never collapsed into a shell string
    assert loaded.dod[1].argv == ["grep", "-n", "needle", "file.txt"]
    assert isinstance(loaded.dod[1].argv, list)
    assert loaded.dod[1].nondeterministic is True and loaded.dod[1].regression is True
    # #458 red-team fix: EVERY DoDCheck field must round-trip -- expected_new
    # was silently dropped by the mirror (stored spec reloaded to a spec that
    # re-rejected at Gate 0a grounding), the same gap class #453 fixed for
    # `regression`
    assert loaded.dod[1].expected_new is True
    store.close()


def test_spec_load_missing_story_returns_none():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    sid = store.create_story(eid, "a story")
    assert store.load_spec(sid) is None       # no spec attached yet
    store.close()


def test_one_active_spec_per_story():
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")

    # branch 1: an ACTIVE current spec (approved) blocks re-attach_spec
    sid1 = store.create_story(eid, "story one")
    store.attach_spec(sid1, _two_check_spec(state=SpecState.APPROVED.value))
    try:
        store.attach_spec(sid1, _two_check_spec(state=SpecState.DRAFT.value))
        assert False, "expected ProductError: story already has an active spec"
    except ProductError as e:
        assert "already has an active spec" in str(e)
    assert store.db.execute(
        "SELECT COUNT(*) FROM specs WHERE story_id=?", (sid1,)).fetchone()[0] == 1

    # branch 2: a REJECTED current spec succeeds and creates a NEW specs row
    # (spec history, not an overwrite)
    sid2 = store.create_story(eid, "story two")
    first_id = store.attach_spec(sid2, _two_check_spec(state=SpecState.REJECTED.value))
    second_spec = _two_check_spec(state=SpecState.DRAFT.value)
    second_id = store.attach_spec(sid2, second_spec)
    assert second_id != first_id
    assert store.db.execute(
        "SELECT COUNT(*) FROM specs WHERE story_id=?", (sid2,)).fetchone()[0] == 2
    # load_spec returns the CURRENT (most recently attached) spec, not the rejected one
    assert store.load_spec(sid2).to_dict() == second_spec.to_dict()
    store.close()


# ------------------------------------------------------------------
# #453 red-team fix: the specs-migration must not corrupt spec_checks' FK
# ------------------------------------------------------------------

def _pre453_db_path() -> str:
    """Build a DB shaped exactly like #451's ORIGINAL schema (specs.story_id
    UNIQUE NOT NULL, no priority/user_story/story_points/regression columns),
    with one row all the way down epics->stories->specs->spec_checks, so the
    migration path has real data to preserve."""
    path = os.path.join(tempfile.mkdtemp(prefix="animal-product-pre453-"), "product.db")
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE epics(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT DEFAULT 'backlog',
        created TEXT)""")
    con.execute("""CREATE TABLE stories(
        id INTEGER PRIMARY KEY, epic_id INTEGER, title TEXT NOT NULL,
        status TEXT DEFAULT 'backlog', created TEXT,
        FOREIGN KEY(epic_id) REFERENCES epics(id))""")
    con.execute("""CREATE TABLE specs(
        id INTEGER PRIMARY KEY, story_id INTEGER UNIQUE NOT NULL, title TEXT,
        body TEXT, status TEXT DEFAULT 'draft', created TEXT,
        FOREIGN KEY(story_id) REFERENCES stories(id))""")
    con.execute("""CREATE TABLE spec_checks(
        id INTEGER PRIMARY KEY, spec_id INTEGER NOT NULL, name TEXT NOT NULL,
        argv TEXT NOT NULL, comparator TEXT NOT NULL DEFAULT 'exit_zero',
        stdout_needle TEXT, nondeterministic INTEGER DEFAULT 0, created TEXT,
        FOREIGN KEY(spec_id) REFERENCES specs(id))""")
    con.execute("""CREATE TABLE commit_links(
        id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL, sha TEXT NOT NULL,
        message TEXT, created TEXT,
        FOREIGN KEY(story_id) REFERENCES stories(id))""")
    con.execute("INSERT INTO epics(id, name, status, created) VALUES (1,'epic','backlog','t')")
    con.execute("INSERT INTO stories(id, epic_id, title, status, created) VALUES (1,1,'story','backlog','t')")
    con.execute("INSERT INTO specs(id, story_id, title, body, status, created)"
                " VALUES (1,1,'title','{}','draft','t')")
    con.execute("INSERT INTO spec_checks(id, spec_id, name, argv, comparator, stdout_needle,"
                " nondeterministic, created) VALUES (1,1,'check','[\"echo\",\"hi\"]',"
                " 'exit_zero',NULL,0,'t')")
    con.commit()
    con.close()
    return path


def test_migration_preserves_fk_integrity_from_pre453_schema():
    """Red-team regression: the FIRST #453 attempt migrated `specs` off its
    old UNIQUE constraint by doing `ALTER TABLE specs RENAME TO specs_pre453`
    before recreating `specs` fresh. SQLite's rename-table logic rewrites the
    declared FOREIGN KEY clause of every OTHER table that references the
    renamed one -- so spec_checks' FK permanently became
    `REFERENCES "specs_pre453"(id)`, a table this method then DROPped.
    `PRAGMA foreign_key_check` caught this live on this project's own
    var/product.db. Migrating through the real ProductStore constructor must
    leave spec_checks' FK correctly targeting `specs`, with zero dangling
    references, and the pre-existing row intact."""
    path = _pre453_db_path()
    store = ProductStore(db_path=path)
    violations = store.db.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == [], f"dangling FK reference(s) after migration: {violations}"
    fk_targets = {row[2] for row in store.db.execute("PRAGMA foreign_key_list(spec_checks)").fetchall()}
    assert fk_targets == {"specs"}
    # the pre-existing row must have survived the rebuild intact
    row = store.db.execute("SELECT spec_id, name FROM spec_checks WHERE id=1").fetchone()
    assert row == (1, "check")
    # and the store must still be fully functional post-migration, even with
    # FK enforcement turned ON (the exact setting the red-team said would break)
    store.db.execute("PRAGMA foreign_keys = ON")
    eid = store.create_epic("epic2")
    sid = store.create_story(eid, "story2")
    spec_row_id = store.attach_spec(sid, _two_check_spec())
    n = store.db.execute(
        "SELECT COUNT(*) FROM spec_checks WHERE spec_id=?", (spec_row_id,)).fetchone()[0]
    assert n == 2
    store.close()


def _post_buggy_migration_db_path() -> str:
    """Reproduces the EXACT corruption the red-team found live in this
    project's own var/product.db: `specs` has ALREADY been rebuilt without
    the unique index (so `_ensure_specs_story_id_not_unique`'s early-return
    fires and never touches it again), but spec_checks' declared FK still
    reads `REFERENCES "specs_pre453"(id)` -- the table the old buggy
    migration renamed away and then dropped."""
    path = os.path.join(tempfile.mkdtemp(prefix="animal-product-corrupt-"), "product.db")
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE epics(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT DEFAULT 'backlog',
        priority INTEGER DEFAULT 0, created TEXT)""")
    con.execute("""CREATE TABLE stories(
        id INTEGER PRIMARY KEY, epic_id INTEGER, title TEXT NOT NULL,
        user_story TEXT, story_points INTEGER, priority INTEGER DEFAULT 0,
        status TEXT DEFAULT 'backlog', created TEXT,
        FOREIGN KEY(epic_id) REFERENCES epics(id))""")
    con.execute("""CREATE TABLE specs(
        id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL, title TEXT,
        body TEXT, status TEXT DEFAULT 'draft', created TEXT,
        FOREIGN KEY(story_id) REFERENCES stories(id))""")
    # the corrupted FK clause: references a table dropped long ago
    con.execute("""CREATE TABLE spec_checks(
        id INTEGER PRIMARY KEY, spec_id INTEGER NOT NULL, name TEXT NOT NULL,
        argv TEXT NOT NULL, comparator TEXT NOT NULL DEFAULT 'exit_zero',
        stdout_needle TEXT, nondeterministic INTEGER DEFAULT 0, created TEXT,
        regression INTEGER DEFAULT 0,
        FOREIGN KEY(spec_id) REFERENCES "specs_pre453"(id))""")
    con.execute("""CREATE TABLE commit_links(
        id INTEGER PRIMARY KEY, story_id INTEGER NOT NULL, sha TEXT NOT NULL,
        message TEXT, created TEXT,
        FOREIGN KEY(story_id) REFERENCES stories(id))""")
    con.execute("INSERT INTO epics(id, name, status, priority, created) VALUES (1,'epic','backlog',0,'t')")
    con.execute("INSERT INTO stories(id, epic_id, title, status, priority, created)"
                " VALUES (1,1,'story','backlog',0,'t')")
    con.execute("INSERT INTO specs(id, story_id, title, body, status, created)"
                " VALUES (1,1,'title','{}','draft','t')")
    con.execute("INSERT INTO spec_checks(id, spec_id, name, argv, comparator, stdout_needle,"
                " nondeterministic, created, regression)"
                " VALUES (1,1,'check','[\"echo\",\"hi\"]','exit_zero',NULL,0,'t',0)")
    con.commit()
    con.close()
    return path


def test_self_heals_already_corrupted_spec_checks_fk():
    """A DB that already went through the OLD buggy migration has `specs`
    looking perfectly fine (no unique index left to detect), so
    `_ensure_specs_story_id_not_unique` alone would never touch it again --
    the corruption lives entirely in spec_checks' declared FK text. Opening
    such a DB through ProductStore must self-heal spec_checks' FK, not
    silently skip because specs already looks migrated."""
    path = _post_buggy_migration_db_path()
    store = ProductStore(db_path=path)
    fk_targets = {row[2] for row in store.db.execute("PRAGMA foreign_key_list(spec_checks)").fetchall()}
    assert fk_targets == {"specs"}
    violations = store.db.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == [], f"dangling FK reference(s) after self-heal: {violations}"
    row = store.db.execute("SELECT spec_id, name, regression FROM spec_checks WHERE id=1").fetchone()
    assert row == (1, "check", 0)
    store.close()


def test_spec_supersede_after_rejection():
    # #453 red-team: attach_spec's one-active-spec gate must not be a ONE-WAY trap.
    # The REAL Act-2 -> Act-4 flow (not a fresh insert pre-set to 'rejected'):
    # approve a spec, the auditor rejects the work, the maker re-authors. Without a
    # status transition the corrected spec is blocked forever. set_spec_status moves
    # the rejected spec aside so the re-authored one attaches as a NEW history row.
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("epic")
    sid = store.create_story(eid, "story")
    store.attach_spec(sid, _two_check_spec(state=SpecState.APPROVED.value))
    try:
        store.attach_spec(sid, _two_check_spec(state=SpecState.DRAFT.value))
        assert False, "expected ProductError while a spec is active"
    except ProductError:
        pass
    store.set_spec_status(sid, SpecState.REJECTED.value)          # auditor rejected -> supersede
    new_id = store.attach_spec(sid, _two_check_spec(state=SpecState.APPROVED.value))
    assert new_id is not None
    assert store.db.execute("SELECT COUNT(*) FROM specs WHERE story_id=?", (sid,)).fetchone()[0] == 2
    assert store.load_spec(sid).state == SpecState.APPROVED.value  # current = the re-authored spec
    store.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
