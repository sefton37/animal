"""Story #447 measurement run: 12 synthetic edit tasks x 3 formats against the
LIVE resident 'coder' seat (Qwen3-Coder-30B-A3B via llama-swap, per
phase0/results/model-roster.md), scored on a REAL signal -- not just "did the
regex match something" but "did the extracted old_string actually anchor,
byte-for-byte, in the real source" (the JSON-escaping failure mode the story
names: a model can produce syntactically-valid JSON whose old_string still
doesn't match the file because of an escaping/quoting slip).

Committed so the numbers in ../EDIT-FORMAT-EVAL-2026-07-06.md are re-runnable,
not asserted (this project's "measure before load-bearing" discipline, per
phase0/PREREGISTRATION.md) -- re-run it against the same live roster and the
raw JSON lands in ../results/edit-format-eval.json.

Run (from the repo root, with llama-swap already serving on config.LLAMA_SWAP_URL):
    python3 phase1/bench/edit_format_eval.py > phase1/results/edit-format-eval.json
"""
import json, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from animal import dialect, config
from animal.model import ModelPlane

URL = config.LLAMA_SWAP_URL
ROLE = "coder"
RC = config.ROLES[ROLE]

# 12 synthetic single-file edit tasks. Each source snippet embeds a double
# quote and/or a backslash -- the exact content class JSON string-escaping
# can mangle -- and each task asks for one small, well-specified change.
TASKS = [
    ("f1.py",  'def greet(name):\n    print("hi, " + name)\n',
     'change the greeting text from "hi, " to "hello, "'),
    ("f2.py",  'def path_of(x):\n    return "C:\\\\data\\\\" + x\n',
     'change the base path from "C:\\\\data\\\\" to "C:\\\\out\\\\"'),
    ("f3.py",  'def warn(msg):\n    print("warning: \\"" + msg + "\\"")\n',
     'change "warning: " to "WARNING: " in the printed prefix'),
    ("f4.py",  'def add(a, b):\n    return a + b\n',
     'rename the function from add to sum_two'),
    ("f5.py",  'def label():\n    return "it\'s fine"\n',
     'change the returned string from "it\'s fine" to "it\'s good"'),
    ("f6.py",  'def quote(s):\n    return \'"\' + s + \'"\'\n',
     'wrap the string in single quotes instead of double quotes'),
    ("f7.py",  'def divide(a, b):\n    return a / b\n',
     'add a check that raises ValueError("division by zero") when b == 0'),
    ("f8.py",  'def title():\n    return "Report: \\n Section 1"\n',
     'change "Section 1" to "Section 2" in the returned string'),
    ("f9.py",  'def cmd():\n    return "echo \\"done\\""\n',
     'change done to finished inside the quoted echo string'),
    ("f10.py", 'def mul(a, b):\n    return a * b\n',
     'rename the function from mul to multiply'),
    ("f11.py", 'def regex():\n    return "\\\\d+\\\\s*"\n',
     'change \\\\d+ to \\\\w+ in the returned regex string'),
    ("f12.py", 'def sub(a, b):\n    return a - b\n',
     'rename the function from sub to subtract'),
]


def _raw_call(system_prompt: str, user_prompt: str, response_format=None) -> str:
    body = {"model": RC["model"], "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}],
            "temperature": 0.2, "max_tokens": 512}
    if response_format:
        body["response_format"] = response_format
    req = urllib.request.Request(URL + "/v1/chat/completions", data=json.dumps(body).encode(),
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read())
    return resp["choices"][0]["message"].get("content", "") or ""


def run_search_replace(path, src, instruction):
    sys_p = ("You are a coding agent editing ONE file.\n" + dialect.SEARCH_REPLACE_PROMPT)
    user_p = f"File `{path}` current content:\n```\n{src}```\n\nTask: {instruction}"
    raw = _raw_call(sys_p, user_p)
    blocks = dialect.parse_search_replace(raw)
    ok = any(b["path"] == path and b["old_string"] and b["old_string"] in src for b in blocks)
    return ok, raw


def run_whole_file(path, src, instruction):
    sys_p = ("You are a coding agent editing ONE file.\n" + dialect.WHOLE_FILE_PROMPT)
    user_p = f"File `{path}` current content:\n```\n{src}```\n\nTask: {instruction}"
    raw = _raw_call(sys_p, user_p)
    blocks = dialect.parse_whole_file(raw)
    ok = any(b["path"] == path and b["new_string"] and b["new_string"].strip() for b in blocks)
    return ok, raw


def run_json(path, src, instruction):
    mp = ModelPlane()
    sys_p = ("You are a coding agent editing ONE file. Respond with exactly one JSON turn "
             '{"thought":..., "action": {"kind":"edit","path":..., "old_string":..., "new_string":...}}. '
             "old_string must be an EXACT substring of the file's current content, copied verbatim.")
    user_p = f"File `{path}` current content:\n```\n{src}```\n\nTask: {instruction}"
    messages = [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]
    try:
        turn, meta = mp.call("coder", messages, temperature=0.2)
    except Exception as e:
        return False, f"ModelError: {e}"
    action = turn.get("action", {})
    old = action.get("old_string", "")
    ok = bool(old) and old in src and action.get("path") == path
    return ok, json.dumps(turn)


def main():
    results = {"search_replace": [], "whole_file": [], "json": []}
    t0 = time.time()
    for path, src, instruction in TASKS:
        for fmt, fn in (("search_replace", run_search_replace),
                        ("whole_file", run_whole_file),
                        ("json", run_json)):
            try:
                ok, raw = fn(path, src, instruction)
            except Exception as e:
                ok, raw = False, f"EXC: {e}"
            results[fmt].append({"task": path, "ok": ok})
            print(f"  {fmt:14s} {path:8s} ok={ok}", file=sys.stderr)
    elapsed = time.time() - t0
    summary = {fmt: {"n": len(v), "ok": sum(1 for x in v if x["ok"])} for fmt, v in results.items()}
    print(json.dumps({"summary": summary, "elapsed_s": round(elapsed, 1), "detail": results}, indent=2))


if __name__ == "__main__":
    main()
