"""The evidence core. A Workspace wraps a target repo and is the ONLY thing that
says what changed on disk — always by computation, never by a model's claim.

Two mechanisms:
  - a shadow git repo (separate GIT_DIR, never touches the user's .git) gives
    whole-workspace snapshots + real tree diffs + revert (the checkpoint the
    edit pipeline reverts to after N failures).
  - per-edit content hashing + difflib gives the precise diff for one edit's
    envelope, and the read-before-edit / staleness invariant.

Law 1 lives here: edit() returns a harness-computed Envelope. An edit that
changes nothing produces an empty diff, which the loop reads as NON_PERSISTENCE
if a change was claimed. "No diff = no work."
"""
from __future__ import annotations
import subprocess, hashlib, difflib, os
from pathlib import Path
from .types import Envelope, ErrorClass
from . import config


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


class Workspace:
    def __init__(self, repo_path, session_id: str, shadow_root=None):
        self.repo = Path(repo_path).resolve()
        if not self.repo.is_dir():
            raise ValueError(f"workspace repo not a dir: {self.repo}")
        self.gitdir = Path(shadow_root or (config.VAR / "shadow")) / f"{session_id}.git"
        self._reads: dict[str, str] = {}   # abspath -> content-hash at read time
        self._git_init()

    # --- shadow git (whole-workspace evidence + checkpoints) ---
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ,
                   GIT_DIR=str(self.gitdir), GIT_WORK_TREE=str(self.repo),
                   GIT_AUTHOR_NAME="animal", GIT_AUTHOR_EMAIL="animal@localhost",
                   GIT_COMMITTER_NAME="animal", GIT_COMMITTER_EMAIL="animal@localhost")
        return subprocess.run(["git", *args], env=env, cwd=str(self.repo),
                              capture_output=True, text=True)

    def _git_init(self):
        self.gitdir.parent.mkdir(parents=True, exist_ok=True)
        if not self.gitdir.exists():
            self._git("init", "-q")

    def snapshot(self) -> str:
        """Snapshot the whole workspace into the shadow repo; return the tree hash.
        This is the checkpoint (for revert) and the basis for whole-run diffs."""
        self._git("add", "-A")
        r = self._git("write-tree")
        return r.stdout.strip()

    def diff_trees(self, tree_a: str, tree_b: str) -> str:
        return self._git("diff", "--no-color", tree_a, tree_b).stdout

    def restore(self, tree: str) -> bool:
        """Best-effort revert of tracked files to a snapshot (edit-retry recovery)."""
        self._git("read-tree", tree)
        return self._git("checkout-index", "-a", "-f").returncode == 0

    # --- reads (windowed) + read-before-edit tracking ---
    def read(self, path: str, offset: int = 0, limit: int = 200) -> Envelope:
        p = self._resolve(path)
        if p is None:
            return Envelope("read", False, ErrorClass.INVARIANT_VIOLATION.value,
                            note=f"path escapes workspace: {path}")
        if not p.is_file():
            return Envelope("read", False, ErrorClass.HARNESS_FAULT.value, note=f"no such file: {path}")
        text = p.read_text(errors="replace")
        self._reads[str(p)] = _sha(text)        # remember what we saw, for staleness
        lines = text.splitlines()
        window = lines[offset: offset + limit]
        truncated = offset + limit < len(lines)
        return Envelope("read", True, computed={
            "path": path, "lines_total": len(lines), "offset": offset,
            "content": "\n".join(window), "truncated": truncated})

    # --- the edit pipeline (invariant -> match -> apply -> computed diff) ---
    def edit(self, path: str, old_string: str, new_string: str) -> Envelope:
        p = self._resolve(path)
        if p is None:
            return Envelope("edit", False, ErrorClass.INVARIANT_VIOLATION.value,
                            note=f"path escapes workspace: {path}")
        if not p.is_file():
            return Envelope("edit", False, ErrorClass.HARNESS_FAULT.value, note=f"no such file: {path}")
        content = p.read_text(errors="replace")
        # invariant: must have read this file this session, and it mustn't have changed since
        seen = self._reads.get(str(p))
        if seen is None:
            return Envelope("edit", False, ErrorClass.INVARIANT_VIOLATION.value,
                            note="read-before-edit: file was not read this session")
        if seen != _sha(content):
            return Envelope("edit", False, ErrorClass.INVARIANT_VIOLATION.value,
                            note="stale: file changed on disk since it was read")
        # match: exact, else whitespace-normalized fallback (minimal fuzzy cascade)
        match = self._locate(content, old_string)
        if match is None:
            return Envelope("edit", False, ErrorClass.MODEL_CLAIM_FALSE.value,
                            note="old_string not found (exact or whitespace-normalized)")
        start, end = match
        # disproportionate-match guard: refuse a replacement that dwarfs the anchor
        if len(new_string) > max(len(old_string) * 8, len(old_string) + 400):
            return Envelope("edit", False, ErrorClass.INVARIANT_VIOLATION.value,
                            note="disproportionate edit refused (replacement >> anchor)")
        new_content = content[:start] + new_string + content[end:]
        before_hash = _sha(content)
        if new_content == content:
            # nothing actually changed -> non-persistence, regardless of what was claimed
            return Envelope("edit", False, ErrorClass.NON_PERSISTENCE.value,
                            note="edit produced no change (empty diff)")
        p.write_text(new_content)
        after = p.read_text(errors="replace")               # read back (fsync-then-read)
        self._reads[str(p)] = _sha(after)                   # keep read-state current
        diff = "".join(difflib.unified_diff(
            content.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}"))
        added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        return Envelope("edit", True, computed={
            "path": path, "before_hash": before_hash, "after_hash": _sha(after),
            "diff": diff, "added": added, "removed": removed})

    def _locate(self, content: str, needle: str):
        i = content.find(needle)
        if i >= 0:
            return (i, i + len(needle))
        # whitespace-normalized fallback: match ignoring run-length of whitespace
        import re
        pat = re.escape(needle)
        pat = re.sub(r"(\\ |\\\t|\\\n|\\\r)+", r"\\s+", pat)
        m = re.search(pat, content)
        return (m.start(), m.end()) if m else None

    def _resolve(self, path: str):
        p = (self.repo / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
        try:
            p.relative_to(self.repo)      # containment: no escaping the workspace
        except ValueError:
            return None
        return p
