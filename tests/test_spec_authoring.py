"""Story #464 -- draft_spec: a raw discovery story becomes a Gate-0-valid
Spec at DRAFT time. Deterministic: the model channel
(animal.product_owner._chat, the #457 machinery draft_spec composes -- the
AC's 'ModelPlane.call' letter predates M3; the deviation is named in
discovery.py's docstring) is monkeypatched; Sandbox / grounding / dod run
REAL. Run: python3 tests/test_spec_authoring.py
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal import product_owner
from animal import discovery
from animal.discovery import draft_spec
from animal.product_owner import ProductOwnerError
from animal.sandbox import Sandbox
from animal.dod import validate_spec

RAW = {"title": "sum things", "narrative": "As a maker, I want calc.add to sum so that totals are right",
       "notes": "input: two ints; output: their sum"}

_GOOD = json.dumps({"user_story": "calc.add must sum", "intent": ["fix add"], "out_of_scope": [],
                    "dod": [{"name": "add-sums",
                             "argv": ["python3", "-c", "import calc; assert calc.add(2,3)==5"],
                             "comparator": "exit_zero"}]})


def _repo():
    r = Path(tempfile.mkdtemp(prefix="animal-p464-"))
    (r / "calc.py").write_text("def add(a,b):\n    return a - b\n")
    return r


def _patched(answers):
    """Run draft_spec with product_owner._chat scripted; returns (result_or_exc, calls)."""
    it = iter(answers)
    calls = {"n": 0, "prompts": []}

    def fake_chat(role, messages, url=None, timeout=600):
        calls["n"] += 1
        calls["prompts"].append(" ".join(m["content"] for m in messages))
        return next(it)

    orig = product_owner._chat
    product_owner._chat = fake_chat
    try:
        try:
            return draft_spec(RAW, str(_repo())), calls
        except ProductOwnerError as e:
            return e, calls
    finally:
        product_owner._chat = orig


def test_draft_spec_valid_first_draft_is_gate0_valid():
    spec, calls = _patched([_GOOD])
    assert not isinstance(spec, Exception), spec
    assert calls["n"] == 1
    assert validate_spec(spec, Sandbox(), str(_repo()))["ok"] is True
    # the raw story's narrative and notes reached the model
    assert "totals are right" in calls["prompts"][0] and "two ints" in calls["prompts"][0]


def test_draft_spec_invalid_then_valid_returns_on_second_attempt():
    """The AC's seeded scenario: first draft references a nonexistent helper
    script (authoring-invalid), the concrete reason is fed back, the second
    draft is clean -- exactly two model calls, Gate-0-valid result."""
    bad = json.dumps({"user_story": "u", "intent": [], "out_of_scope": [],
                      "dod": [{"name": "helper", "argv": ["python3", "missing_helper.py"],
                               "comparator": "exit_zero"}]})
    spec, calls = _patched([bad, _GOOD])
    assert not isinstance(spec, Exception), spec
    assert calls["n"] == 2, calls["n"]
    assert validate_spec(spec, Sandbox(), str(_repo()))["ok"] is True
    assert "missing_helper.py" in calls["prompts"][1], "the concrete rejection reason must reach the retry"


def test_draft_spec_grounding_miss_retries_with_the_misses():
    """The layer #464 ADDS over #457: a draft that passes authoring checks but
    references a file that does not exist (a non-script ref the lint cannot
    see) is caught by ground() AT DRAFT TIME and re-prompted with the miss."""
    ungrounded = json.dumps({"user_story": "recap from data.json", "intent": [], "out_of_scope": [],
                             "dod": [{"name": "data-present", "argv": ["cat", "data.json"],
                                      "comparator": "exit_zero"}]})
    spec, calls = _patched([ungrounded, _GOOD])
    assert not isinstance(spec, Exception), spec
    assert calls["n"] == 2, calls["n"]
    assert "data.json" in calls["prompts"][1], "the unresolved ref must be named in the retry prompt"


def test_draft_spec_is_bounded_and_surfaces_residual_failure():
    """Always-ungrounded drafts exhaust max_retries and raise with the last
    concrete reason -- never an infinite loop, never an ungrounded spec."""
    ungrounded = json.dumps({"user_story": "recap from data.json", "intent": [], "out_of_scope": [],
                             "dod": [{"name": "data-present", "argv": ["cat", "data.json"],
                                      "comparator": "exit_zero"}]})
    err, calls = _patched([ungrounded] * 10)
    assert isinstance(err, ProductOwnerError), err
    assert calls["n"] == 3, calls["n"]        # max_retries outer attempts, one clean call each
    assert "data.json" in str(err)


def test_draft_spec_runs_gate0_pipeline_exactly_once_per_attempt():
    """AC: draft_spec runs the EXISTING ground + validate_spec, unmodified --
    each called exactly once per draft attempt (counted on the happy path)."""
    counts = {"ground": 0, "validate": 0}
    real_ground, real_validate = discovery.ground, discovery.validate_spec

    def counting_ground(spec, repo):
        counts["ground"] += 1
        return real_ground(spec, repo)

    def counting_validate(spec, sb, repo):
        counts["validate"] += 1
        return real_validate(spec, sb, repo)

    discovery.ground, discovery.validate_spec = counting_ground, counting_validate
    try:
        spec, calls = _patched([_GOOD])
    finally:
        discovery.ground, discovery.validate_spec = real_ground, real_validate
    assert not isinstance(spec, Exception)
    assert counts == {"ground": 1, "validate": 1}, counts


def test_draft_spec_story_without_narrative_raises():
    """Audit F6: a story with no NARRATIVE is not draftable -- title-only used
    to render as 'title: ' and burn a real (minutes-long) model call."""
    for story in ({"title": "", "narrative": "", "notes": ""},
                  {"title": "just a title", "narrative": "", "notes": ""},
                  {"title": "", "narrative": "   ", "notes": "notes only"}):
        try:
            draft_spec(story, str(_repo()))
            assert False, f"expected ValueError for {story}"
        except ValueError:
            pass


def test_draft_spec_tdd_shaped_story_can_use_expected_new():
    """Audit F1: the strict draft schema could never emit expected_new, so a
    TDD-shaped story (a DoD check naming a test file the work itself will
    create) could not draft through the front door and the retry advice was
    unfollowable. The schema now carries the flag and the drafted spec
    grounds cleanly with the not-yet-existing path."""
    from animal.product_owner import _SPEC_SCHEMA
    props = _SPEC_SCHEMA["properties"]["dod"]["items"]["properties"]
    assert "expected_new" in props and props["expected_new"]["type"] == "boolean"
    tdd = json.dumps({"user_story": "new behavior, test-first", "intent": [], "out_of_scope": [],
                      "dod": [{"name": "future-test", "argv": ["python3", "tests/test_future.py"],
                               "comparator": "exit_zero", "expected_new": True}]})
    spec, calls = _patched([tdd])
    assert not isinstance(spec, Exception), spec
    assert calls["n"] == 1
    assert spec.dod[0].expected_new is True


def test_draft_spec_feedback_accumulates_across_attempts():
    """Audit F3: rebuilding the feedback each attempt hid earlier misses --
    fix-B-reintroduce-A oscillation was invisible to the model. All misses
    seen so far must reach the final retry prompt."""
    miss_a = json.dumps({"user_story": "u", "intent": [], "out_of_scope": [],
                         "dod": [{"name": "a", "argv": ["cat", "data.json"], "comparator": "exit_zero"}]})
    miss_b = json.dumps({"user_story": "u", "intent": [], "out_of_scope": [],
                         "dod": [{"name": "b", "argv": ["cat", "other.json"], "comparator": "exit_zero"}]})
    spec, calls = _patched([miss_a, miss_b, _GOOD])
    assert not isinstance(spec, Exception), spec
    assert calls["n"] == 3
    final_prompt = calls["prompts"][2]
    assert "data.json" in final_prompt and "other.json" in final_prompt, \
        "the third attempt must see BOTH prior misses"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
