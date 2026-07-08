"""Story #451 tests: the sovereign product-store schema (epics -> stories ->
specs -> spec_checks -> commit_links). Deterministic, offline. Run:
`python3 tests/test_product.py` or under pytest.
"""
import sys, os, tempfile, sqlite3, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from animal.product import ProductStore

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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
