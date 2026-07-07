"""Patch farm on REAL Stalag modules against their REAL tests (mutation-testing
style: seed a validated regression, farm must recover the fix). Real non-toy code,
real test files, DB-free, on copies. Guards against test-gaming: a candidate only
counts if the coder fixed the MODULE and left the test file untouched.
"""
import json, sys, time, tempfile, shutil, subprocess, hashlib, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from animal.loop import run_task
from animal import candidates

STALAG = Path.home() / "dev/stalag"
HERE = Path(__file__).resolve().parent.parent
K = 5
TASKS = [
    {"id": "cells-grass-flip", "module": "src/cells.js", "test": "test/cells.test.mjs",
     "find": "n[1] > cellDef.upThreshold", "replace": "n[1] < cellDef.upThreshold"},
    {"id": "cells-nonorm-z", "module": "src/cells.js", "test": "test/cells.test.mjs",
     "find": "return [cx / len, cy / len, cz / len];", "replace": "return [cx / len, cy / len, cz];"},
    {"id": "geom-coset", "module": "src/to-cell.js", "test": "test/geometry.test.mjs",
     "find": "4 * Math.round(p[0] / 4)", "replace": "4 * Math.round(p[0] / 2)"},
    {"id": "cells-nonorm-x", "module": "src/cells.js", "test": "test/cells.test.mjs",
     "find": "return [cx / len, cy / len, cz / len];", "replace": "return [cx, cy / len, cz / len];"},
]


def _sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def copy_mutated(t):
    d = Path(tempfile.mkdtemp(prefix="stalag-farm-"))
    for s in ("src", "test"):
        shutil.copytree(STALAG / s, d / s)
    shutil.copy2(STALAG / "package.json", d / "package.json")
    p = d / t["module"]
    p.write_text(p.read_text().replace(t["find"], t["replace"], 1))
    return d


def node_pass(d, test):
    try:
        return subprocess.run(["node", test], cwd=d, capture_output=True, timeout=120).returncode == 0
    except Exception:
        return False


for _ in range(120):
    try:
        urllib.request.urlopen("http://127.0.0.1:8890/v1/models", timeout=2); break
    except Exception:
        time.sleep(1)

print(f"=== STALAG PATCH FARM — real modules + real tests, {len(TASKS)} tasks x k={K} ===\n")
results = []
for t in TASKS:
    desc = (f"The test {t['test']} is failing because of a bug introduced into {t['module']}. "
            f"Read {t['module']} and {t['test']}, find the bug, and edit ONLY {t['module']} to make the test pass.")
    cands = []
    for i in range(K):
        d = copy_mutated(t)
        test_hash_before = _sha(d / t["test"])
        s = run_task("Fix the failing test:\n" + desc, str(d), role="coder", checks=[],
                     temperature=candidates.DEFAULT_TEMPS[i % len(candidates.DEFAULT_TEMPS)], max_turns=8)
        test_untouched = _sha(d / t["test"]) == test_hash_before          # anti-test-gaming
        passed = bool(s.get("changed")) and test_untouched and node_pass(d, t["test"])
        cands.append({"i": i, "temp": candidates.DEFAULT_TEMPS[i % len(candidates.DEFAULT_TEMPS)],
                      "dir": str(d), "diff": s.get("run_diff", ""), "changed": bool(s.get("changed")),
                      "test_untouched": test_untouched, "pass": passed})
    survivors = [c for c in cands if c["pass"]]
    winner, _ = candidates.select(survivors, desc) if survivors else (None, "")
    gamed = sum(1 for c in cands if c["changed"] and not c["test_untouched"])
    r = {"id": t["id"], "module": t["module"], "n_changed": sum(c["changed"] for c in cands),
         "n_pass": len(survivors), "pass_temps": [c["temp"] for c in survivors],
         "first_attempt": cands[0]["pass"], "solved": winner is not None,
         "winner_temp": winner["temp"] if winner else None, "test_gamed_attempts": gamed}
    results.append(r)
    print(f"  {t['id']:16s} changed {r['n_changed']}/{K}  passed {r['n_pass']}/{K} (temps {r['pass_temps']})  "
          f"1st={r['first_attempt']}  gamed-test={gamed}  SOLVED={r['solved']}")

solved = sum(r["solved"] for r in results)
firsts = sum(r["first_attempt"] for r in results)
print(f"\nBATCH (real Stalag code): farm solved {solved}/{len(TASKS)}  vs single-attempt(temp0.2) {firsts}/{len(TASKS)}")
json.dump({"repo": "stalag", "k": K, "solved": solved, "first_attempt_solved": firsts, "tasks": results},
          open(HERE / "results" / "stalag-farm.json", "w"), indent=1)
print("saved -> phase3/results/stalag-farm.json")
