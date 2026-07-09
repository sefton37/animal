"""Story #473 -- the deadline-fitting scheduler (M6).

Pick, in priority order, exactly the stories that measured velocity says will
FIT before the review deadline -- so the maker gets a queue they can trust,
never a sprint that starts work it can't finish. The estimate function is
INJECTED (velocity.estimate_seconds in production; a stub in tests), so the
scheduler is pure arithmetic over harness-measured durations -- no store, no
model, no clock of its own.

Selection is greedy by a deterministic order (priority DESC, then points ASC
so the cheapest of equal-priority items land first and MORE items fit, then
spec_id ASC to break remaining ties reproducibly). A story whose estimate
would overflow the remaining budget is DEFERRED, not truncated; nothing is
dropped or duplicated (selected + deferred == every input item). budget<=0
defers everything -- an edge case, never an exception.
"""
from __future__ import annotations


def _order_key(item):
    # priority DESC (higher first), points ASC (cheapest first among equal
    # priority -> maximize items landed), spec_id ASC (reproducible tiebreak)
    return (-(item.get("priority") or 0), item.get("points") or 0, str(item.get("spec_id")))


def select_for_deadline(items, budget_seconds, estimate_fn) -> dict:
    """Greedily select backlog items (dicts with spec_id, points, priority)
    whose cumulative estimated seconds fit budget_seconds, in the
    priority-respecting order above. Returns
    {"selected": [...ordered...], "deferred": [...]} -- a partition of the
    input, nothing lost. estimate_fn(points) -> seconds is injected."""
    ordered = sorted(items, key=_order_key)
    selected, deferred = [], []
    remaining = budget_seconds
    for item in ordered:
        cost = estimate_fn(item.get("points") or 0)
        # budget<=0, or an item that would overflow what's left, defers. A
        # later CHEAPER item can still fit the remaining budget (greedy fill),
        # which is why this continues rather than breaking -- more items
        # landed is the point.
        if remaining > 0 and cost <= remaining:
            selected.append(item)
            remaining -= cost
        else:
            deferred.append(item)
    return {"selected": selected, "deferred": deferred}
