"""The single agentic loop. Model proposes ONE typed action per turn; the kernel
executes it, COMPUTES an envelope, records both to the ledger, and feeds the
computed result (never the model's claim) back into context. Terminates on a
finish action or a hard bound.

The check runner runs any task checks itself and records the REAL exit codes —
so a model that *claims* a check passed is contradicted by the harness's computed
result. That plus the workspace's non-persistence detection are the two seeded
attacks the Phase 1 exit requires the kernel to catch.
"""
from __future__ import annotations
from .ledger import Ledger
from .workspace import Workspace
from .model import ModelPlane, ModelError, SYSTEM_PROMPT
from .sandbox import Sandbox
from .types import (EventType, ErrorClass, Envelope, action_from_dict, ActionParseError,
                    ReadAction, GrepAction, EditAction, ShellAction, FinishAction)
from . import config


def _dispatch(action, ws: Workspace, sb: Sandbox) -> Envelope:
    if isinstance(action, ReadAction):
        return ws.read(action.path, action.offset, action.limit)
    if isinstance(action, EditAction):
        return ws.edit(action.path, action.old_string, action.new_string)
    if isinstance(action, GrepAction):
        r = sb.run(["grep", "-rn", "-e", action.pattern, action.path], ws.repo)
        return Envelope("grep", r["exit_code"] in (0, 1), computed=r)  # grep exit 1 = no match (ok)
    if isinstance(action, ShellAction):
        r = sb.run(action.argv, ws.repo)
        return Envelope("shell", r["exit_code"] == 0, computed=r)
    if isinstance(action, FinishAction):
        return Envelope("finish", True, note=action.message)
    return Envelope("unknown", False, ErrorClass.MODEL_FORMAT_ERROR.value, note=f"no dispatch for {action!r}")


def _feedback(env: Envelope) -> str:
    """What the model sees next turn: the harness-computed result, not its claim."""
    c = env.computed
    if env.action_kind == "read" and env.ok:
        return f"[read ok] {c['path']} ({c['lines_total']} lines, showing from {c['offset']}):\n{c['content']}"
    if env.action_kind == "edit":
        if env.ok:
            return f"[edit APPLIED] computed diff (+{c['added']}/-{c['removed']}):\n{c['diff']}"
        return f"[edit REJECTED: {env.error_class}] {env.note}. Fix your old_string/approach and retry."
    if env.action_kind in ("shell", "grep"):
        return (f"[{env.action_kind} exit={c['exit_code']} sandbox={c.get('sandbox_mode')}]\n"
                f"stdout:\n{c.get('stdout','')}\nstderr:\n{c.get('stderr','')}")
    if not env.ok:
        return f"[{env.action_kind} FAILED: {env.error_class}] {env.note}"
    return f"[{env.action_kind} ok] {env.note}"


def run_task(task: str, repo: str, role: str = "coder", checks: list[dict] | None = None,
             ledger_dir=None, max_turns: int | None = None, ledger: Ledger | None = None,
             temperature: float | None = None) -> dict:
    L = ledger or Ledger(ledger_dir=ledger_dir)   # work lane shares one ledger across the chain
    ws = Workspace(repo, L.session_id)
    mp = ModelPlane()
    sb = Sandbox()
    max_turns = max_turns or config.MAX_TURNS

    L.append(EventType.SESSION_START,
             {"task": task, "repo": str(ws.repo), "role": role, "sandbox_mode": sb.mode,
              "net_off": sb.mode == "full"})
    t0 = ws.snapshot()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Task: {task}\n\nBegin. Emit one action."}]

    edits_landed, finished = 0, False
    for turn_no in range(max_turns):
        try:
            turn, meta = mp.call(role, messages, temperature=temperature)
        except ModelError as e:
            L.append(EventType.ERROR, {"where": "model_call", "error": str(e)})
            break
        L.append(EventType.MODEL_OUTPUT, {"thought": turn.get("thought", ""), "action": turn.get("action"), "meta": meta})
        if meta["context_overflow"]:
            L.append(EventType.ERROR, {"where": "context", "error": "prompt overflowed the window (silent-truncation guard)"})
            break
        messages.append({"role": "assistant", "content": str(turn)})
        # parse the proposed action into a typed one
        try:
            action = action_from_dict(turn["action"])
        except (ActionParseError, KeyError, TypeError) as e:
            env = Envelope("parse", False, ErrorClass.MODEL_FORMAT_ERROR.value, note=str(e))
            L.append(EventType.ENVELOPE, env.to_dict())
            messages.append({"role": "user", "content": f"[invalid action: {e}] Re-emit a valid action."})
            continue
        L.append(EventType.ACTION, action.to_dict())
        env = _dispatch(action, ws, sb)
        L.append(EventType.ENVELOPE, env.to_dict())
        if env.action_kind == "edit" and env.ok:
            edits_landed += 1
        messages.append({"role": "user", "content": _feedback(env)})
        if isinstance(action, FinishAction):
            finished = True
            break

    # whole-run computed diff (evidence, independent of any claim)
    t1 = ws.snapshot()
    run_diff = ws.diff_trees(t0, t1)

    # harness-run checks: the REAL result, regardless of what the model claimed
    check_results = []
    for chk in (checks or []):
        r = sb.run(chk["argv"], ws.repo)
        ok = r["exit_code"] == chk.get("expect_exit", 0)
        env = Envelope("check", ok, ErrorClass.NONE.value if ok else ErrorClass.MODEL_CLAIM_FALSE.value,
                       computed={"name": chk.get("name", chk["argv"][0]), **r})
        L.append(EventType.ENVELOPE, env.to_dict())
        check_results.append({"name": chk.get("name"), "ok": ok, "exit_code": r["exit_code"]})

    summary = {
        "session_id": L.session_id, "finished": finished, "turns": turn_no + 1,
        "edits_landed": edits_landed, "run_diff": run_diff,
        "changed": bool(run_diff.strip()), "checks": check_results,
        "sandbox_mode": sb.mode, "ledger": str(L.path),
    }
    L.append(EventType.SESSION_END, summary)
    from . import bastion                      # export to the security tap (audit the operator)
    summary["bastion_feed"] = bastion.emit(summary, L)
    return summary
