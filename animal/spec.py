"""Spec + DoD contracts for the work lane (Gate 0). A Spec is a schema-constrained
object — the model fills it, the harness validates/stores/executes it. DoD checks
are argv-only (like every action), with a small typed comparator grammar so a
check's pass genuinely implies a property, not "some prose ran".

The state enum is the work-lane state machine; write capability follows state.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import uuid


class SpecState(str, Enum):
    DRAFT = "draft"
    GROUNDED = "grounded"
    APPROVED = "approved"       # only a human-channel event flips to/through here
    BUILDING = "building"       # write capability granted here
    VERIFYING = "verifying"
    NEEDS_HUMAN = "needs_human"
    DONE = "done"
    REJECTED = "rejected"


class Comparator(str, Enum):
    EXIT_ZERO = "exit_zero"          # command succeeded
    EXIT_NONZERO = "exit_nonzero"    # command failed (e.g. an absence check: grep finds nothing)
    STDOUT_CONTAINS = "stdout_contains"
    STDOUT_ABSENT = "stdout_absent"


class SpecError(ValueError):
    pass


@dataclass
class DoDCheck:
    name: str
    argv: list[str]                 # argv-only, like every action
    comparator: str = Comparator.EXIT_ZERO.value
    expected: str = ""              # for stdout_contains / stdout_absent
    nondeterministic: bool = False  # -> executor runs N=3, all must pass
    regression: bool = False        # opt out of the negative-control (expected to pass pre-work)
    expected_new: bool = False      # Story #458: this check names a path (e.g. a not-yet-written
                                     # tests/test_x.py the TDD tester role is about to author) that
                                     # genuinely does not exist yet at spec-authoring time -- an
                                     # opt-out analogous to `regression` above, honored by BOTH
                                     # existence scans: grounding.ground()'s Gate 0a (absence is
                                     # not recorded as a miss) and dod._lint's missing-helper
                                     # check at Gate 0b. The negative-control still runs on
                                     # expected_new checks -- a missing file genuinely fails
                                     # pre-work -- so the flag can never smuggle in a vacuous check.

    def __post_init__(self):
        if not isinstance(self.argv, list) or not self.argv or not all(isinstance(a, str) for a in self.argv):
            raise SpecError(f"check {self.name!r}: argv must be a non-empty list[str] (argv, not a shell string)")
        if self.comparator not in {c.value for c in Comparator}:
            raise SpecError(f"check {self.name!r}: unknown comparator {self.comparator!r}")
        if self.comparator in ("stdout_contains", "stdout_absent") and not self.expected:
            raise SpecError(f"check {self.name!r}: {self.comparator} needs a non-empty 'expected'")

    def verdict(self, result: dict) -> bool:
        c, out = self.comparator, result.get("stdout", "")
        if c == Comparator.EXIT_ZERO.value:      return result["exit_code"] == 0
        if c == Comparator.EXIT_NONZERO.value:   return result["exit_code"] != 0
        if c == Comparator.STDOUT_CONTAINS.value: return self.expected in out
        if c == Comparator.STDOUT_ABSENT.value:   return self.expected not in out
        return False

    def to_dict(self) -> dict: return asdict(self)


@dataclass
class Spec:
    user_story: str
    intent: list[str] = field(default_factory=list)        # decomposition
    out_of_scope: list[str] = field(default_factory=list)
    dod: list[DoDCheck] = field(default_factory=list)
    groundings: list[dict] = field(default_factory=list)   # filled by grounding.py
    state: str = SpecState.DRAFT.value
    id: str = field(default_factory=lambda: "spec-" + uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        d = asdict(self); d["dod"] = [c.to_dict() for c in self.dod]; return d

    @staticmethod
    def from_dict(d: dict) -> "Spec":
        if "user_story" not in d or not str(d.get("user_story", "")).strip():
            raise SpecError("spec must have a non-empty user_story")
        checks = [DoDCheck(**c) for c in d.get("dod", [])]     # round-trip-validates each check
        return Spec(user_story=d["user_story"], intent=d.get("intent", []),
                    out_of_scope=d.get("out_of_scope", []), dod=checks,
                    groundings=d.get("groundings", []),
                    state=d.get("state", SpecState.DRAFT.value),
                    id=d.get("id", "spec-" + uuid.uuid4().hex[:8]))
