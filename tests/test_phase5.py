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

Story #458 (TDD red-green) tests are appended below the product-owner tests:
deterministic, offline -- animal.worklane.run_task is monkeypatched (same
substitution pattern as animal.product_owner._chat above / animal.panel.run_seat
in test_phase3.py), so no live llama-swap is required to exercise the tester
phase, the harness-computed red gate, and the reject/needs_human/done outcomes.
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal import config
from animal import product_owner
from animal.product_owner import ProductOwnerError
from animal.spec import Spec, DoDCheck
from animal.grounding import ground
from animal.model import ModelPlane, system_prompt_for
import animal.worklane as worklane
import animal.loop as loop
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


# --- Story #458: TDD red-green -- config wiring ---

def test_config_tester_role_reuses_a_provisioned_seat():
    assert config.ROLES["tester"]["model"] in ("coder", "architect", "judge", "auditor")


# --- Story #458: loop.run_task's system_prompt override ---

def test_run_task_system_prompt_param_overrides_default():
    captured = {}

    def fake_call(self, role, messages, temperature=None):
        captured["system"] = messages[0]["content"]
        return ({"thought": "t", "action": {"kind": "finish", "message": "done"}},
                {"context_overflow": False})

    orig = ModelPlane.call
    ModelPlane.call = fake_call
    try:
        loop.run_task("t", str(_repo()), role="coder", system_prompt="CUSTOM TESTER PROMPT MARKER")
    finally:
        ModelPlane.call = orig
    assert captured["system"] == "CUSTOM TESTER PROMPT MARKER"


def test_run_task_system_prompt_default_unchanged():
    """system_prompt=None (every existing caller) must behave EXACTLY as before
    this story -- zero behavior change unless a caller opts in."""
    captured = {}

    def fake_call(self, role, messages, temperature=None):
        captured["system"] = messages[0]["content"]
        return ({"thought": "t", "action": {"kind": "finish", "message": "done"}},
                {"context_overflow": False})

    orig = ModelPlane.call
    ModelPlane.call = fake_call
    try:
        loop.run_task("t", str(_repo()), role="coder")   # no system_prompt override
    finally:
        ModelPlane.call = orig
    assert captured["system"] == system_prompt_for("coder")


# --- Story #458: DoDCheck.expected_new + grounding.ground()'s Gate 0a fix ---

def test_grounding_expected_new_dod_check_not_a_miss():
    spec = Spec("write a failing test first, tests/test_x.py",
               dod=[DoDCheck("t", ["python3", "tests/test_x.py"], "exit_zero", expected_new=True)])
    g = ground(spec, str(_repo()))
    assert g["ok"] and "tests/test_x.py" not in g["misses"]


def test_grounding_missing_path_without_expected_new_is_still_a_miss():
    """The opt-out is per-check, not a blanket loosening of Gate 0a: a check
    that does NOT set expected_new is grounded exactly as before this story."""
    spec = Spec("write a failing test first, tests/test_x.py",
               dod=[DoDCheck("t", ["python3", "tests/test_x.py"], "exit_zero")])   # expected_new=False (default)
    g = ground(spec, str(_repo()))
    assert not g["ok"] and "tests/test_x.py" in g["misses"]


def test_expected_new_dod_check_does_not_reject_at_grounding():
    # Story #458 AC + second-round red-team fix. The AC's letter: "a seeded
    # spec with a DoD check pointing at a not-yet-existing tests/test_x.py and
    # expected_new=True passes grounding (task does not reject at
    # 'grounding')". As first shipped, that was true but INERT: dod._lint's
    # missing-helper check (Gate 0b) independently rejected the same spec one
    # gate later at 'dod_authoring', so the flag's own motivating case never
    # worked end-to-end (two auditors flagged it). Both existence scans now
    # honor expected_new, so the spec must clear grounding AND dod_authoring;
    # a DENYING approver stops the run at the approval gate -- which both
    # proves exactly how far it got and keeps this test offline (no model is
    # ever reached).
    spec = Spec("write a failing test first, tests/test_x.py",
               dod=[DoDCheck("t", ["python3", "tests/test_x.py"], "exit_zero", expected_new=True)])
    r = worklane.run_work(spec, str(_repo()), approver=lambda k, s: "deny", max_turns=2)
    assert r["rejected_at"] == "approval", r


# --- Story #458: worklane.run_work(tdd=True) -- the tester phase + red gate ---

def test_tdd_tester_touching_non_test_file_rejects():
    repo = _repo()
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            # the tester wrongly edits the implementation file directly -- not its job
            (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return a + b\n")
            diff = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
                    "@@\n-    return a - b\n+    return a + b\n")
            return {"run_diff": diff, "turns": 1, "changed": True, "edits_landed": 1}
        raise AssertionError("implementer must never run when the tester touched a non-test path")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "rejected" and r["rejected_at"] == "tester_scope", r
    assert "calc.py" in r["reason"]
    assert calls["coder"] == 0, "implementer step must never run"


def test_tdd_red_confirmed_gate_flags_vacuous_red_as_needs_human():
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            # a vacuous tester: claims to have authored a test file, but its
            # actual side effect (standing in for "the test never really
            # exercised the unimplemented behavior") leaves the DoD check
            # ALREADY passing before the implementer ever runs.
            (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return a + b\n")
            diff = ("diff --git a/tests/test_x.py b/tests/test_x.py\nnew file mode 100644\n"
                    "--- /dev/null\n+++ b/tests/test_x.py\n@@\n+def test_x(): pass\n")
            return {"run_diff": diff, "turns": 1, "changed": True, "edits_landed": 1}
        raise AssertionError("implementer must never run after a vacuous (non-red) tester result")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r
    assert "vacuous red" in r["reason"]
    # the early exit necessarily passes through 'verifying' (building cannot
    # reach needs_human directly), so replay tooling gets an explicit marker
    # to distinguish it from the real post-implementer verify step having run
    assert r.get("vacuous_red") is True, r
    assert calls["coder"] == 0, "implementer step must never run"


def test_tdd_end_to_end_genuine_red_then_green_trajectory():
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            # a genuine test, written under tests/ only -- calc.py is left
            # untouched, so re-running the DoD check right after this step
            # still FAILS (calc.add is still wrong): a real red.
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_add.py").write_text(
                "import calc\nassert calc.add(2, 3) == 5\n")
            diff = ("diff --git a/tests/test_add.py b/tests/test_add.py\nnew file mode 100644\n"
                    "--- /dev/null\n+++ b/tests/test_add.py\n@@\n+assert calc.add(2, 3) == 5\n")
            return {"run_diff": diff, "turns": 1, "changed": True, "edits_landed": 1}
        if role == "coder":
            # the implementer makes the (genuinely red) DoD check pass
            (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return a + b\n")
            return {"run_diff": "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n",
                    "turns": 2, "changed": True, "edits_landed": 1}
        raise AssertionError(f"unexpected role {role!r}")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert calls["tester"] == 1 and calls["coder"] == 1, calls
    assert r["final_state"] == "done", r
    assert r["trajectory"] == ["draft", "grounded", "approved", "building", "verifying", "done"], r["trajectory"]


# --- Story #458 red-team fix: the tester's ARTIFACT is harness-run, never inferred ---

def test_tdd_noop_stub_test_is_rejected_as_vacuous_red():
    """The red-team's ADVERSARIAL CONSTRUCTION: a tester that writes a pure
    no-op stub -- `def test_noop(): pass`, never called, asserting nothing --
    to a REAL file on disk. calc.py is left untouched, so spec.dod (calc.add
    is still broken) genuinely still fails -- the OLD gate, which only
    rechecked spec.dod, would have called this a 'genuine red' and let the
    implementer run. The fix must independently RUN the stub file itself:
    `python3 tests/test_noop.py` exits 0 (the function is defined but never
    called), so it must be refused as vacuous regardless of spec.dod."""
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_noop.py").write_text("def test_noop(): pass\n")
            diff = ("diff --git a/tests/test_noop.py b/tests/test_noop.py\nnew file mode 100644\n"
                    "--- /dev/null\n+++ b/tests/test_noop.py\n@@\n+def test_noop(): pass\n")
            return {"run_diff": diff, "turns": 1, "changed": True, "edits_landed": 1}
        raise AssertionError("implementer must never run after a no-op stub tester result")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r
    assert "vacuous red" in r["reason"], r
    assert calls["coder"] == 0, "implementer step must never run against a no-op stub"


def test_tdd_empty_diff_from_tester_is_rejected_as_vacuous_red():
    """The red-team's STRONGER VARIANT: the tester writes NOTHING at all --
    an empty diff, changed=False. The OLD gate's scope check trivially passes
    (0 bad paths among 0 changed paths) and spec.dod still fails exactly as it
    did before, so the OLD 'genuine red confirmed' fired unconditionally. The
    fix requires a REAL, existing test-file artifact before red can ever be
    confirmed -- an empty diff must be refused."""
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0}
        raise AssertionError("implementer must never run after an empty tester diff")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r
    assert "vacuous red" in r["reason"], r
    assert calls["coder"] == 0, "implementer step must never run against an empty diff"


def test_tdd_green_gate_requires_testers_own_test_to_pass_not_just_dod():
    """Closes the coupling gap: spec.dod is authored independently of whatever
    the tester writes, so a WEAK/gameable DoD check can flip to passing for
    reasons that have nothing to do with the tester's actual test. Here the
    tester's real test asserts calc.add(2,3)==5; the DoD check only asserts
    the result isn't the ORIGINAL broken value (!=-1) -- both genuinely fail
    pre-implementation (a real red on both signals). The implementer then
    'cheats': it returns a hardcoded 99, which satisfies the weak DoD check
    (99 != -1) but fails the tester's own test (99 != 5). GREEN must require
    the tester's own artifact to pass too -- final_state must be
    'needs_human', never 'done'."""
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_real.py").write_text("import calc\nassert calc.add(2, 3) == 5\n")
            diff = ("diff --git a/tests/test_real.py b/tests/test_real.py\nnew file mode 100644\n"
                    "--- /dev/null\n+++ b/tests/test_real.py\n@@\n+assert calc.add(2, 3) == 5\n")
            return {"run_diff": diff, "turns": 1, "changed": True, "edits_landed": 1}
        if role == "coder":
            # cheats: satisfies the WEAK DoD check without fixing the real bug
            (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return 99\n")
            return {"run_diff": "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n",
                    "turns": 2, "changed": True, "edits_landed": 1}
        raise AssertionError(f"unexpected role {role!r}")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "weak-not-broken-value", ["python3", "-c", "import calc; assert calc.add(2,3) != -1"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert calls["tester"] == 1 and calls["coder"] == 1, calls
    assert r["dod_all_pass"] is True, "sanity: the WEAK DoD check alone must be satisfied by the cheat"
    assert r["tester_test_pass"] is False, "the tester's own test must still genuinely fail (99 != 5)"
    assert r["final_state"] == "needs_human", (
        "spec.dod alone was satisfied by the cheat, but the tester's OWN test still "
        f"fails -- GREEN must not be driven by spec.dod alone: {r}")


def test_tdd_default_off_keeps_non_tdd_callers_unchanged():
    """tdd=False (the default) must never invoke a tester role at all."""
    repo = _repo("def add(a,b):\n    return a + b\n")   # already correct
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0}

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero",
            regression=True)])   # already passes pre-work -- opt out of the negative-control
        worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2)  # tdd not passed
    finally:
        worklane.run_task = orig
    assert calls["tester"] == 0, "tdd=False must never run a tester role"
    assert calls["coder"] == 1


# --- Story #458 red-team fixes, SECOND round (pre-commit Gate 3) ---

def test_dod_lint_expected_new_missing_helper_is_not_a_problem():
    """dod._lint's missing-helper check must honor expected_new (without it the
    flag was end-to-end inert -- see test_expected_new_dod_check_does_not_
    reject_at_grounding). The negative-control still runs on the flagged
    check: python3 on a missing file genuinely fails pre-work, so ok=True here
    proves 'lint waived' and NOT 'vacuity waived'."""
    from animal.dod import validate_check
    from animal.sandbox import Sandbox
    repo = _repo()
    sb = Sandbox()
    flagged = DoDCheck("t", ["python3", "tests/test_x.py"], "exit_zero", expected_new=True)
    plain = DoDCheck("t2", ["python3", "tests/test_x.py"], "exit_zero")
    ok = validate_check(flagged, sb, str(repo))
    bad = validate_check(plain, sb, str(repo))
    assert ok["ok"], ok
    assert not bad["ok"] and any("does not exist" in reason for reason in bad["reasons"]), bad


def test_is_test_path_requires_tests_directory():
    """Red-team fix: basename-only matching accepted test_*.py anywhere (repo
    root, inside the package tree) -- broader than the tests/test_*.py contract
    TESTER_SYSTEM_PROMPT promises. The directory is now part of the predicate."""
    assert worklane._is_test_path("tests/test_x.py")
    assert worklane._is_test_path("tests/sub/test_y.py")
    assert not worklane._is_test_path("test_root.py")
    assert not worklane._is_test_path("animal/test_evil.py")
    assert not worklane._is_test_path("tests/helper.py")


def test_tdd_tester_test_file_outside_tests_dir_rejects():
    """The worklane consequence of the anchored predicate: a 'test' file the
    tester drops inside the package tree is a scope violation, exactly like
    editing an implementation file."""
    repo = _repo()
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            (Path(repo_) / "test_evil.py").write_text("import calc\nassert calc.add(2,3)==5\n")
            return {"run_diff": "diff --git a/test_evil.py b/test_evil.py\n",
                    "changed_paths": ["test_evil.py"],
                    "turns": 1, "changed": True, "edits_landed": 1}
        raise AssertionError("implementer must never run when the tester wrote outside tests/")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "rejected" and r["rejected_at"] == "tester_scope", r
    assert "test_evil.py" in r["reason"], r
    assert calls["coder"] == 0


def test_workspace_changed_paths_are_never_git_quoted():
    """Red-team fix: plain `git diff --name-only` applies core.quotePath to any
    non-ASCII byte in a filename ("c\\303\\244lc.py"), so a consumer matching or
    resolving the printed name silently loses the file -- demonstrated
    bypassing the tester-scope gate. changed_paths now uses -z (NUL-separated
    raw bytes): the real filename must come back verbatim."""
    from animal.workspace import Workspace
    repo = _repo()
    # shadow_root must live OUTSIDE the repo: a custom GIT_DIR is not
    # auto-excluded the way `.git` is, so an in-repo shadow would see its own
    # object store as changed paths
    ws = Workspace(str(repo), "t-quotepath",
                   shadow_root=tempfile.mkdtemp(prefix="animal-p5-shadow-"))
    t0 = ws.snapshot()
    (repo / "cälc.py").write_text("x = 1\n")
    t1 = ws.snapshot()
    assert ws.changed_paths(t0, t1) == ["cälc.py"]


def test_tdd_scope_gate_sees_nonascii_non_test_path():
    """The worklane side of the quotePath fix: run_diff's text header quotes
    the smuggled filename (the old regex parser never saw it -- bad=[] and the
    file rode through to the implementer), but _tester_phase now consumes the
    harness-computed changed_paths key, so the same edit must reject."""
    repo = _repo()
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            (Path(repo_) / "cälc.py").write_text("x = 1\n")
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_add.py").write_text("import calc\nassert calc.add(2, 3) == 5\n")
            # exactly what the REAL run_task emits for this tree: a QUOTED
            # header in run_diff (invisible to the fallback regex) plus the
            # raw-bytes changed_paths list (the fix)
            quoted = ('diff --git "a/c\\303\\244lc.py" "b/c\\303\\244lc.py"\nnew file mode 100644\n'
                      '--- /dev/null\n+++ "b/c\\303\\244lc.py"\n@@\n+x = 1\n'
                      "diff --git a/tests/test_add.py b/tests/test_add.py\nnew file mode 100644\n"
                      "--- /dev/null\n+++ b/tests/test_add.py\n@@\n+assert calc.add(2, 3) == 5\n")
            return {"run_diff": quoted, "changed_paths": ["cälc.py", "tests/test_add.py"],
                    "turns": 1, "changed": True, "edits_landed": 1}
        raise AssertionError("implementer must never run when the tester smuggled a non-test path")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "rejected" and r["rejected_at"] == "tester_scope", r
    assert "cälc.py" in r["reason"], r
    assert calls["coder"] == 0


def test_tdd_implementer_rewriting_testers_test_cannot_reach_done():
    """THE second-round blocker: GREEN used to re-run the tester's test by
    PATH only, so an implementer that (a) games a weak spec.dod check AND
    (b) rewrites the tester's test file to a no-op reached 'done' with
    tester_test_pass=True -- 'the SAME executable artifact' was a path-spelling
    assumption, not a computed fact (and fix-the-failing-test is plausible
    WEAK-model behavior, not only an adversarial one). With the file sha-pinned
    at RED, the pin mismatch must fail tester_test_pass and route to
    needs_human, naming the modified path in the summary."""
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_real.py").write_text("import calc\nassert calc.add(2, 3) == 5\n")
            return {"run_diff": "diff --git a/tests/test_real.py b/tests/test_real.py\n",
                    "changed_paths": ["tests/test_real.py"],
                    "turns": 1, "changed": True, "edits_landed": 1}
        if role == "coder":
            # the cheat: satisfy the WEAK DoD check AND gut the tester's test
            # (the gutted file runs clean, so without the pin GREEN sees it 'pass')
            (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return 99\n")
            (Path(repo_) / "tests" / "test_real.py").write_text("pass\n")
            return {"run_diff": ("diff --git a/calc.py b/calc.py\n"
                                 "diff --git a/tests/test_real.py b/tests/test_real.py\n"),
                    "changed_paths": ["calc.py", "tests/test_real.py"],
                    "turns": 2, "changed": True, "edits_landed": 2}
        raise AssertionError(f"unexpected role {role!r}")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "weak-not-broken-value", ["python3", "-c", "import calc; assert calc.add(2,3) != -1"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert calls["tester"] == 1 and calls["coder"] == 1, calls
    assert r["dod_all_pass"] is True, "sanity: the weak DoD alone IS satisfied by the cheat"
    assert r["tester_test_pass"] is False, r
    assert r["tester_artifact_modified"] == ["tests/test_real.py"], r
    assert r["final_state"] == "needs_human", r


# --- Story #458 red-team fixes, THIRD round (verification of round two) ---

def test_workspace_changed_paths_report_both_rename_endpoints():
    """Red-team fix: git's default rename detection reports ONLY the
    destination name for a detected rename, so `mv calc.py tests/test_calc.py`
    collapsed to the (scope-legal) destination and the deletion of the
    implementation file was invisible to the tester-scope gate. --no-renames
    must report both endpoints."""
    from animal.workspace import Workspace
    repo = _repo()
    ws = Workspace(str(repo), "t-rename",
                   shadow_root=tempfile.mkdtemp(prefix="animal-p5-shadow-"))
    t0 = ws.snapshot()
    # a byte-identical move -- exactly what triggers rename detection (R100)
    tests_dir = repo / "tests"; tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_calc.py").write_text((repo / "calc.py").read_text())
    (repo / "calc.py").unlink()
    t1 = ws.snapshot()
    assert set(ws.changed_paths(t0, t1)) == {"calc.py", "tests/test_calc.py"}


def test_workspace_changed_paths_invalid_utf8_name_does_not_crash():
    """Red-team fix: -z emits RAW filename bytes; strict decoding raised
    UnicodeDecodeError from inside every ShellAction's lint gate for a
    model-creatable invalid-UTF-8 filename, killing the whole run (no
    envelope, no SESSION_END). surrogateescape decoding must return a name
    that still resolves to the real file through Path()."""
    import os
    from animal.workspace import Workspace
    repo = _repo()
    ws = Workspace(str(repo), "t-rawbytes",
                   shadow_root=tempfile.mkdtemp(prefix="animal-p5-shadow-"))
    t0 = ws.snapshot()
    with open(os.path.join(str(repo).encode(), b"c\xe4lc.py"), "wb") as f:
        f.write(b"x = 1\n")
    t1 = ws.snapshot()
    changed = ws.changed_paths(t0, t1)   # must not raise
    assert len(changed) == 1, changed
    assert (Path(repo) / changed[0]).is_file(), changed


def test_tdd_self_rewriting_tester_test_cannot_reach_done():
    """THE third-round catch: with pins taken AFTER the RED run, a tester test
    that rewrites ITSELF to a no-op during its own execution (red once, clean
    forever after) got its post-mutation bytes pinned -- GREEN's pin matched
    and a false 'done' was demonstrated against a weak spec.dod. Pinned
    BEFORE the run, the self-mutation is a pin mismatch at GREEN and must
    route to needs_human naming the file."""
    repo = _repo()   # calc.add is broken (a - b) on disk
    calls = {"tester": 0, "coder": 0}
    sneaky = ("from pathlib import Path\n"
              "me = Path(__file__)\n"
              "me.write_text('pass\\n')\n"
              "raise AssertionError('red once, clean forever after')\n")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        calls[role] = calls.get(role, 0) + 1
        if role == "tester":
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_sneaky.py").write_text(sneaky)
            return {"run_diff": "diff --git a/tests/test_sneaky.py b/tests/test_sneaky.py\n",
                    "changed_paths": ["tests/test_sneaky.py"],
                    "turns": 1, "changed": True, "edits_landed": 1}
        if role == "coder":
            # games the WEAK DoD without touching the (already self-gutted) test
            (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return 99\n")
            return {"run_diff": "diff --git a/calc.py b/calc.py\n",
                    "changed_paths": ["calc.py"],
                    "turns": 2, "changed": True, "edits_landed": 1}
        raise AssertionError(f"unexpected role {role!r}")

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "weak-not-broken-value", ["python3", "-c", "import calc; assert calc.add(2,3) != -1"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2, tdd=True)
    finally:
        worklane.run_task = orig
    assert calls["tester"] == 1 and calls["coder"] == 1, calls
    assert r["dod_all_pass"] is True, "sanity: the weak DoD alone IS satisfied by the cheat"
    assert r["tester_test_pass"] is False, r
    assert r["tester_artifact_modified"] == ["tests/test_sneaky.py"], r
    assert r["final_state"] == "needs_human", r


# --- Story #459: the verifier gate -- claimed-vs-verified into calibration ---

def _verifier_events(summary):
    events = [json.loads(l) for l in Path(summary["ledger"]).read_text().splitlines()]
    return [e for e in events if e["type"] == "gate" and e["payload"].get("gate") == "verifier"]


def test_verifier_gate_records_model_claim_false():
    """The founding-incident class as DATA: the model claims completion
    (finished=True) but the harness's DoD verdict refutes it. The calibration
    row for (model, role, 'task_complete') must gain n WITHOUT n_true, and the
    ledger's verifier GATE must carry error_class=model_claim_false."""
    from animal.calibration import Calibration
    repo = _repo()   # calc.add is broken (a - b) on disk
    caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0,
                "finished": True}   # the model CLAIMS completion...

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              calibration_db=caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r        # ...the harness says no
    cal = Calibration(db_path=caldb)
    rate = cal.rate("coder", "coder", "task_complete")
    cal.close()
    assert rate["n"] == 1 and rate["p"] == 0.0, rate   # n incremented, n_true unchanged
    ver = _verifier_events(r)
    assert len(ver) == 1, ver
    p = ver[0]["payload"]
    assert p["claimed_done"] is True and p["verified_true"] is False, p
    assert p["error_class"] == "model_claim_false", p
    assert p["calibration_recorded"] is True, p


def test_verifier_gate_records_verified_true_claim():
    """The happy path: claim AND harness verdict agree -> verified_true=True,
    n and n_true both increment, error_class stays none."""
    from animal.calibration import Calibration
    repo = _repo("def add(a,b):\n    return a + b\n")   # already correct
    caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0,
                "finished": True}

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero",
            regression=True)])   # passes pre-work by design -- opt out of the negative-control
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              calibration_db=caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "done", r
    cal = Calibration(db_path=caldb)
    rate = cal.rate("coder", "coder", "task_complete")
    cal.close()
    assert rate["n"] == 1 and rate["p"] == 1.0, rate
    p = _verifier_events(r)[0]["payload"]
    assert p["claimed_done"] is True and p["verified_true"] is True, p
    assert p["error_class"] == "none", p


def test_verifier_gate_no_claim_records_nothing_and_state_unchanged():
    """AC read-only clause, both directions: (a) a run with NO claim
    (finished absent -- max_turns/stuck) still reaches 'done' purely on the
    harness verdict, proving the state transition ignores claimed_done; and
    (b) a no-claim run writes NO calibration row at all -- it says nothing
    about the model's claim reliability. Together with
    test_verifier_gate_records_model_claim_false (claim=True + verdict=False
    -> needs_human), every claim/verdict combination lands exactly where
    all_pass alone dictates."""
    from animal.calibration import Calibration
    repo = _repo("def add(a,b):\n    return a + b\n")   # already correct
    caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0}  # no finish claim

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero",
            regression=True)])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              calibration_db=caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "done", r               # state driven by the verdict alone
    cal = Calibration(db_path=caldb)
    rate = cal.rate("coder", "coder", "task_complete")
    cal.close()
    assert rate["n"] == 0, rate                        # no claim -> no calibration row
    p = _verifier_events(r)[0]["payload"]
    assert p["claimed_done"] is False and p["verified_true"] is False, p
    assert p["error_class"] == "none", p
    assert p["calibration_recorded"] is None, p        # no claim -> nothing to record


# --- Story #459 red-team fixes: observational purity + faithful attribution ---

def test_verifier_gate_calibration_failure_cannot_change_the_outcome():
    """THE red-team blocker: an unguarded calibration write between the
    dod_verify gate and the state transition crashed the whole run on any
    sqlite unavailability -- and only when the model CLAIMED, so the model's
    own claim determined run survival, and the run preferentially killed was
    exactly the model_claim_false run this gate exists to capture. The write
    is now crash-proof: the run must complete to its harness-driven state,
    with the failure recorded IN the verifier GATE event."""
    repo = _repo()   # calc.add is broken (a - b) on disk
    bad_caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "no" / "such" / "dir" / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0,
                "finished": True}   # the model claims -- previously the fatal combination

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              calibration_db=bad_caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r        # run SURVIVED to its harness verdict
    p = _verifier_events(r)[0]["payload"]
    assert p["error_class"] == "model_claim_false", p  # the claim verdict is still recorded...
    assert p["calibration_recorded"] is False, p       # ...and the write failure is data,
    assert "calibration_error" in p, p                 # not a control-flow event


def test_verifier_gate_tester_artifact_fault_not_charged_to_implementer():
    """Red-team attribution fix: under tdd=True, an implementer that TRUTHFULLY
    completes the spec (dod passes) but is blocked by the tester's own
    out-of-scope test (genuine red, unsatisfiable within spec scope, artifact
    untouched) must not have its task_complete row charged -- that failure is
    the TESTER's artifact quality. The event names other_actor_fault; the
    exclusion taxonomy keeps the row empty; the task still lands needs_human
    on the harness verdict exactly as before."""
    from animal.calibration import Calibration
    repo = _repo()   # calc.add is broken (a - b) on disk
    caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        if role == "tester":
            # out-of-scope: asserts a function the spec never asked for --
            # genuinely red now AND after a truthful implementation
            tests_dir = Path(repo_) / "tests"; tests_dir.mkdir(exist_ok=True)
            (tests_dir / "test_scope.py").write_text("import calc\nassert calc.mul(2, 3) == 6\n")
            return {"run_diff": "diff --git a/tests/test_scope.py b/tests/test_scope.py\n",
                    "changed_paths": ["tests/test_scope.py"],
                    "turns": 1, "changed": True, "edits_landed": 1}
        # the implementer TRUTHFULLY makes the spec's DoD pass and claims so
        (Path(repo_) / "calc.py").write_text("def add(a,b):\n    return a + b\n")
        return {"run_diff": "diff --git a/calc.py b/calc.py\n", "changed_paths": ["calc.py"],
                "turns": 2, "changed": True, "edits_landed": 1, "finished": True}

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              tdd=True, calibration_db=caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r        # harness verdict unchanged
    assert r["dod_all_pass"] is True and r["tester_test_pass"] is False, r
    p = _verifier_events(r)[0]["payload"]
    assert p["error_class"] == "other_actor_fault", p
    cal = Calibration(db_path=caldb)
    rate = cal.rate("coder", "coder", "task_complete")
    cal.close()
    assert rate["n"] == 0, rate                        # excluded: not the implementer's conduct


def test_verifier_gate_env_fault_not_charged_to_implementer():
    """Red-team attribution fix: a DoD check that fails because its command
    could not run at all (exit 127) is the environment's fault, not a false
    claim -- error_class env_mismatch, excluded from the implementer's row."""
    from animal.calibration import Calibration
    repo = _repo()
    caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0,
                "finished": True}

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("run the thing", dod=[DoDCheck(
            "env-check", ["bash", "-c", "animal_definitely_missing_cmd_xyz"], "exit_zero")])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              calibration_db=caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "needs_human", r
    p = _verifier_events(r)[0]["payload"]
    assert p["error_class"] == "env_mismatch", p
    cal = Calibration(db_path=caldb)
    rate = cal.rate("coder", "coder", "task_complete")
    cal.close()
    assert rate["n"] == 0, rate                        # excluded: not the model's fault


def test_learn_uses_the_same_calibration_db_and_role():
    """Red-team split-brain fix: learn=True must ingest into the SAME
    calibration_db the verifier gate used (a bare Calibration() split one
    run's rows across two databases), attributed to the implementer_role the
    gate used (the shared ledger's first session_start has no role, so the
    old heuristic silently fell back to 'coder')."""
    from animal.calibration import Calibration
    repo = _repo("def add(a,b):\n    return a + b\n")   # already correct
    caldb = str(Path(tempfile.mkdtemp(prefix="animal-p5-cal-")) / "learning.db")

    def fake_run_task(task, repo_, role="coder", checks=None, ledger=None, max_turns=None,
                      include_repo_map=False, system_prompt=None):
        if ledger is not None:   # make the ledger carry one action->envelope pair to ingest
            from animal.types import EventType
            ledger.append(EventType.ACTION, {"kind": "read"})
            ledger.append(EventType.ENVELOPE, {"ok": True, "error_class": "none"})
        return {"run_diff": "", "turns": 1, "changed": False, "edits_landed": 0,
                "finished": True}

    orig = worklane.run_task
    worklane.run_task = fake_run_task
    try:
        spec = Spec("add must sum", dod=[DoDCheck(
            "add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"], "exit_zero",
            regression=True)])
        r = worklane.run_work(spec, str(repo), approver=lambda k, s: "approve", max_turns=2,
                              learn=True, implementer_role="architect", calibration_db=caldb,
                              ledger_dir=tempfile.mkdtemp(prefix="animal-p5-led-"))
    finally:
        worklane.run_task = orig
    assert r["final_state"] == "done", r
    cal = Calibration(db_path=caldb)
    task_rate = cal.rate("architect", "architect", "task_complete")
    action_rate = cal.rate("architect", "architect", "read")
    cal.close()
    assert task_rate["n"] == 1, task_rate              # the verifier gate's row...
    assert action_rate["n"] == 1, action_rate          # ...and learn's ingest, SAME db, SAME role


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
