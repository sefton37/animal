"""The single agentic loop. Model proposes ONE typed action per turn; the kernel
executes it, COMPUTES an envelope, records both to the ledger, and feeds the
computed result (never the model's claim) back into context. Terminates on a
finish action or a hard bound.

The check runner runs any task checks itself and records the REAL exit codes —
so a model that *claims* a check passed is contradicted by the harness's computed
result. That plus the workspace's non-persistence detection are the two seeded
attacks the Phase 1 exit requires the kernel to catch.

Rollback-and-resample (Story #448): agents succeed fast and fail slow — a coder
stuck compounding the SAME failing edit on one target burns its whole turn
budget on a dead end instead of stepping back. The loop counts consecutive
failed edit envelopes PER PATH; at config.MAX_EDIT_RETRIES it reverts ONLY the
failing path (Workspace.restore_path) to the checkpoint taken right before
that failure streak began, records an EventType.GATE ledger event, and lets
the session keep consuming turns — a fresh resample, not a terminated run.
Path-scoped, not whole-tree: a whole-tree revert would silently destroy any
OTHER file's edit that successfully landed in the interim, with no ledger
trace of the loss (red-team finding on this story's first attempt).

Loop hygiene (Story #450): #448 above only covers repeated FAILED edits on ONE
path. Two general gaps remain, both mandatory for small models per
ARCHITECTURE.md's 'doom-loop detection (3 identical actions -> interrupt)' and
CONSTRUCTION.md's 'detect pathology' step:
  - Repeated actions of ANY kind (read/grep/shell -- EditAction is deliberately
    excluded here since #448 already owns it) get a GATE event on the 3rd
    repeat plus a corrective message; a 4th straight repeat past that
    interrupt is a genuine doom loop and stops the run (stuck:doom_loop),
    rather than silently burning the rest of the turn budget on one dead end.
    "Repeated" is not just byte-identical: a period-1 CONSECUTIVE-identical
    check alone misses (a) a model that varies one incidental field turn-to-
    turn while making zero real progress (e.g. an oscillating read offset:
    0,1,0,1,...) and (b) a ping-pong between two distinct dead-end actions
    (e.g. read(A), read(B), read(A), read(B), ...) -- neither has N
    consecutive identical actions, so the detector also checks for a period-2
    repeating cycle sustained the same N times (red-team finding on this
    story's first attempt; see `_is_repeated`).
  - Bounded, condensed message history: once more than config.OBSERVATION_KEEP
    verbatim turns of a role have accumulated, the older ones of THAT role are
    collapsed to a short DETERMINISTIC templated summary (never a model call)
    so a long session doesn't drown its own context window. This bounds BOTH
    the 'user'-role tool-result turns AND the 'assistant'-role turns that echo
    the model's own free-form 'thought' text every turn -- the first attempt
    at this story bounded only the former, leaving a chatty small model's own
    thought text to grow unbounded forever (red-team finding: 97% of
    accumulated context after 30 turns in a realistic repro).
Both are harness-owned: neither reads the model's free-form 'thought' text to
decide anything (Law 1 -- the model never gets a vote on whether it 'is'
repeating or on what gets collapsed).

Repo map (Story #449): an opt-in `include_repo_map` flag on run_task appends
animal.repomap.build_repo_map's compact file/symbol listing to the system
prompt, so a coder can REQUEST the right file directly instead of groping by
trial-and-error grep/read -- see animal/repomap.py's own docstring for the
tree-sitter-vs-stdlib decision. run_task's OWN default stays OFF (so a caller
that inspects prompt content byte-for-byte, e.g. this suite's rollback/
loop-hygiene tests, sees no change) -- but that default is not the last word:
a first attempt at this story left every PRODUCTION call site -- a maker's actual
invocation (animal/cli.py's `run`
command, animal/worklane.py's gated build step, animal/candidates.py's
patch-farm) at the untouched default, so no maker's actual invocation ever saw
the map (red-team rejection). The fix wires each real call site to pass
include_repo_map=True by default: worklane.run_work and
candidates.sample_candidates both default their own `include_repo_map` kwarg
to True and forward it here; cli.py's `run` subcommand adds a `--no-repo-map`
opt-out flag (default: included). Only run_task's bare signature default
remains False, purely to keep this module directly testable without the flag.
"""
from __future__ import annotations
import json
from .ledger import Ledger
from .workspace import Workspace
from .model import ModelPlane, ModelError, SYSTEM_PROMPT, system_prompt_for
from .repomap import build_repo_map
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
        # a ShellAction writes to the workspace directly (no edit() call) -- the
        # lint gate belongs to the whole edit pipeline, so post-hoc-lint any
        # path the command touched and block a syntax-breaking result the same
        # way edit() blocks one, before it's fed back to the model as fact.
        pre = ws.snapshot()
        r = sb.run(action.argv, ws.repo)
        post = ws.snapshot()
        changed = ws.changed_paths(pre, post)
        lint_msg = ws.lint_gate_paths(pre, changed) if changed else None
        if lint_msg is not None:
            return Envelope("shell", False, ErrorClass.LINT_REJECTED.value,
                            computed=r, note=f"lint rejected before write: {lint_msg}")
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


def _canon(action) -> str:
    """Canonical string key for an action's own typed to_dict() fields -- the
    ONLY thing repeat/cycle comparisons look at. JSON (not a tuple/hash of the
    dict) because ShellAction.argv is a list, which isn't hashable directly.
    Never touches the model's free-form 'thought' text (Law 1)."""
    return json.dumps(action.to_dict(), sort_keys=True)


def _is_repeated(action, history: list, n: int = 3, max_period: int = 2) -> bool:
    """True once the trailing window of canonical actions (history + [action])
    shows a repeating cycle of SOME period p in 1..max_period, sustained for at
    least n full repeats of that cycle (Story #450's general doom-loop
    detector -- the ARCHITECTURE.md 'N identical actions -> interrupt' line,
    generalized past both #448's edit-only case AND the naive 'n CONSECUTIVE
    identical actions' reading of that line).

    p=1 is n consecutive identical actions (the narrow reading: two reads of
    the same path/offset, two greps of the same pattern, two shells with the
    same argv all count as the same repeated action). p=2 additionally catches
    (a) a model that varies ONE incidental field turn-to-turn while making
    zero real progress (e.g. an oscillating read offset: 0,1,0,1,...) and (b)
    a ping-pong between TWO distinct dead-end actions (e.g. read(A), read(B),
    read(A), read(B), ...) -- neither has n CONSECUTIVE identical actions
    (so a period-1-only check misses both -- red-team finding on this story's
    first attempt), but each IS, canonically, a 2-element cycle repeating n
    times.

    Compares each Action's own typed to_dict() fields ONLY, via a JSON
    canonical key -- never the model's free-form 'thought' text (Law 1: the
    model doesn't get a vote on whether it 'is' repeating). Different kinds,
    or genuinely different fields (e.g. a monotonically advancing read offset,
    or reads of 4 distinct paths), never match."""
    window_source = history + [action]
    for p in range(1, max_period + 1):
        need = n * p
        if len(window_source) < need:
            continue
        window = [_canon(a) for a in window_source[-need:]]
        if all(window[i] == window[i - p] for i in range(p, need)):
            return True
    return False


def _collapse_observations(messages: list[dict], keep: int = 5) -> list[dict]:
    """Bounded, condensed message history (Story #450): messages[:2] (the
    system prompt and the initial task message) are never touched. Of every
    OTHER message -- both the 'user'-role tool-result turns AND the
    'assistant'-role turns that echo the model's own free-form thought+action
    every turn -- only the most recent `keep` of EACH role stay verbatim;
    older ones of that role have their content REPLACED with a short
    deterministic templated summary -- derived from the message's own first
    line, never a model call, so it is fully reproducible -- so a long
    session's context doesn't grow without bound in EITHER direction and
    drown a small model's own window.

    Bounding only the 'user' slice (the first attempt at this story) leaves a
    chatty small model's own per-turn 'thought' text, appended unbounded as
    'assistant' messages, to dominate accumulated context over a long run --
    exactly the failure this story's user story names ('drown its own context
    window'). Both roles are bounded independently here so neither can."""
    head, tail = messages[:2], list(messages[2:])
    for role in ("user", "assistant"):
        idxs = [i for i, m in enumerate(tail) if m["role"] == role]
        if len(idxs) <= keep:
            continue
        for i in idxs[:-keep]:
            content = tail[i]["content"]
            if content.startswith("[collapsed]"):
                continue                                   # already condensed -- idempotent
            lines = content.splitlines()
            gist = lines[0][:80] if lines else ""
            tail[i] = {"role": role, "content": f"[collapsed] {gist}"}
    return head + tail


def run_task(task: str, repo: str, role: str = "coder", checks: list[dict] | None = None,
             ledger_dir=None, max_turns: int | None = None, ledger: Ledger | None = None,
             temperature: float | None = None, include_repo_map: bool = False) -> dict:
    L = ledger or Ledger(ledger_dir=ledger_dir)   # work lane shares one ledger across the chain
    ws = Workspace(repo, L.session_id)
    mp = ModelPlane()
    sb = Sandbox()
    max_turns = max_turns or config.MAX_TURNS

    L.append(EventType.SESSION_START,
             {"task": task, "repo": str(ws.repo), "role": role, "sandbox_mode": sb.mode,
              "net_off": sb.mode == "full"})
    t0 = ws.snapshot()
    # Repo map (Story #449): opt-in, default OFF -- appended to the system
    # prompt so it's part of the FIRST prompt the model sees, letting it
    # request the right file directly instead of groping blind.
    system_prompt = system_prompt_for(role)
    if include_repo_map:
        system_prompt = system_prompt + "\n\n" + build_repo_map(str(ws.repo))
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Task: {task}\n\nBegin. Emit one action."}]

    edits_landed, finished = 0, False
    edit_fail_counts: dict[str, int] = {}       # per-path consecutive-failure streaks
    edit_fail_checkpoints: dict[str, str] = {}  # path -> tree hash before its streak began
    rollback_cycles: dict[str, int] = {}        # per-path COUNT of full rollback-and-resample cycles
    cur_temp = temperature                       # bumped on each rollback so a resample is genuinely different
    stuck_path = None                            # set when a path exhausts its rollback-cycle ceiling
    action_history: list = []                    # last dispatched actions, ANY kind (Story #450)
    repeat_gate_fired = False                    # the soft doom-loop gate already fired this streak
    stuck_repeat = False                         # set when the model repeats again past the interrupt
    for turn_no in range(max_turns):
        try:
            turn, meta = mp.call(role, messages, temperature=cur_temp)
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
        # snapshot BEFORE dispatch so a would-be first failure of a new streak has
        # a checkpoint from the moment before it, not after (Story #448)
        pre_edit_snapshot = ws.snapshot() if isinstance(action, EditAction) else None
        env = _dispatch(action, ws, sb)
        L.append(EventType.ENVELOPE, env.to_dict())
        rolled_back = False
        if env.action_kind == "edit":
            path = action.path
            if env.ok:
                edits_landed += 1
                edit_fail_counts.pop(path, None)
                edit_fail_checkpoints.pop(path, None)
            else:
                # rollback-and-resample: a coder that keeps failing the SAME edit
                # is compounding a dead end, not making progress. Count consecutive
                # failures per path; at the retry cap, revert to the checkpoint from
                # before this streak and let the session keep going (a fresh resample)
                # instead of burning its whole turn budget on the same wrong anchor.
                if edit_fail_counts.get(path, 0) == 0:
                    edit_fail_checkpoints[path] = pre_edit_snapshot
                edit_fail_counts[path] = edit_fail_counts.get(path, 0) + 1
                if edit_fail_counts[path] >= config.MAX_EDIT_RETRIES:
                    ws.restore_path(edit_fail_checkpoints[path], path)
                    rollback_cycles[path] = rollback_cycles.get(path, 0) + 1
                    L.append(EventType.GATE, {
                        "path": path, "reason": "max_edit_retries_exceeded",
                        "attempts": edit_fail_counts[path], "rollback_cycle": rollback_cycles[path]})
                    edit_fail_counts[path] = 0
                    edit_fail_checkpoints.pop(path, None)
                    rolled_back = True
                    # a REAL resample: raise the temperature so the next attempt is a
                    # genuinely different sample, not a re-run of the same greedy decode.
                    base = cur_temp if cur_temp is not None else config.ROLES[role]["temperature"]
                    cur_temp = min(round(base + 0.25, 2), 1.2)
                    # CEILING: after MAX_EDIT_RETRIES full rollback cycles on ONE path the
                    # coder is not escaping the dead end -- stop (stuck), rather than burn
                    # the rest of the turn budget looping (the "rather than..." half of #448).
                    if rollback_cycles[path] >= config.MAX_EDIT_RETRIES:
                        stuck_path = path
        # general doom-loop detection (Story #450): repeated actions of ANY kind
        # (exact repeats OR a short repeating cycle -- see _is_repeated). A FAILED
        # EditAction is excluded because #448 already owns repeated failed edits on
        # one path (ceiling+resample); but a SUCCEEDED edit that oscillates
        # (A->B->A->B, each landing) is caught by neither #448 nor a blanket edit
        # exclusion, so successful edits ARE fed to the general cycle detector too
        # (red-team finding on this story).
        is_repeat = ((not isinstance(action, EditAction) or env.ok) and
                     _is_repeated(action, action_history, n=config.REPEAT_ACTION_CEILING,
                                  max_period=config.MAX_CYCLE_PERIOD))
        action_history.append(action)
        hist_cap = config.REPEAT_ACTION_CEILING * config.MAX_CYCLE_PERIOD  # enough trailing
                                                                            # history to recognize
                                                                            # a period-MAX_CYCLE_PERIOD cycle
        if len(action_history) > hist_cap:
            action_history.pop(0)
        messages.append({"role": "user", "content": _feedback(env)})
        if rolled_back:
            messages.append({"role": "user", "content":
                f"[gate] {config.MAX_EDIT_RETRIES} consecutive failed edits on {path} -- "
                f"harness reverted the workspace to the last good checkpoint. "
                f"Re-read {path} first (its read-state was cleared), then resample: a "
                f"different old_string or approach."})
        if is_repeat:
            if not repeat_gate_fired:
                L.append(EventType.GATE, {"reason": "repeated_action", "action_kind": action.kind,
                                          "streak": config.REPEAT_ACTION_CEILING})
                repeat_gate_fired = True
                messages.append({"role": "user", "content":
                    f"[gate] the harness detected {config.REPEAT_ACTION_CEILING} identical "
                    f"{action.kind} actions in a row -- this is a doom loop, not progress. "
                    f"Try a genuinely different approach, or finish if the task is actually done."})
            else:
                stuck_repeat = True          # repeated again past the interrupt -- a real doom loop
        else:
            repeat_gate_fired = False
        # bounded, condensed observation history (Story #450) -- run every turn,
        # including the one that's about to break the loop, so the FINAL messages
        # list (what a caller inspects) always reflects the bound, not just the
        # state as of the second-to-last turn.
        messages = _collapse_observations(messages, keep=config.OBSERVATION_KEEP)
        if stuck_path is not None:
            L.append(EventType.GATE, {"path": stuck_path, "reason": "stuck_rollback_ceiling",
                                      "rollback_cycles": rollback_cycles[stuck_path]})
            break
        if stuck_repeat:
            L.append(EventType.GATE, {"reason": "doom_loop_ceiling", "action_kind": action.kind})
            break
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

    stop_reason = ("stuck:" + stuck_path if stuck_path else
                   "stuck:doom_loop" if stuck_repeat else
                   "finished" if finished else "max_turns")
    summary = {
        "session_id": L.session_id, "finished": finished, "turns": turn_no + 1,
        "edits_landed": edits_landed, "run_diff": run_diff, "stop_reason": stop_reason,
        "changed": bool(run_diff.strip()), "checks": check_results,
        "sandbox_mode": sb.mode, "ledger": str(L.path),
    }
    L.append(EventType.SESSION_END, summary)
    from . import bastion                      # export to the security tap (audit the operator)
    summary["bastion_feed"] = bastion.emit(summary, L)
    summary["messages"] = messages              # in-memory only (not ledger-persisted): lets a
                                                 # caller/test inspect the bounded/condensed history
    return summary
