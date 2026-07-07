"""Phase 4: calibration — the thing Resonance never had. Per (model x role x
claim-type): how often does this model's CLAIM turn out VERIFIED-true? Fed only by
harness-verified outcomes (computed envelopes, seeded ground-truth), never prose.

It is two things at once: the ROUTING function (pick the model with the best
verified track record for a role) and the panel VOTE-WEIGHT. The error taxonomy
keeps non-model faults (harness/env) out of the arithmetic, so a model isn't
charged for infrastructure noise. Confidence uses the Wilson lower bound, so a
model with 1/1 doesn't outrank one with 90/100.
"""
from __future__ import annotations
import sqlite3, math
from pathlib import Path
from . import config
from .types import ErrorClass

# faults that are NOT the model's fault -> excluded from calibration (the taxonomy)
_EXCLUDE = {ErrorClass.HARNESS_FAULT.value, ErrorClass.ENV_MISMATCH.value}
_NEUTRAL = 0.5   # prior for an untested (model, role, claim_type)


def _wilson_lower(n: int, k: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


class Calibration:
    def __init__(self, db_path=None):
        self.db = sqlite3.connect(db_path or str(config.VAR / "learning.db"))
        self.db.execute("""CREATE TABLE IF NOT EXISTS calibration(
            model TEXT, role TEXT, claim_type TEXT, n INTEGER DEFAULT 0, n_true INTEGER DEFAULT 0,
            PRIMARY KEY(model, role, claim_type))""")
        self.db.commit()

    def record(self, model: str, role: str, claim_type: str, verified_true: bool,
               error_class: str = "none") -> None:
        if error_class in _EXCLUDE:      # infrastructure fault, not the model — don't charge it
            return
        row = self.db.execute("SELECT n, n_true FROM calibration WHERE model=? AND role=? AND claim_type=?",
                              (model, role, claim_type)).fetchone()
        n, k = row if row else (0, 0)
        self.db.execute("INSERT OR REPLACE INTO calibration VALUES(?,?,?,?,?)",
                        (model, role, claim_type, n + 1, k + (1 if verified_true else 0)))
        self.db.commit()

    def rate(self, model: str, role: str, claim_type: str) -> dict:
        row = self.db.execute("SELECT n, n_true FROM calibration WHERE model=? AND role=? AND claim_type=?",
                              (model, role, claim_type)).fetchone()
        if not row or row[0] == 0:
            return {"n": 0, "p": None, "lo": 0.0}
        n, k = row
        return {"n": n, "p": round(k / n, 3), "lo": round(_wilson_lower(n, k), 3)}

    def route(self, role: str, claim_type: str, candidates: list[str]) -> dict:
        """Pick the candidate with the best Wilson-lower-bound verified rate. Reading
        this table IS the routing decision (Phase-4 exit: 'routing reads calibration')."""
        scored = {m: self.rate(m, role, claim_type) for m in candidates}
        chosen = max(candidates, key=lambda m: (scored[m]["lo"], scored[m]["n"]))
        return {"chosen": chosen, "rate": scored[chosen], "all": scored}

    def weight(self, model: str, role: str, claim_type: str) -> float:
        """Panel vote-weight = the model's Wilson-lower verified rate (neutral prior
        until it has a track record)."""
        r = self.rate(model, role, claim_type)
        return r["lo"] if r["p"] is not None else _NEUTRAL

    # --- projections from verified sources (calibration is a projection of the ledger) ---

    def ingest_ledger(self, ledger) -> int:
        """Walk a run ledger; for each ACTION its following ENVELOPE is the verified
        outcome. Records (role's model, role, action_kind, envelope.ok)."""
        evs = ledger.replay()
        role = next((e.payload.get("role") for e in evs if e.type == "session_start"), None) or "coder"
        model = config.ROLES.get(role, {}).get("model", role)
        n = 0
        pending = None
        for e in evs:
            if e.type == "action":
                pending = e.payload.get("kind")
            elif e.type == "envelope" and pending is not None:
                self.record(model, role, pending, bool(e.payload.get("ok")),
                            e.payload.get("error_class", "none"))
                n += 1; pending = None
        return n

    def ingest_panel_verdicts(self, seat_model: str, verdicts: dict, ground_truth: dict) -> int:
        """Record a judge seat's detection track record vs seeded ground-truth
        (claim_type='premise_verdict'). This is the panel vote-weight's source."""
        n = 0
        for cid, gt in ground_truth.items():
            v = verdicts.get(cid)
            if v in ("sound", "unsound"):     # abstains don't count as a claim
                self.record(seat_model, "judge", "premise_verdict", v == gt)
                n += 1
        return n

    def close(self):
        self.db.close()
