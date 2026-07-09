"""Story #475 -- the review package. Deterministic, offline.
Run: python3 tests/test_review.py
"""
import os, sys, json, tempfile, io, contextlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ANIMAL_HOME"] = tempfile.mkdtemp(prefix="animal-test-home-")

from animal.review import assemble_review, to_markdown


def _sprint_result():
    return {
        "finished": [
            {"spec_id": 1, "points": 3, "status": "done", "seconds": 120.0, "ran": True,
             "ledger": "/x/abc.ndjson"},
            {"spec_id": 2, "points": 5, "status": "needs_human", "seconds": 300.0, "ran": True,
             "reason": "DoD check failed"},
        ],
        "deferred": [
            {"spec_id": 3, "points": 8, "reason": "did not fit the deadline budget", "ran": False},
        ],
        "totals": {"seconds_used": 420.0, "budget_seconds": 1000.0,
                   "points_done": 3, "points_deferred": 8},
    }


def test_points_conserved():
    """points_done + points_deferred is part of the total; nothing vanishes --
    every given point is attempted or deferred (attempted counts the 5-pt
    needs_human story so it isn't hidden)."""
    review = assemble_review(_sprint_result())
    t = review["totals"]
    assert t["points_done"] == 3
    assert t["points_deferred"] == 8
    assert t["points_attempted"] == 8            # 3 done + 5 needs_human
    assert t["points_total"] == 16               # 8 attempted + 8 deferred
    assert t["points_attempted"] + t["points_deferred"] == t["points_total"]


def test_markdown_contains_both_sections():
    review = assemble_review(_sprint_result())
    md = to_markdown(review)
    assert "finished" in md and "deferred" in md
    assert "story #1" in md and "story #3" in md
    assert "done" in md and "did not fit" in md


def test_conservation_catches_a_story_in_both_buckets():
    """Audit: the conservation check must actually be able to FAIL -- a story
    appearing in both finished and deferred is caught, not silently passed."""
    bad = {"finished": [{"spec_id": 1, "points": 3, "status": "done"}],
           "deferred": [{"spec_id": 1, "points": 3, "reason": "x"}],   # SAME id in both
           "totals": {"seconds_used": 0, "budget_seconds": 100}}
    try:
        assemble_review(bad)
        assert False, "expected the conservation check to catch the double-counted story"
    except AssertionError as e:
        assert "both finished and deferred" in str(e)


def test_markdown_shows_the_why_for_needs_human():
    """Audit major: a needs_human story must render its failed DoD checks and
    the ledger session id -- the maker acts from the page, not archaeology."""
    result = {"finished": [{"spec_id": 7, "points": 5, "status": "needs_human", "seconds": 90.0,
                            "ran": True, "session_id": "abc123def456",
                            "dod": [{"name": "add-sums", "passed": False},
                                    {"name": "other", "passed": True}],
                            "build_turns": 4, "reason": "DoD not met"}],
              "deferred": [], "totals": {"seconds_used": 90, "budget_seconds": 1000}}
    md = to_markdown(assemble_review(result))
    assert "add-sums" in md, md                 # the failing check is named
    assert "abc123def456" in md, md             # where to look
    assert "other" not in md.split("failed DoD")[1].split("evidence")[0]   # only the FAILED one


def test_empty_sprint_is_conserved_and_renders():
    review = assemble_review({"finished": [], "deferred": [],
                              "totals": {"seconds_used": 0, "budget_seconds": 500}})
    assert review["totals"]["points_total"] == 0
    md = to_markdown(review)
    assert "nothing ran" in md and "nothing deferred" in md


def test_all_deferred_conserves():
    review = assemble_review({
        "finished": [],
        "deferred": [{"spec_id": 1, "points": 5, "reason": "budget"},
                     {"spec_id": 2, "points": 3, "reason": "budget"}],
        "totals": {"seconds_used": 0, "budget_seconds": 10}})
    assert review["totals"]["points_deferred"] == 8 and review["totals"]["points_total"] == 8


def test_cli_sprint_end_to_end_writes_package():
    """The sprint CLI runs a stub-backed sprint and writes the JSON+md package.
    (No live model: the backlog is empty, so run_sprint returns cleanly with
    nothing scheduled -- the wiring, arg parsing, and package write are what's
    exercised.)"""
    from animal import cli
    out_dir = tempfile.mkdtemp(prefix="animal-review-out-")
    repo = tempfile.mkdtemp(prefix="animal-review-repo-")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["sprint", "--repo", repo, "--deadline", "+5m", "--out", out_dir])
    assert rc == 0, buf.getvalue()
    pkg = Path(out_dir) / "sprint-review.json"
    md = Path(out_dir) / "sprint-review.md"
    assert pkg.exists() and md.exists()
    review = json.loads(pkg.read_text())
    assert "totals" in review and "finished" in review and "deferred" in review
    assert "Sprint review" in md.read_text()


def test_cli_sprint_bad_deadline_exits_nonzero():
    from animal import cli
    repo = tempfile.mkdtemp(prefix="animal-review-repo-")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["sprint", "--repo", repo, "--deadline", "not-a-time"])
    assert rc == 1 and "bad --deadline" in buf.getvalue()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
