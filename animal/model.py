"""The model plane: the kernel's client to llama-swap (the phase-major scheduler
from Phase 0). It calls a model by ROLE, guards context integrity (no silent
truncation — the local twin of the founding hallucination), and parses a single
typed action per turn.

Protocol (mini-swe-agent-shaped): each turn the model returns ONE JSON object
{"thought", "action"}. We constrain it with response_format json_schema — Phase 0
proved constrained decoding yields 100% parseable output — and the loop turns any
parse failure into a MODEL_FORMAT_ERROR envelope fed back to the model.
"""
from __future__ import annotations
import json, re, urllib.request, urllib.error
from . import config

# Flat action schema (optional fields per kind); action_from_dict enforces the
# per-kind required fields downstream, so a wrong shape is a typed error.
TURN_SCHEMA = {
    "type": "object", "required": ["thought", "action"],
    "properties": {
        "thought": {"type": "string"},
        "action": {
            "type": "object", "required": ["kind"],
            "properties": {
                "kind": {"type": "string", "enum": ["read", "grep", "edit", "shell", "finish"]},
                "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"},
                "pattern": {"type": "string"},
                "old_string": {"type": "string"}, "new_string": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string"},
            },
        },
    },
}

SYSTEM_PROMPT = """You are an agent working inside a code workspace. Each turn, respond with EXACTLY ONE JSON object:
{"thought": "<brief reasoning>", "action": { ... }}

action.kind is one of:
- read   {"kind":"read","path":"file.py","offset":0,"limit":200}   view a file window. You MUST read a file before editing it.
- grep   {"kind":"grep","pattern":"regex","path":"."}
- edit   {"kind":"edit","path":"file.py","old_string":"<EXACT text to replace>","new_string":"<replacement>"}   old_string must match the file exactly.
- shell  {"kind":"shell","argv":["python3","-c","print(1)"]}   argv LIST only — no shell string, no pipes/redirects.
- finish {"kind":"finish","message":"<what you did>"}   when the task is complete.

Rules:
- Emit ONE action per turn. The harness executes it and returns the REAL result (a computed diff, a real exit code, real file content). Never assume success — read the result before continuing.
- To change code: read the file, then edit with an exact old_string. If the harness says the edit produced no change or the anchor was not found, fix your old_string and retry.
- Finish only when the task is actually done, as shown by the results the harness returned."""


class ModelError(RuntimeError):
    pass


class ModelPlane:
    def __init__(self, url: str | None = None):
        self.url = url or config.LLAMA_SWAP_URL

    def call(self, role: str, messages: list[dict]) -> tuple[dict, dict]:
        """Return (turn_obj, meta). turn_obj is {"thought","action"}; meta carries
        context-integrity signals. Raises ModelError on transport/parse failure."""
        rc = config.ROLES[role]
        body = {
            "model": rc["model"], "messages": messages,
            "temperature": rc["temperature"], "max_tokens": rc["max_tokens"],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "turn", "strict": True, "schema": TURN_SCHEMA}},
        }
        req = urllib.request.Request(
            self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                resp = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError) as e:
            raise ModelError(f"llama-swap call failed ({role}): {e}") from e
        choice = resp["choices"][0]
        content = choice["message"].get("content", "") or ""
        usage = resp.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ctx = rc["num_ctx"]
        meta = {
            "role": role, "prompt_tokens": pt, "num_ctx": ctx,
            "finish_reason": choice.get("finish_reason"),
            # context integrity: the prompt must have fit the window. If it hit the
            # ceiling, the model saw a truncated prompt — a hard fault, not a fact.
            "context_overflow": bool(pt) and pt >= ctx,
            "completion_tokens": usage.get("completion_tokens", 0),
        }
        return self._parse(content), meta

    def _parse(self, content: str) -> dict:
        m = re.search(r"\{.*\}", content, re.S)   # tolerate fences/prose around the JSON
        raw = m.group(0) if m else content
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ModelError(f"model output was not JSON: {e}: {content[:200]!r}") from e
        if not isinstance(obj, dict) or "action" not in obj:
            raise ModelError(f"model turn missing 'action': {obj!r}")
        return obj
