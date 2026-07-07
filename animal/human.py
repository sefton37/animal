"""The human channel: approval is a transport, not a token. Approvals arrive here
over a channel no model output can write to — a TUI keypress interactively, or a
programmatic grant standing in for that channel in tests/headless runs. The model
has NO action that flips approval (see types.py — read/grep/edit/shell/finish),
so it literally cannot self-approve. Every request/decision is a ledger APPROVAL
event with its channel recorded (provenance the model can't forge).
"""
from __future__ import annotations
from .types import EventType


class ApprovalService:
    def __init__(self, ledger, channel=None):
        """channel: a callable(key, summary)->("approve"|"reject") representing the
        real human channel (phone/CLI grant). None => interactive TUI prompt."""
        self.ledger = ledger
        self._channel = channel
        self._decisions: dict[str, str] = {}

    def request(self, key: str, summary: str) -> str:
        self.ledger.append(EventType.APPROVAL, {"phase": "request", "key": key, "summary": summary})
        if self._channel is not None:
            decision = self._channel(key, summary)          # the human channel (not model output)
            src = "programmatic"
        else:
            decision = self._tui(summary)
            src = "tui"
        decision = "approve" if decision == "approve" else "reject"
        self.ledger.append(EventType.APPROVAL,
                           {"phase": "decision", "key": key, "decision": decision, "channel": src})
        self._decisions[key] = decision
        return decision

    def _tui(self, summary: str) -> str:
        try:
            ans = input(f"\n[APPROVAL NEEDED]\n{summary}\nApprove? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        return "approve" if ans in ("y", "yes") else "reject"

    def decided(self, key: str) -> str | None:
        return self._decisions.get(key)
