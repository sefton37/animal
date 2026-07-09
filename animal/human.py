"""The human channel: approval is a transport, not a token. Approvals arrive here
over a channel no model output can write to — a TUI keypress interactively, or a
programmatic grant standing in for that channel in tests/headless runs. The model
has NO action that flips approval (see types.py — read/grep/edit/shell/finish),
so it literally cannot self-approve. Every request/decision is a ledger APPROVAL
event with its channel recorded (provenance the model can't forge).
"""
from __future__ import annotations
from .types import EventType


class MakerAbsent(Exception):
    """No maker on the human channel (EOF, dead pipe). The harness halts on
    this -- it never fabricates a human's reply (the #462 standard). Canonical
    here because both the discovery lane and the sizing escalation share the
    transport; discovery re-exports it."""


class ApprovalService:
    def __init__(self, ledger, channel=None, channel_name=None):
        """channel: a callable(key, summary)->("approve"|"reject") representing the
        real human channel (phone/CLI grant). None => interactive TUI prompt.
        channel_name (#471 audit): an explicit provenance label for the channel
        (e.g. 'channel-test'), so a test injection is distinguishable in the
        ledger from a real programmatic human grant -- defaults to
        'programmatic' for a plain callable."""
        self.ledger = ledger
        self._channel = channel
        self._channel_name = channel_name or "programmatic"
        self._decisions: dict[str, str] = {}

    def request(self, key: str, summary: str) -> str:
        self.ledger.append(EventType.APPROVAL, {"phase": "request", "key": key, "summary": summary})
        if self._channel is not None:
            decision = self._channel(key, summary)          # the human channel (not model output)
            src = self._channel_name
        else:
            decision = self._tui(summary)
            src = "tui"
        decision = "approve" if decision == "approve" else "reject"
        self.ledger.append(EventType.APPROVAL,
                           {"phase": "decision", "key": key, "decision": decision, "channel": src})
        self._decisions[key] = decision
        return decision

    def ask(self, key: str, summary: str) -> str:
        """Story #468: a free-form question over the SAME human transport --
        same ledger APPROVAL provenance, same no-model-writable channel -- but
        the reply comes back VERBATIM instead of being collapsed to
        approve/reject (request() normalizes, which cannot carry a Fibonacci
        point value; sizing escalation needs the human's actual answer)."""
        self.ledger.append(EventType.APPROVAL, {"phase": "request", "key": key, "summary": summary})
        if self._channel is not None:
            reply = str(self._channel(key, summary))
            src = self._channel_name
        else:
            try:
                reply = input(f"\n[HUMAN INPUT NEEDED]\n{summary}\n> ").strip()
            except EOFError:
                # #468 audit: EOF is maker-ABSENCE, not an empty decision -- a
                # decision-phase event here would forge the act of answering
                self.ledger.append(EventType.APPROVAL,
                                   {"phase": "aborted", "key": key, "reason": "maker_absent"})
                raise MakerAbsent("EOF on the interactive channel: no maker present")
            src = "tui"
        self.ledger.append(EventType.APPROVAL,
                           {"phase": "decision", "key": key, "reply": reply, "channel": src})
        return reply

    def _tui(self, summary: str) -> str:
        try:
            ans = input(f"\n[APPROVAL NEEDED]\n{summary}\nApprove? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        return "approve" if ans in ("y", "yes") else "reject"

    def decided(self, key: str) -> str | None:
        return self._decisions.get(key)
