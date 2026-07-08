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

Story #464 lives here too: draft_spec bridges Act 1 to Act 2 -- a raw story
dict becomes a Gate-0-valid Spec by COMPOSING the existing #457 product-owner
machinery (author_spec: schema-constrained model call + structural round-trip
+ per-check authoring validation, with its own concrete-reason retries) with
a draft-time GROUNDING loop: a draft whose references don't resolve is
re-prompted with the exact misses, bounded, instead of sailing on to fail at
run_work's Gate 0a later. No gate logic is duplicated -- ground() and
validate_spec() are the same functions the work lane runs. NAMED DEVIATION
from the AC's letter (authored pre-M3): the model channel in this machinery
is product_owner._chat (JSON-schema-constrained spec authoring), not
ModelPlane.call's turn protocol -- the substance (architect-seat model,
constrained draft object, Spec.from_dict validation) is identical.

Story #465 lives here too: refine_scope surfaces scope AMBIGUITY before a
story is finalized -- it reuses panel.py's interpretation-enumeration (the
Phase-3 shared-prior machinery; never a second enumeration prompt/schema) to
list ambiguous terms/boundaries/units in the spec, puts each ONE to the
maker over the channel, and folds the maker's LITERAL answer into the spec
as an explicit resolved-reading bullet (intent, or out_of_scope when the
maker excludes it) -- never silently dropped, never paraphrased. The amended
spec is re-validated with the same dod.validate_spec the work lane runs.
NAMED DEVIATION from the AC letter: re-validation requires the repo, which
the AC's two-arg signature omitted -- repo is a required third parameter.
"""
from __future__ import annotations
import json
from . import config
from .ledger import Ledger
from .model import ModelPlane, ModelError
from .types import EventType
from .spec import Spec, SpecState
from .grounding import ground
from .dod import validate_spec
from .sandbox import Sandbox
from .panel import enumerate_case

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


def _story_text(raw_story: dict) -> str:
    """Render a #462 raw story (title/narrative/notes) into the plain-language
    user story author_spec expects. A story with no NARRATIVE is not
    draftable (audit F6: title-only used to render as 'title: ' and burn a
    real model call) -- returns "" so draft_spec can refuse it."""
    title = (raw_story.get("title") or "").strip()
    narrative = (raw_story.get("narrative") or "").strip()
    notes = (raw_story.get("notes") or "").strip()
    if not narrative:
        return ""
    parts = [f"{title}: {narrative}" if title else narrative]
    if notes:
        parts.append(f"notes: {notes}")
    return "\n\n".join(parts)


def draft_spec(raw_story: dict, repo: str, *, channel=None, max_retries: int = 3,
               url: str | None = None, timeout: int = 600) -> Spec:
    """Story #464: raw story dict -> a Spec that is Gate-0-valid AGAINST THE
    REPO at draft time. Composes, never duplicates:

      author_spec (#457)  -- the schema-constrained architect-seat draft, with
                             its own structural + per-check validation retries
      ground (Gate 0a)    -- every referenced file/symbol must resolve
      validate_spec (0b)  -- the same authoring validation run_work runs

    A draft that grounds badly is re-prompted with the CONCRETE misses,
    bounded to max_retries outer attempts; the residual failure surfaces as
    ProductOwnerError (author_spec's own error type), never an infinite loop
    and never a silently-ungrounded spec handed onward. Worst-case model
    calls = max_retries x author_spec's own inner attempts (3 x 3 = 9 by
    default -- audit F2: hard-bounded, but name the multiplication; a live
    architect-seat call can take minutes). Rejection feedback ACCUMULATES
    across outer attempts (audit F3: rebuilding it each time hid earlier
    misses, inviting fix-B-reintroduce-A oscillation the model could not
    see). channel is keyword-only and reserved for a future maker-in-the-loop
    refinement pass (#465); unused here."""
    from .product_owner import author_spec, ProductOwnerError
    sb = Sandbox()
    base = _story_text(raw_story)
    if not base:
        raise ValueError("raw_story has no narrative to draft from")
    feedback = ""
    last_reason = "no attempt made"
    for _ in range(max_retries):
        spec = author_spec(base + feedback, repo, url=url, timeout=timeout)
        g = ground(spec, repo)
        v = validate_spec(spec, sb, repo)
        if g["ok"] and v["ok"]:
            Spec.from_dict(spec.to_dict())     # round-trip invariant, cheap final proof
            return spec
        reasons = []
        if not g["ok"]:
            reasons.append(f"unresolved references (files that do not exist in the repo): {g['misses']}")
        if not v["ok"]:
            bad = [c for c in v["checks"] if not c["ok"]] or ["no DoD checks emitted"]
            reasons.append(f"authoring validation failed: {bad}")
        last_reason = "; ".join(reasons)
        feedback += ("\n\nA PRIOR DRAFT WAS REJECTED at Gate 0: " + last_reason +
                     ". Every file your DoD references must already exist in the repo "
                     "(use python3 -c behavior checks against real modules, or set "
                     "expected_new true on a check naming a file the WORK ITSELF will create).")
    raise ProductOwnerError(
        f"draft_spec: no Gate-0-valid spec for {base[:80]!r} in {max_retries} attempts; "
        f"last failure: {last_reason}")


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


def refine_scope(spec: Spec, channel, repo: str, *, ledger: Ledger | None = None,
                 url: str | None = None, max_questions: int = 12) -> Spec:
    """Story #465: surface and resolve scope ambiguity BEFORE a story is
    finalized. panel.enumerate_case (Phase 3's interpretation-enumeration --
    reused, not redefined; strict mode, so a dead model plane RAISES instead
    of masquerading as 'no ambiguities' -- audit F1) lists every ambiguous
    term/boundary/unit in the spec's user story; each is put to the MAKER
    over the channel, and the maker's answer is folded in as an explicit
    resolved-reading bullet: spec.intent gets 'resolved reading: <term> =
    <answer>', or spec.out_of_scope gets the bullet when the answer begins
    with 'out of scope' (the routing target is ledger-recorded -- audit F2).
    Verbatim means strip()-verbatim: outer whitespace trimmed, inner text
    untouched. An EMPTY answer resolves nothing and is recorded as skipped,
    never folded as a vacuous bullet; a termless enumeration item is likewise
    recorded as skipped, never silently dropped (audit F5/F8). Questions are
    capped at max_questions with the truncation recorded (audit F6).

    The amended spec is a NEW Spec (from_dict round-trip) re-checked with the
    SAME Gate-0 pair draft_spec runs: ground() -- maker prose can name an
    existing-but-not-a-file token that would brick Gate 0a one gate later
    (audit F3) -- and dod.validate_spec; either failure raises ValueError
    naming the problem, before the maker moves on. If nothing was folded the
    ORIGINAL spec object is returned. MakerAbsent propagates (no maker, no
    refinement); other channel exceptions propagate raw -- this is a library
    call, not a session loop."""
    try:
        ambiguities = enumerate_case_default(spec, url)
    except Exception as e:
        raise RuntimeError(f"ambiguity enumeration failed (model plane unreachable?): "
                           f"{type(e).__name__}: {e}") from e
    if ledger is not None:
        ledger.append(DISCOVERY_EVENT, {"kind": "enumerate", "count": len(ambiguities)})
    if not ambiguities:
        return spec
    d = spec.to_dict()
    intent = list(d.get("intent") or [])
    out_of_scope = list(d.get("out_of_scope") or [])
    folded = 0
    for n, amb in enumerate(ambiguities):
        if n >= max_questions:
            if ledger is not None:
                ledger.append(DISCOVERY_EVENT, {"kind": "refine_truncated",
                                                "asked": max_questions,
                                                "dropped": len(ambiguities) - max_questions})
            break
        amb = amb if isinstance(amb, dict) else {}
        term = str(amb.get("term") or "").strip()
        assumed = str(amb.get("assumed_reading") or "").strip()
        if not term:
            if ledger is not None:
                ledger.append(DISCOVERY_EVENT, {"kind": "refine_skipped",
                                                "why": "enumeration item has no term", "item": amb})
            continue
        question = (f"Ambiguity in scope: {term!r}"
                    + (f" (the spec currently assumes: {assumed})" if assumed else "")
                    + " -- which reading do you want?")
        raw_answer = channel(question)                 # MakerAbsent propagates
        answer = "" if raw_answer is None else str(raw_answer).strip()
        if not answer:
            if ledger is not None:
                ledger.append(DISCOVERY_EVENT, {"kind": "refine_skipped",
                                                "why": "empty answer resolves nothing",
                                                "term": term, "question": question})
            continue
        bullet = f"resolved reading: {term} = {answer}"
        routed_to = "out_of_scope" if answer.lower().startswith("out of scope") else "intent"
        (out_of_scope if routed_to == "out_of_scope" else intent).append(bullet)
        folded += 1
        if ledger is not None:
            ledger.append(DISCOVERY_EVENT, {"kind": "refine", "term": term,
                                            "question": question, "answer": answer,
                                            "routed_to": routed_to})
    if not folded:
        return spec                                    # nothing changed, nothing rebuilt
    d["intent"], d["out_of_scope"] = intent, out_of_scope
    refined = Spec.from_dict(d)                        # structural validation, new object
    g = ground(refined, repo)                          # Gate 0a NOW, not one gate later
    if not g["ok"]:
        raise ValueError(f"refined spec no longer grounds: unresolved refs {g['misses']} "
                         "(a resolved-reading bullet names something that is not a real file)")
    v = validate_spec(refined, Sandbox(), repo)        # the SAME Gate-0b the work lane runs
    if not v["ok"]:
        bad = [c for c in v["checks"] if not c["ok"]]
        raise ValueError(f"refined spec fails DoD authoring validation: {bad}")
    return refined


def enumerate_case_default(spec: Spec, url: str | None = None) -> list[dict]:
    """panel.enumerate_case with its measured seat default (qwen -- gpt-oss's
    reasoning channel returns empty content on the nested-enumeration schema;
    see panel.measure_shared_prior) in STRICT mode: enumeration failure
    raises, it never masquerades as 'no ambiguities' (audit F1). Split out so
    tests can monkeypatch the enumeration without touching panel internals."""
    from . import panel as _panel
    seat = next((x for x in _panel.JUDGE_SEATS if x["name"] == "qwen"), _panel.JUDGE_SEATS[-1])
    return enumerate_case(seat, {"user_story": spec.user_story}, url, strict=True)


def run_discovery_to_backlog(topic: str, repo: str, *, channel=None, store=None,
                             ledger: Ledger | None = None, max_turns: int | None = None,
                             url: str | None = None) -> dict:
    """Story #466 -- the M4 end-to-end: ONE open-ended sentence becomes a real
    epic with grounded specs. Pure composition of this milestone's pieces:

      run_discovery (#462)      elicit raw stories, maker-in-the-loop
      cluster_into_epics (#463) group them (deterministic fallback)
      ingest_epics (#463)       session-atomic projection into the store
      draft_spec (#464)         each story -> a Gate-0-valid Spec
      refine_scope (#465)       ambiguities put to the maker, folded verbatim
      ProductStore.attach_spec  the spec persisted WITH its story (#453)

    Every persisted spec is left at state 'grounded' (draft_spec grounded and
    validated it) or 'draft' (refinement could not run -- maker absent) --
    NEVER approved or beyond: approval remains the existing human channel in
    worklane.run_work, untouched by this milestone. Per-story failures are
    recorded and do not sink the rest (the backlog keeps what was won); a
    maker who leaves mid-refinement keeps every drafted spec, unrefined,
    honestly marked. The returned summary names the epic(s), every story with
    its spec id/state, and the session status. One projection per session:
    a session already in the store is refused loudly (the positional
    story-row mapping is only valid for a fresh projection -- audit F2)."""
    from .clustering import cluster_into_epics, ingest_epics
    from .product import ProductStore, ProductError
    from .product_owner import ProductOwnerError
    L = ledger or Ledger()
    st = store or ProductStore()
    # #466 audit F2: the positional story-row mapping below is only valid for
    # a FRESH projection of THIS session. Re-running the pipeline on a shared
    # ledger would zip THIS call's (possibly re-ordered, re-proposed) stories
    # against the STORED projection and silently attach wrong DoDs -- refuse
    # loudly instead; a re-decide needs a fresh ledger/session.
    already = st.db.execute("SELECT COUNT(*) FROM epics WHERE source_key LIKE ?",
                            (f"discovery:{L.session_id}:%",)).fetchone()[0]
    if already:
        raise RuntimeError(f"session {L.session_id} is already projected into the store; "
                           "re-running would attach specs by position against the stored "
                           "projection -- use a fresh ledger/session")
    stories = run_discovery(topic, channel=channel, ledger=L, max_turns=max_turns)
    ends = L.events_of("session_end")
    status = ends[-1].payload.get("status", "?") if ends else "?"
    if not stories:
        return {"status": status, "epic": None, "stories": [], "session": L.session_id}
    clusters = cluster_into_epics(stories)
    epic_ids = ingest_epics(st, L.session_id, clusters, stories)
    # map each raw story index to its persisted row (ingest inserts in
    # cluster order, so per-epic row order == story_indices order)
    story_rows: dict[int, int] = {}
    for eid, cluster in zip(epic_ids, clusters):
        rows = st.db.execute("SELECT id FROM stories WHERE epic_id=? ORDER BY id", (eid,)).fetchall()
        for (row_id,), idx in zip(rows, cluster["story_indices"]):
            story_rows[idx] = row_id
    maker_present = True
    out_stories = []
    for idx, raw in enumerate(stories):
        entry = {"story_id": story_rows.get(idx), "title": raw.get("title", "")}
        try:
            spec = draft_spec(raw, repo, url=url)
            if maker_present:
                try:
                    spec = refine_scope(spec, channel or _tui_channel, repo, ledger=L, url=url)
                    spec.state = SpecState.GROUNDED.value
                except MakerAbsent:
                    # no maker: keep the DRAFT (grounded+validated but with
                    # ambiguities unresolved), stop asking for the rest
                    maker_present = False
                    spec.state = SpecState.DRAFT.value
                    L.append(DISCOVERY_EVENT, {"kind": "maker_absent",
                                               "at": f"refine story {idx}"})
            else:
                spec.state = SpecState.DRAFT.value
            row_id = story_rows.get(idx)
            if row_id is None:      # mapping hole: recorded per-story, never a KeyError crash
                raise ProductError(f"no persisted story row for index {idx}")
            try:
                st.attach_spec(row_id, spec)
            except ProductError as e:
                # the DRAFT succeeded; the ATTACH failed (e.g. an active spec
                # already on the story) -- typed honestly, not as draft_failed
                L.append(DISCOVERY_EVENT, {"kind": "attach_failed", "story_index": idx,
                                           "title": raw.get("title", ""),
                                           "error": f"{type(e).__name__}: {e}"})
                entry.update({"spec_id": None, "spec_state": None,
                              "error": f"attach failed: {e}"})
                out_stories.append(entry)
                continue
            entry.update({"spec_id": spec.id, "spec_state": spec.state})
        except (ProductOwnerError, ProductError, RuntimeError, ValueError) as e:
            # a story that cannot draft does not sink the others -- recorded,
            # surfaced in the summary, visible in the ledger
            L.append(DISCOVERY_EVENT, {"kind": "draft_failed", "story_index": idx,
                                       "title": raw.get("title", ""),
                                       "error": f"{type(e).__name__}: {e}"})
            entry.update({"spec_id": None, "spec_state": None,
                          "error": f"{type(e).__name__}: {e}"})
        out_stories.append(entry)
    epics = [{"id": r[0], "title": r[1]} for r in st.db.execute(
        f"SELECT id, name FROM epics WHERE id IN ({','.join('?' * len(epic_ids))}) ORDER BY id",
        epic_ids).fetchall()]
    return {"status": status, "session": L.session_id,
            "epic": epics[0],                # the AC's singular; epics is authoritative
            "epics": epics,
            "stories": out_stories}
