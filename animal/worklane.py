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


def run_work_from_story(user_story: str, repo: str, approver=None, po_role: str = "product_owner",
                        po_max_retries: int = 2, po_timeout: int = 600, **kw) -> dict:
    """Story #457: the maker gives a raw, plain-language user_story; a
    product-owner model call authors the Spec (intent/out_of_scope/DoD) via
    animal.product_owner.author_spec, which already round-trips it through
    Spec.from_dict + dod.validate_check before returning -- so the SAME
    grounding/authoring-validation chain in run_work below runs UNCHANGED on a
    model-authored spec exactly as it does on a hand-authored one (a
    vacuous/ungrounded model-authored spec is rejected exactly as a
    hand-authored one would be). author_spec raises ProductOwnerError (never
    silently) if it can't produce a valid, non-vacuous spec within
    po_max_retries corrective attempts -- that error propagates here, so a
    maker never gets a rejected/degraded spec back disguised as a normal run.
    po_timeout (seconds, per model call) defaults to 600 -- see
    animal.product_owner._chat's docstring for why a real call can legitimately
    take minutes on a contended host."""
    from .product_owner import author_spec
    spec = author_spec(user_story, repo, role=po_role, max_retries=po_max_retries, timeout=po_timeout)
    # #457 red-team: a MODEL-authored spec lacks the human's implicit check-authoring
    # scrutiny that Gate 0 always quietly relied on. Gate 0 catches STRUCTURAL badness
    # (vacuous/ungrounded checks) but not SEMANTIC badness (a check whose plausible
    # name doesn't match what its argv actually tests). So the cross-family premise
    # panel (Gate 0c, built for exactly this gameable-check class) runs BY DEFAULT on a
    # model-authored spec -- the caller can still override premise_panel explicitly.
    kw.setdefault("premise_panel", True)
    return run_work(spec, repo, approver=approver, **kw)


def run_work(spec: Spec, repo: str, approver=None, implementer_role: str = "coder",
             ledger_dir=None, max_turns: int | None = None, premise_panel: bool = False,
             learn: bool = False, include_repo_map: bool = True) -> dict:
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

    # Human approval over the real channel (a model has no action that reaches this).
    # #457 red-team: show each check's BODY (argv/comparator/expected), not just its
    # name -- a model-authored check with a plausible name but a trivial, story-
    # irrelevant body is invisible when only names are shown, and Gate 0 catches
    # structural, not semantic, badness. The approver must be able to read what each
    # check ACTUALLY tests before approving.
    def _check_line(c):
        exp = getattr(c, "expected", "") or ""
        tail = f" [{c.comparator}{': ' + exp if exp else ''}]"
        return f"  - {c.name}: `{' '.join(c.argv)}`{tail}"
    summary_line = (f"Spec {spec.id}: {spec.user_story}\n"
                    f"DoD checks (verify each check actually tests the story):\n"
                    + "\n".join(_check_line(c) for c in spec.dod))
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
    # Story #449 fix: this IS the harness's real coder build step (a red-team
    # rejection of the prior attempt found zero real call sites for
    # include_repo_map) -- default it ON here so the gated work lane's actual
    # coding session sees the repo map without any extra opt-in from a caller.
    build = run_task("Make this specification true:\n" + prompt, repo,
                     role=implementer_role, checks=[], ledger=L, max_turns=max_turns,
                     include_repo_map=include_repo_map)

    # Verify — the HARNESS runs the DoD; real verdicts, not the model's claim
    task.transition("verifying"); traj.append(task.state)
    results = [run_check(c, sb, repo) for c in spec.dod]
    all_pass = all(r["passed"] for r in results)
    L.append(EventType.GATE, {"gate": "dod_verify", "all_pass": all_pass,
                              "results": [{"name": r["name"], "passed": r["passed"]} for r in results]})
    task.transition("done" if all_pass else "needs_human"); traj.append(task.state)

    # Learning plane (opt-in): learn from the VERIFIED outcome of this run — record
    # calibration from the ledger, and upsert each passed DoD check as a lesson
    # (re-observation compiles it into a standing regression check).
    if learn:
        from .calibration import Calibration
        from .lessons import Lessons
        cal = Calibration(); n_cal = cal.ingest_ledger(L); cal.close()
        les = Lessons()
        paths = [g["ref"] for g in spec.groundings if g.get("exists")]
        n_les = 0
        for c, r in zip(spec.dod, results):
            if r["passed"]:
                les.upsert(f"{spec.id}:{c.name}", spec.user_story, paths=paths, check=c, verified_good=True)
                n_les += 1
        les.close()
        L.append(EventType.GATE, {"gate": "learn", "calibration_records": n_cal, "lessons_upserted": n_les})

    summary = _finish(L, task, traj, {
        "approved": True, "dod_all_pass": all_pass,
        "dod": [{"name": r["name"], "passed": r["passed"]} for r in results],
        "build_changed": build.get("changed"), "build_turns": build.get("turns"),
        "edits_landed": build.get("edits_landed"), "sandbox_mode": sb.mode,
        "ledger": str(L.path), "session_id": L.session_id})
    from . import bastion
    bastion.emit({**summary, "turns": build.get("turns")}, L)
    return summary
