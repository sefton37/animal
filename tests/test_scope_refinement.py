"""Story #465 -- refine_scope: surface and resolve scope ambiguity before a
story is finalized. Deterministic: the enumeration (panel.enumerate_case via
discovery.enumerate_case_default) is monkeypatched; the maker's channel is
scripted; Sandbox / dod.validate_spec run REAL against a temp repo.
Run: python3 tests/test_scope_refinement.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal import discovery
from animal.discovery import refine_scope, MakerAbsent, DISCOVERY_EVENT
from animal.spec import Spec, DoDCheck
from animal.ledger import Ledger


def _repo():
    r = Path(tempfile.mkdtemp(prefix="animal-p465-"))
    (r / "calc.py").write_text("def add(a,b):\n    return a - b\n")
    return r


def _spec():
    return Spec("daily totals: calc.add must sum entries per day",
                intent=["fix add"], out_of_scope=["timezone conversion UI"],
                dod=[DoDCheck("add-sums", ["python3", "-c", "import calc; assert calc.add(2,3)==5"],
                              "exit_zero")])


def _refine(ambiguities, answers, spec=None, ledger=None):
    """Run refine_scope with scripted enumeration + channel; returns
    (result_or_exc, asked_questions)."""
    asked = []
    it = iter(answers)

    def channel(question):
        asked.append(question)
        return next(it)

    orig = discovery.enumerate_case_default
    discovery.enumerate_case_default = lambda spec_, url=None: ambiguities
    try:
        try:
            return refine_scope(spec or _spec(), channel, str(_repo()), ledger=ledger), asked
        except (ValueError, MakerAbsent) as e:
            return e, asked
    finally:
        discovery.enumerate_case_default = orig


def test_refine_scope_folds_the_makers_literal_answer():
    """The AC's planted scenario: 'per day' (UTC vs local); the maker's exact
    words must land in the returned spec -- verbatim, never paraphrased."""
    refined, asked = _refine([{"term": "per day", "assumed_reading": "UTC midnight"}],
                             ["local time, midnight to midnight"])
    assert not isinstance(refined, Exception), refined
    assert len(asked) == 1 and "per day" in asked[0] and "UTC midnight" in asked[0]
    folded = refined.intent + refined.out_of_scope
    assert any("local time, midnight to midnight" in b for b in folded), folded
    assert any("per day" in b for b in folded), "the resolved TERM must be named too"


def test_refine_scope_asks_one_question_per_ambiguity_drops_none():
    refined, asked = _refine(
        [{"term": "per day", "assumed_reading": "UTC"},
         {"term": "entries", "assumed_reading": "one row per add() call"}],
        ["local midnight", "one row per call is right"])
    assert not isinstance(refined, Exception), refined
    assert len(asked) == 2
    folded = " | ".join(refined.intent + refined.out_of_scope)
    assert "local midnight" in folded and "one row per call is right" in folded


def test_refine_scope_out_of_scope_answer_lands_in_out_of_scope():
    refined, _ = _refine([{"term": "multi-user sync", "assumed_reading": "single user"}],
                         ["out of scope: single user only for now"])
    assert not isinstance(refined, Exception), refined
    assert any("multi-user sync" in b for b in refined.out_of_scope), refined.out_of_scope
    assert not any("multi-user sync" in b for b in refined.intent)


def test_refine_scope_no_ambiguities_returns_spec_unchanged():
    spec = _spec()
    refined, asked = _refine([], [], spec=spec)
    assert refined is spec, "nothing changed, nothing rebuilt"
    assert asked == []


def test_refine_scope_original_spec_is_not_mutated():
    spec = _spec()
    before = spec.to_dict()
    refined, _ = _refine([{"term": "per day", "assumed_reading": "UTC"}], ["local"], spec=spec)
    assert not isinstance(refined, Exception)
    assert spec.to_dict() == before, "refine_scope must return a NEW spec, not mutate"
    assert refined is not spec


def test_refine_scope_revalidates_and_raises_on_broken_dod():
    """AC: the amended spec is re-run through dod.validate_spec -- a break is
    caught HERE, loudly, before the maker moves on."""
    real = discovery.validate_spec
    discovery.validate_spec = lambda spec_, sb, repo: {
        "ok": False, "checks": [{"name": "add-sums", "ok": False, "reasons": ["seeded break"]}],
        "n_checks": 1, "n_bad": 1}
    try:
        err, _ = _refine([{"term": "per day", "assumed_reading": "UTC"}], ["local"])
    finally:
        discovery.validate_spec = real
    assert isinstance(err, ValueError), err
    assert "add-sums" in str(err)


def test_refine_scope_maker_absent_propagates():
    """No maker, no refinement -- the harness never invents the resolution."""
    def absent(question):
        raise MakerAbsent("nobody here")

    orig = discovery.enumerate_case_default
    discovery.enumerate_case_default = lambda spec_, url=None: [{"term": "t", "assumed_reading": "a"}]
    try:
        try:
            refine_scope(_spec(), absent, str(_repo()))
            assert False, "expected MakerAbsent to propagate"
        except MakerAbsent:
            pass
    finally:
        discovery.enumerate_case_default = orig


def test_refine_scope_records_the_dialogue_when_given_a_ledger():
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p465-led-"))
    refined, _ = _refine([{"term": "per day", "assumed_reading": "UTC"}],
                         ["local midnight"], ledger=L)
    assert not isinstance(refined, Exception)
    evs = [e for e in L.events_of(DISCOVERY_EVENT) if e.payload["kind"] == "refine"]
    assert len(evs) == 1
    assert evs[0].payload["term"] == "per day"
    assert evs[0].payload["answer"] == "local midnight"


def test_refine_scope_enumeration_failure_raises_never_masks():
    """Audit F1 (HIGH): a dead model plane used to make refine_scope the
    identity function -- 'enumeration failed' indistinguishable from 'no
    ambiguities'. Strict enumeration now raises, loudly."""
    orig = discovery.enumerate_case_default

    def dead(spec_, url=None):
        raise ConnectionError("connection refused")

    discovery.enumerate_case_default = dead
    try:
        try:
            refine_scope(_spec(), lambda q: "x", str(_repo()))
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "enumeration failed" in str(e)
    finally:
        discovery.enumerate_case_default = orig


def test_refine_scope_regrounds_the_refined_spec():
    """Audit F3: maker prose can name an existing-but-not-a-file token (a
    directory) that grounds scan of intent would reject one gate later --
    refine_scope now re-grounds and raises HERE."""
    repo = Path(tempfile.mkdtemp(prefix="animal-p465-"))
    (repo / "calc.py").write_text("def add(a,b):\n    return a - b\n")
    (repo / "conf.d").mkdir()

    orig = discovery.enumerate_case_default
    discovery.enumerate_case_default = lambda spec_, url=None: [
        {"term": "config layout", "assumed_reading": "flat file"}]
    try:
        try:
            refine_scope(_spec(), lambda q: "use the conf.d layout", str(repo))
            assert False, "expected ValueError from re-grounding"
        except ValueError as e:
            assert "conf.d" in str(e)
    finally:
        discovery.enumerate_case_default = orig


def test_refine_scope_none_term_and_empty_answer_are_recorded_skips():
    """Audit F4/F5/F8: a None term must not become the string 'None'; an
    empty answer resolves nothing -- both are ledger-recorded skips, never
    silent drops, never vacuous bullets; all-skipped returns the ORIGINAL."""
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p465-led-"))
    spec = _spec()
    refined, asked = _refine([{"term": None, "assumed_reading": "x"},
                              {"term": "real term", "assumed_reading": "y"}],
                             [""], spec=spec, ledger=L)   # only 'real term' is asked; answer empty
    assert refined is spec, "all-skipped must return the original object"
    assert len(asked) == 1, asked
    kinds = [e.payload["kind"] for e in L.events_of(DISCOVERY_EVENT)]
    assert kinds == ["enumerate", "refine_skipped", "refine_skipped"], kinds


def test_refine_scope_question_cap_is_recorded():
    """Audit F6: the module's thesis is hard-bounded; 50 ambiguities must not
    mean 50 questions."""
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p465-led-"))
    many = [{"term": f"t{i}", "assumed_reading": "r"} for i in range(50)]
    refined, asked = _refine(many, ["a"] * 50, ledger=L)
    assert not isinstance(refined, Exception), refined
    assert len(asked) == 12, len(asked)
    trunc = [e for e in L.events_of(DISCOVERY_EVENT) if e.payload["kind"] == "refine_truncated"]
    assert len(trunc) == 1 and trunc[0].payload["dropped"] == 38, trunc


def test_refine_scope_ledger_records_routing_target():
    """Audit F2: the ledger must say WHICH list each resolution landed on."""
    L = Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-p465-led-"))
    refined, _ = _refine([{"term": "a", "assumed_reading": "r"},
                          {"term": "b", "assumed_reading": "r"}],
                         ["keep it", "out of scope: later"], ledger=L)
    assert not isinstance(refined, Exception), refined
    routes = [e.payload["routed_to"] for e in L.events_of(DISCOVERY_EVENT)
              if e.payload["kind"] == "refine"]
    assert routes == ["intent", "out_of_scope"], routes


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
