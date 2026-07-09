"""Story #470 -- value/effort prioritization over the SOVEREIGN product store.

DEVIATION FROM THE STORY'S ORIGINAL AC, named not silent (the same class
#463 documented): the AC sketched a NEW BacklogStore class with its own
value/points rows -- the exact "quadruple product-DB duplication" drift the
roadmap pre-flagged as its single highest-leverage correction ("enforcing
'extend M2's productdb.py' at each of those milestones"). This module holds
NO store: prioritized() reads M2's ProductStore.

VALUE vs PRIORITY (Gate-3 blocker fix): value is a DISTINCT stories column
(the WSJF numerator, higher = more valuable), NOT the existing `priority`
field -- `backlog list` orders priority ASC (P1 = top), and overloading it
as value made two sibling views sort the same field in opposite directions.
Effort is the Fibonacci `story_points`.

The ratio is WSJF-lite, harness-COMPUTED, no model call: value/points,
descending. A story missing either field cannot be ranked honestly -- it is
never given an invented ratio; it sorts last, flagged 'unsized' or
'unvalued' (or both), each with the CLI remedy that fills the gap. By
default only ACTIONABLE stories are ranked (a done/in-flight story must not
top a "work next" view -- the Gate-3 major); pass status=None to include all.
"""
from __future__ import annotations
from .product import ProductStore

# statuses a "what to work next" ranking should consider by default -- a done
# or in-flight story is not a candidate to START next (#470/#471 audit major)
WORKABLE_STATUSES = ("backlog",)


def prioritized(store: ProductStore, epic_id: int | None = None,
                status: str | tuple | None = WORKABLE_STATUSES) -> list[dict]:
    """The backlog ordered by value against effort. Ranked stories (both
    value>0 and points set) come first, descending value/points; ties break
    on higher value, then smaller points, then id. Unrankable stories follow,
    each carrying a `flag` naming what is missing and a `remedy` CLI hint.
    status filters which stories are candidates (default: WORKABLE_STATUSES,
    so a done story never tops a 'work next' view; None = all). Every dict:
    {id, epic_id, title, value, points, status, ratio, flag, remedy}."""
    rows = store.list_backlog(epic_id=epic_id)
    keep = None if status is None else ((status,) if isinstance(status, str) else tuple(status))
    ranked, unrankable = [], []
    for r in rows:
        if keep is not None and r.get("status") not in keep:
            continue
        value = r.get("value") or 0
        points = r.get("story_points")
        entry = {"id": r["id"], "epic_id": r.get("epic_id"), "title": r["title"],
                 "value": value, "points": points, "status": r.get("status")}
        missing = []
        if points is None:
            missing.append("unsized")
        if not value:
            missing.append("unvalued")
        if missing:
            remedies = []
            if "unsized" in missing:
                remedies.append(f"animal size {r['id']}")
            if "unvalued" in missing:
                remedies.append(f"animal backlog set-value {r['id']} <n>")
            entry["ratio"] = None
            entry["flag"] = "+".join(missing)
            entry["remedy"] = "; ".join(remedies)
            unrankable.append(entry)
        else:
            entry["ratio"] = round(value / points, 3)
            entry["flag"] = None
            entry["remedy"] = None
            ranked.append(entry)
    ranked.sort(key=lambda e: (-e["ratio"], -e["value"], e["points"], e["id"]))
    return ranked + unrankable
