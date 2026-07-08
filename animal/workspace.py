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
import subprocess, hashlib, difflib, os, re
from pathlib import Path
from .types import Envelope, ErrorClass
from . import config
from . import editlint


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


class AmbiguousMatch(Exception):
    """Raised by a fuzzy-cascade tier (Story #446) when >=2 candidate spans in
    the same file score within _AMBIGUITY_MARGIN of the best score -- it is
    genuinely unclear which one old_string meant. The harness refuses to guess:
    edit() turns this into a MODEL_CLAIM_FALSE envelope (the anchor wasn't the
    unique locator its use implicitly claimed to be), never a silent pick of
    the first/best candidate."""


# The fuzzy-apply cascade: an explicit, ordered, named list of match strategies.
# Workspace._locate tries each in turn and stops at the first that finds
# something -- so a small, cosmetically-imperfect old_string (indentation
# reshaped, whitespace run-length changed, or just plain "close enough") still
# lands, instead of bouncing forever as "old_string not found". Every successful
# match reports WHICH tier fired (env.computed['match_strategy']) so a fuzzy hit
# is never silently indistinguishable from an exact one.
_STRATEGIES = ("exact", "whitespace_normalized", "indentation_agnostic", "line_window")

_LINE_WINDOW_FLOOR = 0.85    # similarity floor for the line-window (last-resort) tier
_AMBIGUITY_MARGIN = 0.02     # candidates within this score of the best are indistinguishable
# A FIXED absolute margin is not enough: two DIFFERENT (non-duplicate) candidate
# windows can be structurally similar enough that old_string scores higher against
# the block the model did NOT mean than against the one it did, by a gap bigger
# than any small fixed constant -- yet the winning score still isn't close to a
# perfect match, which is itself the tell that the fuzzy hit is not trustworthy
# on its own. So the effective margin SCALES with how far the winner is from a
# perfect match (1.0): a fuzzy hit that isn't near-perfect must beat its nearest
# rival by MORE than its own remaining imperfection (times this safety factor)
# to be trusted outright; a near-perfect hit (best ~= 1.0) falls back to the
# small fixed floor below. See _match_line_window.
_AMBIGUITY_RELATIVE_FACTOR = 1.25


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

    def restore_path(self, tree: str, path: str) -> bool:
        """Revert exactly ONE path to its content at a shadow-git snapshot,
        leaving every other file in the workspace untouched.

        Story #448 red-team fix: the rollback-and-resample gate must not use
        the whole-tree restore() above, because a successful edit to a
        DIFFERENT path that landed after the checkpoint was taken (but before
        the failing streak on THIS path hit its retry cap) would be silently
        destroyed -- with zero ledger trace, since the GATE event only records
        the failing path. Scoping the revert to exactly `path` means an
        unrelated file's already-landed work can never be wiped by a gate it
        has nothing to do with."""
        p = self._resolve(path)
        if p is None:
            return False
        content = self.blob_at(tree, path)
        if content is None:
            if p.exists():
                p.unlink()               # didn't exist at the checkpoint -- remove it
        else:
            p.write_text(content)
        self._reads.pop(str(p), None)    # any prior read-state for this path is now stale
        return True

    def changed_paths(self, tree_a: str, tree_b: str) -> list[str]:
        """Names of paths that differ (added/modified/deleted) between two
        shadow-git snapshots."""
        r = self._git("diff", "--name-only", tree_a, tree_b)
        return [l for l in r.stdout.splitlines() if l]

    def blob_at(self, tree: str, path: str) -> str | None:
        """path's content at a shadow-git snapshot, or None if it didn't exist
        there (i.e. path was newly created since that snapshot)."""
        r = self._git("show", f"{tree}:{path}")
        return r.stdout if r.returncode == 0 else None

    # --- post-hoc lint gate: for writes that don't go through edit() ---
    def lint_gate_paths(self, pre_tree: str, paths: list[str]) -> str | None:
        """Applies the same lint gate edit() enforces, but to files a non-edit
        action (e.g. a ShellAction's argv) may have written directly to disk --
        the lint gate belongs to the whole edit pipeline, not to one action
        kind. Any changed path whose CURRENT on-disk content fails the lint is
        blocked from landing: reverted to its pre_tree content, or deleted if
        it did not exist at pre_tree (a newly-created broken file). Returns the
        first rejection message, or None if every changed path is clean."""
        rejection = None
        for path in paths:
            p = self._resolve(path)
            if p is None or not p.is_file():
                continue
            content = p.read_text(errors="replace")
            msg = editlint.lint(path, content)
            if msg is None:
                continue
            if rejection is None:
                rejection = f"{path}: {msg}"
            prior = self.blob_at(pre_tree, path)
            if prior is None:
                p.unlink()                  # didn't exist before the write -- remove it
            else:
                p.write_text(prior)         # existed before -- put its content back
            self._reads.pop(str(p), None)   # any prior read-state is now stale
        return rejection

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
        # match: the ordered fuzzy-apply cascade (_STRATEGIES) -- exact first,
        # then progressively fuzzier tiers, stopping at the first hit. A tier
        # that finds >=2 equally-good candidates refuses rather than guesses.
        try:
            match = self._locate(content, old_string)
        except AmbiguousMatch as e:
            return Envelope("edit", False, ErrorClass.MODEL_CLAIM_FALSE.value,
                            note=f"old_string is ambiguous, refusing to guess: {e}")
        if match is None:
            return Envelope("edit", False, ErrorClass.MODEL_CLAIM_FALSE.value,
                            note=f"old_string not found (tried: {', '.join(_STRATEGIES)})")
        start, end, strategy = match
        # disproportionate-match guard: refuse a replacement that dwarfs the anchor.
        # Applied AFTER the cascade returns a span, so it fires at every tier --
        # exact or fuzzy -- not just on an exact match.
        if len(new_string) > max(len(old_string) * 8, len(old_string) + 400):
            return Envelope("edit", False, ErrorClass.INVARIANT_VIOLATION.value,
                            note="disproportionate edit refused (replacement >> anchor)")
        new_content = content[:start] + new_string + content[end:]
        before_hash = _sha(content)
        if new_content == content:
            # nothing actually changed -> non-persistence, regardless of what was claimed
            return Envelope("edit", False, ErrorClass.NON_PERSISTENCE.value,
                            note="edit produced no change (empty diff)")
        # lint gate: run on the COMPUTED new_content BEFORE any write reaches disk.
        # Advisory-only for extensions the linter doesn't recognize (never rejects).
        lint_msg = editlint.lint(path, new_content)
        if lint_msg is not None:
            return Envelope("edit", False, ErrorClass.LINT_REJECTED.value,
                            note=f"lint rejected before write: {lint_msg}")
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
            "diff": diff, "added": added, "removed": removed, "match_strategy": strategy})

    # --- the fuzzy-apply cascade (Story #446) ---
    def _locate(self, content: str, needle: str):
        """Try each strategy in _STRATEGIES, in order, stopping at the first
        that finds a match. Returns (start, end, strategy_name), or None if no
        strategy locates old_string. Raises AmbiguousMatch if a tier finds the
        anchor but can't tell which of >=2 equally-good candidates was meant."""
        for name in _STRATEGIES:
            result = getattr(self, f"_match_{name}")(content, needle)
            if result is not None:
                start, end = result
                return (start, end, name)
        return None

    @staticmethod
    def _line_starts(content: str, lines: list[str]) -> list[int]:
        """Byte offsets into `content` at which each physical line (and one
        past the last) begins -- lets a line-window tier slice back into the
        original string once it has picked a window of lines."""
        starts, pos = [], 0
        for l in lines:
            starts.append(pos)
            pos += len(l)
        starts.append(pos)
        return starts

    def _match_exact(self, content: str, needle: str):
        """Tier 1: byte-for-byte substring match. Refuses (AmbiguousMatch) when
        old_string occurs >1 time -- the user story wants a refusal, not a silent
        guess, when the anchor matches two candidate spots (e.g. two byte-identical
        code blocks). A single unique occurrence lands as before. (#446 red-team:
        the ambiguity guard belongs on every tier, exact included, not only fuzzy.)"""
        i = content.find(needle)
        if i < 0:
            return None
        if content.find(needle, i + 1) >= 0:
            raise AmbiguousMatch(
                f"'exact' tier: old_string occurs {content.count(needle)} times "
                f"-- refusing to guess which was meant; add surrounding context to disambiguate")
        return (i, i + len(needle))

    def _match_whitespace_normalized(self, content: str, needle: str):
        """Tier 2: match ignoring RUN-LENGTH of whitespace -- any run of
        whitespace in old_string matches any run of whitespace on disk (tabs
        vs spaces, 2- vs 4-space reindents, trailing-space drift). This is the
        original single fallback the cascade replaces; kept first among the
        fuzzy tiers as the tightest. >=2 equally-good (verbatim, post-
        normalization) matches are refused as ambiguous."""
        pat = re.escape(needle)
        pat = re.sub(r"(\\ |\\\t|\\\n|\\\r)+", r"\\s+", pat)
        matches = list(re.finditer(pat, content))
        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousMatch(
                f"'whitespace_normalized' tier: {len(matches)} equally-good candidate matches")
        return (matches[0].start(), matches[0].end())

    def _match_indentation_agnostic(self, content: str, needle: str):
        """Tier 3: per-physical-line match after normalizing each line's
        whitespace (leading and trailing stripped, internal runs collapsed to
        a single space) and requiring WHOLE-LINE correspondence across the
        window. Catches indentation reshapes (spaces vs tabs, 2- vs 4-space)
        via a structurally different mechanism than tier 2's unanchored
        substring regex: a line-oriented exact comparison rather than a
        single regex search over the whole file. For plain leading-indent
        drift tier 2 usually already resolves it (its \\s+ substitution is
        unanchored and reaches the same result first); this tier is defense
        in depth for that same failure class and the natural step down before
        the last-resort genuinely-fuzzy line_window tier."""
        def _norm_line(l: str) -> str:
            return re.sub(r"\s+", " ", l.strip())

        needle_lines = needle.splitlines()
        if not needle_lines:
            return None
        n = len(needle_lines)
        target = [_norm_line(l) for l in needle_lines]
        content_lines = content.splitlines(keepends=True)
        if len(content_lines) < n:
            return None
        starts = self._line_starts(content, content_lines)
        candidates = []
        for i in range(0, len(content_lines) - n + 1):
            window = content_lines[i:i + n]
            if [_norm_line(l) for l in window] == target:
                candidates.append((starts[i], starts[i + n]))
        if not candidates:
            return None
        if len(candidates) > 1:
            raise AmbiguousMatch(
                f"'indentation_agnostic' tier: {len(candidates)} equally-good candidate windows")
        return candidates[0]

    def _match_line_window(self, content: str, needle: str):
        """Tier 4 (last resort): slide a window the same line-length as
        old_string across the file and score each against it with
        difflib.SequenceMatcher, keeping windows at/above _LINE_WINDOW_FLOOR.
        This is the genuinely-fuzzy tier -- everything before it is a
        structural (whitespace/indentation) match. When the best-scoring
        window has a clear margin over the rest, it wins outright (that's the
        cascade doing its job, not guessing); when >=2 windows are too close
        to call apart, it is genuinely unclear which the model meant and the
        tier refuses.

        "Too close to call" is NOT a fixed absolute gap (see the comment on
        _AMBIGUITY_RELATIVE_FACTOR above): two structurally-different,
        non-duplicate blocks can legitimately separate by more than a small
        fixed constant while the winner is still nowhere near a perfect
        match -- exactly the shape where an old_string that already contains
        the model's intended fix for block A scores incidentally higher
        against unrelated, already-correct block B than against the real,
        still-imperfect target A. The effective margin scales with the
        winner's own distance from 1.0 so that a merely-decent win over a
        decent runner-up is still refused, while a near-exact hit confidently
        beats an unrelated partial match."""
        needle_lines = needle.splitlines(keepends=True)
        n = len(needle_lines)
        if n == 0:
            return None
        content_lines = content.splitlines(keepends=True)
        if len(content_lines) < n:
            return None
        starts = self._line_starts(content, content_lines)
        scored = []
        for i in range(0, len(content_lines) - n + 1):
            window_text = "".join(content_lines[i:i + n])
            ratio = difflib.SequenceMatcher(None, window_text, needle).ratio()
            if ratio >= _LINE_WINDOW_FLOOR:
                scored.append((ratio, starts[i], starts[i + n]))
        if not scored:
            return None
        scored.sort(key=lambda t: -t[0])
        best = scored[0][0]
        margin = max(_AMBIGUITY_MARGIN, (1.0 - best) * _AMBIGUITY_RELATIVE_FACTOR)
        close = [s for s in scored if best - s[0] <= margin]
        if len(close) > 1:
            raise AmbiguousMatch(
                f"'line_window' tier: {len(close)} candidate windows score within "
                f"{margin:.4f} of the best ({best:.3f}) -- too close to tell which "
                f"one old_string meant")
        return (scored[0][1], scored[0][2])

    def _resolve(self, path: str):
        p = (self.repo / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
        try:
            p.relative_to(self.repo)      # containment: no escaping the workspace
        except ValueError:
            return None
        return p
