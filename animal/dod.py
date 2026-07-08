"""The DoD executor + authoring-time validation.

Execution: the HARNESS runs each check (via the sandbox) and applies the typed
comparator. Nothing a model says about a check counts. Nondeterministic checks
run N=3 (all must pass).

Authoring validation makes "checks must be falsifiable by construction" real —
the direct fix for the corpus audit (48% existence-only, 4.6% vacuous):
  - negative-control: run the check against the PRE-WORK tree. If it already
    passes (and isn't a regression check), it doesn't test the new work -> reject.
  - lints for the recurring authoring bugs: grep BRE-alternation without -E,
    a referenced helper script that doesn't exist, always-exit-0 shapes.
"""
from __future__ import annotations
import os, re
from pathlib import Path
from .spec import DoDCheck, Comparator
from .sandbox import Sandbox

N_NONDET = 3


def run_check(check: DoDCheck, sandbox: Sandbox, workspace, timeout: int = 120) -> dict:
    """Harness-run result: {passed, exit_code, stdout, stderr, runs}. All computed."""
    runs = N_NONDET if check.nondeterministic else 1
    last = None
    passes = 0
    for _ in range(runs):
        last = sandbox.run(check.argv, workspace, timeout=timeout)
        if check.verdict(last):
            passes += 1
    passed = (passes == runs)                     # nondeterministic -> all N must pass
    return {"name": check.name, "passed": passed, "exit_code": last["exit_code"],
            "stdout": last.get("stdout", "")[-2000:], "stderr": last.get("stderr", "")[-1000:],
            "runs": runs, "passes": passes, "sandbox_mode": last.get("sandbox_mode")}


# --- authoring-time validation ---

_GREP = {"grep", "egrep", "fgrep", "rg", " grep"}
_SCRIPT_EXT = (".py", ".sh", ".js", ".mjs", ".ts", ".rb")


def _lint(check: DoDCheck, workspace) -> list[str]:
    problems = []
    argv = check.argv
    prog = os.path.basename(argv[0])
    # 1) grep BRE-alternation: `grep 'a|b'` matches the literal 'a|b' unless -E/-P
    if prog in ("grep", "fgrep"):
        has_ere = any(a in ("-E", "-P") or (a.startswith("-") and ("E" in a or "P" in a)) for a in argv)
        if not has_ere:
            for a in argv[1:]:
                if not a.startswith("-") and "|" in a:
                    problems.append(f"grep pattern {a!r} uses BRE alternation '|' without -E "
                                    "(matches the literal string; add -E)")
    # 2) referenced helper script that doesn't exist in the workspace.
    # expected_new (Story #458) opts a check out of THIS lint too, not only
    # grounding's Gate 0a scan -- otherwise a TDD spec whose DoD runs the
    # tester's future test file cleared grounding only to be rejected here,
    # one gate later, and the flag's motivating case never worked end-to-end.
    # Safe because the negative-control below still runs on expected_new
    # checks: python3 on a missing file genuinely fails pre-work, so the
    # check is provably non-vacuous even though its file does not exist yet.
    ws = Path(workspace)
    for a in argv[1:]:
        if a.endswith(_SCRIPT_EXT) and "/" not in a.lstrip("./") or (a.endswith(_SCRIPT_EXT) and not a.startswith("-")):
            cand = (ws / a).resolve()
            try:
                cand.relative_to(ws.resolve())
                if not cand.exists() and not check.expected_new:
                    problems.append(f"references helper {a!r} which does not exist in the workspace")
            except ValueError:
                pass
    # 3) an exit_zero check on a command that structurally always exits 0
    if check.comparator == Comparator.EXIT_ZERO.value and prog in ("true", ":"):
        problems.append("comparator exit_zero on a command that always exits 0 (vacuous)")
    return problems


def validate_check(check: DoDCheck, sandbox: Sandbox, workspace) -> dict:
    """Return {ok, reasons}. A check is rejected at authoring if it lints bad or is
    vacuous (passes before the work exists, and isn't marked regression)."""
    reasons = _lint(check, workspace)
    # negative-control: run against the current (pre-work) tree
    neg = None
    if not check.regression:
        res = sandbox.run(check.argv, workspace)
        if check.verdict(res):
            neg = "vacuous: passes against the pre-work tree, so it does not test the new work"
            reasons.append(neg)
    return {"name": check.name, "ok": not reasons, "reasons": reasons,
            "vacuous": neg is not None}


def validate_spec(spec, sandbox: Sandbox, workspace) -> dict:
    """Validate every DoD check at authoring. spec is authorable iff all checks ok."""
    per = [validate_check(c, sandbox, workspace) for c in spec.dod]
    return {"ok": all(v["ok"] for v in per) and len(per) > 0,
            "checks": per, "n_checks": len(per),
            "n_bad": sum(1 for v in per if not v["ok"])}
