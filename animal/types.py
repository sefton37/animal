"""Core contracts for the animal kernel.

Everything the kernel records or acts on is one of three things:
  Event     — an append-only ledger record (the ONLY source of truth)
  Action    — a typed thing a model proposed (argv-shaped, never a shell string)
  Envelope  — the harness-COMPUTED result of executing an action (the evidence)

The invariant these types exist to enforce (Law 1): a model's prose never asserts
what happened. It proposes an Action; the kernel executes it and computes an
Envelope; only the Envelope is authoritative. A claim that contradicts its
envelope is a tool error, not a fact.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import uuid

SCHEMA_VERSION = 1


class EventType(str, Enum):
    SESSION_START = "session_start"
    PROMPT = "prompt"            # what we sent the model
    MODEL_OUTPUT = "model_output"  # raw model turn (prose + proposed actions)
    ACTION = "action"            # a typed action the kernel is about to execute
    ENVELOPE = "envelope"        # the computed result of an action (the evidence)
    GATE = "gate"                # a gate/policy decision, with its triggering input
    APPROVAL = "approval"        # a human-channel event (never model-synthesizable)
    COMPACTION = "compaction"    # context was compacted here (taints prior claims)
    ERROR = "error"
    SESSION_END = "session_end"


class ErrorClass(str, Enum):
    """Closed taxonomy (ARCHITECTURE §learning plane). Keeps non-model faults out
    of any future calibration arithmetic, and names the founding-incident classes."""
    NONE = "none"
    MODEL_CLAIM_FALSE = "model_claim_false"      # model asserted X; computed evidence says not-X
    MODEL_FORMAT_ERROR = "model_format_error"    # model emitted an unparseable/invalid action
    NON_PERSISTENCE = "non_persistence"          # claimed an edit that left no diff
    HARNESS_FAULT = "harness_fault"              # the kernel itself failed
    ENV_MISMATCH = "env_mismatch"                # pinned environment wrong (not the model's fault)
    SANDBOX_DENIED = "sandbox_denied"            # action hit the sandbox wall (-> escalation)
    INVARIANT_VIOLATION = "invariant_violation"  # read-before-edit / staleness / out-of-grant
    FLAKE_RETRY_PASSED = "flake_retry_passed"
    LINT_REJECTED = "lint_rejected"               # computed new_content fails the syntax-lint gate (rejected before write)


# --- Actions: what a model may propose. Structured, never a shell string. ---

@dataclass
class Action:
    kind: str
    def to_dict(self) -> dict: return {"kind": self.kind, **asdict(self)}


@dataclass
class ReadAction(Action):
    path: str
    offset: int = 0
    limit: int = 200          # windowed viewer (SWE-agent: ~100-line pages)
    def __init__(self, path: str, offset: int = 0, limit: int = 200):
        self.kind = "read"; self.path = path; self.offset = offset; self.limit = limit


@dataclass
class GrepAction(Action):
    pattern: str
    path: str = "."
    def __init__(self, pattern: str, path: str = "."):
        self.kind = "grep"; self.pattern = pattern; self.path = path


@dataclass
class EditAction(Action):
    """Exact/fuzzy search-replace. The canonical internal edit format; per-model
    dialects (whole-file / udiff) normalize to this before execution."""
    path: str
    old_string: str
    new_string: str
    def __init__(self, path: str, old_string: str, new_string: str):
        self.kind = "edit"; self.path = path
        self.old_string = old_string; self.new_string = new_string


@dataclass
class ShellAction(Action):
    """argv ONLY. No shell interpreter, no string-assembled command — this is what
    makes the tool-argument-corruption class unrepresentable (Fork 1)."""
    argv: list[str]
    def __init__(self, argv: list[str]):
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            raise ActionParseError("ShellAction.argv must be a list[str] (argv, not a shell string)")
        self.kind = "shell"; self.argv = argv


@dataclass
class FinishAction(Action):
    message: str = ""
    def __init__(self, message: str = ""):
        self.kind = "finish"; self.message = message


class ActionParseError(ValueError):
    """Raised when a model-emitted action can't round-trip into a typed Action.
    The loop turns this into a MODEL_FORMAT_ERROR envelope fed back to the model."""


_ACTION_CTORS = {
    "read": lambda d: ReadAction(d["path"], d.get("offset", 0), d.get("limit", 200)),
    "grep": lambda d: GrepAction(d["pattern"], d.get("path", ".")),
    "edit": lambda d: EditAction(d["path"], d["old_string"], d["new_string"]),
    "shell": lambda d: ShellAction(d["argv"]),
    "finish": lambda d: FinishAction(d.get("message", "")),
}


def action_from_dict(d: dict) -> Action:
    """The round-trip codec entrypoint. Rejects unknown kinds and bad shapes so a
    malformed action is a typed error, never a silently-mis-executed one."""
    if not isinstance(d, dict) or "kind" not in d:
        raise ActionParseError(f"action must be an object with a 'kind': {d!r}")
    ctor = _ACTION_CTORS.get(d["kind"])
    if ctor is None:
        raise ActionParseError(f"unknown action kind: {d['kind']!r} (known: {sorted(_ACTION_CTORS)})")
    try:
        return ctor(d)
    except ActionParseError:
        raise
    except (KeyError, TypeError) as e:
        raise ActionParseError(f"malformed {d['kind']} action: missing/invalid field ({e})") from e


# --- Envelope: the harness-computed result. The truth. ---

@dataclass
class Envelope:
    action_kind: str
    ok: bool
    error_class: str = ErrorClass.NONE.value
    computed: dict = field(default_factory=dict)  # diff, hashes, exit_code, stdout, content...
    note: str = ""                                 # short human-facing summary
    def to_dict(self) -> dict: return asdict(self)


# --- Event: the append-only ledger record. ---

@dataclass
class Event:
    session_id: str
    seq: int
    type: str
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    schema_version: int = SCHEMA_VERSION
    ts: Optional[str] = None       # stamped by the ledger (harness), never by a model
    def to_dict(self) -> dict: return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Event":
        return Event(session_id=d["session_id"], seq=d["seq"], type=d["type"],
                     payload=d.get("payload", {}), id=d.get("id", uuid.uuid4().hex),
                     schema_version=d.get("schema_version", SCHEMA_VERSION), ts=d.get("ts"))
