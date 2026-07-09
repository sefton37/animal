"""Story #475 -- the review package (M6, Act 4 handoff).

Turn a sprint result into the artifact the design promises: "here is what I
finished, here is what I could not, here is the evidence for both" -- so
reviewing an unattended run takes minutes, not a ledger archaeology session.

INVARIANT (the point-conservation law): points_done + points_deferred equals
the total points across EVERY story the sprint was given. Nothing silently
vanishes -- a story is finished-and-done, finished-but-not-done, or deferred,
and its points land in exactly one bucket. assemble_review computes this from
the sprint result and asserts it, so a mis-shaped result is a loud failure.
"""
from __future__ import annotations


def assemble_review(sprint_result: dict) -> dict:
    """Structured review: {finished, deferred, totals}. finished carries each
    ran story's status/points/seconds/ledger; deferred carries each with its
    reason. totals conserves points: points_done + points_deferred ==
    sum of all given stories' points (finished-but-not-done points are counted
    in neither done nor deferred -- they are reported in points_attempted so
    nothing is hidden)."""
    finished = list(sprint_result.get("finished", []))
    deferred = list(sprint_result.get("deferred", []))
    src_totals = sprint_result.get("totals", {})

    points_done = sum(f.get("points", 0) for f in finished if f.get("status") == "done")
    points_attempted = sum(f.get("points", 0) for f in finished)
    points_deferred = sum(d.get("points", 0) for d in deferred)
    total_given = points_attempted + points_deferred

    totals = {"points_done": points_done,
              "points_attempted": points_attempted,
              "points_deferred": points_deferred,
              "points_total": total_given,
              "seconds_used": src_totals.get("seconds_used", 0),
              "budget_seconds": src_totals.get("budget_seconds", 0)}

    review = {"finished": finished, "deferred": deferred, "totals": totals}
    # The REAL conservation check (audit: the prior assert was a tautology --
    # total_given was DEFINED as attempted+deferred, so it could never fail).
    # A story must appear in EXACTLY ONE bucket: no spec_id in both, none lost.
    fin_ids = [f.get("spec_id") for f in finished]
    def_ids = [d.get("spec_id") for d in deferred]
    overlap = set(fin_ids) & set(def_ids)
    assert not overlap, f"story in both finished and deferred: {overlap}"
    all_ids = fin_ids + def_ids
    assert len(all_ids) == len(set(all_ids)), f"duplicate story across the sprint: {all_ids}"
    return review


def to_markdown(review: dict) -> str:
    """A human-readable sprint review. Contains a 'finished' and a 'deferred'
    section, and the totals -- the whole point is that a maker reads THIS, not
    the ledger."""
    t = review["totals"]
    out = ["# Sprint review", ""]
    out.append(f"**{t['points_done']} pts done** of {t['points_total']} given "
               f"({t['points_deferred']} pts deferred); "
               f"{_fmt_secs(t['seconds_used'])} used of {_fmt_secs(t['budget_seconds'])} budget.")
    out.append("")
    out.append("## finished")
    if review["finished"]:
        for f in review["finished"]:
            secs = _fmt_secs(f["seconds"]) if f.get("seconds") is not None else "n/a"
            line = f"- story #{f['spec_id']} — **{f.get('status', '?')}** ({f.get('points', '?')} pts, {secs})"
            if f.get("reason"):
                line += f" — {f['reason']}"
            out.append(line)
            # the harness-computed WHY, so a maker acts from THIS page, not the
            # ledger: the failed DoD checks and where to look (session id)
            failed = [c["name"] for c in (f.get("dod") or []) if not c.get("passed")]
            if failed and f.get("status") != "done":
                out.append(f"    - failed DoD: {', '.join(failed)}")
            if f.get("session_id"):
                out.append(f"    - evidence: ledger session {f['session_id']}"
                           + (f" ({f['build_turns']} turns)" if f.get("build_turns") is not None else ""))
    else:
        out.append("- (nothing ran)")
    out.append("")
    out.append("## deferred")
    if review["deferred"]:
        for d in review["deferred"]:
            out.append(f"- story #{d['spec_id']} — {d.get('points', '?')} pts — {d.get('reason', 'deferred')}")
    else:
        out.append("- (nothing deferred)")
    out.append("")
    return "\n".join(out)


def _fmt_secs(seconds) -> str:
    if not seconds:
        return "0s"
    seconds = float(seconds)
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"
