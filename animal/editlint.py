"""Advisory syntax-lint gate for the edit pipeline (Story #445, M1-execution-craft).

Runs on the COMPUTED new_content before it is ever written to disk, so an edit
that would break a file's syntax is rejected before it lands -- not discovered
later, after the coder has already spent turns compounding a break it doesn't
know it made.

Per-extension, closed-world dispatch: an extension the dispatcher does not
recognize is always clean. This must never produce a false rejection for a
language the linter doesn't understand -- lint is advisory-only outside the
languages it actually knows.

Coverage, and why each is or isn't in scope (Audit 1.5 fix -- the prior cut
only registered .py, which left the pipeline's own repo mostly unprotected:
a `git ls-files` extension census here is 30 .py / 14 .md / 12 .txt / 11 .json
/ 5 .sh / 1 .yaml / 1 .c):
  - .py   -- ast.parse, in-process, exact.
  - .json -- json.loads (stdlib), in-process, exact.
  - .sh   -- `bash -n`, a real syntax-only pass by the system's own bash over
             stdin. Calling an external binary via subprocess is the same
             pattern workspace.py already uses for the shadow git repo -- it
             is not a pip dependency, so it holds to the stdlib-only rule.
  - .c    -- `gcc -fsyntax-only -xc -`, same subprocess pattern, syntax-only
             (does not compile/link/execute).
  - .js/.mjs/.cjs -- `node --check` over a temp file (node re-opens its path
             argument, so stdin fails). A primary target language of this harness
             (the Stalag codebase). Added in the #445 red-team follow-up after a
             spirit-audit landed a syntax-broken JS/Kotlin edit on disk while
             every letter-of-the-DoD check still passed.
  - .kt/.ts -- advisory-only, NOT by choice but by toolchain: kotlinc/tsc are not
             installed here, and rejecting a language we cannot actually parse is
             exactly the false-rejection this module forbids. They become real
             linters the moment their checker is on PATH. Named here so the gap is
             honest and tracked, not silent.
  - .sh/.c/.js binaries: if bash / gcc / node isn't installed on a given machine,
    that extension silently falls back to advisory-only for this run -- a missing
    tool must never cause a false rejection.
  - .yaml -- deliberately NOT covered. The standard library has no YAML
    parser, and a hand-rolled indentation/heuristic checker would risk the
    exact false-rejection failure mode this module exists to prevent (YAML's
    grammar -- block scalars, anchors, flow collections, multi-doc streams --
    is not safely approximable without a real parser). Left advisory-only
    until a real parser is available, rather than shipping an unsound one.
  - .md/.txt -- deliberately NOT covered. Prose has no syntax to break.
"""
from __future__ import annotations
import ast, json, os, subprocess, tempfile


def _lint_python(content: str) -> str | None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno})"
    return None


def _lint_json(content: str) -> str | None:
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        return f"JSONDecodeError: {e.msg} (line {e.lineno} col {e.colno})"
    return None


def _lint_via_subprocess(cmd: list[str], content: str) -> str | None:
    """Run an external syntax-only checker over content on stdin. Advisory-only
    if the binary isn't present on this machine -- a missing tool is an
    environment fact, never grounds to reject the model's edit."""
    try:
        r = subprocess.run(cmd, input=content, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode == 0:
        return None
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    return lines[0] if lines else f"{cmd[0]}: syntax check failed (exit {r.returncode})"


def _lint_sh(content: str) -> str | None:
    return _lint_via_subprocess(["bash", "-n"], content)


def _lint_c(content: str) -> str | None:
    return _lint_via_subprocess(["gcc", "-fsyntax-only", "-xc", "-"], content)


def _node_check(content: str, suffix: str):
    """`node --check` over content in a temp file of the given extension (node
    re-opens its path argument, so a pipe fails). None = clean, False = node
    absent (advisory), else the first error line."""
    try:
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except OSError:
        return False
    try:
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if r.returncode == 0:
        return None
    return next((ln.strip() for ln in (r.stderr or r.stdout or "").splitlines() if "Error" in ln),
                "node --check: syntax error")


def _lint_js(content: str) -> str | None:
    """Syntax-check JS via `node --check`. node SKIPS checking a bare .js temp
    file that uses ESM syntax, so check as an ES module (.mjs) -- which catches
    real errors -- and, to never reject code merely invalid under ESM strictness,
    only reject when the failure ALSO reproduces as CommonJS (.cjs). A genuine
    syntax error fails both; a module-type artifact fails only one. Advisory-only
    if node is absent. A primary target language of this harness (Stalag)."""
    esm = _node_check(content, ".mjs")
    if esm is None or esm is False:      # clean, or node absent -> advisory
        return None
    cjs = _node_check(content, ".cjs")
    if cjs is None or cjs is False:      # ESM-strictness artifact, not a real break
        return None
    return esm


_LINTERS = {
    ".py": _lint_python,
    ".json": _lint_json,
    ".sh": _lint_sh,
    ".c": _lint_c,
    ".js": _lint_js,
    ".mjs": _lint_js,
    ".cjs": _lint_js,
}


def lint(path: str, content: str) -> str | None:
    """Dispatch on path's extension. Returns None when content is clean (or
    the extension isn't recognized -- advisory-only for unknown languages),
    else a short human-readable message describing why it would not parse."""
    for ext, fn in _LINTERS.items():
        if path.endswith(ext):
            return fn(content)
    return None
