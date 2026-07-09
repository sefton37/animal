"""Stories #467/#468 -- the diverse-model PLANNING-POKER panel (M5).

The diversity thesis (O4), applied to estimation: three decorrelated model
lineages (the SAME seats Phase 3 measured at pairwise co-failure phi<0) each
give an INDEPENDENT Fibonacci estimate -- one round, no debate, no shared
transcript (a shared transcript is a contamination channel; the
architecture's explicit no-multi-round-debate refusal). The decoder is
constrained to the Fibonacci enum, so a seat cannot emit 4 or 6.

Aggregation is NUMERIC and harness-computed -- the roadmap itself pre-flagged
that panel.py's boolean any/majority aggregation was never measured for
numeric consensus and must not be naively repurposed: here the median is
taken on the FIBONACCI INDEX scale (never an arithmetic mean -- "wide
disagreement ... escalated to you -- rather than averaged away",
CONSTRUCTION.md), and disagreement is the index distance between the lowest
and highest vote.

Convergence is a HUMAN decision when the panel disagrees (O6): converge()
returns the median only under low disagreement; at/over the threshold -- or
when every seat abstained, because "the panel could not size" must never
silently become a size (the #460 all-abstain lesson) -- it escalates over the
human channel (human.ApprovalService.ask: same transport, same ledger
APPROVAL provenance, verbatim reply). There is NO model-side resolution path:
converge never re-prompts a seat.
"""
from __future__ import annotations
import json
import re
from .ledger import Ledger
from .human import ApprovalService
from .product import FIBONACCI_POINTS
from . import panel as _panel

# The ordered Fibonacci scale. The literal is what the decoder schema carries;
# the assert pins it to the store's own validation set (single source of
# discipline -- product.py rejects points outside this set).
FIB = [1, 2, 3, 5, 8, 13, 21]
assert set(FIB) == FIBONACCI_POINTS, "poker FIB and product FIBONACCI_POINTS diverged"

# The same three decorrelated lineages Phase 3 measured (pairwise phi < 0,
# phase3/results/panel-measurement.json) -- reused by reference, not re-declared,
# so a roster change cannot silently fork the estimation panel from the
# premise/audit panels.
ESTIMATOR_SEATS = [dict(s) for s in _panel.JUDGE_SEATS]

_POINTS_SCHEMA = {"type": "object", "required": ["points", "reasoning"],
                  "properties": {"points": {"type": "integer", "enum": [1, 2, 3, 5, 8, 13, 21]},
                                 "reasoning": {"type": "string"}}}

_SYS_ESTIMATE = ("You are an experienced engineer running planning poker. Estimate the story in "
                 "Fibonacci points (1/2/3/5/8/13/21): 1-3 = small, well-understood; 5-8 = real work "
                 "with some unknowns; 13-21 = large or uncertain, probably needs splitting. Judge "
                 "EFFORT AND UNCERTAINTY of the described work only -- never its value. Return JSON "
                 '{"points": <fib>, "reasoning": "<one or two sentences>"}.')


def _story_prompt(story) -> str:
    if isinstance(story, dict):
        title = str(story.get("title") or "").strip()
        body = str(story.get("user_story") or story.get("narrative") or "").strip()
        text = f"{title}: {body}" if title else body
    else:
        text = str(story)
    return f"STORY TO SIZE:\n{text}\n\nReturn JSON {{points, reasoning}}."


def estimate_story(seat: dict, story, url: str | None = None) -> dict:
    """ONE seat's independent estimate: {points: int|None, reasoning: str}.
    points=None is an abstain (model error / malformed reply) -- recorded,
    never guessed. Follows panel.py's _chat/JSON-schema pattern (reused, not
    duplicated)."""
    try:
        raw = _panel._chat(seat["model"],
                           [{"role": "system", "content": _SYS_ESTIMATE},
                            {"role": "user", "content": _story_prompt(story)}],
                           _POINTS_SCHEMA, seat["max_tokens"], url)
        m = re.search(r"\{.*\}", raw, re.S)
        o = json.loads(m.group(0)) if m else {}
        pts = o.get("points")
        # bool guard (#467 audit): JSON true is a Python bool, and
        # isinstance(True, int) would let it masquerade as a 1-point vote
        ok = isinstance(pts, int) and not isinstance(pts, bool) and pts in FIBONACCI_POINTS
        return {"points": pts if ok else None,
                "reasoning": str(o.get("reasoning", ""))[:300],
                "model": seat.get("model", seat.get("name", "?"))}
    except Exception as e:
        return {"points": None, "reasoning": f"abstain: {type(e).__name__}: {e}"}


def run_panel(story, seats: list[dict] = ESTIMATOR_SEATS, url: str | None = None) -> dict:
    """Independent estimates from every seat -- one round, no debate, no seat
    sees another's answer (the run_seat contract). Returns
    {seat_name: {points, reasoning, model}} -- the model identity travels
    WITH the vote (#469 audit: a roster lookup at record time could silently
    misattribute a renamed/custom seat in the durable record)."""
    return {s["name"]: estimate_story(s, story, url) for s in seats}


def aggregate_votes(votes: list) -> dict:
    """Harness-computed numeric aggregation on the FIBONACCI INDEX scale:
    {median, disagreement}. median is the index-median vote (lower middle for
    even counts -- always a real Fibonacci value, never an average);
    disagreement is index(max) - index(min). Abstains/invalid values are
    excluded; an all-abstain set returns {None, None} -- no votes is not a
    size."""
    valid = sorted(v for v in votes
                   if isinstance(v, int) and not isinstance(v, bool) and v in FIBONACCI_POINTS)
    if not valid:
        return {"median": None, "disagreement": None}
    idxs = [FIB.index(v) for v in valid]
    median = FIB[idxs[(len(idxs) - 1) // 2]]
    return {"median": median, "disagreement": idxs[-1] - idxs[0]}


def converge(story, votes: list, approvals=None, threshold: int = 3,
             ledger: Ledger | None = None, reasons: dict | None = None,
             channel_name: str | None = None) -> dict:
    """The convergence decision (Story #468). disagreement < threshold ->
    the harness-computed median stands, the human is not interrupted.
    disagreement >= threshold, OR every seat abstained -> ESCALATE to the
    human channel (ApprovalService.ask -- verbatim reply, ledger APPROVAL
    provenance); the human's Fibonacci answer is the size. A non-Fibonacci
    reply leaves points=None (unresolved -- surfaced, never guessed).
    There is NO model-side path: no re-prompt, no debate, no second round.

    Returns {points, escalated, median, disagreement, reply?}."""
    agg = aggregate_votes(votes)
    valid_count = len([v for v in votes
                       if isinstance(v, int) and not isinstance(v, bool) and v in FIBONACCI_POINTS])
    # Quorum (#468 audit, major): a single seat's opinion is not a panel
    # consensus -- two of three seats abstaining must escalate, not let one
    # vote silently become the size.
    quorum_ok = valid_count >= 2
    if agg["disagreement"] is not None and agg["disagreement"] < threshold and quorum_ok:
        return {"points": agg["median"], "escalated": False, **agg}
    # escalation: the human decides -- the only resolution path
    L = ledger or Ledger()
    svc = ApprovalService(L, channel=approvals, channel_name=channel_name)
    raw_title = (story.get("title") if isinstance(story, dict) else str(story or "story")) or "story"
    # Sanitize model-adjacent text (#468 audit, major): the title and seat
    # reasons are model-authored; a newline/control char in them could forge
    # harness-formatted lines in the very summary the human decides from.
    title = " ".join(str(raw_title).split())[:80]
    if agg["median"] is None:
        why = "every seat abstained -- the panel could not size this"
    elif not quorum_ok:
        why = f"only {valid_count} of {len(votes)} seats could size this -- no quorum"
    else:
        why = f"wide disagreement (index spread {agg['disagreement']}, median {agg['median']})"
    lines = [f"SIZING ESCALATION for {title!r}: {why}.", f"votes: {votes}"]
    for name, r in (reasons or {}).items():
        if r:
            clean = " ".join(str(r).split())[:300]
            lines.append(f"  {' '.join(str(name).split())[:40]}: {clean}")
    lines.append(f"Pick the Fibonacci size ({'/'.join(map(str, FIB))}):")
    reply = svc.ask(f"size:{title}", "\n".join(lines))
    # Strict reply parse (#468 audit): first-number extraction could invert
    # the human's decision ("21 or maybe 13" must not become 21). Exactly ONE
    # number, and it must be Fibonacci; anything else stays unresolved.
    nums = re.findall(r"\d+", reply or "")
    picked = int(nums[0]) if len(nums) == 1 else None
    return {"points": picked if picked in FIBONACCI_POINTS else None,
            "escalated": True, "reply": reply, **agg}
