"""Story #466 -- the M4 end-to-end: one open-ended sentence yields a real
epic with grounded specs. Deterministic canned scripts for BOTH model
channels (discovery's ModelPlane and the product-owner's _chat -- the AC's
single-ModelPlane letter predates M3's split channels, deviation named in
discovery.py's #464 section); Sandbox / grounding / dod / ProductStore run
REAL. NAMED DEVIATION from the AC's runner letter: this repo's suite runs
files directly (python3 tests/test_discovery_e2e.py), not via pytest (not
installed by design). Run: python3 tests/test_discovery_e2e.py
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal import discovery, product_owner
from animal.discovery import run_discovery_to_backlog
from animal.ledger import Ledger
from animal.product import ProductStore
from animal.sandbox import Sandbox
from animal.spec import Spec
from animal.dod import validate_spec


def _game_repo():
    r = Path(tempfile.mkdtemp(prefix="animal-p466-"))
    (r / "game.py").write_text(
        "def spawn_crop():\n    return None\n\n\ndef day_length():\n    return 0\n")
    return r


class _ScriptedPlane:
    def __init__(self, actions):
        self.actions = list(actions); self.calls = 0

    def call(self, role, messages, temperature=None):
        i = min(self.calls, len(self.actions) - 1)
        self.calls += 1
        return {"thought": "t", "action": self.actions[i]}, {"context_overflow": False}


_DISCOVERY_SCRIPT = [
    {"kind": "ask", "question": "What is the core loop you want first?"},
    {"kind": "propose_story", "title": "plant a crop",
     "narrative": "As a maker, I want game.spawn_crop to return a crop so that planting works",
     "notes": "input: none; output: a crop name"},
    {"kind": "propose_story", "title": "day cycle",
     "narrative": "As a maker, I want game.day_length to be a real day so that time passes",
     "notes": "input: none; output: minutes per day > 0"},
    {"kind": "finish", "message": "two stories shaped"},
]

_SPEC_1 = json.dumps({"user_story": "game.spawn_crop returns a crop", "intent": ["make spawn_crop real"],
                      "out_of_scope": ["crop growth stages"],
                      "dod": [{"name": "crop-spawns",
                               "argv": ["python3", "-c", "import game; assert game.spawn_crop() == 'parsnip'"],
                               "comparator": "exit_zero"}]})
_SPEC_2 = json.dumps({"user_story": "game.day_length is a real day", "intent": ["set day length"],
                      "out_of_scope": ["seasons"],
                      "dod": [{"name": "day-passes",
                               "argv": ["python3", "-c", "import game; assert game.day_length() > 0"],
                               "comparator": "exit_zero"}]})


def _run_e2e(store, repo):
    """Drive the whole pipeline with canned scripts; maker channel scripted;
    no ambiguities (enumeration mocked empty -- #465's own tests cover the
    refinement dialogue)."""
    plane = _ScriptedPlane(_DISCOVERY_SCRIPT)
    chats = iter([_SPEC_1, _SPEC_2])
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p466-led-"))

    orig = (discovery.ModelPlane, product_owner._chat, discovery.enumerate_case_default)
    discovery.ModelPlane = lambda *a, **kw: plane
    product_owner._chat = lambda role, messages, url=None, timeout=600: next(chats)
    discovery.enumerate_case_default = lambda spec_, url=None: []
    try:
        summary = run_discovery_to_backlog(
            "I want to make a video game like Stardew Valley", str(repo),
            channel=lambda q: "just the farming core", store=store, ledger=L)
    finally:
        discovery.ModelPlane, product_owner._chat, discovery.enumerate_case_default = orig
    return summary, L


def test_video_game_prompt_yields_epic_with_stories():
    """THE M4 exit: one sentence -> one epic, >=2 stories, each with a spec
    that (a) persists, (b) passes a FRESH Gate-0b re-run from its STORED
    form, (c) never left draft/grounded, and (d) whose discovery session
    contains zero edit/shell actions."""
    repo = _game_repo()
    store = ProductStore(db_path=":memory:")
    summary, L = _run_e2e(store, repo)

    # (a) exactly one epic, >= 2 stories persisted
    assert summary["epic"] is not None and summary["epic"]["title"], summary
    assert store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0] == 1
    n_stories = store.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
    assert n_stories >= 2, n_stories
    assert len([s for s in summary["stories"] if s.get("spec_id")]) == 2, summary["stories"]

    # (b) every persisted spec passes validate_spec on a FRESH re-run of its
    # STORED form (load_spec -> the same artifact worklane.run_work would get)
    sb = Sandbox()
    for s in summary["stories"]:
        stored = store.load_spec(s["story_id"])
        assert stored is not None, s
        v = validate_spec(stored, sb, str(repo))
        assert v["ok"] is True, (s, v)

    # (c) draft/grounded only -- approval remains the human channel
    states = [r[0] for r in store.db.execute("SELECT status FROM specs").fetchall()]
    assert states and all(st in ("draft", "grounded") for st in states), states

    # (d) the discovery session's ledger replay: ZERO edit/shell actions
    actions = [e.payload.get("kind") for e in L.replay() if e.type == "action"]
    assert not any(k in ("edit", "shell") for k in actions), actions


def test_persisted_spec_round_trips_into_run_work_no_glue():
    """AC + audit F1: the stored artifact is usable by worklane.run_work with
    NO new glue -- PROVEN by invoking run_work itself, not just re-validating
    (the audit demonstrated a stored 'grounded' spec used to CRASH run_work
    on the no-op grounded->grounded transition -- the flagship artifact
    breaking its one named consumer). A denying approver stops it at the
    approval gate, which is exactly the point: it traversed grounding and
    authoring with zero adapters, and approval stayed human."""
    import animal.worklane as worklane
    repo = _game_repo()
    store = ProductStore(db_path=":memory:")
    summary, _ = _run_e2e(store, repo)
    story_id = summary["stories"][0]["story_id"]
    stored = store.load_spec(story_id)
    assert stored.state == "grounded", stored.state     # the flagship artifact
    rebuilt = Spec.from_dict(stored.to_dict())          # the exact worklane input shape
    assert validate_spec(rebuilt, Sandbox(), str(repo))["ok"] is True
    r = worklane.run_work(rebuilt, str(repo), approver=lambda k, s2: "deny", max_turns=1,
                          ledger_dir=tempfile.mkdtemp(prefix="animal-p466-led-"))
    assert r["rejected_at"] == "approval", r            # traversed Gate 0a/0b, stopped at the human


def test_already_projected_session_is_refused_loudly():
    """Audit F2: re-running the pipeline on a shared ledger would zip THIS
    call's stories against the STORED projection by position -- wrong DoDs on
    wrong stories, then an uncaught crash. Refused loudly instead."""
    repo = _game_repo()
    store = ProductStore(db_path=":memory:")
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p466-led-"))
    plane = _ScriptedPlane(_DISCOVERY_SCRIPT)
    chats = iter([_SPEC_1, _SPEC_2])
    orig = (discovery.ModelPlane, product_owner._chat, discovery.enumerate_case_default)
    discovery.ModelPlane = lambda *a, **kw: plane
    product_owner._chat = lambda role, messages, url=None, timeout=600: next(chats)
    discovery.enumerate_case_default = lambda spec_, url=None: []
    try:
        run_discovery_to_backlog("game", str(repo), channel=lambda q: "a", store=store, ledger=L)
        try:
            run_discovery_to_backlog("game", str(repo), channel=lambda q: "a", store=store, ledger=L)
            assert False, "expected the already-projected session to be refused"
        except RuntimeError as e:
            assert "already projected" in str(e)
    finally:
        discovery.ModelPlane, product_owner._chat, discovery.enumerate_case_default = orig
    # nothing doubled: still one epic, two stories, two specs
    assert store.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 2


def test_maker_leaving_mid_refinement_keeps_drafts():
    """A maker who walks away after drafting keeps every drafted spec --
    persisted at state 'draft' (grounded+validated, ambiguities unresolved),
    the absence typed in the ledger, nothing invented."""
    from animal.discovery import MakerAbsent
    repo = _game_repo()
    store = ProductStore(db_path=":memory:")
    plane = _ScriptedPlane(_DISCOVERY_SCRIPT)
    chats = iter([_SPEC_1, _SPEC_2])
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p466-led-"))

    def absent_after_discovery(question):
        # present for the discovery ask, gone by refinement time -- the
        # refine questions are recognizable by their fixed prefix
        if question.startswith("Ambiguity in scope:"):
            raise MakerAbsent("left after the stories were shaped")
        return "answered while still here"

    orig = (discovery.ModelPlane, product_owner._chat, discovery.enumerate_case_default)
    discovery.ModelPlane = lambda *a, **kw: plane
    product_owner._chat = lambda role, messages, url=None, timeout=600: next(chats)
    discovery.enumerate_case_default = lambda spec_, url=None: [
        {"term": "farming core", "assumed_reading": "crops only"}]
    try:
        summary = run_discovery_to_backlog(
            "game", str(repo), channel=absent_after_discovery, store=store, ledger=L)
    finally:
        discovery.ModelPlane, product_owner._chat, discovery.enumerate_case_default = orig
    # the maker answered discovery's ask, so both stories were shaped and
    # drafted; absence hit at REFINEMENT -- every draft is kept, at 'draft'
    assert len([s for s in summary["stories"] if s.get("spec_id")]) == 2, summary["stories"]
    states = [r[0] for r in store.db.execute("SELECT status FROM specs").fetchall()]
    assert len(states) == 2 and all(st == "draft" for st in states), states
    absents = [e for e in L.events_of(discovery.DISCOVERY_EVENT)
               if e.payload["kind"] == "maker_absent"]
    assert absents, "the absence must be typed in the ledger"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
