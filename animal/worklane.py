"""The work-lane full chain, on top of the kernel:

  spec -> ground -> validate DoD (authoring: vacuous/lint rejected) -> HUMAN
  approval (real channel) -> build (write capability granted ONLY now) ->
  verify (harness runs the DoD) -> done | needs_human | rejected

Capability follows state (Task.can_write is true only while building); a vacuous
DoD never reaches approval; only a human-channel grant reaches the build state.
Everything lands in one replayable ledger.
"""
from __future__ import annotations
from .ledger import Ledger
from .sandbox import Sandbox
from .spec import Spec, SpecState
from .task import Task
from .human import ApprovalService
from .grounding import ground
from .dod import validate_spec, run_check
from .loop import run_task
from .types import EventType


def _finish(L, task, traj, extra) -> dict:
    s = {"spec_id": task.spec.id, "final_state": task.state, "trajectory": traj, **extra}
    L.append(EventType.SESSION_END, s)
    return s


def run_work(spec: Spec, repo: str, approver=None, implementer_role: str = "coder",
             ledger_dir=None, max_turns: int | None = None, premise_panel: bool = False) -> dict:
    L = Ledger(ledger_dir=ledger_dir)
    sb = Sandbox()
    task = Task(spec)
    approvals = ApprovalService(L, channel=approver)
    traj = [task.state]
    L.append(EventType.SESSION_START,
             {"lane": "work", "spec_id": spec.id, "user_story": spec.user_story, "sandbox_mode": sb.mode})

    # Gate 0a: grounding — referenced files must resolve
    g = ground(spec, repo)
    L.append(EventType.GATE, {"gate": "grounding", "ok": g["ok"], "misses": g["misses"]})
    if not g["ok"]:
        task.transition("rejected"); traj.append(task.state)
        return _finish(L, task, traj, {"rejected_at": "grounding", "reason": f"unresolved refs: {g['misses']}"})
    task.transition("grounded"); traj.append(task.state)

    # Gate 0b: DoD authoring validation — vacuous / lint-bad checks rejected here
    v = validate_spec(spec, sb, repo)
    bad = [c for c in v["checks"] if not c["ok"]]
    L.append(EventType.GATE, {"gate": "dod_authoring", "ok": v["ok"], "bad": bad})
    if not v["ok"]:
        task.transition("rejected"); traj.append(task.state)
        return _finish(L, task, traj, {"rejected_at": "dod_authoring", "reason": bad})

    # Gate 0c: the cross-family premise panel (optional — a real gate that surfaces
    # gameable/misaligned checks to the human, not a blocker; the human decides)
    finding = None
    if premise_panel:
        from . import panel as _panel
        finding = _panel.review_spec(spec)
        L.append(EventType.GATE, {"gate": "premise_panel", "verdict": finding["panel_verdict"],
                                  "per_seat": finding["per_seat"], "reasons": finding["reasons"]})

    # Human approval over the real channel (a model has no action that reaches this)
    summary_line = f"Spec {spec.id}: {spec.user_story}\nDoD checks: {[c.name for c in spec.dod]}"
    if finding and finding["flagged"]:
        summary_line += ("\n\n[PREMISE PANEL FLAGGED this spec as UNSOUND — checks may pass while the "
                         "story is violated]\n" + "\n".join(
            f"  - {n}: {finding['reasons'].get(n,'')}" for n in finding["per_seat"]
            if finding["per_seat"][n] == "unsound"))
    decision = approvals.request(spec.id, summary_line)
    if decision != "approve":
        task.transition("rejected"); traj.append(task.state)
        return _finish(L, task, traj, {"rejected_at": "approval", "reason": "not approved by human"})
    task.transition("approved", approval="approve"); traj.append(task.state)

    # Build — write capability is granted only now
    task.transition("building"); traj.append(task.state)
    assert task.can_write(), "invariant: writes only while building"
    prompt = spec.user_story + ("\n\nIntent:\n- " + "\n- ".join(spec.intent) if spec.intent else "")
    build = run_task("Make this specification true:\n" + prompt, repo,
                     role=implementer_role, checks=[], ledger=L, max_turns=max_turns)

    # Verify — the HARNESS runs the DoD; real verdicts, not the model's claim
    task.transition("verifying"); traj.append(task.state)
    results = [run_check(c, sb, repo) for c in spec.dod]
    all_pass = all(r["passed"] for r in results)
    L.append(EventType.GATE, {"gate": "dod_verify", "all_pass": all_pass,
                              "results": [{"name": r["name"], "passed": r["passed"]} for r in results]})
    task.transition("done" if all_pass else "needs_human"); traj.append(task.state)

    summary = _finish(L, task, traj, {
        "approved": True, "dod_all_pass": all_pass,
        "dod": [{"name": r["name"], "passed": r["passed"]} for r in results],
        "build_changed": build.get("changed"), "build_turns": build.get("turns"),
        "edits_landed": build.get("edits_landed"), "sandbox_mode": sb.mode,
        "ledger": str(L.path), "session_id": L.session_id})
    from . import bastion
    bastion.emit({**summary, "turns": build.get("turns")}, L)
    return summary
