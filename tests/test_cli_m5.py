"""Story #471 -- `animal size` + `animal backlog prioritized` end-to-end.
Deterministic: poker.estimate_story is monkeypatched (no live llama-swap);
the escalation channel is the CLI's own --channel-test injection; the stores
are the process defaults under a redirected ANIMAL_HOME.
Run: python3 tests/test_cli_m5.py
"""
import os, sys, json, tempfile, io, contextlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Redirect ALL var/ writes for this test process BEFORE any animal import
# resolves config.VAR -- the CLI uses default store paths, so this is what
# keeps the whole end-to-end inside a temp home.
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

import animal.poker as poker
from animal import cli
from animal.product import ProductStore
from animal.estimates import query_by_story


def _seed_story(priority=5):
    st = ProductStore()
    eid = st.create_epic("sizing epic")
    sid = st.create_story(eid, "the story to size",
                          user_story="As a maker, I want a thing so that value", priority=priority)
    st.close()
    return sid


def _scripted_panel(mapping):
    def fake_estimate(seat, story, url=None):
        return mapping[seat["name"]]
    return fake_estimate


def _run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cli.main(argv)
    return rc, out.getvalue()


def test_size_converges_and_persists_everywhere():
    """The agreeing-panel path: converged points land on the story row AND
    every seat's vote lands durably in story_estimates -- both stores, one
    command, zero human interruptions."""
    sid = _seed_story()
    orig = poker.estimate_story
    poker.estimate_story = _scripted_panel({
        "gpt-oss": {"points": 5, "reasoning": "medium"},
        "mistral": {"points": 5, "reasoning": "clear scope"},
        "qwen": {"points": 8, "reasoning": "some unknowns"}})
    try:
        rc, out = _run_cli(["size", str(sid)])
    finally:
        poker.estimate_story = orig
    assert rc == 0, out
    summary = json.loads(out)
    assert summary["points"] == 5 and summary["escalated"] is False, summary
    st = ProductStore()
    assert st.get_story(sid)["story_points"] == 5
    st.close()
    rows = query_by_story(sid)
    assert len(rows) == 3 and {r["seat"] for r in rows} == {"gpt-oss", "mistral", "qwen"}
    assert all(r["aggregate_points"] == 5 and not r["escalated"] for r in rows)


def test_size_escalates_to_the_injected_human_channel():
    """The disagreeing-panel path: the human (here the --channel-test
    injection) decides; the decision is written back and recorded escalated."""
    sid = _seed_story()
    orig = poker.estimate_story
    poker.estimate_story = _scripted_panel({
        "gpt-oss": {"points": 1, "reasoning": "trivial"},
        "mistral": {"points": 3, "reasoning": "small"},
        "qwen": {"points": 21, "reasoning": "huge unknowns"}})
    try:
        rc, out = _run_cli(["size", str(sid), "--channel-test", "13"])
    finally:
        poker.estimate_story = orig
    assert rc == 0, out
    summary = json.loads(out)
    assert summary["escalated"] is True and summary["points"] == 13, summary
    st = ProductStore()
    assert st.get_story(sid)["story_points"] == 13
    st.close()
    rows = query_by_story(sid)
    assert rows and all(r["escalated"] for r in rows)
    assert {r["points"] for r in rows} == {1, 3, 21}


def test_size_unresolved_exits_nonzero_and_writes_no_points():
    """All seats abstain AND the human reply is unusable: the story stays
    honestly unsized -- exit 1, no story_points write, the abstain run still
    recorded (an abstain is a real observation)."""
    sid = _seed_story()
    orig = poker.estimate_story
    poker.estimate_story = _scripted_panel({
        "gpt-oss": {"points": None, "reasoning": "abstain"},
        "mistral": {"points": None, "reasoning": "abstain"},
        "qwen": {"points": None, "reasoning": "abstain"}})
    try:
        rc, out = _run_cli(["size", str(sid), "--channel-test", "no idea"])
    finally:
        poker.estimate_story = orig
    assert rc == 1, out
    st = ProductStore()
    assert st.get_story(sid)["story_points"] is None
    st.close()
    assert query_by_story(sid), "the abstain run must still be recorded"


def test_size_missing_story_exits_nonzero():
    rc, out = _run_cli(["size", "999999"])
    assert rc == 1 and "no story" in out


def test_backlog_prioritized_prints_ranked_table():
    st = ProductStore()
    eid = st.create_epic("prio epic")
    a = st.create_story(eid, "best bet", value=8, story_points=2)
    st.create_story(eid, "worst bet", value=2, story_points=8)
    st.create_story(eid, "unsized one", value=5)
    st.close()
    rc, out = _run_cli(["backlog", "prioritized", "--epic-id", str(eid)])
    assert rc == 0
    table = out.split("to rank")[0]               # the ranked table, before the remedy footer
    lines = [l for l in table.splitlines() if l.strip()]
    assert "best bet" in lines[1], out            # ranked first, right under the header
    assert "unsized" in out and "unsized one" in lines[-1], out   # flagged story sorts last


def test_backlog_set_value_then_ranks():
    """Audit remedy: an unvalued story is unrankable until `set-value` fills
    the WSJF numerator -- then it ranks."""
    st = ProductStore()
    eid = st.create_epic("e")
    sid = st.create_story(eid, "needs value", story_points=2)   # unvalued
    st.close()
    rc, out = _run_cli(["backlog", "prioritized", "--epic-id", str(eid)])
    assert "unvalued" in out
    rc, _ = _run_cli(["backlog", "set-value", str(sid), "8"])
    assert rc == 0
    rc, out = _run_cli(["backlog", "prioritized", "--epic-id", str(eid)])
    lines = [l for l in out.splitlines() if l.strip()]
    assert "needs value" in lines[1] and "unvalued" not in out.split("to rank")[0], out


def test_bare_backlog_is_the_prioritized_view_not_an_error():
    """Audit minor: `animal backlog` with no subcommand answers with the
    prioritized view, never an argparse usage error."""
    st = ProductStore()
    eid = st.create_epic("e")
    st.create_story(eid, "a story", value=5, story_points=5)
    st.close()
    rc, out = _run_cli(["backlog"])
    assert rc == 0 and "a story" in out, out


def test_channel_test_provenance_is_labeled_in_the_ledger():
    """Audit minor: a --channel-test reply must be distinguishable in the
    ledger from a real programmatic human grant."""
    from animal.ledger import Ledger
    import glob, json as _json
    from animal import config
    sid = _seed_story()
    orig = poker.estimate_story
    poker.estimate_story = _scripted_panel({
        "gpt-oss": {"points": 1, "reasoning": "a"}, "mistral": {"points": 3, "reasoning": "b"},
        "qwen": {"points": 21, "reasoning": "c"}})
    try:
        _run_cli(["size", str(sid), "--channel-test", "8"])
    finally:
        poker.estimate_story = orig
    # scan the ledger dir for the decision event's channel label
    channels = []
    for f in glob.glob(str(config.LEDGER_DIR / "*.ndjson")):
        for line in Path(f).read_text().splitlines():
            e = _json.loads(line)
            if e.get("type") == "approval" and e["payload"].get("phase") == "decision":
                channels.append(e["payload"].get("channel"))
    assert "channel-test" in channels, channels


def test_full_m5_suite_green_together():
    """The AC's ALL GREEN gate, run from inside the suite itself."""
    import subprocess
    for f in ("tests/test_backlog.py", "tests/test_poker.py", "tests/test_estimates.py"):
        r = subprocess.run([sys.executable, f], capture_output=True, text=True,
                           cwd=str(Path(__file__).resolve().parent.parent),
                           env={**os.environ, "ANIMAL_HOME": tempfile.mkdtemp(prefix="animal-m5-")})
        assert r.returncode == 0, (f, r.stdout[-500:], r.stderr[-500:])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
