"""Minimal headless CLI: `python3 -m animal.cli run "<task>" --repo <path>`.
The full NDJSON control protocol + TUI are later; this is enough to do and
inspect real trivial-lane work."""
from __future__ import annotations
import argparse, json, shlex, sys
from .loop import run_task


def main(argv=None):
    ap = argparse.ArgumentParser(prog="animal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a task in a repo")
    r.add_argument("task")
    r.add_argument("--repo", required=True)
    r.add_argument("--role", default="coder")
    r.add_argument("--check", action="append", default=[],
                   help="a check command (shlex-split); the harness runs it and records the real exit code")
    r.add_argument("--max-turns", type=int, default=None)
    r.add_argument("--no-repo-map", dest="repo_map", action="store_false", default=True,
                   help="omit the compact repo file/symbol map from the system prompt "
                        "(Story #449: included by default so the coder can request the right "
                        "file directly instead of groping by trial-and-error grep/read)")
    d = sub.add_parser("discover", help="bounded conversational discovery: decompose a topic into raw user stories (#462); with --repo, the full M4 pipeline (#466): elicit -> cluster -> draft -> refine -> persist")
    d.add_argument("topic")
    d.add_argument("--repo", default=None, help="run the full pipeline against this repo, persisting an epic + grounded specs")
    d.add_argument("--max-turns", type=int, default=None)
    sz = sub.add_parser("size", help="size a backlog story with the diverse-model planning-poker panel (#467-471); wide disagreement escalates to YOU")
    sz.add_argument("story_id", type=int)
    sz.add_argument("--threshold", type=int, default=3,
                    help="index-distance disagreement at/over which the panel escalates to the human (default 3)")
    sz.add_argument("--channel-test", default=None, dest="channel_test",
                    help="TESTING ONLY: a scripted human reply for the escalation channel (bypasses the TUI)")
    sp = sub.add_parser("sprint", help="run a deadline-boxed sprint over the backlog, iterate the gated chain, emit a review package (#472-476)")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--deadline", required=True,
                    help="ISO8601 timestamp, or a relative +Nm / +Nh / +Ns from now")
    sp.add_argument("--out", default=None, help="directory for the review package (default: var/)")
    sub.add_parser("learn", help="inspect the learning plane (calibration, lessons, incidents, health) — read-only")
    b = sub.add_parser("backlog", help="read/write the local product backlog (epics + stories) — #452 CRUD")
    # bare `animal backlog` -> the prioritized view (#471 audit: an argparse
    # usage error is not an answer to "show me my backlog")
    bsub = b.add_subparsers(dest="backlog_cmd", required=False)
    be = bsub.add_parser("add-epic", help="create an epic")
    be.add_argument("title")
    be.add_argument("--priority", type=int, default=0,
                    help="ORDERING signal, ascending (P1 = top); NOT the value used by `backlog prioritized`")
    bs = bsub.add_parser("add-story", help="create a story under an epic (Fibonacci-validated points)")
    bs.add_argument("epic_id", type=int)
    bs.add_argument("title")
    bs.add_argument("--user-story", default=None)
    bs.add_argument("--points", type=int, default=None, dest="story_points")
    bs.add_argument("--priority", type=int, default=0,
                    help="ORDERING signal, ascending (P1 = top); distinct from --value")
    bs.add_argument("--value", type=int, default=0,
                    help="business VALUE (WSJF numerator), higher = more valuable; feeds `backlog prioritized`")
    bsv = bsub.add_parser("set-value", help="set a story's business value (WSJF numerator) — the remedy for an 'unvalued' story")
    bsv.add_argument("story_id", type=int)
    bsv.add_argument("value", type=int)
    bl = bsub.add_parser("list", help="list backlog stories (optionally filtered)")
    bl.add_argument("--epic-id", type=int, default=None)
    bl.add_argument("--status", default=None)
    ble = bsub.add_parser("list-epics", help="list epics (optionally filtered by status)")
    ble.add_argument("--status", default=None)
    bp = bsub.add_parser("prioritized", help="the backlog ordered by value/effort (WSJF-lite, harness-computed) — #470")
    bp.add_argument("--epic-id", type=int, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "run":
        checks = [{"name": f"check{i}", "argv": shlex.split(c)} for i, c in enumerate(args.check)]
        s = run_task(args.task, args.repo, role=args.role, checks=checks, max_turns=args.max_turns,
                     include_repo_map=args.repo_map)
        printable = {k: v for k, v in s.items() if k != "run_diff"}
        print(json.dumps(printable, indent=2))
        print("\n--- computed run diff ---\n" + (s["run_diff"] or "(no changes on disk)"))
        # exit non-zero if any harness-run check failed (real verdict, not a claim)
        return 0 if all(c["ok"] for c in s["checks"]) else 1

    if args.cmd == "discover":
        from .discovery import run_discovery
        from .ledger import Ledger
        if args.repo:
            # Story #466: the single orchestration entrypoint -- elicit,
            # cluster, draft, refine, persist. Specs land at draft/grounded
            # only; approval remains worklane.run_work's human channel.
            from .discovery import run_discovery_to_backlog
            summary = run_discovery_to_backlog(args.topic, args.repo, max_turns=args.max_turns)
            print(json.dumps(summary, indent=2))
            died = summary["status"] in ("model_error", "maker_absent", "channel_error", "context_overflow")
            # #466 audit F3: this branch's deliverable is SPECS, not stories --
            # a run where every story failed to draft is a failure even if
            # the conversation itself finished cleanly
            specced = [st_ for st_ in summary["stories"] if st_.get("spec_id")]
            if died and not summary["stories"]:
                return 1
            if summary["stories"] and not specced:
                return 1
            return 0
        L = Ledger()
        stories = run_discovery(args.topic, ledger=L, max_turns=args.max_turns)
        ends = L.events_of("session_end")
        status = ends[-1].payload.get("status", "?") if ends else "?"
        print(json.dumps({"status": status, "stories": stories}, indent=2))
        # Red-team fix: zero stories from a session that DIED (model server
        # down, maker absent, context fault) is a FAILURE and must exit
        # non-zero -- an empty result from a finished conversation is a real
        # (if disappointing) outcome and exits 0. The status field makes the
        # difference visible either way.
        died = status in ("model_error", "maker_absent", "channel_error", "context_overflow")
        return 1 if (died and not stories) else 0

    if args.cmd == "size":
        from . import poker, estimates
        from .product import ProductStore
        from .ledger import Ledger
        st = ProductStore()
        story = st.get_story(args.story_id)
        if story is None:
            print(json.dumps({"error": f"no story {args.story_id}"}))
            return 1
        L = Ledger()
        votes = poker.run_panel(story)
        vote_list = [v["points"] for v in votes.values()]
        reasons = {k: v["reasoning"] for k, v in votes.items()}
        approvals = (lambda k, s_: args.channel_test) if args.channel_test is not None else None
        r = poker.converge(story, vote_list, approvals=approvals,
                           threshold=args.threshold, ledger=L, reasons=reasons,
                           channel_name=("channel-test" if args.channel_test is not None else None))
        estimates.record_panel_run(args.story_id, votes, r["points"], r["disagreement"],
                                   r["escalated"])
        if r["points"] is not None:
            st.update_story(args.story_id, story_points=r["points"])
        summary = {"story_id": args.story_id, "title": story["title"], "votes": votes,
                   "median": r["median"], "disagreement": r["disagreement"],
                   "escalated": r["escalated"], "points": r["points"],
                   **({"reply": r["reply"]} if "reply" in r else {})}
        print(json.dumps(summary, indent=2))
        # an unresolved size (all-abstain + no usable human reply) is a failure
        return 0 if r["points"] is not None else 1

    if args.cmd == "sprint":
        import re, time
        from datetime import datetime, timezone
        from . import config
        from pathlib import Path
        from .product import ProductStore
        from .sprint import run_sprint
        from .review import assemble_review, to_markdown
        m = re.fullmatch(r"\+(\d+)([smh])", args.deadline.strip())
        if m:
            mult = {"s": 1, "m": 60, "h": 3600}[m.group(2)]
            deadline_ts = time.time() + int(m.group(1)) * mult
        else:
            try:
                dt = datetime.fromisoformat(args.deadline)
                # a naive ISO string is read as UTC (matches _real_now's UTC
                # epoch), so a maker's '2026-07-09T06:00' is not silently
                # shifted by the host's local offset
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                deadline_ts = dt.timestamp()
            except ValueError:
                print(json.dumps({"error": f"bad --deadline {args.deadline!r} (use ISO8601 or +Nm/+Nh/+Ns)"}))
                return 1
        st = ProductStore()
        result = run_sprint(st, deadline_ts, args.repo)
        st.close()
        review = assemble_review(result)
        md = to_markdown(review)
        out_dir = Path(args.out) if args.out else config.VAR
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "sprint-review.json").write_text(json.dumps(review, indent=2))
        (out_dir / "sprint-review.md").write_text(md)
        print(md)
        print(f"\n(review package written to {out_dir}/sprint-review.{{json,md}})")
        return 0

    if args.cmd == "learn":
        from .calibration import Calibration
        from .lessons import Lessons
        from .incidents import Incidents
        from . import watchdogs
        cal, les, inc = Calibration(), Lessons(), Incidents()
        print("=== calibration (verified track record: model/role/claim -> true/total) ===")
        for m, r_, ct, n, nt in cal.db.execute("SELECT model,role,claim_type,n,n_true FROM calibration ORDER BY role,claim_type"):
            print(f"  {m}/{r_}/{ct}: {nt}/{n}")
        print("=== lessons ===")
        for k, pos, neg, comp, ret in les.db.execute("SELECT key,pos,neg,compiled,retired FROM lessons ORDER BY key"):
            print(f"  {k}  pos={pos} neg={neg} compiled={bool(comp)} retired={bool(ret)}")
        print("=== incidents (active, first 15) ===")
        for i in inc.active()[:15]:
            print(f"  [{i['date'] or '?'}] {i['class']}: {i['claim'][:80]}")
        print("=== watchdog health ===")
        h = watchdogs.health()
        for c in h["checks"]:
            print(f"  {'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
        print("=== product store (local backlog) ===")
        from .product import ProductStore
        ps = ProductStore()
        ec = ps.db.execute("SELECT COUNT(*) FROM epics").fetchone()[0]
        sc = ps.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        print(f"  {ec} epics / {sc} stories (the work lane populates this as specs land)")
        ps.close()
        print("healthy:", h["healthy"])
        return 0

    if args.cmd == "backlog" and getattr(args, "backlog_cmd", None) in (None, "prioritized"):
        from .backlog import prioritized
        from .product import ProductStore
        st = ProductStore()
        epic = getattr(args, "epic_id", None)
        rows = prioritized(st, epic_id=epic)
        st.close()
        if not rows:
            print("(no workable stories — try `animal backlog list` to see all)")
            return 0
        print(f"{'id':>4}  {'ratio':>6}  {'val':>3}  {'pts':>3}  {'flag':<16} title")
        remedied = []
        for r in rows:
            print(f"{r['id']:>4}  {str(r['ratio'] if r['ratio'] is not None else '-'):>6}  "
                  f"{r['value']:>3}  {str(r['points'] if r['points'] is not None else '-'):>3}  "
                  f"{(r['flag'] or ''):<16} {r['title']}")
            if r.get("remedy"):
                remedied.append(f"  #{r['id']} ({r['flag']}): {r['remedy']}")
        if remedied:
            print("\nto rank the flagged stories:")
            for line in remedied:
                print(line)
        return 0

    if args.cmd == "backlog":
        from .product import ProductStore, ProductError
        ps = ProductStore()
        try:
            if args.backlog_cmd == "add-epic":
                eid = ps.create_epic(args.title, priority=args.priority)
                print(f"epic #{eid} created: {args.title}")
            elif args.backlog_cmd == "add-story":
                sid = ps.create_story(args.epic_id, args.title, user_story=args.user_story,
                                       story_points=args.story_points, priority=args.priority,
                                       value=args.value)
                print(f"story #{sid} created under epic #{args.epic_id}: {args.title}")
            elif args.backlog_cmd == "set-value":
                ps.update_story(args.story_id, value=args.value)
                print(f"story #{args.story_id} value set to {args.value}")
            elif args.backlog_cmd == "list":
                for s in ps.list_backlog(epic_id=args.epic_id, status=args.status):
                    pts = s["story_points"] if s["story_points"] is not None else "-"
                    print(f"  #{s['id']} [{s['status']}] pts={pts} epic={s['epic_id']} {s['title']}")
            elif args.backlog_cmd == "list-epics":
                for e in ps.list_epics(status=args.status):
                    print(f"  epic #{e['id']} [{e['status']}] pri={e['priority']} {e['title']}")
        except ProductError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        finally:
            ps.close()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
