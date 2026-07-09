"""Story #474 -- the sprint runner (M6): iterate the gated chain against a
deadline.

Given a review deadline, run the REAL gated verification chain
(worklane.run_work: Gate 0 -> human approval -> build -> verify -> audit) on
every scheduled story, one after another, stopping CLEANLY at the deadline --
never interrupted mid-build. A story that has STARTED is allowed to finish
(the design's "finishes in-flight edits"); a story that has NOT started once
the budget is spent is DEFERRED, never aborted. This is the lifecycle stage
the project is named for.

Two injection seams, both following worklane.py's own `approver` pattern:
- runner defaults to worklane.run_work (lazy import), swappable for a stub so
  the sprint's tests never touch a live model.
- now_fn defaults to a real clock but is overridable -- the 2026-04-20
  flaky-timing incident was exactly an uninjected clock; the budget re-check
  BEFORE each story must be deterministically testable.

NAMED DEVIATION from the AC letter (authored pre-M2/M5): the AC named a
`BacklogStore`/`var/backlog.db`; the sovereign store is M2's ProductStore
(the roadmap's own "extend M2, don't fork" correction). run_sprint takes a
ProductStore. Each story's final outcome is written back to its story row
exactly once (done/needs_human/rejected/deferred); velocity is recorded only
for stories that actually RAN.
"""
from __future__ import annotations
from datetime import datetime, timezone
from .scheduler import select_for_deadline
from . import velocity as _velocity


def _real_now() -> float:
    return datetime.now(timezone.utc).timestamp()


# run_work's final_state / rejected_at collapse to one backlog status per story
def _outcome_status(result: dict) -> str:
    st = (result or {}).get("final_state")
    if st == "done":
        return "done"
    if st == "rejected":
        return "rejected"
    return "needs_human"    # verifying->needs_human, approval-stopped, anything else


def run_sprint(store, deadline_ts: float, repo: str, runner=None, now_fn=None,
               approver=None, estimate_fn=None, points_of=None,
               velocity_db=None) -> dict:
    """Run a deadline-boxed sprint over the store's backlog. Returns a result
    dict: {finished: [...], deferred: [...], totals: {...}, selected_ids,
    deadline_ts}. runner(spec, repo, approver=...) defaults to
    worklane.run_work; now_fn()->epoch-seconds defaults to the real clock;
    estimate_fn(points)->seconds defaults to velocity.estimate_seconds."""
    now_fn = now_fn or _real_now
    estimate_fn = estimate_fn or (lambda p: _velocity.estimate_seconds(p, db_path=velocity_db))
    points_of = points_of or (lambda row: row.get("story_points"))
    if runner is None:
        from .worklane import run_work as _rw
        runner = lambda spec, repo_, **kw: _rw(spec, repo_, **kw)

    # candidates: workable, sized stories with a loadable spec
    rows = store.list_backlog(status="backlog")
    items = []
    for r in rows:
        pts = points_of(r)
        if pts is None:
            continue                       # unsized -> not schedulable (velocity can't estimate)
        items.append({"spec_id": r["id"], "points": pts, "priority": r.get("priority") or 0})

    budget = deadline_ts - now_fn()
    plan = select_for_deadline(items, budget, estimate_fn)
    selected_ids = [i["spec_id"] for i in plan["selected"]]

    finished, deferred = [], []
    # every scheduler-deferred story: written back once, recorded, no run
    for item in plan["deferred"]:
        store.update_story(item["spec_id"], status="deferred")
        deferred.append({"spec_id": item["spec_id"], "points": item["points"],
                         "reason": "did not fit the deadline budget", "ran": False})

    for item in plan["selected"]:
        sid = item["spec_id"]
        # RE-CHECK the budget before STARTING each story (not only upfront):
        # a story that would begin past the deadline is deferred, not started
        # and killed -- "stops starting new work" from the design.
        if now_fn() >= deadline_ts:
            store.update_story(sid, status="deferred")
            deferred.append({"spec_id": sid, "points": item["points"],
                             "reason": "deadline reached before this story started", "ran": False})
            continue
        spec = store.load_spec(sid)
        if spec is None:
            store.update_story(sid, status="needs_human")
            finished.append({"spec_id": sid, "points": item["points"], "status": "needs_human",
                             "seconds": None, "ran": True, "ledger": None,
                             "reason": "no loadable spec"})
            continue
        # the story STARTS here -- once started it runs to completion, never
        # aborted mid-build by the clock
        result = runner(spec, repo, approver=approver)
        status = _outcome_status(result)
        store.update_story(sid, status=status)
        # velocity is recorded ONLY for stories that actually ran, and only
        # when the run produced a measurable ledger
        recorded_seconds = None
        ledger_path = (result or {}).get("ledger")
        if ledger_path:
            try:
                recorded_seconds = _record_velocity(ledger_path, spec.id, item["points"], velocity_db)
            except Exception:
                recorded_seconds = None      # unmeasurable run -> no velocity row, never a crash
        finished.append({"spec_id": sid, "points": item["points"], "status": status,
                         "seconds": recorded_seconds, "ran": True,
                         "ledger": ledger_path,
                         "session_id": (result or {}).get("session_id"),
                         "dod": (result or {}).get("dod"),
                         "build_turns": (result or {}).get("build_turns"),
                         **({"reason": result.get("reason")} if result and result.get("reason") else {})})

    seconds_used = sum((f.get("seconds") or 0) for f in finished)
    return {"finished": finished, "deferred": deferred,
            "selected_ids": selected_ids, "deadline_ts": deadline_ts,
            "totals": {"points_done": sum(f["points"] for f in finished if f["status"] == "done"),
                       "points_deferred": sum(d["points"] for d in deferred),
                       "seconds_used": seconds_used, "budget_seconds": budget}}


def _record_velocity(ledger_path, spec_id, points, velocity_db):
    """Reconstruct a Ledger over the run's session and record its measured
    duration -- the completion time is the ledger's own, never the sprint's."""
    from pathlib import Path
    from .ledger import Ledger
    p = Path(ledger_path)
    session_id = p.stem
    L = Ledger(session_id=session_id, ledger_dir=str(p.parent))
    return _velocity.record_completion(L, spec_id, points, db_path=velocity_db)
