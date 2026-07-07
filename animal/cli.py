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
    args = ap.parse_args(argv)

    if args.cmd == "run":
        checks = [{"name": f"check{i}", "argv": shlex.split(c)} for i, c in enumerate(args.check)]
        s = run_task(args.task, args.repo, role=args.role, checks=checks, max_turns=args.max_turns)
        printable = {k: v for k, v in s.items() if k != "run_diff"}
        print(json.dumps(printable, indent=2))
        print("\n--- computed run diff ---\n" + (s["run_diff"] or "(no changes on disk)"))
        # exit non-zero if any harness-run check failed (real verdict, not a claim)
        return 0 if all(c["ok"] for c in s["checks"]) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
