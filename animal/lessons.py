"""Phase 4: lessons — learned from VERIFIED outcomes, and delivered two ways.

Resonance's necropsy drives every choice: it duplicated 'Scope Drift' 35 times
(no reinforcement path) and only ever injected static prose. Here:
  - UPSERT by key (re-observation reinforces, never duplicates).
  - confidence is a running Beta posterior (pos/neg), not a birth certificate;
    it reinforces on verified-good, decrements on contradiction, decays with age.
  - delivery is TWO modes: (a) injection of relevant lessons into a task's context;
    (b) COMPILATION — a lesson that earns enough support mints a project-scoped
    standing CHECK (a DoDCheck) the harness runs on relevant diffs. That is the
    move that turns 'warned in memory' into 'the harness won't let it regress'.
"""
from __future__ import annotations
import sqlite3, json, time
from pathlib import Path
from . import config
from .spec import DoDCheck
from .dod import run_check
from .sandbox import Sandbox

COMPILE_THRESHOLD = 2   # verified-good observations before a lesson compiles to a check


def _confidence(pos: int, neg: int) -> float:
    return round((pos + 1) / (pos + neg + 2), 3)      # Laplace-smoothed Beta mean


class Lessons:
    def __init__(self, db_path=None, now: float | None = None):
        self.db = sqlite3.connect(db_path or str(config.VAR / "learning.db"))
        self._now = now if now is not None else time.time()
        self.db.execute("""CREATE TABLE IF NOT EXISTS lessons(
            key TEXT PRIMARY KEY, text TEXT, pos INTEGER DEFAULT 0, neg INTEGER DEFAULT 0,
            paths TEXT DEFAULT '', check_json TEXT, compiled INTEGER DEFAULT 0,
            retired INTEGER DEFAULT 0, updated REAL)""")
        self.db.commit()

    def upsert(self, key: str, text: str, paths: list[str] | None = None,
               check: DoDCheck | None = None, verified_good: bool = True) -> dict:
        row = self.db.execute("SELECT pos, neg FROM lessons WHERE key=?", (key,)).fetchone()
        pos, neg = row if row else (0, 0)
        pos += 1 if verified_good else 0
        neg += 0 if verified_good else 1
        cj = json.dumps(check.to_dict()) if check is not None else None
        # only a lesson carrying a check AND enough verified support compiles into a standing check
        self.db.execute(
            "INSERT INTO lessons(key,text,pos,neg,paths,check_json,compiled,updated) VALUES(?,?,?,?,?,?,?,?)\n"
            "ON CONFLICT(key) DO UPDATE SET pos=excluded.pos, neg=excluded.neg, text=excluded.text,\n"
            "  paths=excluded.paths, updated=excluded.updated,\n"
            "  check_json=COALESCE(excluded.check_json, lessons.check_json),\n"
            "  compiled=MAX(lessons.compiled, excluded.compiled)",
            (key, text, pos, neg, ",".join(paths or []), cj, 1 if (cj and pos >= COMPILE_THRESHOLD) else 0, self._now))
        self.db.commit()
        return self.get(key)

    def contradict(self, key: str) -> None:
        self.upsert(key, self.get(key)["text"], verified_good=False)

    def get(self, key: str) -> dict:
        r = self.db.execute("SELECT key,text,pos,neg,paths,check_json,compiled,retired FROM lessons WHERE key=?",
                            (key,)).fetchone()
        if not r:
            return {}
        return {"key": r[0], "text": r[1], "pos": r[2], "neg": r[3], "confidence": _confidence(r[2], r[3]),
                "paths": r[4].split(",") if r[4] else [], "check_json": r[5],
                "compiled": bool(r[6]), "retired": bool(r[7])}

    def relevant(self, touched_paths: list[str]) -> list[dict]:
        """Lessons to inject for a task touching these paths (delivery mode a)."""
        out = []
        for r in self.db.execute("SELECT key FROM lessons WHERE retired=0"):
            L = self.get(r[0])
            if not L["paths"] or any(p in touched_paths for p in L["paths"]):
                out.append(L)
        return out

    def compiled_checks(self, touched_paths: list[str] | None = None) -> list[tuple[str, DoDCheck]]:
        out = []
        for r in self.db.execute("SELECT key, check_json, paths FROM lessons WHERE compiled=1 AND retired=0 AND check_json IS NOT NULL"):
            key, cj, paths = r
            lesson_paths = paths.split(",") if paths else []
            if touched_paths is not None and lesson_paths and not any(p in touched_paths for p in lesson_paths):
                continue
            out.append((key, DoDCheck(**json.loads(cj))))
        return out

    def run_compiled(self, repo, touched_paths: list[str] | None = None, sandbox: Sandbox | None = None) -> dict:
        """Run every relevant compiled check against the repo. Any failure is a
        REGRESSION the standing lesson blocks (Phase-4 exit)."""
        sb = sandbox or Sandbox()
        results, regressions = [], []
        for key, chk in self.compiled_checks(touched_paths):
            r = run_check(chk, sb, repo)
            results.append({"lesson": key, "check": chk.name, "passed": r["passed"]})
            if not r["passed"]:
                regressions.append(key)
        return {"blocked": bool(regressions), "regressions": regressions, "results": results}

    def decay(self, half_life_days: float = 30.0, retire_below: float = 0.4) -> int:
        """Age-decay pos/neg toward the prior; retire faded lessons. Nothing is a
        birth certificate — an unreinforced lesson loses confidence over time."""
        retired = 0
        for r in self.db.execute("SELECT key, pos, neg, updated FROM lessons WHERE retired=0").fetchall():
            key, pos, neg, updated = r
            age_days = max(0.0, (self._now - (updated or self._now)) / 86400.0)
            f = 0.5 ** (age_days / half_life_days)
            npos, nneg = pos * f, neg * f
            if _confidence(npos, nneg) < retire_below and (npos + nneg) < 1.0:
                self.db.execute("UPDATE lessons SET retired=1 WHERE key=?", (key,)); retired += 1
        self.db.commit()
        return retired

    def close(self):
        self.db.close()
