"""Story #462 -- the bounded conversational DISCOVERY loop (Act 1 / Stage C).

The discovery turn is the SAME primitive as the execution turn
(docs/CONSTRUCTION.md Part II, "anatomy of a discovery turn"): one move per
turn, hard-bounded, every move ledger-recorded, exit on a computed condition.
The two loops differ only in WHO supplies the observation -- here the human is
the ground truth of intent, exactly as the computed envelope is the ground
truth of execution. The harness NEVER fabricates the act of answering: if the
maker is absent (EOF on the interactive channel, a dead pipe, a headless
cron), the session HALTS with a typed maker_absent event -- it does not tell
the model "the maker answers" and let it invent intent (red-team blocker: a
headless run used to burn the full turn budget conversing with nobody and
return model-invented stories as if a human had shaped them).

Capability by construction, not by discipline: the discovery vocabulary is
ask / propose_story / finish ONLY. There is no edit and no shell action here
-- not disabled, ABSENT -- and the constrained-decoding grammar the role is
held to (model.DISCOVERY_TURN_SCHEMA, selected by ROLES["discovery"]'s
turn_schema) closes the vocabulary at the DECODER too. A conversation cannot
touch the tree; a hostile emission of {"kind":"edit"} lands in the invalid
branch and executes nothing (adversarially verified).

Every exit path is honest and ledger-paired: SESSION_END always fires (even
on Ctrl-C) and carries a `status` --
  finished | max_turns | maker_absent | channel_error | model_error |
  context_overflow | aborted
-- so a caller (the CLI does) can distinguish "the conversation genuinely
yielded nothing" from "the session died before it could" (red-team major: an
offline model server used to exit 0 with {"stories": []}, masking total
failure as an empty outcome).

Deliberately NOT here (later M4 stories): clustering raw stories into epics
and persisting them (#463), drafting a Gate-0-valid Spec from a raw story
(#464), and the ambiguity-resolution pass (#465). run_discovery returns RAW
stories -- title / narrative / notes -- shaped enough to hand onward, nothing
more.
"""
from __future__ import annotations
import json
from . import config
from .ledger import Ledger
from .model import ModelPlane, ModelError
from .types import EventType

# The event-type string every dialogue move lands under (model question, maker
# answer, proposed story, finish, and every fault) -- discovery is auditable
# like every lane: `ledger.events_of(DISCOVERY_EVENT)` replays the whole
# conversation.
DISCOVERY_EVENT = "discovery_turn"

DISCOVERY_SYSTEM_PROMPT = """You are a DISCOVERY agent helping a maker turn a pain point or idea into buildable user stories. Each turn, respond with EXACTLY ONE JSON object:
{"thought": "<brief reasoning>", "action": { ... }}

action.kind is one of:
- ask            {"kind":"ask","question":"<ONE targeted clarifying question>"}
- propose_story  {"kind":"propose_story","title":"<short name>","narrative":"As a maker, I want <X> so that <Y>","notes":"<input -> expected output, constraints, anything load-bearing>"}
- finish         {"kind":"finish","message":"<summary of the stories proposed>"}

You are CONVERSING, not interrogating. A story is buildable only when three
things are concrete: the PAIN (what is wrong or wanted), the INPUT (data,
trigger, starting state), and the EXPECTED OUTPUT (what good looks like --
sharp enough to become a test). Ask when a slot is genuinely under-determined;
propose when you can fill all three; never guess what the maker means. A
propose_story requires a non-empty title AND narrative. Propose each distinct
story separately. Finish when the topic is decomposed."""


class MakerAbsent(Exception):
    """Raised by a channel when there is no maker to answer (EOF, dead pipe).
    The harness halts the session on this -- it never fabricates an answer."""


def _tui_channel(question: str) -> str:
    """Interactive default: the maker answers at the terminal. EOF means the
    maker is NOT THERE (piped stdin, headless invocation, Ctrl-D) -- that is
    maker-absence, not an empty answer, and the session must halt rather than
    pretend somebody replied."""
    try:
        return input(f"\n[discovery] {question}\n> ")
    except EOFError:
        raise MakerAbsent("EOF on the interactive channel: no maker present")


def run_discovery(topic: str, channel=None, ledger: Ledger | None = None,
                  max_turns: int | None = None, role: str = "discovery") -> list[dict]:
    """Drive the bounded discovery conversation on `topic`. Returns the raw
    stories the model proposed and the maker saw: list of
    {title, narrative, notes} dicts, in proposal order.

    channel: callable(question: str) -> str supplying the MAKER's answer to
    each `ask` (defaults to the interactive terminal; raise MakerAbsent to
    signal nobody is there). ledger: share a lane's ledger or omit for a
    fresh one -- SESSION_END always fires, with a `status` naming how the
    session ended. max_turns: hard bound; None means config.MAX_TURNS, and an
    explicit 0 genuinely means zero turns (not the default)."""
    L = ledger or Ledger()
    mp = ModelPlane()
    ch = channel or _tui_channel
    limit = config.MAX_TURNS if max_turns is None else max_turns
    stories: list[dict] = []
    status = "max_turns"       # what SESSION_END reports unless an exit says otherwise
    L.append(EventType.SESSION_START, {"lane": "discovery", "topic": topic, "max_turns": limit})
    messages = [{"role": "system", "content": DISCOVERY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Topic from the maker:\n{topic}\n\nBegin. Emit one action."}]

    try:
        for turn in range(limit):
            try:
                out, meta = mp.call(role, messages)
            except ModelError as e:
                L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "model_error", "error": str(e)})
                status = "model_error"
                break
            # context integrity is a hard fault here exactly as in the kernel
            # loop: a truncated window means the model no longer sees the real
            # conversation, so nothing it proposes is grounded in it
            if (meta or {}).get("context_overflow"):
                L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "context_overflow"})
                status = "context_overflow"
                break
            action = out.get("action") if isinstance(out, dict) else None
            if not isinstance(action, dict):
                action = {}
            kind = action.get("kind")
            messages.append({"role": "assistant", "content": json.dumps(out)})

            if kind == "ask":
                question = str(action.get("question", "")).strip()
                try:
                    answer = str(ch(question))
                except MakerAbsent as e:
                    # the harness never fabricates the act of answering: no
                    # maker means the session ENDS, typed and visible
                    L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "maker_absent",
                                               "question": question, "detail": str(e)})
                    status = "maker_absent"
                    break
                except KeyboardInterrupt:
                    raise                      # handled by the outer aborted path
                except Exception as e:
                    L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "channel_error",
                                               "question": question,
                                               "error": f"{type(e).__name__}: {e}"})
                    status = "channel_error"
                    break
                # the maker's words are recorded VERBATIM -- the human is this
                # lane's ground truth, and the ledger must let anyone replay
                # exactly what was asked and exactly what was answered
                L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "ask",
                                           "question": question, "answer": answer})
                messages.append({"role": "user", "content": f"The maker answers: {answer}"})

            elif kind == "propose_story":
                story = {"title": str(action.get("title", "")).strip(),
                         "narrative": str(action.get("narrative", "")).strip(),
                         "notes": str(action.get("notes", "")).strip()}
                if not story["title"] or not story["narrative"]:
                    # grammar-legal but vacuous: an empty story is no story --
                    # recorded, surfaced back, never counted or handed onward
                    L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "invalid",
                                               "action": action,
                                               "why": "propose_story requires a non-empty title and narrative"})
                    messages.append({"role": "user", "content":
                                     "Rejected: propose_story requires a non-empty title AND narrative."})
                    continue
                stories.append(story)
                L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "propose_story", **story})
                messages.append({"role": "user", "content":
                                 f"Story {len(stories)} recorded: {story['title']!r}. "
                                 "Propose another, ask, or finish."})

            elif kind == "finish":
                L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "finish",
                                           "message": str(action.get("message", "")),
                                           "stories": len(stories)})
                status = "finished"
                break

            else:
                # unknown/malformed move: recorded, surfaced back, still bounded
                L.append(DISCOVERY_EVENT, {"turn": turn, "kind": "invalid", "action": action})
                messages.append({"role": "user", "content":
                                 "Invalid action. Use exactly one of ask / propose_story / finish."})
    except KeyboardInterrupt:
        # the maker chose to stop mid-conversation: the stories already
        # proposed are real maker-shaped material -- keep them, mark the end
        status = "aborted"
    finally:
        # SESSION_END fires on EVERY exit path -- pairing is an invariant, and
        # the status makes "nothing came back" distinguishable from "the
        # session died before anything could"
        L.append(EventType.SESSION_END, {"lane": "discovery", "status": status,
                                         "stories": len(stories),
                                         "titles": [s["title"] for s in stories]})
    return stories
