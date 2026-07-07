"""Security-tap adapter. Exports each animal session as a compact AI-activity
record to a feed Bastion tails — so the operator (animal itself) is audited like
any other actor, per the Bastion constitution ("auditing the auditor").

The ledger is the full transcript; this is the signal Bastion's AI-activity
pillar cares about: what ran, where, under what isolation, and any faults. Full
native Bastion-format ingestion is a follow-up; this makes sessions VISIBLE now.
"""
from __future__ import annotations
import json
from pathlib import Path
from . import config


def emit(summary: dict, ledger, sink=None) -> str:
    sink = Path(sink or config.VAR / "bastion-feed.jsonl")
    sink.parent.mkdir(parents=True, exist_ok=True)
    evs = ledger.replay()
    start = next((e.payload for e in evs if e.type == "session_start"), {})
    actions = [e.payload for e in evs if e.type == "action"]
    rec = {
        "source": "animal",
        "session": summary["session_id"],
        "ts": evs[-1].ts if evs else None,
        "repo": start.get("repo"),
        "sandbox_mode": summary.get("sandbox_mode"),
        "net_off": summary.get("sandbox_mode") == "full",
        "turns": summary.get("turns"),
        "edits_landed": summary.get("edits_landed"),
        # egress-relevant signal: the actual argv of anything the agent shelled out
        "shell_argv": [a.get("argv") for a in actions if a.get("kind") == "shell"],
        "errors": [e.payload for e in evs if e.type == "error"],
        "ledger": summary.get("ledger"),
    }
    with open(sink, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return str(sink)
