"""Grounding (Gate 0): resolve the files a spec references against the actual repo,
recording hash + existence and — crucially — MISSES. A spec that references a file
that doesn't exist is caught here, before any work or approval. Re-run at build
start and verify (files can vanish mid-chain).
"""
from __future__ import annotations
import hashlib, re
from pathlib import Path

_SRC = (".py", ".sh", ".js", ".mjs", ".ts", ".rb", ".go", ".rs", ".c", ".h",
        ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".txt")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def ground(spec, repo) -> dict:
    repo = Path(repo)
    refs: set[str] = set()
    for chk in spec.dod:                       # files named in DoD check argv
        for a in chk.argv[1:]:
            if not a.startswith("-") and (a.endswith(_SRC) or (repo / a).exists()):
                refs.add(a)
    for text in [spec.user_story, *spec.intent]:   # file-like tokens in the story
        for tok in re.findall(r"[\w./-]+\.[A-Za-z]{1,4}", text):
            if (repo / tok).exists():
                refs.add(tok)

    groundings, misses = [], []
    for r in sorted(refs):
        p = repo / r
        if p.is_file():
            data = p.read_bytes()
            snip = data.decode("utf-8", "replace").splitlines()[0][:80] if data else ""
            groundings.append({"ref": r, "exists": True, "sha": _sha(data), "snippet": snip})
        else:
            groundings.append({"ref": r, "exists": False})
            misses.append(r)
    spec.groundings = groundings
    return {"groundings": groundings, "misses": misses, "ok": not misses}
