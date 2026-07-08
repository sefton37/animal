"""Story #449 -- repo map (tree-sitter-fallback field-scan) for file/symbol
discovery. Covers: (1) build_repo_map finds every fixture symbol across a
3-file, multi-language fixture (proving the stdlib ast/regex fallback works,
not just the .py path); (2) the token budget is respected AND truncation is
never silent -- an under-budget run has no truncation marker, an
over-budget run stays near budget and says so explicitly; (3) run_task
actually wires the map into the FIRST prompt when include_repo_map=True, and
leaves it out (byte-for-byte unaffected callers) when the flag is left at
its default (False); (4) REACHABILITY -- a red-team rejection of this
story's first attempt found the flag defaulted off everywhere and was never
set True at any real call site (animal/cli.py, animal/worklane.py,
animal/candidates.py), so every actual invocation of the harness sent an
unchanged prompt. The fix wires each real call site to default the map ON;
the tests below prove each site independently, the same way the red-team's
own grep did.

Deterministic: no live model server required (run_task's ModelPlane is
monkeypatched to a scripted stand-in, the same pattern
test_rollback_resample.py uses). Run: python3 tests/test_repomap.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (candidates.sample_candidates creates a default-path
# Ledger; without this each suite run leaks it into production var/ledger).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal import repomap
import animal.loop as loop
import animal.cli as cli
from animal.ledger import Ledger

FIXTURE_SYMBOLS = ["alpha", "Beta", "gamma", "Delta", "epsilon", "Zeta"]


def _make_fixture() -> Path:
    """3 files, 3 different languages, known top-level function/class names --
    proves the map is language-agnostic best-effort, not python-only."""
    d = Path(tempfile.mkdtemp(prefix="animal-repomap-"))
    (d / "fixture1.py").write_text(
        "def alpha():\n    return 1\n\n\nclass Beta:\n    def method(self):\n        return 2\n"
    )
    (d / "fixture2.js").write_text(
        "function gamma() {\n  return 3;\n}\n\nclass Delta {\n  method() {}\n}\n"
    )
    (d / "fixture3.kt").write_text(
        "fun epsilon() {\n}\n\nclass Zeta {\n}\n"
    )
    return d


def test_build_repo_map_finds_every_fixture_symbol():
    fixture = _make_fixture()
    out = repomap.build_repo_map(str(fixture), max_tokens=1000)
    for name in FIXTURE_SYMBOLS:
        assert name in out, f"missing symbol {name!r} in repo map:\n{out}"


def test_map_ranks_by_symbol_count_when_truncated():
    # #449 red-team: a truncated map must show the MEATIEST files, not an arbitrary
    # alphabetical prefix. z_many.py (10 symbols, alphabetically LAST) must survive a
    # tight budget while the symbol-poor alphabetical-first files are truncated -- the
    # opposite of what the old sorted-path cutoff did (it dropped z_many first).
    d = Path(tempfile.mkdtemp(prefix="animal-repomap-rank-"))
    for name in ("a_one.py", "b_one.py", "c_one.py", "d_one.py"):
        (d / name).write_text("def only():\n    return 1\n")            # 1 symbol, alpha-first
    (d / "z_many.py").write_text("".join(f"def s{i}():\n    return {i}\n\n" for i in range(10)))
    small = repomap.build_repo_map(str(d), max_tokens=25)               # can't fit all 5
    assert "z_many.py" in small, f"meaty file dropped under budget:\n{small}"
    assert "truncated" in small                                        # truncation is signalled
    assert small.count(".py:") < 5                                     # not every file shown


def test_under_budget_produces_no_truncation_marker():
    fixture = _make_fixture()
    out = repomap.build_repo_map(str(fixture), max_tokens=1000)
    assert "truncated" not in out


def test_over_budget_truncates_explicitly_and_stays_near_budget():
    fixture = _make_fixture()
    budget = 16   # enough for the header + ~2 of the 3 file blocks, not all 3
    out = repomap.build_repo_map(str(fixture), max_tokens=budget)
    assert "truncated" in out, f"expected explicit truncation marker:\n{out}"
    words = len(out.split())
    slack = 50   # the truncation notice + header are a handful of extra words --
                 # "reasonable slack" per the DoD, never an unbounded blow-out
    assert words <= budget + slack, f"truncated output ballooned to {words} words for budget={budget}"


def test_exactly_one_build_repo_map_definition():
    # the DoD's own grep check, run here too so a regression is caught by the suite
    src = Path(repomap.__file__).read_text()
    matches = [l for l in src.splitlines() if l.startswith("def build_repo_map")]
    assert len(matches) == 1


class _CaptureModelPlane:
    """Deterministic stand-in for ModelPlane: captures the messages list on
    its FIRST call (proving what the loop actually sent, not what it claims
    to send) and immediately finishes. Same monkeypatch-in-finally style
    test_rollback_resample.py uses."""
    def __init__(self):
        self.first_messages = None

    def call(self, role, messages, temperature=None):
        if self.first_messages is None:
            self.first_messages = [dict(m) for m in messages]
        return {"thought": "done", "action": {"kind": "finish", "message": "done"}}, {"context_overflow": False}


def _run_with_capture(fixture: Path, **kwargs):
    orig = loop.ModelPlane
    plane = _CaptureModelPlane()
    loop.ModelPlane = lambda *a, **kw: plane
    ledger_dir = tempfile.mkdtemp(prefix="animal-repomap-ledger-")
    try:
        loop.run_task("t", str(fixture), ledger=Ledger(ledger_dir=ledger_dir), max_turns=3, **kwargs)
    finally:
        loop.ModelPlane = orig
    return plane


def test_run_task_includes_repo_map_in_first_prompt_when_flag_enabled():
    fixture = _make_fixture()
    plane = _run_with_capture(fixture, include_repo_map=True)
    assert plane.first_messages is not None
    first_prompt_text = " ".join(m["content"] for m in plane.first_messages[:2])
    assert "repo map" in first_prompt_text
    # at least one real fixture symbol must actually be present, not just the header
    assert any(name in first_prompt_text for name in FIXTURE_SYMBOLS), \
        f"repo map header present but no fixture symbol found:\n{first_prompt_text}"


def test_run_task_omits_repo_map_by_default():
    fixture = _make_fixture()
    plane = _run_with_capture(fixture)   # include_repo_map left at its default (False)
    assert plane.first_messages is not None
    first_prompt_text = " ".join(m["content"] for m in plane.first_messages[:2])
    assert "repo map" not in first_prompt_text


# --- reachability (fix iteration): every REAL call site must actually pass
# include_repo_map=True by default, not just run_task's own bare signature ---

def test_worklane_build_step_includes_repo_map_by_default():
    """The gated work-lane's real coder build step (worklane.run_work) is a
    real invocation the harness makes on every approved spec -- it must see
    the repo map with no extra opt-in from the caller."""
    from animal.spec import Spec, DoDCheck
    from animal.worklane import run_work
    fixture = _make_fixture()
    (fixture / "target.py").write_text("def add(a, b):\n    return a - b\n")  # buggy pre-work (not vacuous)
    plane = _CaptureModelPlane()
    orig = loop.ModelPlane
    loop.ModelPlane = lambda *a, **kw: plane
    ledger_dir = tempfile.mkdtemp(prefix="animal-repomap-worklane-")
    try:
        spec = Spec("fix add so it sums", dod=[DoDCheck(
            "sums", ["python3", "-c", "import target; assert target.add(2,3)==5"], "exit_zero")])
        # calibration_db redirect (#459): this scripted plane CLAIMS finish, so
        # without it the verifier gate would write a fabricated task_complete
        # row into the real var/learning.db on every suite run
        run_work(spec, str(fixture), approver=lambda k, s: "approve", ledger_dir=ledger_dir, max_turns=3,
                 calibration_db=str(Path(ledger_dir) / "learning.db"))
    finally:
        loop.ModelPlane = orig
    assert plane.first_messages is not None, "the build step never reached the model call"
    first_prompt_text = " ".join(m["content"] for m in plane.first_messages[:2])
    assert "repo map" in first_prompt_text
    assert any(name in first_prompt_text for name in FIXTURE_SYMBOLS)


def test_candidates_sample_includes_repo_map_by_default():
    """The patch-farm's real coding attempts (candidates.sample_candidates) must
    each see the repo map with no extra opt-in from the caller."""
    from animal import candidates
    fixture = _make_fixture()
    plane = _CaptureModelPlane()
    orig = loop.ModelPlane
    loop.ModelPlane = lambda *a, **kw: plane
    try:
        candidates.sample_candidates("fix it", str(fixture), k=1, max_turns=2)
    finally:
        loop.ModelPlane = orig
    assert plane.first_messages is not None
    first_prompt_text = " ".join(m["content"] for m in plane.first_messages[:2])
    assert "repo map" in first_prompt_text
    assert any(name in first_prompt_text for name in FIXTURE_SYMBOLS)


def test_cli_run_includes_repo_map_by_default_and_no_repo_map_opts_out():
    """The CLI is the harness's one user-facing entry point (`python3 -m
    animal.cli run "<task>" --repo <path>`). Prove args.repo_map defaults True
    and is threaded into run_task's include_repo_map kwarg, and that
    --no-repo-map flips it -- without needing a live model server."""
    import io, contextlib
    captured = {}

    def _stub(task, repo, role="coder", checks=None, max_turns=None, include_repo_map=False):
        captured["include_repo_map"] = include_repo_map
        return {"checks": [], "run_diff": ""}

    orig = cli.run_task
    cli.run_task = _stub
    fixture = _make_fixture()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["run", "t", "--repo", str(fixture)])
        assert captured["include_repo_map"] is True, \
            "python3 -m animal.cli run must include the repo map by default (Story #449 fix)"
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["run", "t", "--repo", str(fixture), "--no-repo-map"])
        assert captured["include_repo_map"] is False
    finally:
        cli.run_task = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
