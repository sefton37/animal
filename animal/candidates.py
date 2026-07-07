"""Phase 3: the candidate-sampling / patch-farm lane.

Diverse GENERATION (sample k from the resident coder at raised temperature — never
mix families in generation, per Self-MoA) -> OBJECTIVE test-filter (harness-run
checks, not model opinion) -> CROSS-FAMILY SELECTION among the survivors (objective
filters first, model judgment last, per CodeMonkeys). Leans on local inference
being electricity-cheap: sample many, keep what passes, let a different lineage
pick the winner.
"""
from __future__ import annotations
import shutil, tempfile, json, re
from pathlib import Path
from .loop import run_task
from .sandbox import Sandbox
from . import panel

DEFAULT_TEMPS = [0.2, 0.5, 0.7, 0.9, 1.1]
_SEL_SCHEMA = {"type": "object", "required": ["choice", "reason"],
               "properties": {"choice": {"type": "integer"}, "reason": {"type": "string"}}}


def _copy_repo(src) -> Path:
    dst = Path(tempfile.mkdtemp(prefix="animal-cand-"))
    for p in Path(src).iterdir():
        if p.name in (".git", "var", "__pycache__"):
            continue
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, dst / p.name)
    return dst


def sample_candidates(task: str, repo, k: int = 5, coder_role: str = "coder", max_turns: int = 6) -> list[dict]:
    """k independent coder attempts on k fresh copies, at spread temperatures."""
    temps = (DEFAULT_TEMPS * (k // len(DEFAULT_TEMPS) + 1))[:k]
    out = []
    for i in range(k):
        wd = _copy_repo(repo)
        s = run_task("Fix the bug so the task is satisfied:\n" + task, str(wd),
                     role=coder_role, checks=[], temperature=temps[i], max_turns=max_turns)
        out.append({"i": i, "temp": temps[i], "dir": str(wd),
                    "diff": s.get("run_diff", ""), "changed": bool(s.get("changed"))})
    return out


def test_filter(cands: list[dict], check_argv: list[str], sb: Sandbox | None = None) -> list[dict]:
    """Harness runs the task's test against each candidate; survivors pass + changed."""
    sb = sb or Sandbox()
    for c in cands:
        c["test_pass"] = sb.run(check_argv, c["dir"])["exit_code"] == 0
    return [c for c in cands if c["test_pass"] and c["changed"]]


def select(survivors: list[dict], task: str, selector_model: str = "auditor", url=None) -> tuple[dict | None, str]:
    """Cross-family selector picks the best among candidates that ALL pass the tests
    (a different lineage from the coder). 0 -> None; 1 -> that one; >1 -> model picks."""
    if not survivors:
        return None, "no candidate passed the tests"
    if len(survivors) == 1:
        return survivors[0], "only one candidate passed the tests"
    diffs = "\n\n".join(f"CANDIDATE {i} (diff):\n{c['diff'][:1500]}" for i, c in enumerate(survivors))
    sys = ("You pick the best of several patches that ALL already pass the tests. Prefer the smallest, "
           "clearest, most correct fix that matches the task and avoids unrelated changes.")
    user = f"TASK:\n{task}\n\n{diffs}\n\nReturn JSON {{choice, reason}} — choice = index of the best candidate."
    try:
        raw = panel._chat(selector_model, [{"role": "system", "content": sys}, {"role": "user", "content": user}],
                          _SEL_SCHEMA, 400, url)
        m = re.search(r"\{.*\}", raw, re.S)
        idx = int(json.loads(m.group(0))["choice"])
        if 0 <= idx < len(survivors):
            return survivors[idx], json.loads(m.group(0)).get("reason", "")[:200]
    except Exception:
        pass
    return survivors[0], "selector failed/out-of-range; took first survivor"


def farm_task(t: dict, k: int = 5, coder_role: str = "coder", selector_model: str = "auditor",
              url=None, max_turns: int = 6) -> dict:
    """Materialize one backlog task, sample -> test-filter -> select. Reports the
    single-attempt baseline (candidate 0, temp 0.2) vs the farm's result."""
    repo = Path(tempfile.mkdtemp(prefix="animal-farm-"))
    (repo / t["filename"]).write_text(t["buggy_code"])
    (repo / t["test_filename"]).write_text(t["test_code"])
    check = ["python3", t["test_filename"]]
    cands = sample_candidates(t["task_description"], str(repo), k, coder_role, max_turns)
    survivors = test_filter(cands, check)
    winner, reason = select(survivors, t["task_description"], selector_model, url)
    return {"id": t["id"], "k": k, "n_changed": sum(c["changed"] for c in cands),
            "n_pass": len(survivors), "pass_temps": [c["temp"] for c in survivors],
            "first_attempt_pass": bool(cands and cands[0]["test_pass"]),   # baseline: 1 try @ temp 0.2
            "farm_solved": winner is not None,
            "winner_temp": winner["temp"] if winner else None, "selector_reason": reason}


def run_farm(backlog: dict, k: int = 5, coder_role: str = "coder", selector_model: str = "auditor",
             url=None, max_turns: int = 6) -> dict:
    results = [farm_task(t, k, coder_role, selector_model, url, max_turns) for t in backlog["tasks"]]
    return {"n_tasks": len(results), "k": k,
            "farm_solved": sum(r["farm_solved"] for r in results),
            "first_attempt_solved": sum(r["first_attempt_pass"] for r in results),
            "results": results}
