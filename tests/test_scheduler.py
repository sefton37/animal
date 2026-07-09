"""Story #473 -- deadline-fitting scheduler. Pure arithmetic, injected
estimate_fn (never touches learning.db). Run: python3 tests/test_scheduler.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal.scheduler import select_for_deadline

# estimate_fn: seconds = points * 100 (deterministic, injected -- no store)
def _est(points):
    return (points or 0) * 100.0


def test_partial_fit():
    """Cumulative cost exceeds budget -> some selected, some deferred, nothing
    lost or duplicated."""
    items = [{"spec_id": "a", "points": 5, "priority": 1},
             {"spec_id": "b", "points": 8, "priority": 1},
             {"spec_id": "c", "points": 3, "priority": 1}]
    # costs 500/800/300, budget 900 -> can't fit all (1600 total)
    r = select_for_deadline(items, 900, _est)
    assert len(r["selected"]) >= 1 and len(r["deferred"]) >= 1
    assert len(r["selected"]) + len(r["deferred"]) == 3
    ids = {i["spec_id"] for i in r["selected"]} | {i["spec_id"] for i in r["deferred"]}
    assert ids == {"a", "b", "c"}, "partition must cover every input exactly once"


def test_tie_break_deterministic():
    """Reversed insertion order + equal cost still selects the higher-priority
    item; equal priority -> cheapest (points ASC) first."""
    items = [{"spec_id": "low", "points": 3, "priority": 1},
             {"spec_id": "high", "points": 3, "priority": 9}]
    r = select_for_deadline(items, 300, _est)   # room for exactly one (cost 300 each)
    assert [i["spec_id"] for i in r["selected"]] == ["high"], r
    assert [i["spec_id"] for i in r["deferred"]] == ["low"], r
    # equal priority -> cheapest first
    eq = [{"spec_id": "big", "points": 8, "priority": 5},
          {"spec_id": "small", "points": 2, "priority": 5}]
    r2 = select_for_deadline(eq, 100000, _est)
    assert [i["spec_id"] for i in r2["selected"]] == ["small", "big"], r2


def test_zero_budget():
    """budget<=0 defers everything -- an edge case, not an exception."""
    items = [{"spec_id": "a", "points": 1, "priority": 1},
             {"spec_id": "b", "points": 2, "priority": 1}]
    for budget in (0, -100):
        r = select_for_deadline(items, budget, _est)
        assert r["selected"] == [] and len(r["deferred"]) == 2, (budget, r)


def test_greedy_fill_lands_a_later_cheaper_item():
    """A big item that overflows is deferred, but a later cheaper item that
    still fits the remaining budget is landed -- more items is the goal."""
    items = [{"spec_id": "big", "points": 13, "priority": 5},   # cost 1300
             {"spec_id": "tiny", "points": 1, "priority": 5}]   # cost 100
    r = select_for_deadline(items, 500, _est)
    assert [i["spec_id"] for i in r["selected"]] == ["tiny"], r
    assert [i["spec_id"] for i in r["deferred"]] == ["big"], r


def test_empty_items():
    assert select_for_deadline([], 1000, _est) == {"selected": [], "deferred": []}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
