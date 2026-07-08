"""The work-lane full chain, on top of the kernel:

  spec -> ground -> validate DoD (authoring: vacuous/lint rejected) -> HUMAN
  approval (real channel) -> build (write capability granted ONLY now) ->
  verify (harness runs the DoD) -> done | needs_human | rejected

Capability follows state (Task.can_write is true only while building); a vacuous
DoD never reaches approval; only a human-channel grant reaches the build state.
Everything lands in one replayable ledger.

TDD red-green (Story #458): inside the build step, an opt-in `tdd=True` inserts
a TESTER phase BEFORE the implementer runs -- the tester authors a test, and the
harness (never the model's claim) confirms it is a genuine RED against the
current code, the same negative-control discipline dod.py's authoring-time
validate_check already applies, now applied again at build time to whatever
the tester just wrote. A vacuous "red" (every DoD check already passes right
after the tester's change) routes to needs_human instead of silently letting
the implementer run against a test that never really tested anything; a tester
change that touches a non-test path is rejected outright (that's the
implementer's job, not the tester's). On a genuine red, task.state is left
untouched (still 'building') and the existing implementer + DoD-verify steps
below run completely unchanged -- so a successful tdd=True run has the exact
same trajectory as the non-tdd path.

Red-team fix (this revision): a prior attempt's "red" gate only ever checked
(a) scope (every changed path looks like tests/test_*.py) and (b) that
spec.dod -- authored independently, at Gate 0, before the tester ever ran --
still fails. Neither check ever inspects, runs, or in any way validates the
CONTENT of the artifact the tester actually produced, so a no-op stub
(`def test_noop(): pass`) or even a completely empty diff (no file written at
all) trivially satisfied both checks and rode straight through to 'done'.
The fix: `_tester_phase` now (1) restricts "changed" to paths that ACTUALLY
EXIST on disk after the tester's turn (a claimed diff is not evidence -- an
empty or non-existent artifact yields an empty list), and (2) has the harness
itself RUN each such file (`python3 <path>`, the same sandbox every DoD check
uses) and requires at least one to genuinely fail -- a no-op stub runs clean
(exit 0) and is correctly refused, exactly like an empty diff. spec.dod's
still-fails check is KEPT as a second, independent signal (AND'd, not
replaced). Symmetrically, GREEN (post-implementer) now re-runs the SAME
tester-written file(s) and requires them to now pass, in addition to
spec.dod -- so 'done' is driven by the SAME executable artifact the tester
wrote flipping from fail to pass, not by spec.dod alone (which could
otherwise pass for reasons that have nothing to do with what the tester
actually tested).

Red-team fix (second round, pre-commit Gate 3): three more holes closed.
(1) ARTIFACT PINNING: the GREEN re-run used to find the tester's test by PATH
only, so an implementer that rewrote the test to a no-op AND gamed a weak
spec.dod check reached 'done' with tester_test_pass=True (demonstrated
end-to-end). The harness now pins each tester file's sha256 BEFORE its RED
run (a third-round red-team demonstrated that pinning after the run let a
test that rewrites ITSELF during its own execution -- red once, clean forever
after -- pin its post-mutation bytes and reach a false 'done'); at GREEN, any
pin mismatch (rewritten, gutted, deleted, or RED-time self-mutated file)
fails tester_test_pass with the modified paths named in the dod_verify GATE
event -- "the SAME executable artifact" is now enforced by content identity,
not path spelling. Residual, acknowledged: a test whose bytes never change
but whose behavior depends on EXTERNAL state it planted during RED (e.g. a
marker file elsewhere in the workspace) is not caught by the pin; it stays
bounded because spec.dod -- authored at Gate 0, before the tester existed --
is AND'd at both RED and GREEN.
(2) SCOPE-GATE QUOTING BYPASS: changed paths used to be regex-parsed from
run_diff's text headers, which git quotes for any non-ASCII filename
(core.quotePath) -- one non-ASCII byte in a filename made a non-test edit
invisible to the tester_scope gate. worklane now consumes run_task's
harness-computed `changed_paths` (git diff --name-only --no-renames -z: raw
bytes, never quoted; --no-renames because rename detection reported only the
destination, hiding a `mv impl.py tests/test_impl.py` from the scope gate;
surrogateescape decoding so a raw invalid-UTF-8 byte in a name cannot crash
the run). The header parser survives only as a fallback for callers that
don't provide the key.
(3) DIRECTORY ANCHORING: _is_test_path matched basename only, accepting
test_*.py anywhere (repo root, inside the package) despite the documented
tests/test_*.py contract; the directory is now part of the predicate.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .ledger import Ledger
from .sandbox import Sandbox
from .spec import Spec, SpecState
from .task import Task
from .human import ApprovalService
from .grounding import ground
from .dod import validate_spec, run_check
from .loop import run_task
from .types import EventType


# Story #458: the tester role's system prompt -- a narrower variant of
# animal.model.SYSTEM_PROMPT whose ONLY job is authoring a failing test, never
# implementation code (that division of labor is what makes the harness-
# computed red gate below meaningful: the tester genuinely cannot make its own
# test pass).
TESTER_SYSTEM_PROMPT = """You are a TESTER agent working inside a code workspace. Each turn, respond with EXACTLY ONE JSON object:
{"thought": "<brief reasoning>", "action": { ... }}

action.kind is one of:
- read   {"kind":"read","path":"file.py","offset":0,"limit":200}   view a file window. You MUST read a file before editing it.
- grep   {"kind":"grep","pattern":"regex","path":"."}
- edit   {"kind":"edit","path":"tests/test_x.py","old_string":"<EXACT text to replace>","new_string":"<replacement>"}   old_string must match the file exactly.
- shell  {"kind":"shell","argv":["python3","-c","print(1)"]}   argv LIST only — no shell string, no pipes/redirects.
- finish {"kind":"finish","message":"<what you did>"}   when the test is written.

Your ONLY job this turn is TDD RED: author (or extend) exactly one test file under
tests/ (a path whose name starts with "test_" and ends in ".py") that captures this
specification's Definition of Done and genuinely FAILS against the CURRENT,
not-yet-implemented code -- a real red, never a vacuous one (a test that already
passes proves nothing). Do NOT edit any non-test file; implementing the feature is
a later step, not yours. Finish once the test file is written."""


def _is_test_path(path: str) -> bool:
    """True iff `path` is a test file the tester role is allowed to touch during
    the TDD red phase: tests/test_*.py, directory included (red-team fix:
    basename-only matching quietly accepted test_x.py at the repo root or
    inside the package tree, broader than the contract TESTER_SYSTEM_PROMPT
    promises). Subdirectories under tests/ are fine. Any other changed path is
    the implementer's job, not the tester's."""
    p = Path(path)
    return (len(p.parts) >= 2 and p.parts[0] == "tests"
            and p.name.startswith("test_") and p.suffix == ".py")


def _changed_paths_from_diff(diff_text: str) -> list[str]:
    """FALLBACK ONLY -- path names regex-parsed from a unified diff's
    "diff --git a/X b/Y" header lines. Red-team fix: git QUOTES any filename
    with a non-ASCII byte in these headers (core.quotePath), which this regex
    then misses -- so a non-test edit could ride past the tester_scope gate on
    its filename alone. _tester_phase therefore prefers run_task's
    harness-computed `changed_paths` (git diff --name-only -z, never quoted);
    this parser remains only for callers whose run_task substitute predates
    that key (e.g. older mocks returning just run_diff)."""
    paths: set[str] = set()
    for line in (diff_text or "").splitlines():
        m = re.match(r"^diff --git a/(.+) b/(.+)$", line)
        if m:
            paths.add(m.group(1)); paths.add(m.group(2))
    return sorted(paths)


def _sha_file(p: Path) -> str | None:
    """sha256 of a file's current bytes, or None if it does not exist -- the
    identity pin that makes RED's and GREEN's "same tester artifact" a
    computed fact instead of a path-spelling assumption."""
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _finish(L, task, traj, extra) -> dict:
    s = {"spec_id": task.spec.id, "final_state": task.state, "trajectory": traj, **extra}
    L.append(EventType.SESSION_END, s)
    return s


def _run_test_file(sb: Sandbox, repo, path: str, timeout: int = 60) -> dict:
    """Red-team fix: the harness ACTUALLY RUNS the exact file the tester wrote
    (`python3 <path>`, executed in the same sandbox every DoD check uses) and
    reports what genuinely happened -- exit_code and pass/fail computed by the
    harness, never inferred from the tester's own claim or from spec.dod (which
    is authored independently and can pass or fail for reasons that have
    nothing to do with what this specific file contains). A no-op stub such as
    `def test_noop(): pass` defines a function and never calls it -- running it
    exits 0, same as any other command that trivially succeeds, and is
    correctly reported as NOT failing.

    extra_env=PYTHONPATH(repo root): `python3 <path>` (script mode) sets
    sys.path[0] to the test file's OWN directory (tests/), not the repo root,
    so a test that does `import <module under test>` (living at the repo
    root) would otherwise ModuleNotFoundError for a reason that has nothing to
    do with the assertion it's testing -- unlike this repo's own DoD checks,
    which use `python3 -c "..."` and get cwd on sys.path[0] for free. Adding
    the repo root to PYTHONPATH gives script-mode execution the same reach
    without changing what's executed (still the file's own source, __file__
    still resolves correctly -- unlike exec()-ing the source via -c, which
    would silently break any test file following this repo's own convention
    of `Path(__file__).resolve()...`)."""
    r = sb.run(["python3", path], repo, timeout=timeout,
              extra_env={"PYTHONPATH": str(Path(repo).resolve())})
    return {"path": path, "exit_code": r["exit_code"], "passed": r["exit_code"] == 0}


def _tester_phase(L, task, traj, spec, repo, sb, tester_role, max_turns, include_repo_map):
    """Story #458: run the tester role FIRST, inside the 'building' state (write
    capability already granted), and let the harness -- never the tester's own
    claim -- decide the outcome:
      - the tester touched a non-test path -> REJECTED (that's the
        implementer's job, not the tester's); implementer never runs.
      - the tester produced no real artifact (an empty diff, or a claimed path
        that was never actually written to disk), or every changed test file
        the harness actually RUNS exits clean (a vacuous/no-op test, e.g.
        `def test_noop(): pass`), or every spec.dod check ALREADY passes right
        after the tester's change -> no genuine red was achieved -> NEEDS_HUMAN;
        implementer never runs.
      - otherwise: a genuine red is confirmed (a real test file exists, the
        harness ran it and it genuinely failed, AND spec.dod independently
        still fails). Returns (None, pins) -- pins maps each tester test path
        to the sha256 of its bytes at RED -- so the caller proceeds to the
        implementer with task.state left untouched (still 'building'); a
        successful tdd run's trajectory is therefore byte-for-byte identical
        to the non-tdd path. The pins are threaded through to the
        post-implementer GREEN check, which re-runs the SAME artifact and
        fails any file whose pin no longer matches (an implementer that
        rewrites/guts/deletes the tester's test cannot reach 'done').
    Returns (finished_dict, {}) on either early-exit outcome, or (None, pins)
    to continue.
    """
    tester_prompt = (
        "Write a test that FAILS on the current code and captures this specification's "
        "Definition of Done (TDD red phase):\n" + spec.user_story +
        ("\n\nIntent:\n- " + "\n- ".join(spec.intent) if spec.intent else "") +
        "\n\nDoD checks the eventual implementation must satisfy:\n" +
        "\n".join(f"  - {c.name}: `{' '.join(c.argv)}`" for c in spec.dod))
    tester_out = run_task(tester_prompt, repo, role=tester_role, checks=[], ledger=L,
                          max_turns=max_turns, include_repo_map=include_repo_map,
                          system_prompt=TESTER_SYSTEM_PROMPT)
    # Red-team fix: prefer the harness-computed changed_paths (never quoted,
    # so a non-ASCII filename cannot hide from the scope gate); the regex
    # header parser is only a fallback for run_task substitutes without the key.
    changed = tester_out.get("changed_paths") or _changed_paths_from_diff(tester_out.get("run_diff", ""))
    bad = [p for p in changed if not _is_test_path(p)]
    L.append(EventType.GATE, {"gate": "tester_scope", "changed": changed, "bad": bad})
    if bad:
        task.transition("rejected"); traj.append(task.state)
        return _finish(L, task, traj, {"rejected_at": "tester_scope",
                       "reason": f"tester edited non-test path(s): {bad}",
                       "tester_turns": tester_out.get("turns")}), {}

    # Red-team fix: a claimed diff is not evidence. Only paths that actually
    # exist on disk after the tester's turn count as an artifact -- an empty
    # diff (changed=False, nothing written) or a diff naming a path that was
    # never really written both collapse to an empty list here, and an empty
    # list can never produce a genuine red below (there is nothing to run).
    test_paths = [p for p in changed if (Path(repo) / p).is_file()]
    # Pin each artifact's content identity BEFORE the harness runs it
    # (red-team, third round): pinning after the RED run let a test that
    # rewrites ITSELF during its own execution -- red once, clean forever
    # after -- get its post-mutation bytes pinned, so GREEN's pin check
    # matched and a false 'done' was demonstrated against a weak spec.dod.
    # Pinned pre-run, any RED-time self-mutation is a pin mismatch at GREEN.
    pins = {p: _sha_file(Path(repo) / p) for p in test_paths}
    file_results = [_run_test_file(sb, repo, p) for p in test_paths]
    # Harness-COMPUTED content check: at least one of the tester's own test
    # files must ACTUALLY FAIL when the harness runs it -- not claimed, run.
    file_red = any(not r["passed"] for r in file_results)
    L.append(EventType.GATE, {"gate": "tester_artifact", "test_paths": test_paths,
                              "file_results": file_results, "file_red": file_red})

    # Second, independent signal (kept from the original design): re-run every
    # spec.dod check against the post-tester tree (nothing here trusts the
    # tester's own claim either).
    red_results = [run_check(c, sb, repo) for c in spec.dod]
    dod_red = not all(r["passed"] for r in red_results)
    L.append(EventType.GATE, {"gate": "red_confirmed", "all_pass": not dod_red,
                              "results": [{"name": r["name"], "passed": r["passed"]} for r in red_results]})

    if not (test_paths and file_red and dod_red):
        reasons = []
        if not test_paths:
            reasons.append("tester produced no test artifact (no changed path exists on disk)")
        elif not file_red:
            reasons.append("the tester's own test file(s) ran clean (no genuine failure)")
        if not dod_red:
            reasons.append("spec.dod checks already pass")
        # verifying -> needs_human is an allowed transition (task.py); building
        # cannot reach needs_human directly, so this passes through 'verifying'
        # exactly as the real post-implementer verify step would.
        task.transition("verifying"); traj.append(task.state)
        task.transition("needs_human"); traj.append(task.state)
        # vacuous_red marker: the trajectory necessarily shows 'verifying'
        # (building cannot reach needs_human directly), so replay tooling
        # needs an explicit flag to distinguish this early exit from the real
        # post-implementer verify step having run.
        return _finish(L, task, traj, {"reason": "tests did not fail (vacuous red): " + "; ".join(reasons),
                       "vacuous_red": True,
                       "tester_turns": tester_out.get("turns")}), {}
    # Genuine red confirmed -- task.state left at 'building'. The pins (taken
    # above, BEFORE the RED run) let GREEN prove it is re-running the very
    # bytes the tester wrote, not whatever any later step left at that path.
    return None, pins


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
             learn: bool = False, include_repo_map: bool = True, tdd: bool = False,
             tester_role: str = "tester") -> dict:
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

    # Story #458: TDD red-green -- opt-in (tdd=False, the default, keeps every
    # existing caller byte-for-byte unchanged). The tester role runs BEFORE the
    # implementer; a harness-computed genuine red is required to proceed. An
    # early exit here (reject / needs_human) means the implementer never runs.
    tester_pins: dict[str, str] = {}   # test path -> sha256 of its bytes at RED
    if tdd:
        tester_finish, tester_pins = _tester_phase(L, task, traj, spec, repo, sb, tester_role,
                                       max_turns, include_repo_map)
        if tester_finish is not None:
            return tester_finish

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
    dod_pass = all(r["passed"] for r in results)
    # Red-team fix (Story #458): GREEN must be driven by the SAME artifact the
    # tester wrote, not by spec.dod alone -- otherwise a spec.dod check that
    # happens to pass for reasons unrelated to what the tester actually tested
    # could mark the task 'done' while the tester's own test still fails. When
    # tdd confirmed a genuine red against real file(s), re-run those same
    # files here (harness-computed, never the model's claim) and require them
    # to now pass too. Kept as a SEPARATE signal from dod_pass (never folded
    # into it) so dod_all_pass in the returned summary keeps meaning exactly
    # what it always has: "every spec.dod check passed" -- a caller reading
    # dod_all_pass to debug a spec.dod check specifically must not see it
    # silently start reflecting an unrelated tester-artifact result.
    tester_test_results = [_run_test_file(sb, repo, p) for p in tester_pins] if tester_pins else []
    # Red-team fix (second round): "the SAME artifact" is enforced by content
    # identity -- any tester file whose sha256 no longer matches its RED pin
    # (rewritten, gutted, or deleted by the implementer) fails tester_test_pass
    # outright, with the offending paths named in the GATE event. Without this,
    # re-running by PATH let an implementer replace the test with a no-op and
    # reach 'done' against a weak spec.dod (demonstrated end-to-end).
    tester_modified = [p for p, sha in tester_pins.items()
                       if _sha_file(Path(repo) / p) != sha]
    tester_test_pass = (all(r["passed"] for r in tester_test_results)
                        and not tester_modified) if tester_pins else True
    all_pass = dod_pass and tester_test_pass
    L.append(EventType.GATE, {"gate": "dod_verify", "all_pass": all_pass, "dod_pass": dod_pass,
                              "results": [{"name": r["name"], "passed": r["passed"]} for r in results],
                              **({"tester_test_results": tester_test_results,
                                  "tester_artifact_modified": tester_modified,
                                  "tester_test_pass": tester_test_pass} if tester_pins else {})})
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
        "approved": True, "dod_all_pass": dod_pass,
        "dod": [{"name": r["name"], "passed": r["passed"]} for r in results],
        "build_changed": build.get("changed"), "build_turns": build.get("turns"),
        "edits_landed": build.get("edits_landed"), "sandbox_mode": sb.mode,
        "ledger": str(L.path), "session_id": L.session_id,
        # Story #458: only present when tdd confirmed a genuine red against a
        # real file -- the SAME artifact (sha-pinned at RED) re-checked here at
        # GREEN, separate from dod_all_pass above (see the dod_verify GATE
        # comment). tester_artifact_modified names any pin mismatch so the
        # human reading a needs_human summary sees WHY at a glance.
        **({"tester_test_pass": tester_test_pass,
            **({"tester_artifact_modified": tester_modified} if tester_modified else {})}
           if tester_pins else {})})
    from . import bastion
    bastion.emit({**summary, "turns": build.get("turns")}, L)
    return summary
