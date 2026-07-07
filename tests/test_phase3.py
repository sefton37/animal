"""Phase 3 panel logic — deterministic, offline (verdicts injected, no model). Proves
the aggregation rules, the abstain/degeneracy guards, and the recall/FP arithmetic
so the live measurement only has to prove the judges. Run: python3 tests/test_phase3.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import animal.panel as panel


def test_aggregate_any_vs_majority():
    assert panel.aggregate(["sound", "sound", "unsound"], "any") == "unsound"     # any flag -> flag
    assert panel.aggregate(["sound", "sound", "unsound"], "majority") == "sound"  # 1/3 -> pass
    assert panel.aggregate(["unsound", "unsound", "sound"], "majority") == "unsound"  # 2/3 -> flag


def test_aggregate_ignores_abstains():
    # abstains ('?') don't vote; majority = >=half of voters (a tie flags — a split
    # panel surfaces the doubt to the human rather than passing silently)
    assert panel.aggregate(["?", "sound", "unsound"], "majority") == "unsound"    # 1-1 tie of 2 -> flag
    assert panel.aggregate(["?", "sound", "sound"], "majority") == "sound"        # 0 of 2 -> pass
    assert panel.aggregate(["?", "?", "unsound"], "majority") == "unsound"        # 1 of 1 vote
    assert panel.aggregate(["?", "?", "?"], "any") == "?"                          # no votes -> abstain


def test_seat_stats_flags_degenerate():
    gt = {f"c{i}": ("unsound" if i < 5 else "sound") for i in range(10)}
    always_unsound = {i: "unsound" for i in gt}
    s = panel._seat_stats(always_unsound, gt)
    assert s["degenerate"] and s["said_sound"] == 0
    abstainer = {k: ("?" if idx % 2 else "unsound") for idx, k in enumerate(gt)}
    assert panel._seat_stats(abstainer, gt)["degenerate"]           # >20% abstain


def test_measure_recall_fp_and_excludes_degenerate(monkeypatch=None):
    battery = {"cases": [{"id": "u1", "ground_truth": "unsound"}, {"id": "u2", "ground_truth": "unsound"},
                         {"id": "s1", "ground_truth": "sound"},   {"id": "s2", "ground_truth": "sound"}]}
    fake = {  # gpt-oss + mistral perfect; qwen misses u2; a hypothetical degenerate would be excluded
        "gpt-oss": {"u1": "unsound", "u2": "unsound", "s1": "sound", "s2": "sound"},
        "mistral": {"u1": "unsound", "u2": "unsound", "s1": "sound", "s2": "sound"},
        "qwen":    {"u1": "unsound", "u2": "sound",   "s1": "sound", "s2": "sound"},
    }
    orig = panel.run_seat
    panel.run_seat = lambda seat, cases, url=None: fake[seat["name"]]
    try:
        m = panel.measure(battery)
    finally:
        panel.run_seat = orig
    # majority: u1 (3/3), u2 (2/3) both flagged -> recall 100; clean never flagged -> fp 0
    assert m["rules"]["majority"]["recall_pct"] == 100 and m["rules"]["majority"]["fp_pct"] == 0
    assert m["gate_pass"] and not any(m["seats"][n]["degenerate"] for n in m["seats"])
    # a single perfect judge doesn't drag the panel; the panel catches u2 the weak seat missed
    assert m["seats"]["qwen"]["accuracy"] == 75 and m["rules"]["majority"]["recall_pct"] == 100


def test_candidate_select_edges():
    import animal.candidates as candidates
    w, why = candidates.select([], "task")            # no survivor -> None (no model call)
    assert w is None
    c = {"i": 0, "temp": 0.2, "diff": "d"}
    w, why = candidates.select([c], "task")           # one survivor -> that one (no model call)
    assert w is c and "one candidate" in why


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
