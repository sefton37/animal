"""Phase-3 exit measurement: run the seeded battery through the cross-family panel
and grade against the pre-registered bar (>=80% recall, <=10% FP), plus the
shared-prior sub-exit. Assumes llama-swap is up on :8890 with the roster.
"""
import json, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from animal import panel

HERE = Path(__file__).resolve().parent.parent
battery = json.load(open(HERE / "battery.json"))
shared = json.load(open(HERE / "shared-prior.json"))

for _ in range(120):
    try:
        urllib.request.urlopen("http://127.0.0.1:8890/v1/models", timeout=2); break
    except Exception:
        time.sleep(1)

print(f"=== PANEL MEASUREMENT — {len(battery['cases'])} cases x {len(panel.JUDGE_SEATS)} lineages ===")
m = panel.measure(battery)
print(f"battery: {m['n_unsound']} unsound / {m['n_clean']} clean\n")
print("per-seat (individual judges):")
for n, s in m["seats"].items():
    print(f"  {n:8s} acc={s['accuracy']:3d}%  abstain={s['abstain']:2d}  said(sound/unsound)={s['said_sound']}/{s['said_unsound']}  degenerate={s['degenerate']}")
print(f"\nlive seats (non-degenerate): {m['live_seats']}")
print("panel aggregation:")
for rule, r in m["rules"].items():
    print(f"  rule={rule:9s} recall={r['recall_pct']:3d}%  fp={r['fp_pct']:3d}%  meets_bar(>=80/<=10)={r['meets_bar']}")
print(f"\nBEST RULE: {m['best_rule']}   GATE: {'PASS' if m['gate_pass'] else 'FAIL'}")

print("\n=== SHARED-PRIOR SUB-EXIT (interpretation-enumeration) ===")
sp = panel.measure_shared_prior(shared)
print(f"surfaced the planted ambiguity in {sp['surfaced']}/{sp['n']} ({sp['surfaced_pct']}%)")
for d in sp["detail"]:
    print(f"  {d['id']}: surfaced={d['surfaced']}  listed={d['n_listed']}  term={d['term'][:44]!r}")

json.dump({"panel": m, "shared_prior": sp}, open(HERE / "results" / "panel-measurement.json", "w"), indent=1)
print("\nsaved -> phase3/results/panel-measurement.json")
