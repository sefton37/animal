"""Patch-farm run: sample k candidates per backlog task, test-filter, cross-family
select. Reports the farm's solved rate vs the single-attempt baseline. Assumes
llama-swap up on :8890. GPU-heavy (k * n_tasks coder runs + swaps)."""
import json, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from animal import candidates

HERE = Path(__file__).resolve().parent.parent
backlog = json.load(open(HERE / "backlog.json"))
for _ in range(120):
    try:
        urllib.request.urlopen("http://127.0.0.1:8890/v1/models", timeout=2); break
    except Exception:
        time.sleep(1)

K = 5
print(f"=== PATCH FARM — {len(backlog['tasks'])} tasks x k={K} candidates (coder=qwen, selector=mistral) ===")
r = candidates.run_farm(backlog, k=K)
print(f"\nBATCH: farm solved {r['farm_solved']}/{r['n_tasks']}   "
      f"vs single-attempt(temp0.2) {r['first_attempt_solved']}/{r['n_tasks']}\n")
for t in r["results"]:
    print(f"  {t['id']:5s} changed {t['n_changed']}/{t['k']}  passed-tests {t['n_pass']}/{t['k']} "
          f"(temps {t['pass_temps']})  1st-attempt={t['first_attempt_pass']}  SOLVED={t['farm_solved']} "
          f"(winner temp {t['winner_temp']})")
json.dump(r, open(HERE / "results" / "patch-farm.json", "w"), indent=1)
print("\nsaved -> phase3/results/patch-farm.json")
