"""Story #474 -- the sprint runner. Deterministic and OFFLINE: the runner is
a stub (never worklane.run_work, never a live model), the clock is injected.
This file never pulls in the LLM plane (AC: the sprint suite stays offline).
Run: python3 tests/test_sprint.py
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

import animal.sprint as sprint
from animal.sprint import run_sprint
from animal.product import ProductStore
from animal.spec import Spec, DoDCheck
from animal.ledger import Ledger


def _fake_ledger(seconds: float) -> str:
    """Write a real NDJSON ledger with a controlled start->end span; return
    its path (what run_work's summary carries as 'ledger')."""
    d = tempfile.mkdtemp(prefix="animal-sprint-led-")
    L = Ledger(ledger_dir=d)
    sid = L.session_id
    lines = [
        {"id": "e1", "session_id": sid, "seq": 1, "schema_version": 1,
         "type": "session_start", "ts": "2026-07-08T00:00:00+00:00", "payload": {}},
        {"id": "e2", "session_id": sid, "seq": 2, "schema_version": 1,
         "type": "session_end", "ts": _plus(seconds), "payload": {"final_state": "done"}},
    ]
    p = Path(d) / f"{sid}.ndjson"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return str(p)


def _plus(seconds: float) -> str:
    from datetime import datetime, timedelta
    return (datetime.fromisoformat("2026-07-08T00:00:00+00:00") + timedelta(seconds=seconds)).isoformat()


def _seed(store, specs):
    """specs: list of (title, points, priority). Returns story ids in order."""
    eid = store.create_epic("sprint epic")
    ids = []
    for title, pts, pri in specs:
        sid = store.create_story(eid, title, story_points=pts, priority=pri, status="backlog")
        spec = Spec(f"{title} story", dod=[DoDCheck(
            "c", ["python3", "-c", "assert True"], "exit_zero", regression=True)])
        store.attach_spec(sid, spec)
        ids.append(sid)
    return ids


def test_recheck_before_each_story():
    """A story STARTED before the deadline finishes; a not-yet-started story
    past the deadline is DEFERRED, never aborted mid-call. The clock advances
    only as the runner runs."""
    # est=50 so BOTH stories pass the static scheduler at budget 150 (100<=150);
    # the runtime clock re-check is what this test isolates. clock advances
    # only as the runner runs.
    clock = {"t": 0.0}
    est = lambda p: 50.0

    def now_fn():
        return clock["t"]

    # runner cost 100 each: first t0->100, second re-check t=100<150 -> BOTH run
    store = ProductStore(db_path=":memory:")
    a, b = _seed(store, [("first", 3, 9), ("second", 3, 5)])
    clock["t"] = 0.0

    def fast_runner(spec, repo, approver=None):
        clock["t"] += 100.0
        return {"final_state": "done", "ledger": _fake_ledger(100.0)}

    r = run_sprint(store, deadline_ts=250.0, repo=".", runner=fast_runner,
                   now_fn=now_fn, estimate_fn=est, velocity_db=_vdb())
    assert [f["spec_id"] for f in r["finished"]] == [a, b], r
    assert r["deferred"] == [], r

    # runner cost 200 each, deadline 150: first STARTS at t=0 (<150) and runs
    # to completion (t->200) -- never aborted mid-call; second re-check
    # t=200>=150 -> DEFERRED, not started
    store2 = ProductStore(db_path=":memory:")
    a2, b2 = _seed(store2, [("first", 3, 9), ("second", 3, 5)])
    clock["t"] = 0.0

    def slow_runner(spec, repo, approver=None):
        clock["t"] += 200.0
        return {"final_state": "done", "ledger": _fake_ledger(200.0)}

    r2 = run_sprint(store2, deadline_ts=150.0, repo=".", runner=slow_runner,
                    now_fn=now_fn, estimate_fn=est, velocity_db=_vdb())
    assert [f["spec_id"] for f in r2["finished"]] == [a2], r2      # started before deadline, finished
    assert [d["spec_id"] for d in r2["deferred"]] == [b2], r2      # not started past deadline
    assert r2["deferred"][0]["reason"].startswith("deadline reached"), r2["deferred"][0]


def test_state_written_once():
    """Each story's backlog state is written exactly once (no double-write)."""
    store = ProductStore(db_path=":memory:")
    ids = _seed(store, [("s1", 3, 5), ("s2", 5, 5)])
    writes = []
    orig = store.update_story

    def spy(story_id, **fields):
        writes.append((story_id, fields.get("status")))
        return orig(story_id, **fields)

    store.update_story = spy
    run_sprint(store, deadline_ts=1e9, repo=".",
               runner=lambda spec, repo, approver=None: {"final_state": "done", "ledger": _fake_ledger(50.0)},
               now_fn=lambda: 0.0, estimate_fn=lambda p: 100.0, velocity_db=_vdb())
    # exactly one write per story, no id written twice
    written_ids = [w[0] for w in writes]
    assert sorted(written_ids) == sorted(ids), writes
    assert len(written_ids) == len(set(written_ids)), f"double-write: {writes}"


def test_velocity_recorded_only_for_run_stories():
    """record_completion fires once per story that RAN, never for a deferred
    one."""
    store = ProductStore(db_path=":memory:")
    _seed(store, [("cheap", 3, 9), ("expensive", 13, 5)])
    calls = []
    orig = sprint._velocity.record_completion

    def spy(ledger, spec_id, points, db_path=None):
        calls.append(spec_id)
        return orig(ledger, spec_id, points, db_path=db_path)

    sprint._velocity.record_completion = spy
    try:
        # budget 500: cheap (est 300) fits, expensive (est 1300) deferred
        r = run_sprint(store, deadline_ts=500.0, repo=".",
                       runner=lambda spec, repo, approver=None: {"final_state": "done", "ledger": _fake_ledger(42.0)},
                       now_fn=lambda: 0.0, estimate_fn=lambda p: p * 100.0, velocity_db=_vdb())
    finally:
        sprint._velocity.record_completion = orig
    ran = [f["spec_id"] for f in r["finished"] if f["ran"]]
    deferred = [d["spec_id"] for d in r["deferred"]]
    assert len(calls) == len(ran) == 1, (calls, ran)
    assert calls[0] not in deferred


def test_deferred_and_run_partition_the_backlog():
    store = ProductStore(db_path=":memory:")
    ids = _seed(store, [("a", 3, 5), ("b", 5, 5), ("c", 8, 5)])
    r = run_sprint(store, deadline_ts=400.0, repo=".",
                   runner=lambda spec, repo, approver=None: {"final_state": "done", "ledger": _fake_ledger(10.0)},
                   now_fn=lambda: 0.0, estimate_fn=lambda p: p * 100.0, velocity_db=_vdb())
    seen = {f["spec_id"] for f in r["finished"]} | {d["spec_id"] for d in r["deferred"]}
    assert seen == set(ids), (seen, ids)


def test_unsized_story_is_not_scheduled():
    """A story with no points can't be velocity-estimated -- it is not a sprint
    candidate (never silently sized)."""
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("e")
    sid = store.create_story(eid, "unsized", priority=5, status="backlog")
    store.attach_spec(sid, Spec("u", dod=[DoDCheck("c", ["python3", "-c", "assert True"], "exit_zero", regression=True)]))
    r = run_sprint(store, deadline_ts=1e9, repo=".",
                   runner=lambda spec, repo, approver=None: {"final_state": "done", "ledger": _fake_ledger(10.0)},
                   now_fn=lambda: 0.0, estimate_fn=lambda p: 100.0, velocity_db=_vdb())
    assert r["finished"] == [] and r["deferred"] == [], r


def test_no_loadable_spec_does_not_crash_the_sprint():
    """Audit BLOCKER: a sized story whose spec won't load must yield a
    needs_human finished entry with a uniform shape (seconds present) -- never
    a KeyError that kills the whole sprint and destroys the review package."""
    from animal.review import assemble_review
    store = ProductStore(db_path=":memory:")
    eid = store.create_epic("e")
    sid = store.create_story(eid, "sized but specless", story_points=3, priority=5, status="backlog")
    # NO attach_spec -> load_spec returns None
    r = run_sprint(store, deadline_ts=1e9, repo=".",
                   runner=lambda spec, repo, approver=None: {"final_state": "done", "ledger": _fake_ledger(10.0)},
                   now_fn=lambda: 0.0, estimate_fn=lambda p: 100.0, velocity_db=_vdb())
    entry = next(f for f in r["finished"] if f["spec_id"] == sid)
    assert entry["status"] == "needs_human" and entry["seconds"] is None
    assert "no loadable spec" in entry["reason"]
    review = assemble_review(r)                 # the review package still assembles
    assert review["totals"]["points_total"] >= 3


def _vdb():
    return os.path.join(tempfile.mkdtemp(prefix="animal-sprint-vel-"), "learning.db")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
