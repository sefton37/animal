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
    sub.add_parser("learn", help="inspect the learning plane (calibration, lessons, incidents, health) — read-only")
    b = sub.add_parser("backlog", help="read/write the local product backlog (epics + stories) — #452 CRUD")
    bsub = b.add_subparsers(dest="backlog_cmd", required=True)
    be = bsub.add_parser("add-epic", help="create an epic")
    be.add_argument("title")
    be.add_argument("--priority", type=int, default=0)
    bs = bsub.add_parser("add-story", help="create a story under an epic (Fibonacci-validated points)")
    bs.add_argument("epic_id", type=int)
    bs.add_argument("title")
    bs.add_argument("--user-story", default=None)
    bs.add_argument("--points", type=int, default=None, dest="story_points")
    bs.add_argument("--priority", type=int, default=0)
    bl = bsub.add_parser("list", help="list backlog stories (optionally filtered)")
    bl.add_argument("--epic-id", type=int, default=None)
    bl.add_argument("--status", default=None)
    ble = bsub.add_parser("list-epics", help="list epics (optionally filtered by status)")
    ble.add_argument("--status", default=None)
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

    if args.cmd == "backlog":
        from .product import ProductStore, ProductError
        ps = ProductStore()
        try:
            if args.backlog_cmd == "add-epic":
                eid = ps.create_epic(args.title, priority=args.priority)
                print(f"epic #{eid} created: {args.title}")
            elif args.backlog_cmd == "add-story":
                sid = ps.create_story(args.epic_id, args.title, user_story=args.user_story,
                                       story_points=args.story_points, priority=args.priority)
                print(f"story #{sid} created under epic #{args.epic_id}: {args.title}")
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
