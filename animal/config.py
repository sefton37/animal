"""Kernel configuration: paths, the model roster (from phase0/PHASE0-EXIT.md),
and the control-plane paths the sandbox must protect."""
from __future__ import annotations
import os
from pathlib import Path

ANIMAL_HOME = Path(os.environ.get("ANIMAL_HOME", Path.home() / "dev" / "animal"))
VAR = ANIMAL_HOME / "var"
LEDGER_DIR = Path(os.environ.get("ANIMAL_LEDGER", VAR / "ledger"))
MODELS_DIR = VAR / "models"

# The kernel talks to models through llama-swap (the phase-major scheduler
# validated in Phase 0). Start it with: llama-swap --config phase0/llama-swap.roster.yaml
LLAMA_SWAP_URL = os.environ.get("ANIMAL_LLAMA_SWAP", "http://127.0.0.1:8890")

# role -> (llama-swap model name, call params). Measured seat configs live in the
# roster yaml; these are the request-side params. max_tokens is generous for
# reasoning seats (gpt-oss's trace precedes its content — Phase-0 lesson).
ROLES = {
    "coder":     {"model": "coder",      "max_tokens": 2048, "temperature": 0.2, "num_ctx": 32768},
    "architect": {"model": "architect",  "max_tokens": 2048, "temperature": 0.3, "num_ctx": 32768},
    "judge":     {"model": "judge",      "max_tokens": 1024, "temperature": 0.0, "num_ctx": 8192},
    "auditor":   {"model": "auditor",    "max_tokens": 512,  "temperature": 0.0, "num_ctx": 8192},
}

# Loop bounds (mini-swe-agent-shaped: hard caps, not open-ended).
MAX_TURNS = int(os.environ.get("ANIMAL_MAX_TURNS", "20"))
MAX_EDIT_RETRIES = 3          # then revert-to-checkpoint + resample (90.5->57.2 lesson)

# Paths that must be READ-ONLY inside any agent sandbox: the kernel cannot be
# edited by the thing it runs (the implementer-edited-the-hook loophole, closed).
def control_plane() -> list[Path]:
    return [ANIMAL_HOME / "animal", LEDGER_DIR, ANIMAL_HOME / "phase0"]

# The trivial-lane budget (the only lane the kernel ships with). Above this,
# the session must escalate (full lane/state-machine is Phase 2).
TRIVIAL_BUDGET = {"files": 3, "loc": 30, "edits": 10}
