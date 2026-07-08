"""Story #462 -- the bounded conversational discovery loop. Deterministic,
offline: animal.discovery.ModelPlane is monkeypatched to a scripted stand-in
(the test_repomap.py/_CaptureModelPlane substitution pattern), the maker's
channel is a scripted callable, and every assertion reads either the returned
stories or the ledger the loop wrote. Run: python3 tests/test_discovery.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal import config
from animal import discovery
from animal.discovery import run_discovery, DISCOVERY_EVENT
from animal.ledger import Ledger


class _ScriptedPlane:
    """Deterministic ModelPlane stand-in: plays a fixed list of actions, one
    per call, recording what it was shown."""
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = 0
        self.seen_messages = []

    def call(self, role, messages, temperature=None):
        self.seen_messages.append([dict(m) for m in messages])
        i = min(self.calls, len(self.actions) - 1)   # repeat the last action if over-asked
        self.calls += 1
        return {"thought": "t", "action": self.actions[i]}, {"context_overflow": False}


def _run(actions, answers=None, max_turns=None):
    """Drive run_discovery with a scripted plane + scripted channel; returns
    (stories, plane, ledger, asked_questions)."""
    asked = []
    answers = list(answers or [])

    def channel(question):
        asked.append(question)
        return answers.pop(0) if answers else "no further detail"

    plane = _ScriptedPlane(actions)
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: plane
    try:
        stories = run_discovery("a tiny habit tracker", channel=channel, ledger=L,
                                max_turns=max_turns)
    finally:
        discovery.ModelPlane = orig
    return stories, plane, L, asked


_SCRIPT = [
    {"kind": "ask", "question": "What is the pain?"},
    {"kind": "ask", "question": "What does good output look like?"},
    {"kind": "propose_story", "title": "log a habit",
     "narrative": "As a maker, I want to log a habit completion so that my streak is recorded",
     "notes": "input: habit name + date; output: a row in the log"},
    {"kind": "propose_story", "title": "see my streak",
     "narrative": "As a maker, I want to see my current streak so that I stay motivated",
     "notes": "input: the log; output: streak length per habit"},
    {"kind": "finish", "message": "two stories shaped"},
]


def test_discovery_scripted_conversation_returns_stories():
    """The AC's seeded conversation: 2 clarifying questions (each answered by
    the scripted channel) + 2 proposed stories + finish -> exactly 2 raw
    stories, each with a non-empty narrative, in proposal order."""
    stories, plane, _, asked = _run(_SCRIPT, answers=["forgetting my habits", "a visible streak"])
    assert len(stories) == 2, stories
    assert all(s["narrative"].strip() for s in stories), stories
    assert [s["title"] for s in stories] == ["log a habit", "see my streak"]
    assert asked == ["What is the pain?", "What does good output look like?"]
    assert plane.calls == 5   # ask, ask, propose, propose, finish -- then stopped
    # the maker's answers must reach the model's next turn verbatim
    flat = " ".join(m["content"] for m in plane.seen_messages[-1])
    assert "forgetting my habits" in flat and "a visible streak" in flat


def test_discovery_ledger_records_every_turn():
    """Every dialogue move -- question + verbatim answer, each proposed story,
    the finish -- lands in the ledger under DISCOVERY_EVENT: the conversation
    replays like any other lane."""
    _, _, L, _ = _run(_SCRIPT, answers=["a1", "a2"])
    evs = L.events_of(DISCOVERY_EVENT)
    kinds = [e.payload["kind"] for e in evs]
    assert kinds == ["ask", "ask", "propose_story", "propose_story", "finish"], kinds
    assert evs[0].payload["answer"] == "a1" and evs[1].payload["answer"] == "a2"
    assert evs[2].payload["title"] == "log a habit"


def test_discovery_is_hard_bounded():
    """A model that never finishes cannot loop forever: the kernel-loop bound
    applies (max_turns, defaulting to config.MAX_TURNS)."""
    never_ends = [{"kind": "ask", "question": "and then?"}]
    stories, plane, _, _ = _run(never_ends, max_turns=4)
    assert stories == []
    assert plane.calls == 4, plane.calls


def test_discovery_invalid_action_is_recorded_and_bounded():
    """A malformed move is ledger-recorded and surfaced back to the model --
    never crashes, never silently dropped, still bounded."""
    script = [{"kind": "teleport"},
              {"kind": "propose_story", "title": "t", "narrative": "As a maker, I want x so that y",
               "notes": ""},
              {"kind": "finish", "message": "done"}]
    stories, _, L, _ = _run(script)
    assert len(stories) == 1
    kinds = [e.payload["kind"] for e in L.events_of(DISCOVERY_EVENT)]
    assert kinds == ["invalid", "propose_story", "finish"], kinds


def test_discovery_has_no_write_vocabulary():
    """Conversation-only BY CONSTRUCTION: the module must not import or name
    the edit/shell actions at all -- absence, not a disabled flag, is what
    makes it impossible for this lane to gain write capability."""
    src = Path(discovery.__file__).read_text()
    assert "EditAction" not in src and "ShellAction" not in src
    # and the vocabulary the prompt offers is exactly the conversational three
    for kind in ("ask", "propose_story", "finish"):
        assert kind in discovery.DISCOVERY_SYSTEM_PROMPT


def test_discovery_role_reuses_a_provisioned_seat():
    assert config.ROLES["discovery"]["model"] in ("coder", "architect", "judge", "auditor")


def test_discovery_turn_grammar_is_conversation_only():
    """The REAL enforcement is at the decoder: the work-lane TURN_SCHEMA
    closes action.kind to read/grep/edit/shell/finish, which would make
    ask/propose_story token-level impossible -- so the discovery role must
    select its own closed grammar, whose vocabulary has no edit and no shell.
    (A mocked ModelPlane can never catch this; this pins the schema wiring.)"""
    from animal.model import turn_schema_for, TURN_SCHEMA, DISCOVERY_TURN_SCHEMA
    assert turn_schema_for(config.ROLES["discovery"]) is DISCOVERY_TURN_SCHEMA
    assert turn_schema_for(config.ROLES["coder"]) is TURN_SCHEMA
    kinds = DISCOVERY_TURN_SCHEMA["properties"]["action"]["properties"]["kind"]["enum"]
    assert kinds == ["ask", "propose_story", "finish"], kinds
    work_kinds = TURN_SCHEMA["properties"]["action"]["properties"]["kind"]["enum"]
    assert "ask" not in work_kinds and "edit" not in kinds


# --- Story #462 red-team fixes: honest exits on every path ---

def _session_status(L):
    ends = L.events_of("session_end")
    assert ends, "SESSION_END must fire on every exit path"
    return ends[-1].payload["status"]


def test_discovery_absent_maker_halts_never_fabricates():
    """THE red-team blocker: a headless run (EOF on the channel) used to
    convert maker-absence into 'The maker answers: ' -- asserting to the model
    that a human replied when nobody exists -- and return model-invented
    stories with exit 0. No maker now HALTS the session with a typed event;
    the model is never told anyone answered."""
    from animal.discovery import MakerAbsent

    def absent_channel(question):
        raise MakerAbsent("nobody here")

    plane = _ScriptedPlane([{"kind": "ask", "question": "pain?"}])
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: plane
    try:
        stories = run_discovery("t", channel=absent_channel, ledger=L)
    finally:
        discovery.ModelPlane = orig
    assert stories == []
    assert plane.calls == 1, "the session must halt, not keep conversing with nobody"
    kinds = [e.payload["kind"] for e in L.events_of(DISCOVERY_EVENT)]
    assert kinds == ["maker_absent"], kinds
    assert _session_status(L) == "maker_absent"
    # the fabricated phrase must never have been sent to the model
    flat = " ".join(m["content"] for msgs in plane.seen_messages for m in msgs)
    assert "The maker answers" not in flat


def test_discovery_tui_channel_raises_maker_absent_on_eof():
    """The production interactive channel maps EOF to MakerAbsent -- never to
    an empty 'answer'."""
    import io
    from animal.discovery import MakerAbsent, _tui_channel
    orig = sys.stdin
    sys.stdin = io.StringIO("")   # EOF immediately
    try:
        try:
            _tui_channel("anyone there?")
            assert False, "EOF must raise MakerAbsent"
        except MakerAbsent:
            pass
    finally:
        sys.stdin = orig


def test_discovery_model_error_is_a_typed_status():
    """A dead model server is a FAULT, not an empty outcome: status
    model_error in SESSION_END, typed event in the conversation record."""
    from animal.model import ModelError

    class _DeadPlane:
        def call(self, role, messages, temperature=None):
            raise ModelError("connection refused")

    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: _DeadPlane()
    try:
        stories = run_discovery("t", channel=lambda q: "x", ledger=L)
    finally:
        discovery.ModelPlane = orig
    assert stories == []
    assert _session_status(L) == "model_error"
    assert [e.payload["kind"] for e in L.events_of(DISCOVERY_EVENT)] == ["model_error"]


def test_discovery_cli_exits_nonzero_when_session_died_empty():
    """The CLI must not mask total failure as a genuine empty result."""
    from animal.model import ModelError
    from animal import cli

    class _DeadPlane:
        def call(self, role, messages, temperature=None):
            raise ModelError("connection refused")

    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: _DeadPlane()
    try:
        rc = cli.main(["discover", "nothing will come of this"])
    finally:
        discovery.ModelPlane = orig
    assert rc == 1, rc


def test_discovery_context_overflow_is_a_hard_fault():
    """The kernel loop treats a truncated context as a hard integrity fault;
    discovery must too -- a model that no longer sees the real conversation
    cannot ground anything it proposes in it."""
    class _OverflowPlane:
        def __init__(self):
            self.calls = 0
        def call(self, role, messages, temperature=None):
            self.calls += 1
            return {"thought": "t", "action": {"kind": "ask", "question": "q"}}, {"context_overflow": True}

    plane = _OverflowPlane()
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: plane
    try:
        stories = run_discovery("t", channel=lambda q: "x", ledger=L)
    finally:
        discovery.ModelPlane = orig
    assert stories == [] and plane.calls == 1
    assert _session_status(L) == "context_overflow"


def test_discovery_nondict_action_is_invalid_not_a_crash():
    """A malformed turn object (action not a dict / out None) lands in the
    invalid branch -- recorded, surfaced, bounded -- never an AttributeError."""
    script = [{"kind": None}]   # will be replaced below by raw shapes
    plane = _ScriptedPlane(script)
    # override: emit genuinely broken shapes then a finish
    shapes = iter([({"thought": "t", "action": "not-a-dict"}, {}),
                   (None, {}),
                   ({"thought": "t", "action": {"kind": "finish", "message": "m"}}, {})])
    plane.call = lambda role, messages, temperature=None: next(shapes)
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: plane
    try:
        stories = run_discovery("t", channel=lambda q: "x", ledger=L)
    finally:
        discovery.ModelPlane = orig
    assert stories == []
    kinds = [e.payload["kind"] for e in L.events_of(DISCOVERY_EVENT)]
    assert kinds == ["invalid", "invalid", "finish"], kinds
    assert _session_status(L) == "finished"


def test_discovery_vacuous_story_is_rejected_not_counted():
    """Grammar-legal but empty propose_story (blank title/narrative) is no
    story: rejected back to the model, never returned or handed onward."""
    script = [
        {"kind": "propose_story", "title": "", "narrative": "", "notes": ""},
        {"kind": "propose_story", "title": "real", "narrative": "As a maker, I want x so that y", "notes": ""},
        {"kind": "finish", "message": "done"},
    ]
    stories, _, L, _ = _run(script)
    assert [s["title"] for s in stories] == ["real"]
    kinds = [e.payload["kind"] for e in L.events_of(DISCOVERY_EVENT)]
    assert kinds == ["invalid", "propose_story", "finish"], kinds


def test_discovery_keyboard_interrupt_keeps_stories_and_pairs_session():
    """Ctrl-C mid-conversation: the stories already proposed are real
    maker-shaped material -- returned, with SESSION_END fired (status aborted),
    never a lost session."""
    script = [
        {"kind": "propose_story", "title": "kept", "narrative": "As a maker, I want x so that y", "notes": ""},
        {"kind": "ask", "question": "more?"},
    ]

    def interrupting_channel(question):
        raise KeyboardInterrupt

    plane = _ScriptedPlane(script)
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: plane
    try:
        stories = run_discovery("t", channel=interrupting_channel, ledger=L)
    finally:
        discovery.ModelPlane = orig
    assert [s["title"] for s in stories] == ["kept"]
    assert _session_status(L) == "aborted"


def test_discovery_max_turns_zero_means_zero():
    """An explicit max_turns=0 runs ZERO turns -- it must not fall through a
    falsy-default into 20 real GPU calls."""
    plane = _ScriptedPlane([{"kind": "ask", "question": "q"}])
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-disc-led-"))
    orig = discovery.ModelPlane
    discovery.ModelPlane = lambda *a, **kw: plane
    try:
        stories = run_discovery("t", channel=lambda q: "x", ledger=L, max_turns=0)
    finally:
        discovery.ModelPlane = orig
    assert stories == [] and plane.calls == 0
    assert _session_status(L) == "max_turns"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
