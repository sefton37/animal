"""Story #451 tests: the sovereign product-store schema (epics -> stories ->
specs -> spec_checks -> commit_links). Deterministic, offline. Run:
`python3 tests/test_product.py` or under pytest.
"""
import sys, os, tempfile, sqlite3, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from animal.product import ProductStore, ProductError, FIBONACCI_POINTS

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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
