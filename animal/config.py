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
#
# edit_format (Story #447): a per-role property naming which dialect that
# role's edits are emitted in -- "json" keeps today's TURN_SCHEMA/
# response_format path in model.py completely unchanged (the default, and the
# only value any role uses today); any other value names a key in
# animal.dialect.EDIT_FORMATS (e.g. "search_replace", "whole_file") whose
# fenced-text parser feeds animal.types.action_from_dict the same way. See
# animal/dialect.py + the dated edit-format eval markdown alongside it for the
# measured parse-success numbers this default is based on.
ROLES = {
    "coder":     {"model": "coder",      "max_tokens": 2048, "temperature": 0.2, "num_ctx": 32768, "edit_format": "json"},
    "architect": {"model": "architect",  "max_tokens": 2048, "temperature": 0.3, "num_ctx": 32768, "edit_format": "json"},
    "judge":     {"model": "judge",      "max_tokens": 1024, "temperature": 0.0, "num_ctx": 8192,  "edit_format": "json"},
    "auditor":   {"model": "auditor",    "max_tokens": 512,  "temperature": 0.0, "num_ctx": 8192,  "edit_format": "json"},
    # Story #457: the product-owner role authors a Spec from a plain-language user
    # story. Rides the already-provisioned "architect" GPU seat (a thinking model
    # with a generous 32768 context is the right fit for decomposing a story into
    # intent/out_of_scope/DoD) -- no new GPU seat, no new roster entry. max_tokens
    # is 8192 (well above the other roles' 2048) because architect is a "thinking"
    # model: a live round-trip showed its chain-of-thought alone can run into the
    # thousands of tokens before it ever emits the schema-constrained JSON content
    # -- 2048 measured empty (finish_reason=length, content="") on a real call.
    "product_owner": {"model": "architect", "max_tokens": 8192, "temperature": 0.2, "num_ctx": 32768, "edit_format": "json"},
    # Story #458: the tester role authors a failing test (TDD red) before the
    # implementer runs. It emits edits the same shape/complexity as the coder's
    # (a new or modified tests/test_*.py file), so it rides the already-
    # provisioned "coder" GPU seat -- no new GPU seat, no new roster entry.
    "tester": {"model": "coder", "max_tokens": 2048, "temperature": 0.2, "num_ctx": 32768, "edit_format": "json"},
}

# Loop bounds (mini-swe-agent-shaped: hard caps, not open-ended).
MAX_TURNS = int(os.environ.get("ANIMAL_MAX_TURNS", "20"))
MAX_EDIT_RETRIES = 3          # then revert-to-checkpoint + resample (90.5->57.2 lesson)

# Loop hygiene (Story #450): the GENERAL doom-loop and context-growth guards that
# complement #448's edit-specific rollback ceiling.
REPEAT_ACTION_CEILING = 3    # N identical non-edit actions in a row -> interrupt (ARCHITECTURE.md)
MAX_CYCLE_PERIOD = 3         # also catch a period-2 or period-3 repeating CYCLE sustained for
                             # REPEAT_ACTION_CEILING full cycles -- a model that varies one
                             # incidental field each turn (e.g. an oscillating read offset) or
                             # ping-pongs between two distinct dead-end actions never has
                             # REPEAT_ACTION_CEILING CONSECUTIVE identical actions, so a
                             # period-1-only check misses both (red-team finding on this
                             # story's first attempt)
OBSERVATION_KEEP = 5         # verbatim turns kept per role (tool-result 'user' AND the model's
                             # own per-turn 'thought' echoed as 'assistant'); older ones of
                             # EACH role collapsed to a template -- a chatty small model's
                             # thought text left unbounded can dwarf the tool-result slice by
                             # orders of magnitude over a long run (red-team finding)

# Paths that must be READ-ONLY inside any agent sandbox: the kernel cannot be
# edited by the thing it runs (the implementer-edited-the-hook loophole, closed).
def control_plane() -> list[Path]:
    return [ANIMAL_HOME / "animal", LEDGER_DIR, ANIMAL_HOME / "phase0"]

# The trivial-lane budget (the only lane the kernel ships with). Above this,
# the session must escalate (full lane/state-machine is Phase 2).
TRIVIAL_BUDGET = {"files": 3, "loc": 30, "edits": 10}
