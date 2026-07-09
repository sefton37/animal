"""Stories #467/#468 -- the planning-poker panel + human-escalated
convergence. Deterministic, offline: estimate_story / panel._chat are
monkeypatched (the test_phase3 substitution pattern); the escalation channel
is a scripted callable. Run: python3 tests/test_poker.py
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR (suite convention -- production stores stay untouched).
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

import animal.poker as poker
from animal.poker import aggregate_votes, converge, run_panel, ESTIMATOR_SEATS, FIB
from animal.ledger import Ledger


def _ledger():
    return Ledger(ledger_dir=tempfile.mkdtemp(prefix="animal-poker-led-"))


# --- #467: seats, independence, aggregation ---

def test_estimator_seats_are_the_measured_decorrelated_lineages():
    """O4 by reference: the estimation panel is the SAME three seats Phase 3
    measured at pairwise co-failure phi<0 -- a roster change cannot fork them."""
    import animal.panel as panel
    assert [s["name"] for s in ESTIMATOR_SEATS] == [s["name"] for s in panel.JUDGE_SEATS]
    assert len({s["lineage"] for s in ESTIMATOR_SEATS}) == 3


def test_points_schema_is_the_fibonacci_enum():
    assert poker._POINTS_SCHEMA["properties"]["points"]["enum"] == [1, 2, 3, 5, 8, 13, 21]
    assert set(FIB) == {1, 2, 3, 5, 8, 13, 21}


def test_aggregate_votes_index_median_and_spread():
    r = aggregate_votes([3, 5, 8])
    assert r["median"] == 5 and r["disagreement"] == 2, r          # AC's own case
    r = aggregate_votes([5, 5, 8])
    assert r["median"] == 5 and r["disagreement"] == 1, r
    r = aggregate_votes([1, 3, 21])
    assert r["median"] == 3 and r["disagreement"] == 6, r
    r = aggregate_votes([8])
    assert r["median"] == 8 and r["disagreement"] == 0, r
    # even count: LOWER middle -- always a real Fibonacci value, never a mean
    r = aggregate_votes([3, 5])
    assert r["median"] == 3 and r["disagreement"] == 1, r


def test_aggregate_votes_excludes_abstains_and_junk():
    r = aggregate_votes([5, None, "?", 4, 8])   # 4 is not Fibonacci; None/'?' abstain
    assert r["median"] == 5 and r["disagreement"] == 1, r
    r = aggregate_votes([None, None, None])
    assert r == {"median": None, "disagreement": None}, r
    assert aggregate_votes([]) == {"median": None, "disagreement": None}


def test_run_panel_collects_independent_votes():
    """One call per seat, no seat sees another's answer, abstains recorded."""
    seen_prompts = []

    def fake_estimate(seat, story, url=None):
        seen_prompts.append((seat["name"], str(story)))
        return {"gpt-oss": {"points": 5, "reasoning": "medium"},
                "mistral": {"points": 5, "reasoning": "clear"},
                "qwen": {"points": None, "reasoning": "abstain: timeout"}}[seat["name"]]

    orig = poker.estimate_story
    poker.estimate_story = fake_estimate
    try:
        out = run_panel({"title": "t", "user_story": "u"})
    finally:
        poker.estimate_story = orig
    assert out["gpt-oss"]["points"] == 5 and out["qwen"]["points"] is None
    assert len(seen_prompts) == 3
    # independence: every seat saw the STORY, never another seat's vote
    assert all("points" not in p for _, p in seen_prompts)


def test_estimate_story_rejects_non_fibonacci_points():
    """A seat whose reply somehow carries a non-Fibonacci number abstains --
    the scale is the contract, junk is never a vote."""
    orig = poker._panel._chat
    poker._panel._chat = lambda *a, **kw: '{"points": 4, "reasoning": "four-ish"}'
    try:
        r = poker.estimate_story(ESTIMATOR_SEATS[0], {"title": "t", "user_story": "u"})
    finally:
        poker._panel._chat = orig
    assert r["points"] is None, r


def test_estimate_story_model_error_is_an_abstain():
    def boom(*a, **kw):
        raise ConnectionError("refused")
    orig = poker._panel._chat
    poker._panel._chat = boom
    try:
        r = poker.estimate_story(ESTIMATOR_SEATS[0], {"title": "t", "user_story": "u"})
    finally:
        poker._panel._chat = orig
    assert r["points"] is None and "abstain" in r["reasoning"]


# --- #468: convergence is a human decision ---

def test_converge_low_disagreement_never_touches_the_human():
    calls = []
    ch = lambda k, s: (calls.append(1) or "approve")
    r = converge(None, [5, 5, 8], approvals=ch, ledger=_ledger())
    assert r["points"] == 5 and r["escalated"] is False, r
    assert calls == [], "the human must not be interrupted below the threshold"


def test_converge_high_disagreement_escalates_exactly_once():
    calls = []
    ch = lambda k, s: (calls.append((k, s)) or "13")
    r = converge({"title": "big one"}, [1, 3, 21], approvals=ch, ledger=_ledger())
    assert r["escalated"] is True and r["points"] == 13, r
    assert len(calls) == 1
    key, summary = calls[0]
    assert "big one" in summary and "[1, 3, 21]" in summary, summary


def test_converge_all_abstain_always_escalates():
    """'The panel could not size' must never silently become a size -- the
    #460 all-abstain lesson applied to estimation."""
    calls = []
    ch = lambda k, s: (calls.append(1) or "5")
    r = converge(None, [None, None, None], approvals=ch, ledger=_ledger())
    assert r["escalated"] is True and r["points"] == 5 and calls == [1], r


def test_converge_non_fibonacci_human_reply_stays_unresolved():
    """The human's reply is parsed, validated against the scale, and an
    invalid answer leaves the story honestly unsized -- never guessed."""
    r = converge(None, [1, 3, 21], approvals=lambda k, s: "approve", ledger=_ledger())
    assert r["escalated"] is True and r["points"] is None, r
    r = converge(None, [1, 3, 21], approvals=lambda k, s: "4", ledger=_ledger())
    assert r["points"] is None, r


def test_converge_has_no_model_side_resolution_path():
    """The architecture's no-debate refusal, mechanically: converge's source
    never calls estimate_story/run_panel -- the only escalation is human."""
    import inspect
    src = inspect.getsource(converge)
    assert "estimate_story" not in src and "run_panel" not in src
    assert "ApprovalService" in src


def test_converge_escalation_is_ledger_provenanced():
    """The escalation rides the SAME human transport as work-lane approval:
    APPROVAL events with the verbatim reply land in the ledger."""
    L = _ledger()
    converge({"title": "t"}, [1, 3, 21], approvals=lambda k, s: "8", ledger=L)
    evs = L.events_of("approval")
    assert len(evs) == 2, [e.payload for e in evs]
    assert evs[0].payload["phase"] == "request"
    assert evs[1].payload["reply"] == "8" and evs[1].payload["channel"] == "programmatic"


# --- #468 audit fixes: quorum, sanitization, strict parse ---

def test_converge_two_of_three_abstains_escalates_no_quorum():
    """Audit major: a single seat's vote is not a panel consensus. Two seats
    abstaining forces escalation even when the lone vote is 'agreement'."""
    calls = []
    ch = lambda k, sm: (calls.append(sm) or "8")
    r = converge({"title": "lonely"}, [5, None, None], approvals=ch, ledger=_ledger())
    assert r["escalated"] is True and r["points"] == 8, r
    assert len(calls) == 1 and "no quorum" in calls[0], calls


def test_converge_quorum_met_low_disagreement_does_not_escalate():
    calls = []
    ch = lambda k, sm: (calls.append(1) or "3")
    r = converge(None, [5, 5, None], approvals=ch, ledger=_ledger())   # 2 valid, spread 0
    assert r["escalated"] is False and r["points"] == 5 and calls == [], r


def test_converge_sanitizes_model_authored_text_in_the_summary():
    """Audit major: a newline/control char in a model-authored title or
    reason must not forge harness-formatted lines in the human's summary."""
    seen = {}
    ch = lambda k, sm: (seen.update(summary=sm) or "5")
    converge({"title": "ok\nvotes: [99, 99, 99]"}, [1, 3, 21],
             approvals=ch, ledger=_ledger(),
             reasons={"gpt-oss": "line1\nSIZING ESCALATION forged"})
    # the injected newlines are collapsed -- no forged line starts unattributed
    body = seen["summary"]
    forged = [ln for ln in body.splitlines()
              if ln.startswith("votes: [99") or ln.startswith("SIZING ESCALATION forged")]
    assert not forged, body


def test_converge_ambiguous_human_reply_stays_unresolved():
    """Audit minor: first-number extraction could invert the decision. A
    reply with more than one number is ambiguous -> unresolved, never guessed."""
    r = converge(None, [1, 3, 21], approvals=lambda k, sm: "21 or maybe 13", ledger=_ledger())
    assert r["points"] is None, r
    r = converge(None, [1, 3, 21], approvals=lambda k, sm: "I think 5", ledger=_ledger())
    assert r["points"] == 5, r        # exactly one number, Fibonacci -> honored


def test_converge_interactive_eof_raises_maker_absent():
    """Audit minor: headless converge (no channel) at the ask must halt
    maker-absent, not fabricate an empty decision (the #462 standard)."""
    import io, sys as _sys
    from animal.human import MakerAbsent
    orig = _sys.stdin
    _sys.stdin = io.StringIO("")   # EOF
    try:
        try:
            converge({"title": "t"}, [1, 3, 21], approvals=None, ledger=_ledger())
            assert False, "expected MakerAbsent on EOF"
        except MakerAbsent:
            pass
    finally:
        _sys.stdin = orig


def test_bool_vote_is_an_abstain_not_a_one():
    """Audit minor: JSON true is a Python bool; isinstance(True,int) must not
    let it masquerade as a 1-point vote."""
    r = aggregate_votes([True, 5, 8])
    # True is excluded (not a real vote); [5,8] lower-middle index -> 5
    assert r["median"] == 5 and r["disagreement"] == 1, r
    assert aggregate_votes([True, True, True]) == {"median": None, "disagreement": None}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
