"""The work-lane task: a Spec + a state machine where WRITE CAPABILITY FOLLOWS
STATE. The build transition (which is where writes are allowed) is unreachable
until a human-channel approval has advanced the task to APPROVED. A model can't
reach it — there is no approval action.
"""
from __future__ import annotations
from .spec import Spec, SpecState

# allowed transitions; `approved` additionally requires a human approval grant
_ALLOWED = {
    "draft":       {"grounded", "rejected"},
    "grounded":    {"approved", "rejected"},
    "approved":    {"building"},
    "building":    {"verifying", "rejected"},
    "verifying":   {"done", "needs_human", "building"},
    "needs_human": {"done", "rejected", "building"},
    "done":        set(),
    "rejected":    set(),
}


class TransitionError(RuntimeError):
    pass


class Task:
    def __init__(self, spec: Spec):
        self.spec = spec

    @property
    def state(self) -> str:
        return self.spec.state

    def can_write(self) -> bool:
        """The kernel grants file-write capability ONLY while building."""
        return self.spec.state == SpecState.BUILDING.value

    def transition(self, to: str, *, approval: str | None = None) -> None:
        cur = self.spec.state
        if to not in _ALLOWED.get(cur, set()):
            raise TransitionError(f"illegal transition {cur} -> {to}")
        if to == SpecState.APPROVED.value and approval != "approve":
            raise TransitionError("approve transition requires a human-channel approval grant "
                                  "(a model cannot reach this state)")
        self.spec.state = to
