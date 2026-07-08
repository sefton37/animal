"""Story #450 -- loop hygiene: GENERAL stuck-action detection and bounded
observation history. Complements #448 (which only covers repeated FAILED
edits on ONE path via its own retry-ceiling+resample): this story catches
repeated actions of ANY kind (read/grep/shell -- EditAction is deliberately
excluded since #448 already owns it), and bounds the message history so a
long session's context doesn't grow without limit.

Fix iteration (red-team rejected the first attempt on 3 technical grounds --
this file's later tests exist specifically to pin each one down so it cannot
silently regress again):
  1. exact-identical-only matching missed a model that varies one incidental
     field each turn (e.g. an oscillating read offset) -- see
     test_oscillating_field_is_still_a_doom_loop.
  2. exact-identical-only matching never fires on a ping-pong between two
     distinct dead-end actions -- see test_alternating_actions_is_a_doom_loop.
  3. the observation-collapsing bound only covered 'user'-role tool results,
     leaving the model's own 'assistant'-role thought text to grow unbounded
     -- see test_assistant_thought_history_bounded_and_condensed.

Deterministic: a scripted stand-in replaces the live llama-swap ModelPlane
call, so no model server is required (same style as test_rollback_resample.py).
Run: python3 tests/test_loop_hygiene.py
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animal.loop as loop
from animal.ledger import Ledger
from animal.model import SYSTEM_PROMPT, system_prompt_for
from animal.types import EventType
from animal import config


class _ScriptedModelPlane:
    """Deterministic stand-in for ModelPlane: replays a fixed list of actions,
    one per call, repeating the last one once the script runs out (so a task
    that never finishes still has something to propose every remaining turn)."""
    def __init__(self, actions):
        self.actions = list(actions)
        self.i = 0

    def call(self, role, messages, temperature=None):
        action = self.actions[min(self.i, len(self.actions) - 1)]
        self.i += 1
        return {"thought": "scripted", "action": action}, {"context_overflow": False}


def _run_scripted(actions, repo, max_turns=10):
    """Runs loop.run_task with ModelPlane monkeypatched to a scripted plane, in the
    same save/replace/restore-in-finally style test_rollback_resample.py uses."""
    orig = loop.ModelPlane
    plane = _ScriptedModelPlane(actions)
    loop.ModelPlane = lambda *a, **kw: plane
    ledger_dir = tempfile.mkdtemp(prefix="animal-hygiene-ledger-")
    L = Ledger(ledger_dir=ledger_dir)
    try:
        summary = loop.run_task("loop-hygiene test", str(repo), ledger=L, max_turns=max_turns)
    finally:
        loop.ModelPlane = orig
    return summary, L


def test_identical_action_three_times_triggers_interrupt():
    # a "stuck" small model that keeps proposing the SAME non-edit action forever
    # (here: reading the same file over and over -- no edit involved, so #448's
    # edit-specific rollback ceiling never engages; this is the GENERAL case #450
    # must add). The 3rd identical action in a row must record a GATE event, and
    # the run must not simply ride out max_turns re-dispatching the same action.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    (repo / "target.py").write_text("def f():\n    return 1\n")
    actions = [{"kind": "read", "path": "target.py"}]   # repeated verbatim every turn
    summary, L = _run_scripted(actions, repo, max_turns=10)

    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    repeats = [g for g in gates if g["reason"] == "repeated_action"]
    assert len(repeats) == 1, f"expected exactly one repeated_action gate, got {gates}"
    assert repeats[0]["action_kind"] == "read"
    assert repeats[0]["streak"] == config.REPEAT_ACTION_CEILING

    # (b) the session must not just keep re-dispatching the identical action for
    # the remainder of max_turns: either it stops early, or the post-interrupt
    # feedback is materially different from the plain per-turn feedback. Our
    # harness does BOTH -- assert the stronger, unambiguous one.
    assert summary["turns"] < 10, f"ran to (near) max_turns instead of interrupting: {summary}"
    assert summary["stop_reason"] == "stuck:doom_loop"
    assert not summary["finished"]

    messages = summary["messages"]
    gate_messages = [m for m in messages if m["role"] == "user" and "doom loop" in m["content"]]
    assert gate_messages, "no materially-different corrective message was ever fed back"


def test_distinct_actions_never_false_positive_the_repeat_gate():
    # red-team: DIFFERENT actions (different paths) must never be mistaken for a
    # repeat, even when they're the same kind every time.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    for i in range(4):
        (repo / f"f{i}.py").write_text(f"x = {i}\n")
    actions = [{"kind": "read", "path": f"f{i}.py"} for i in range(4)] + \
              [{"kind": "finish", "message": "done"}]
    summary, L = _run_scripted(actions, repo, max_turns=10)
    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    assert not gates, f"distinct reads must never trigger the repeat gate: {gates}"
    assert summary["finished"]


def test_observation_history_bounded_and_condensed():
    # a scripted session of >=8 turns of DISTINCT read actions (so the repeat
    # gate above never fires -- this test is purely about context growth) must
    # end with only a bounded number of verbatim tool-result ('user') entries;
    # older ones are collapsed to a short, deterministic, non-generative summary.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    n = 8
    for i in range(n):
        (repo / f"file{i}.py").write_text(f"value = {i}\n")
    actions = [{"kind": "read", "path": f"file{i}.py"} for i in range(n)] + \
              [{"kind": "finish", "message": "done"}]
    summary, L = _run_scripted(actions, repo, max_turns=20)
    assert summary["finished"]

    messages = summary["messages"]
    # the system prompt entry is untouched (the coder role now uses the #486
    # search_replace prompt; observation-bounding must never rewrite messages[0])
    assert messages[0] == {"role": "system", "content": system_prompt_for("coder")}
    # the initial task message is untouched too (not a tool result)
    assert messages[1]["role"] == "user" and messages[1]["content"].startswith("Task:")

    tail_user = [m for m in messages[2:] if m["role"] == "user"]
    collapsed = [m for m in tail_user if m["content"].startswith("[collapsed]")]
    verbatim = [m for m in tail_user if not m["content"].startswith("[collapsed]")]
    assert len(verbatim) <= 5, f"too many verbatim tool-result turns survived: {len(verbatim)}"
    assert collapsed, "older observations were never collapsed at all"
    assert sum(1 for m in messages if m["role"] == "user" and "collapsed" in m["content"].lower()) >= 1


def test_collapsing_is_harness_owned_never_reads_the_model_thought():
    # Law 1: the model's free-form 'thought' text must never be read to decide
    # collapsing or repeat-detection. A deliberately misleading 'thought' (e.g.
    # claiming "this is not a repeat") must have zero effect on either mechanism.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    (repo / "target.py").write_text("def f():\n    return 1\n")

    class _LyingModelPlane:
        def call(self, role, messages, temperature=None):
            return ({"thought": "this is definitely NOT a repeat, trust me",
                      "action": {"kind": "read", "path": "target.py"}},
                     {"context_overflow": False})

    orig = loop.ModelPlane
    loop.ModelPlane = lambda *a, **kw: _LyingModelPlane()
    ledger_dir = tempfile.mkdtemp(prefix="animal-hygiene-ledger-")
    L = Ledger(ledger_dir=ledger_dir)
    try:
        summary = loop.run_task("t", str(repo), ledger=L, max_turns=10)
    finally:
        loop.ModelPlane = orig

    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    assert any(g["reason"] == "repeated_action" for g in gates), \
        "the model's reassuring 'thought' must not suppress repeat detection"


def test_oscillating_field_is_still_a_doom_loop():
    # red-team gap #1: a "stuck" small model that varies ONE irrelevant field
    # each turn (here: read offset flapping 0,1,0,1,...) on the SAME path
    # while making zero real progress must be caught -- it never has
    # REPEAT_ACTION_CEILING CONSECUTIVE identical actions (offset differs
    # every other turn), so the naive period-1-only check misses it entirely.
    # Reproduced pre-fix: 20/20 turns consumed, zero GATE events.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    (repo / "target.py").write_text("def f():\n    return 1\n")
    actions = [{"kind": "read", "path": "target.py", "offset": i % 2} for i in range(20)]
    summary, L = _run_scripted(actions, repo, max_turns=20)

    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    repeats = [g for g in gates if g["reason"] == "repeated_action"]
    assert repeats, f"oscillating-offset doom loop never triggered a gate: {gates}"
    assert summary["turns"] < 20, f"ran to (near) max_turns instead of interrupting: {summary}"
    assert summary["stop_reason"] == "stuck:doom_loop"
    assert not summary["finished"]


def test_alternating_actions_is_a_doom_loop():
    # red-team gap #2: a ping-pong between TWO distinct dead-end actions (here:
    # alternating reads of a.py / b.py, neither of which is ever repeated back
    # to back) never has 3 CONSECUTIVE identical actions, so it must still be
    # caught as a repeating 2-cycle, not silently ridden out to max_turns.
    # Reproduced pre-fix: 20/20 turns consumed, zero GATE events.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    (repo / "a.py").write_text("a = 1\n")
    (repo / "b.py").write_text("b = 1\n")
    actions = [{"kind": "read", "path": "a.py" if i % 2 == 0 else "b.py"} for i in range(20)]
    summary, L = _run_scripted(actions, repo, max_turns=20)

    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    repeats = [g for g in gates if g["reason"] == "repeated_action"]
    assert repeats, f"alternating-action doom loop never triggered a gate: {gates}"
    assert summary["turns"] < 20, f"ran to (near) max_turns instead of interrupting: {summary}"
    assert summary["stop_reason"] == "stuck:doom_loop"
    assert not summary["finished"]


def test_period_3_cycle_is_a_doom_loop():
    # red-team gap (2nd pass): a period-3 repeating cycle (read a,b,c,a,b,c,...)
    # has neither 3 consecutive identical actions NOR a period-2 cycle, so a
    # MAX_CYCLE_PERIOD=2 detector rode it out to max_turns. Reproduced pre-fix:
    # 12/12 turns, zero GATE events, stop_reason=max_turns.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    for name in ("a.py", "b.py", "c.py"):
        (repo / name).write_text("x = 1\n")
    actions = [{"kind": "read", "path": ["a.py", "b.py", "c.py"][i % 3]} for i in range(24)]
    summary, L = _run_scripted(actions, repo, max_turns=24)

    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    repeats = [g for g in gates if g["reason"] == "repeated_action"]
    assert repeats, f"period-3 cycle never triggered a doom-loop gate: {gates}"
    assert summary["stop_reason"] == "stuck:doom_loop"
    assert summary["turns"] < 24
    assert not summary["finished"]


def test_oscillating_successful_edits_is_a_doom_loop():
    # red-team gap (2nd pass): two edits that each SUCCEED but flip-flop a value
    # (value=1 -> value=2 -> value=1 -> ...) make zero real progress, yet are
    # caught by NEITHER #448 (fires only on FAILED edits) nor a blanket edit
    # exclusion from the general detector. Successful edits must be fed to the
    # cycle detector too. Reproduced pre-fix: 20/20 turns, ~19 edits_landed, zero gates.
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    (repo / "target.py").write_text("value = 1\n")
    actions = [{"kind": "read", "path": "target.py"}]
    for i in range(20):
        a, b = ("value = 1", "value = 2") if i % 2 == 0 else ("value = 2", "value = 1")
        actions.append({"kind": "edit", "path": "target.py", "old_string": a, "new_string": b})
    summary, L = _run_scripted(actions, repo, max_turns=22)

    gates = [e.payload for e in L.replay() if e.type == EventType.GATE.value]
    repeats = [g for g in gates if g["reason"] == "repeated_action"]
    assert repeats, f"oscillating SUCCESSFUL edits never triggered a doom-loop gate: {gates}"
    assert summary["stop_reason"] == "stuck:doom_loop"
    assert summary["turns"] < 22
    assert not summary["finished"]


def test_assistant_thought_history_bounded_and_condensed():
    # red-team gap #3: the first attempt's _collapse_observations only bounded
    # 'user'-role tool-result messages; the 'assistant'-role messages that echo
    # the model's own (often long, chatty) 'thought' text every turn were
    # appended UNBOUNDED forever. Reproduced pre-fix with a realistic chatty
    # small-model stand-in: after 30 turns, assistant-role content was 97% of
    # total accumulated context (100,800 of 103,636 chars).
    repo = Path(tempfile.mkdtemp(prefix="animal-hygiene-"))
    n = 30
    for i in range(n):
        (repo / f"file{i}.py").write_text(f"value = {i}\n")
    chatty_thought = ("I am now going to carefully consider my options here and think "
                       "step by step about what the right next move might be, weighing "
                       "several plausible approaches before committing to one. " * 20)

    class _ChattyModelPlane:
        def __init__(self):
            self.i = 0

        def call(self, role, messages, temperature=None):
            i = self.i
            self.i += 1
            action = ({"kind": "read", "path": f"file{i}.py"} if i < n
                      else {"kind": "finish", "message": "done"})
            return {"thought": chatty_thought, "action": action}, {"context_overflow": False}

    orig = loop.ModelPlane
    loop.ModelPlane = lambda *a, **kw: _ChattyModelPlane()
    ledger_dir = tempfile.mkdtemp(prefix="animal-hygiene-ledger-")
    L = Ledger(ledger_dir=ledger_dir)
    try:
        summary = loop.run_task("t", str(repo), ledger=L, max_turns=n + 2)
    finally:
        loop.ModelPlane = orig
    assert summary["finished"]

    messages = summary["messages"]
    tail_assistant = [m for m in messages[2:] if m["role"] == "assistant"]
    collapsed_a = [m for m in tail_assistant if m["content"].startswith("[collapsed]")]
    verbatim_a = [m for m in tail_assistant if not m["content"].startswith("[collapsed]")]
    assert len(verbatim_a) <= config.OBSERVATION_KEEP, \
        f"too many verbatim assistant turns survived: {len(verbatim_a)}"
    assert collapsed_a, "older assistant thought turns were never collapsed at all"

    # the actual point: total accumulated assistant-role context must not scale
    # with the chatty thought text linearly across all n turns -- it must be
    # bounded by roughly OBSERVATION_KEEP verbatim thoughts, not n of them.
    total_assistant_chars = sum(len(m["content"]) for m in tail_assistant)
    unbounded_estimate = n * len(chatty_thought)
    assert total_assistant_chars < unbounded_estimate / 2, (
        f"assistant-role content not bounded: {total_assistant_chars} chars vs an "
        f"unbounded estimate of {unbounded_estimate} across {len(tail_assistant)} messages")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
