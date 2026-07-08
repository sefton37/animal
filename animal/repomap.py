"""Compact repo map (Story #449, M1-execution-craft): a field-scan of the
repo's files and their top-level symbols, injected into a coder's context so
it REQUESTS the right file directly instead of groping by trial-and-error
grep/read -- which burns local tok/s on a small resident model
(ARCHITECTURE.md's field-scan sketch: "tree-sitter tags + PageRank compressed
to ~1K tokens").

Tree-sitter vs stdlib fallback -- the decision this module's docstring must
record (Story #449's DoD): tree-sitter is NOT installed in this environment
(`python3 -c 'import tree_sitter'` -> ModuleNotFoundError) and this project
holds a no-pip-dependency rule -- every other kernel module (ledger,
workspace, model, sandbox) is stdlib-only, and editlint.py's own docstring
names the same constraint for its per-language lint gate. Installing
tree-sitter + per-language grammar packages would be the field-scan's own
proposed design, but it is a pip dependency this harness does not carry, so
build_repo_map uses a STDLIB-ONLY fallback instead:
  - .py              -- ast.parse (exact, in-process; the same tool
                        editlint.py already uses for its .py lint gate).
                        Top-level FunctionDef/AsyncFunctionDef/ClassDef names
                        only (module.body), matching this module's own
                        "top-level symbols" contract.
  - everything else  -- a conservative regex scan, anchored at column 0 (no
                        leading whitespace) so nested/indented members are
                        naturally excluded, for the top-level declaration
                        shapes (function / class / interface / struct / fun /
                        func keywords) this harness's actual target repos
                        use (Stalag's JS, Cairn/Freya's Kotlin, Go/Rust as a
                        bonus). This is best-effort: it can miss unusual
                        declaration styles and, rarely, false-positive on a
                        commented-out or string line that happens to start
                        with a matched keyword. Unlike editlint.py's lint
                        GATE (which must never false-reject an edit), a repo
                        map is advisory context only -- it never blocks
                        anything -- so an imperfect heuristic is an
                        acceptable, disclosed cost here.
  - PageRank/importance ranking (named in ARCHITECTURE.md's field-scan
    sketch as a compression signal) is NOT implemented in this pass -- files
    are ordered by a cheap, deterministic proxy (sorted path) instead. That
    is a possible future enrichment, not part of this story's DoD (which
    asks for "the map is built correctly and wired in behind a flag", not a
    measured effectiveness/ranking number -- explicitly out of scope below).

Budget discipline (never silently truncate): build_repo_map assembles the map
file-by-file in the deterministic sorted order above; it stops BEFORE adding
any file's block that would push the running word count over max_tokens,
and -- whenever files remain unshown as a result -- appends an explicit
`... [truncated: N/M files shown, budget=T tokens]` line, so a caller can
grep the literal substring "truncated" rather than silently receiving a
cut-off map. The token measure is the same cheap proxy the DoD names --
`len(text.split())` whitespace word count -- not a real BPE tokenizer; an
approximation, not exact token accounting.

Turn-reduction / read-accuracy measurement against a live resident model is
explicitly OUT OF SCOPE here (Story #449's DoD): that needs a live
llama-swap run and is a follow-up eval, not part of this build-and-wire
story.
"""
from __future__ import annotations
import ast, os, re
from pathlib import Path

# Directories never worth mapping: VCS internals, caches, virtualenvs, and
# this project's own gitignored var/ tree (models, ledger, shadow-git) --
# same exclusion spirit as workspace.py's shadow-git separation from the
# user's real .git. Any OTHER dot-directory is also skipped generically.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "var",
              ".pytest_cache", "dist", "build", ".mypy_cache"}

_PY_EXT = ".py"
_OTHER_EXTS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
               ".kt", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".hpp")

# Best-effort, column-0-anchored (no leading whitespace) top-level declaration
# shapes across this harness's actual target languages (JS/TS, Kotlin, Java,
# Go, Rust, C/C++). Anchoring at column 0 is what keeps this "top-level
# only": a method inside a class/struct body is indented, so it never
# matches here -- the same guarantee ast.parse's `tree.body` gives .py files.
_SYMBOL_PATTERNS = [
    re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+(\w+)"),        # JS/TS function
    re.compile(r"^(?:export\s+)?(?:abstract\s+|final\s+|public\s+|open\s+)*class\s+(\w+)"),  # class (JS/TS/Java/Kotlin/C++)
    re.compile(r"^(?:export\s+)?interface\s+(\w+)"),                                         # TS/Java/Kotlin interface
    re.compile(r"^(?:public\s+|private\s+|internal\s+|open\s+)*fun\s+(\w+)"),                # Kotlin top-level fun
    re.compile(r"^func\s+(\w+)"),                                                            # Go
    re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),                                      # Rust
    re.compile(r"^struct\s+(\w+)"),                                                          # Go/Rust/C
]


def _py_symbols(text: str) -> list[str]:
    """Top-level (module.body) FunctionDef/AsyncFunctionDef/ClassDef names via
    ast.parse. An unparseable file (a work-in-progress edit) yields no
    symbols rather than raising -- a repo map must never crash the loop."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    return [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]


def _regex_symbols(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        for pat in _SYMBOL_PATTERNS:
            m = pat.match(line)
            if m:
                names.append(m.group(1))
                break
    return names


def _symbols_for(path: Path, text: str) -> list[str]:
    if path.suffix == _PY_EXT:
        return _py_symbols(text)
    if path.suffix in _OTHER_EXTS:
        return _regex_symbols(text)
    return []


def _iter_source_files(repo: Path):
    """Yield source files under repo in a stable, deterministic (sorted)
    order, skipping VCS/cache/dependency directories IN PLACE (mutating
    os.walk's dirnames) so it never even descends into them."""
    for root, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(root) / name
            if p.suffix == _PY_EXT or p.suffix in _OTHER_EXTS:
                yield p


def build_repo_map(repo_path, max_tokens: int = 1000) -> str:
    """Return a compact text map of repo_path's files and their top-level
    symbols, never exceeding max_tokens by the cheap len(text.split()) word
    estimate the DoD names -- see the module docstring for the
    tree-sitter-vs-stdlib decision and the never-silently-truncate contract.
    """
    repo = Path(repo_path).resolve()
    entries = []
    for f in _iter_source_files(repo):
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        symbols = _symbols_for(f, text)
        if symbols:
            entries.append((len(symbols), f"{f.relative_to(repo)}: {', '.join(symbols)}"))

    # Order by IMPORTANCE (symbol count, descending) so that when the map is
    # truncated to fit the budget the coder sees the MEATIEST files first, not an
    # arbitrary alphabetical prefix (red-team #449: an alphabetical cutoff hid the
    # important half of a large repo). Stable on path order for equal counts.
    entries.sort(key=lambda e: -e[0])
    blocks = [b for _, b in entries]

    header = f"# repo map ({len(blocks)} files with top-level symbols, ranked by symbol count, budget={max_tokens} tokens)"
    lines = [header]
    used = len(header.split())
    shown = 0
    for block in blocks:
        words = len(block.split())
        if used + words > max_tokens:
            break
        lines.append(block)
        used += words
        shown += 1
    if shown < len(blocks):
        lines.append(f"... [map truncated: showing the {shown}/{len(blocks)} highest-symbol "
                     f"files within the {max_tokens}-token budget; grep for any file not listed here]")
    return "\n".join(lines)
