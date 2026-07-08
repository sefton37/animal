"""Phase 5 / Story #457 tests: the product-owner role. Deterministic, offline --
animal.product_owner._chat is monkeypatched (same substitution pattern as
tests/test_phase3.py's panel.run_seat), so no live llama-swap is required.
Proves author_spec runs a model-authored spec through the SAME Spec.from_dict +
dod.validate_check machinery a hand-authored spec faces (a vacuous/malformed
attempt is rejected and corrected, not silently accepted), that it raises
ProductOwnerError rather than ever returning a bad spec, and that
worklane.run_work_from_story wires it into the existing, unmodified run_work.
Run: python3 tests/test_phase5.py

test_author_spec_live_smoke below is the ONE test in this file that is NOT
offline -- it calls the real, non-monkeypatched animal.product_owner._chat
against a live llama-swap (the fix for a red-team finding on this story: the
prior attempt's DoD only ever exercised a monkeypatched _chat, so the story's
actual value proposition -- a maker gets a real Spec back from a plain-language
story via a model -- had never been proven end-to-end). It is SKIPPED by
default (this file must stay fast + deterministic for the normal suite run) and
only runs when ANIMAL_LIVE_MODEL_TEST=1 is set. Run it explicitly with:
  ANIMAL_LIVE_MODEL_TEST=1 python3 tests/test_phase5.py
It uses a generous per-call timeout (900s): a real call on this project's
"architect" seat (a thinking model) can legitimately take several minutes on a
contended host -- see animal/product_owner.py's _SYS / _chat docstrings for the
measured cause (host CPU contention + a thinking model's chain-of-thought, not
a hang -- confirmed by streaming the raw completion end-to-end).
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal import config
from animal import product_owner
from animal.product_owner import ProductOwnerError
from animal.spec import Spec
from animal.worklane import run_work_from_story


def _repo(src="def add(a,b):\n    return a - b\n"):
    r = Path(tempfile.mkdtemp(prefix="animal-p5-"))
    (r / "calc.py").write_text(src)
    return r


def _patched(fn):
    """Run fn() with product_owner._chat monkeypatched, always restoring."""
    orig = product_owner._chat
    try:
        return fn()
    finally:
        product_owner._chat = orig


# --- config wiring ---

def test_config_product_owner_role_reuses_a_provisioned_seat():
    assert config.ROLES["product_owner"]["model"] in ("coder", "architect", "judge", "auditor")


# --- author_spec: the corrective-retry loop ---

def test_author_spec_repairs_vacuous_check():
    repo = _repo()
    calls = {"n": 0}

    def fake_chat(role, messages, url=None, timeout=600):
        calls["n"] += 1
        if calls["n"] == 1:                    # first attempt: a vacuous check (always passes)
            return json.dumps({"user_story": "fix calc.add to sum, not subtract",
                               "intent": ["fix add"], "out_of_scope": [],
                               "dod": [{"name": "vac", "argv": ["python3", "-c", "print(1)"],
                                        "comparator": "exit_zero"}]})
        return json.dumps({"user_story": "fix calc.add to sum, not subtract",           # corrected
                           "intent": ["fix add"], "out_of_scope": [],
                           "dod": [{"name": "add-sums",
                                    "argv": ["python3", "-c", "import calc; assert calc.add(2,3)==5"],
                                    "comparator": "exit_zero"}]})

    def run():
        product_owner._chat = fake_chat
        return product_owner.author_spec("fix calc.add to sum, not subtract", str(repo), max_retries=2)

    spec = _patched(run)
    assert calls["n"] == 2, "the vacuous first attempt must be rejected and corrected"
    assert spec.dod[0].name == "add-sums"
    spec2 = Spec.from_dict(spec.to_dict())                 # round-trips without SpecError
    assert spec2.user_story == spec.user_story and spec2.dod[0].argv == spec.dod[0].argv


def test_author_spec_recovers_from_malformed_json():
    repo = _repo()
    calls = {"n": 0}

    def fake_chat(role, messages, url=None, timeout=600):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not JSON at all {broken"     # no closing brace -> unparseable
        return json.dumps({"user_story": "u", "intent": [], "out_of_scope": [],
                           "dod": [{"name": "add-sums",
                                    "argv": ["python3", "-c", "import calc; assert calc.add(2,3)==5"],
                                    "comparator": "exit_zero"}]})

    def run():
        product_owner._chat = fake_chat
        return product_owner.author_spec("u", str(repo), max_retries=2)

    spec = _patched(run)
    assert calls["n"] == 2 and spec.dod[0].name == "add-sums"


def test_author_spec_raises_after_max_retries():
    repo = _repo()

    def always_vacuous(role, messages, url=None, timeout=600):
        return json.dumps({"user_story": "u", "intent": [], "out_of_scope": [],
                           "dod": [{"name": "vac", "argv": ["python3", "-c", "print(1)"],
                                    "comparator": "exit_zero"}]})

    def run():
        product_owner._chat = always_vacuous
        try:
            product_owner.author_spec("u", str(repo), max_retries=2)
            assert False, "expected ProductOwnerError, spec was never valid"
        except ProductOwnerError:
            pass

    _patched(run)


# --- worklane wiring: author_spec feeds the SAME unmodified run_work ---

def test_run_work_from_story_wires_into_existing_gate_chain():
    repo = _repo()

    def fake_chat(role, messages, url=None, timeout=600):
        return json.dumps({"user_story": "fix add", "intent": ["fix add"], "out_of_scope": [],
                           "dod": [{"name": "add-sums",
                                    "argv": ["python3", "-c", "import calc; assert calc.add(2,3)==5"],
                                    "comparator": "exit_zero"}]})

    def run():
        product_owner._chat = fake_chat
        # a REJECT here (not "grounding"/"dod_authoring") proves the model-authored
        # spec passed grounding + DoD authoring validation exactly like a hand-authored one
        # premise_panel=False keeps this a fast OFFLINE chain test (the panel now
        # defaults ON for model-authored specs -- covered by the dedicated test that
        # mocks panel.review_spec); this test is about the grounding/authoring chain.
        return run_work_from_story("fix add", str(repo), approver=lambda k, s: "reject",
                                   max_turns=2, premise_panel=False)

    r = _patched(run)
    assert r["final_state"] == "rejected" and r["rejected_at"] == "approval"


def test_run_work_from_story_propagates_product_owner_error():
    repo = _repo()

    def always_vacuous(role, messages, url=None, timeout=600):
        return json.dumps({"user_story": "u", "intent": [], "out_of_scope": [],
                           "dod": [{"name": "vac", "argv": ["python3", "-c", "print(1)"],
                                    "comparator": "exit_zero"}]})

    def run():
        product_owner._chat = always_vacuous
        try:
            run_work_from_story("u", str(repo), approver=lambda k, s: "approve", max_turns=2)
            assert False, "a permanently-vacuous model spec must never silently reach run_work"
        except ProductOwnerError:
            pass

    _patched(run)


def test_model_authored_spec_surfaces_check_bodies_and_defaults_panel_on():
    # #457 red-team: Gate 0 catches STRUCTURAL badness (vacuous/ungrounded checks) but
    # not SEMANTIC badness -- a model-authored check with a plausible NAME but a
    # story-irrelevant BODY. Two fixes here: (1) the human-approval summary shows each
    # check's ARGV (not just its name), so the name/body mismatch is visible; (2) the
    # cross-family premise panel runs BY DEFAULT on a model-authored spec (the human no
    # longer authored the checks, so their implicit scrutiny is replaced).
    repo = _repo()

    def fake_chat(role, messages, url=None, timeout=600):
        return json.dumps({"user_story": "reject sql injection with 400",
                           "intent": ["guard login"], "out_of_scope": ["signup"],
                           "dod": [{"name": "rejects-sql-injection-with-400",
                                    "argv": ["python3", "-c", "import calc; assert calc.add(2,3)==5"],
                                    "comparator": "exit_zero"}]})

    captured, panel_calls = {}, []

    def capturing_approver(spec_id, summary):
        captured["summary"] = summary
        return "reject"

    import animal.panel as _panel
    saved_review = _panel.review_spec
    _panel.review_spec = lambda spec: (panel_calls.append(spec.id),
        {"panel_verdict": "sound", "flagged": False, "per_seat": {}, "reasons": {}})[1]

    def run():
        product_owner._chat = fake_chat
        return run_work_from_story("reject sql injection", str(repo),
                                   approver=capturing_approver, max_turns=2)
    try:
        _patched(run)
    finally:
        _panel.review_spec = saved_review

    assert "calc.add(2,3)==5" in captured["summary"], captured["summary"]   # (1) body shown
    assert "rejects-sql-injection-with-400" in captured["summary"]
    assert panel_calls, "cross-family premise panel did not run by default on a model-authored spec"


# --- live smoke: the real, non-monkeypatched _chat against a real llama-swap ---

def test_author_spec_live_smoke():
    """SKIPPED unless ANIMAL_LIVE_MODEL_TEST=1 (see module docstring). When it
    runs, NOTHING is monkeypatched: author_spec calls the real
    animal.product_owner._chat, which hits the real llama-swap URL and the real
    "architect" seat, and the returned spec still has to clear the SAME
    Spec.from_dict + dod.validate_check gate a hand-authored spec faces."""
    if not os.environ.get("ANIMAL_LIVE_MODEL_TEST"):
        print("  skip test_author_spec_live_smoke (set ANIMAL_LIVE_MODEL_TEST=1 to run)")
        return
    repo = _repo()
    spec = product_owner.author_spec(
        "fix calc.add to return the sum, not the difference", str(repo),
        max_retries=2, timeout=900)
    assert spec.user_story and spec.dod, "a real model-authored spec must be non-vacuous"
    spec2 = Spec.from_dict(spec.to_dict())                 # round-trips without SpecError
    assert spec2.dod[0].argv == spec.dod[0].argv


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
