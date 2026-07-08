"""Tests for the genuine multi-strategy fuzzy-apply cascade + ambiguity guard
(Story #446, builds on Phase 1's Workspace._locate / Workspace.edit).
Runnable directly (`python3 tests/test_fuzzy_apply.py`) or under pytest.

The story: a model's old_string that differs only by whitespace/indentation
from the real file should still land -- via an explicit, ordered, named
cascade of strategies -- instead of bouncing forever as "old_string not
found". But when a fuzzy match is genuinely ambiguous between two candidate
spots, the cascade must REFUSE, not guess.
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal.workspace import Workspace, AmbiguousMatch, _STRATEGIES
from animal.types import ErrorClass


def _ws_with(name: str, content: str):
    repo = Path(tempfile.mkdtemp(prefix="animal-fuzzy-"))
    (repo / name).write_text(content)
    return repo, Workspace(repo, session_id="t", shadow_root=tempfile.mkdtemp())


# --- the cascade is real: >=4 named, ordered strategies ---

def test_cascade_has_at_least_four_ordered_strategies():
    assert len(_STRATEGIES) >= 4
    assert _STRATEGIES[0] == "exact"      # exact must stay the first, tightest tier
    assert len(set(_STRATEGIES)) == len(_STRATEGIES)   # no duplicate tier names


def test_exact_tier_refuses_ambiguous_duplicate():
    # #446 red-team: old_string matching two byte-identical blocks must REFUSE
    # (ok=False, file untouched), not silently rewrite the first -- the ambiguity
    # guard belongs on the exact tier too, not only the fuzzy tiers.
    pre = ("def validate_username(s):\n    if not s: return False\n    return True\n\n"
           "def validate_email(s):\n    if not s: return False\n    return True\n")
    repo, ws = _ws_with("v.py", pre)
    ws.read("v.py")
    e = ws.edit("v.py", "    if not s: return False\n    return True",
                "    if not s: return False\n    return None")
    assert e.ok is False
    assert (repo / "v.py").read_text() == pre          # nothing landed on the wrong block
    e2 = ws.edit("v.py", "def validate_username(s):", "def check_username(s):")
    assert e2.ok is True                                # a unique anchor still lands


# --- fuzzy hit lands and is labeled (never silently indistinguishable from exact) ---

def test_indentation_mismatch_lands_and_is_labeled():
    pre_edit_content = "def f():\n\tif True:\n\t\treturn 1\n"     # tab-indented on disk
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    # model's old_string is 4-space indented -- cosmetically different, same code
    old = "def f():\n    if True:\n        return 1\n"
    new = "def f():\n    if True:\n        return 2\n"
    e = ws.edit("m.py", old, new)
    assert e.ok is True
    assert e.computed["match_strategy"] != "exact"
    # the matched span is replaced verbatim by new_string (search-replace, not a
    # merge) -- the point of this test is that the mismatched anchor still LANDS
    assert (repo / "m.py").read_text() == new


def test_exact_match_is_labeled_exact():
    pre_edit_content = "def add(a, b):\n    return a + b\n"
    repo, ws = _ws_with("calc.py", pre_edit_content)
    ws.read("calc.py")
    e = ws.edit("calc.py", "return a + b", "return a - b")
    assert e.ok is True
    assert e.computed["match_strategy"] == "exact"


def test_two_space_vs_four_space_reindent_lands():
    pre_edit_content = "class C:\n  def m(self):\n    return 1\n"     # 2-space on disk
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    old = "class C:\n    def m(self):\n        return 1\n"            # model wrote 4-space
    new = "class C:\n    def m(self):\n        return 2\n"
    e = ws.edit("m.py", old, new)
    assert e.ok is True
    assert e.computed["match_strategy"] != "exact"
    assert "return 2" in (repo / "m.py").read_text()


# --- the indentation_agnostic tier itself is real, working code (not decorative) ---
# exercised directly since tier 2 (whitespace_normalized)'s unanchored regex search
# already resolves plain leading-indent drift first in the full cascade -- this
# proves tier 3's own per-physical-line mechanism independently produces the
# same, correct, single span.

def test_indentation_agnostic_tier_matches_directly():
    _, ws = _ws_with("m.py", "def f():\n\tif True:\n\t\treturn 1\n")
    content = (ws.repo / "m.py").read_text()
    needle = "def f():\n    if True:\n        return 1\n"
    span = ws._match_indentation_agnostic(content, needle)
    assert span is not None
    start, end = span
    assert content[start:end] == content


# --- the ambiguity guard: refuse, don't guess ---

def test_ambiguous_fuzzy_match_is_refused():
    pre_edit_content = (
        "def compute_alpha(x):\n"
        "    # step one\n"
        "    total = x * 2\n"
        "    return total\n"
        "\n"
        "def compute_beta(x):\n"
        "    # step one\n"
        "    total = x * 2\n"
        "    return total\n"
    )
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    # a typo'd old_string that is NOT an exact/whitespace/indentation match
    # anywhere, but fuzzy-matches BOTH near-duplicate blocks about equally well
    old = "    # stepp one\n    total = x * 2\n    retun total\n"
    new = "    # step one\n    total = x * 3\n    return total\n"
    e = ws.edit("m.py", old, new)
    assert e.ok is False
    assert e.error_class == ErrorClass.MODEL_CLAIM_FALSE.value
    assert "ambiguous" in e.note
    # refusing to guess means nothing landed
    assert (repo / "m.py").read_text() == pre_edit_content


def test_ambiguous_whitespace_normalized_matches_refused():
    # two verbatim-identical (post-whitespace-normalization) occurrences of the
    # same anchor text -- the whitespace_normalized tier itself must refuse
    # rather than silently apply to the first one.
    pre_edit_content = "if x:\n    return 1\nif x:\n    return 1\n"
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    old = "if x:\n\treturn 1"     # tab, so it skips the plain exact tier
    new = "if x:\n\treturn 2"
    e = ws.edit("m.py", old, new)
    assert e.ok is False
    assert e.error_class == ErrorClass.MODEL_CLAIM_FALSE.value
    assert "ambiguous" in e.note
    assert (repo / "m.py").read_text() == pre_edit_content


def test_ambiguous_non_duplicate_blocks_the_wrong_candidate_scores_higher():
    """Red-team repro (fix iteration on #446): two DIFFERENT, non-duplicate
    functions -- process_alpha (already correct) and process_beta (the
    model's ACTUAL intended target, which has a pre-existing typo:
    'resutl' instead of 'result'). The model's old_string already contains
    the fix it means to apply to beta ('result', spelled correctly, paired
    with beta's own parameter name 'y'). Because old_string is closer,
    character-for-character, to alpha's already-correct text than to
    beta's still-typo'd text, a fixed-absolute-margin ambiguity guard scores
    alpha higher by a gap bigger than any small fixed constant -- and
    confidently (and silently) rewrites the UNINTENDED block (alpha),
    referencing alpha's undefined name `y`, while beta (the real target)
    is left with its original typo. The cascade must refuse this outright:
    two structurally-similar-but-different blocks both clearing the
    line-window floor is exactly the "genuinely unclear which one" case the
    story asks the guard to catch, regardless of the raw score gap between
    them."""
    pre_edit_content = (
        "def process_alpha(x):\n"
        "    result = x + 1\n"
        "    return result\n"
        "\n"
        "def process_beta(y):\n"
        "    resutl = y + 1\n"
        "    return resutl\n"
    )
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    # old_string is neither block's actual on-disk text (not exact/whitespace/
    # indentation-agnostic match anywhere) -- it only fuzzy-matches, and it
    # fuzzy-matches BOTH blocks well enough to clear the line-window floor.
    old = "result = y + 1\n    return result\n"
    new = "result = y + 2\n    return result\n"
    e = ws.edit("m.py", old, new)
    assert e.ok is False
    assert e.error_class == ErrorClass.MODEL_CLAIM_FALSE.value
    assert "ambiguous" in e.note
    # refusing to guess means NEITHER block was touched -- not the wrong one
    # (alpha), not a guess at the right one (beta), nothing at all.
    assert (repo / "m.py").read_text() == pre_edit_content


def test_match_indentation_agnostic_raises_ambiguous_match_directly():
    _, ws = _ws_with("m.py", "def m():\n    return 1\ndef m():\n    return 1\n")
    content = (ws.repo / "m.py").read_text()
    try:
        ws._match_indentation_agnostic(content, "def m():\n\treturn 1")
        assert False, "expected AmbiguousMatch"
    except AmbiguousMatch:
        pass


# --- the disproportionate-match guard still fires at EVERY cascade tier ---

def test_disproportionate_guard_fires_on_a_fuzzy_tier_match():
    pre_edit_content = "def f():\n\tif True:\n\t\treturn 1\n"    # tab-indented on disk
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    old = "def f():\n    if True:\n        return 1\n"   # 4-space -- a fuzzy-tier hit
    new = "x" * 5000                                     # dwarfs the anchor
    e = ws.edit("m.py", old, new)
    assert e.ok is False
    assert e.error_class == ErrorClass.INVARIANT_VIOLATION.value
    assert "disproportionate" in e.note
    assert (repo / "m.py").read_text() == pre_edit_content   # nothing landed


def test_disproportionate_guard_still_fires_on_an_exact_match():
    # regression: the pre-existing guard behavior (exact-match tier) must be unchanged
    pre_edit_content = "def f():\n    return 1\n"
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    e = ws.edit("m.py", "return 1", "x" * 5000)
    assert e.ok is False
    assert e.error_class == ErrorClass.INVARIANT_VIOLATION.value
    assert (repo / "m.py").read_text() == pre_edit_content


# --- old_string genuinely absent (not just fuzzy-mismatched) still reports cleanly ---

def test_no_strategy_matches_reports_not_found():
    pre_edit_content = "def f():\n    return 1\n"
    repo, ws = _ws_with("m.py", pre_edit_content)
    ws.read("m.py")
    e = ws.edit("m.py", "this text is nowhere in the file", "x")
    assert e.ok is False
    assert e.error_class == ErrorClass.MODEL_CLAIM_FALSE.value
    assert (repo / "m.py").read_text() == pre_edit_content


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
