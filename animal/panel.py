"""Phase 3: the cross-family panel — the diversity thesis turned into machinery.

Runs a premise-review battery through diverse judge-LINEAGE seats (via llama-swap),
collects their INDEPENDENT verdicts (one round, no debate — a shared transcript is
a contamination channel), aggregates, and measures recall-on-unsound / FP-on-clean
against the pre-registered bar (>=80% recall, <=10% FP).

Phase-0 taught the guards the hard way: judges that ABSTAIN (reasoning overran the
token budget) or DEGENERATE (answer one class to everything) poison the number.
Each seat's abstain/degeneracy is computed and surfaced; a degenerate seat is
excluded from aggregation and flagged.

Interpretation-enumeration (a distinct task shape) handles shared-prior
ambiguities that no construct-a-failure panel can catch — it only asks the model
to NAME the choice, which is robust to a shared prior.
"""
from __future__ import annotations
import json, re, urllib.request, urllib.error
from . import config

# 3 capable distinct lineages (Phase 0: gpt-oss 94% / mistral 94% / qwen 88%,
# all pairwise co-failure phi < 0). model = llama-swap roster name; max_tokens
# generous for the reasoning seat (gpt-oss's trace precedes its content).
JUDGE_SEATS = [
    {"name": "gpt-oss", "model": "judge",   "lineage": "openai",  "max_tokens": 1024},
    {"name": "mistral", "model": "auditor", "lineage": "mistral", "max_tokens": 320},
    {"name": "qwen",    "model": "coder",   "lineage": "qwen",    "max_tokens": 320},
]

_VERDICT_SCHEMA = {"type": "object", "required": ["verdict", "reason"],
                   "properties": {"verdict": {"type": "string", "enum": ["sound", "unsound"]},
                                  "reason": {"type": "string"}}}
_ENUM_SCHEMA = {"type": "object", "required": ["ambiguities"],
                "properties": {"ambiguities": {"type": "array", "items": {
                    "type": "object", "required": ["term", "assumed_reading"],
                    "properties": {"term": {"type": "string"}, "assumed_reading": {"type": "string"}}}}}}

_SYS_REVIEW = ("You are a strict specification reviewer. Judge exactly one thing: whether the premise "
               "encoded by a spec's Definition-of-Done checks faithfully serves the user story, or whether "
               "an implementation could satisfy every check while still violating what the story wants.")
_SYS_ENUM = ("You are a specification reviewer hunting for AMBIGUITY. List every term, boundary, or unit in "
             "the spec that could reasonably be read more than one way, and for each state the specific reading "
             "the checks/story assume. Do not judge correctness — only surface the choices being made.")


def _chat(model: str, messages: list[dict], schema: dict, max_tokens: int, url: str | None = None) -> str:
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "r", "strict": True, "schema": schema}}}
    req = urllib.request.Request((url or config.LLAMA_SWAP_URL) + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"].get("content", "") or ""


def _review_user(case: dict) -> str:
    return (f'USER STORY:\n{case["user_story"]}\n\nDoD CHECKS:\n- ' + "\n- ".join(case["dod_checks"]) +
            f'\n\nThe checks encode this PREMISE:\n"{case["premise"]}"\n\n'
            'Is the premise SOUND (faithfully serves the story) or UNSOUND (checks could all pass while the '
            'story is violated)? Return JSON {verdict, reason}.')


def _parse(txt: str, key: str = "verdict"):
    try:
        m = re.search(r"\{.*\}", txt, re.S)
        o = json.loads(m.group(0) if m else txt)
        v = str(o.get(key, "")).lower()
        return v if v in ("sound", "unsound") else "?"
    except Exception:
        return "?"


def run_seat(seat: dict, cases: list[dict], url: str | None = None) -> dict:
    """Run every case through ONE seat (llama-swap loads it once — amortizes swaps).
    Returns {case_id: 'sound'|'unsound'|'?'}."""
    out = {}
    for c in cases:
        try:
            out[c["id"]] = _parse(_chat(seat["model"],
                [{"role": "system", "content": _SYS_REVIEW}, {"role": "user", "content": _review_user(c)}],
                _VERDICT_SCHEMA, seat["max_tokens"], url))
        except Exception:
            out[c["id"]] = "?"
    return out


def _seat_stats(verdicts: dict, gt: dict) -> dict:
    ids = list(gt)
    ab = sum(1 for i in ids if verdicts.get(i) == "?")
    ns = sum(1 for i in ids if verdicts.get(i) == "sound")
    nu = sum(1 for i in ids if verdicts.get(i) == "unsound")
    acc = round(100 * sum(1 for i in ids if verdicts.get(i) == gt[i]) / len(ids))
    degenerate = ab > 0.2 * len(ids) or ns == 0 or nu == 0
    return {"accuracy": acc, "abstain": ab, "said_sound": ns, "said_unsound": nu, "degenerate": degenerate}


def aggregate(per_seat: list[str], rule: str) -> str:
    """Combine seats' verdicts for one case into a panel verdict. Abstains ('?')
    don't vote. rule 'any' = flag unsound if any seat flags; 'majority' = >=half of
    voting seats flag."""
    votes = [v for v in per_seat if v in ("sound", "unsound")]
    if not votes:
        return "?"
    flags = sum(1 for v in votes if v == "unsound")
    if rule == "any":
        return "unsound" if flags >= 1 else "sound"
    return "unsound" if flags * 2 >= len(votes) else "sound"


def measure(battery: dict, url: str | None = None, rules=("any", "majority")) -> dict:
    """The Phase-3 exit measurement: recall on unsound, FP on clean, per rule."""
    cases = battery["cases"]
    gt = {c["id"]: c["ground_truth"] for c in cases}
    unsound_ids = [i for i in gt if gt[i] == "unsound"]
    clean_ids = [i for i in gt if gt[i] == "sound"]
    seat_verdicts = {s["name"]: run_seat(s, cases, url) for s in JUDGE_SEATS}
    seat_stats = {n: _seat_stats(v, gt) for n, v in seat_verdicts.items()}
    live = [n for n in seat_verdicts if not seat_stats[n]["degenerate"]]   # exclude degenerate seats

    rule_results = {}
    for rule in rules:
        panel = {}
        for c in cases:
            panel[c["id"]] = aggregate([seat_verdicts[n][c["id"]] for n in live], rule)
        recall = round(100 * sum(1 for i in unsound_ids if panel[i] == "unsound") / max(1, len(unsound_ids)))
        fp = round(100 * sum(1 for i in clean_ids if panel[i] == "unsound") / max(1, len(clean_ids)))
        rule_results[rule] = {"recall_pct": recall, "fp_pct": fp,
                              "meets_bar": recall >= 80 and fp <= 10}
    best = max(rule_results, key=lambda r: (rule_results[r]["meets_bar"], rule_results[r]["recall_pct"] - rule_results[r]["fp_pct"]))
    return {"n_unsound": len(unsound_ids), "n_clean": len(clean_ids),
            "seats": seat_stats, "live_seats": live, "rules": rule_results,
            "best_rule": best, "gate_pass": rule_results[best]["meets_bar"]}


# --- the premise panel as a real Gate-0 step (reviews a live Spec) ---

def _review_spec_user(spec) -> str:
    checks = "\n- ".join(f"{c.name}: {' '.join(c.argv)}  [{c.comparator}]" for c in spec.dod)
    return (f'USER STORY:\n{spec.user_story}\n\nDoD CHECKS:\n- {checks}\n\n'
            'Could an implementation satisfy EVERY check while still violating what the user story wants? '
            'Answer "unsound" if the checks are gameable or misaligned with the story, "sound" if they '
            'faithfully pin it. Return JSON {verdict, reason}.')


def review_spec(spec, url: str | None = None, rule: str = "majority") -> dict:
    """Run the cross-family premise panel on a live Spec at Gate 0. Independent
    verdicts, one round. Returns the panel verdict + each seat's reason (surfaced
    to the human in the approval request)."""
    per, reasons = {}, {}
    for s in JUDGE_SEATS:
        try:
            raw = _chat(s["model"],
                        [{"role": "system", "content": _SYS_REVIEW}, {"role": "user", "content": _review_spec_user(spec)}],
                        _VERDICT_SCHEMA, s["max_tokens"], url)
            per[s["name"]] = _parse(raw)
            m = re.search(r"\{.*\}", raw, re.S)
            reasons[s["name"]] = (json.loads(m.group(0)).get("reason", "") if m else "")[:200]
        except Exception:
            per[s["name"]] = "?"
    verdict = aggregate(list(per.values()), rule)
    return {"panel_verdict": verdict, "flagged": verdict == "unsound", "per_seat": per, "reasons": reasons}


# --- shared-prior sub-exit: interpretation-enumeration ---

def enumerate_case(seat: dict, shared_case: dict, url: str | None = None) -> list[dict]:
    user = (f'SPEC:\n{shared_case["user_story"]}\n\nList every ambiguous term/boundary/unit and the reading '
            'the spec assumes. Return JSON {ambiguities:[{term, assumed_reading}]}.')
    try:
        o = _chat(seat["model"], [{"role": "system", "content": _SYS_ENUM}, {"role": "user", "content": user}],
                  _ENUM_SCHEMA, 640, url)
        m = re.search(r"\{.*\}", o, re.S)
        return json.loads(m.group(0) if m else o).get("ambiguities", [])
    except Exception:
        return []


def measure_shared_prior(shared_cases: list[dict], seat=None, url: str | None = None) -> dict:
    """Does interpretation-enumeration surface the planted ambiguity that a
    construct-a-failure panel would miss?"""
    # gpt-oss's reasoning channel returns empty content on the nested-enumeration
    # schema (measured); default to a non-reasoning seat for enumeration.
    seat = seat or next((s for s in JUDGE_SEATS if s["name"] == "qwen"), JUDGE_SEATS[-1])
    hits, detail = 0, []
    for sc in shared_cases:
        amb = enumerate_case(seat, sc, url)
        blob = " ".join((a.get("term", "") + " " + a.get("assumed_reading", "")) for a in amb).lower()
        term = sc["ambiguous_term"].lower()
        named = any(w in blob for w in term.split() if len(w) > 3) or term in blob
        hits += named
        detail.append({"id": sc["id"], "term": sc["ambiguous_term"], "surfaced": named, "n_listed": len(amb)})
    return {"n": len(shared_cases), "surfaced": hits,
            "surfaced_pct": round(100 * hits / max(1, len(shared_cases))), "detail": detail}
