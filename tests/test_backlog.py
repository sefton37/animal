"""Story #470 -- value/effort prioritization over the sovereign store.
Deterministic, temp-db, no model calls (the ratio is harness-computed).
Run: python3 tests/test_backlog.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal.backlog import prioritized
from animal.product import ProductStore


def _store():
    st = ProductStore(db_path=":memory:")
    eid = st.create_epic("epic")
    return st, eid


def test_exact_ratio_descending_order():
    """The AC's seeded scenario against the sovereign store (value = the
    distinct value field, effort = story_points): a(8/2)=4 > c(3/1)=3 >
    b(8/8)=1."""
    st, eid = _store()
    a = st.create_story(eid, "A", value=8, story_points=2)
    b = st.create_story(eid, "B", value=8, story_points=8)
    c = st.create_story(eid, "C", value=3, story_points=1)
    order = [s["title"] for s in prioritized(st)]
    assert order == ["A", "C", "B"], order
    ratios = [s["ratio"] for s in prioritized(st)]
    assert ratios == [4.0, 3.0, 1.0], ratios
    st.close()


def test_unsized_and_unvalued_sort_last_and_are_flagged():
    """A story missing value or points is never given an invented ratio --
    it sorts last with a flag naming exactly what is missing."""
    st, eid = _store()
    st.create_story(eid, "ranked", value=5, story_points=5)
    st.create_story(eid, "no-points", value=5)                        # unsized
    st.create_story(eid, "no-value", story_points=3)                  # unvalued (value 0)
    st.create_story(eid, "neither")                                   # both
    out = prioritized(st)
    assert out[0]["title"] == "ranked" and out[0]["flag"] is None
    flags = {s["title"]: s["flag"] for s in out[1:]}
    assert flags["no-points"] == "unsized"
    assert flags["no-value"] == "unvalued"
    assert flags["neither"] == "unsized+unvalued"
    assert all(s["ratio"] is None for s in out[1:])
    st.close()


def test_ties_break_on_value_then_smaller_points():
    st, eid = _store()
    st.create_story(eid, "big", value=8, story_points=8)     # ratio 1
    st.create_story(eid, "small", value=2, story_points=2)   # ratio 1
    out = [s["title"] for s in prioritized(st) if s["flag"] is None]
    assert out == ["big", "small"], out                          # higher value first on equal ratio
    st.close()


def test_epic_filter():
    st, e1 = _store()
    e2 = st.create_epic("other")
    st.create_story(e1, "in-epic-1", value=1, story_points=1)
    st.create_story(e2, "in-epic-2", value=1, story_points=1)
    titles = [s["title"] for s in prioritized(st, epic_id=e2)]
    assert titles == ["in-epic-2"], titles
    st.close()


def test_done_story_is_not_a_work_next_candidate():
    """Gate-3 major: a done/in-flight story must not top a 'work next' view;
    the default status filter drops it (status=None includes everything)."""
    st, eid = _store()
    st.create_story(eid, "shipped", value=21, story_points=1, status="done")   # best ratio, but DONE
    st.create_story(eid, "todo", value=3, story_points=1, status="backlog")
    default = [s["title"] for s in prioritized(st)]
    assert default == ["todo"], default              # 'shipped' excluded by default
    allst = [s["title"] for s in prioritized(st, status=None)]
    assert "shipped" in allst and allst[0] == "shipped", allst
    st.close()


def test_unrankable_stories_carry_a_cli_remedy():
    """Gate-3 major: the flag names what's missing AND how to fix it."""
    st, eid = _store()
    sid_u = st.create_story(eid, "no-value", story_points=3)
    sid_s = st.create_story(eid, "no-points", value=5)
    out = {s["id"]: s for s in prioritized(st)}
    assert f"animal backlog set-value {sid_u}" in out[sid_u]["remedy"]
    assert f"animal size {sid_s}" in out[sid_s]["remedy"]
    st.close()


def test_negative_value_is_rejected_at_the_store():
    """Gate-3 minor: a negative value would produce an unflagged negative
    ratio -- rejected at create/update, never ranked."""
    from animal.product import ProductError
    st, eid = _store()
    try:
        st.create_story(eid, "bad", value=-5, story_points=2)
        assert False, "expected ProductError"
    except ProductError:
        pass
    st.close()


def test_no_second_store_exists():
    """The roadmap's own correction, mechanically: this module must hold NO
    store class and NO CREATE TABLE -- it reads M2's ProductStore only."""
    import ast
    src = Path(__file__).resolve().parent.parent.joinpath("animal", "backlog.py").read_text()
    assert "CREATE TABLE" not in src
    tree = ast.parse(src)
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert not classes, f"backlog.py must not define a store class, found {[c.name for c in classes]}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
