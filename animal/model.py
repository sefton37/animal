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
from . import config, dialect

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

# Story #462: the turn grammar is per-LANE. The work-lane schema above closes
# action.kind to read/grep/edit/shell/finish, which makes the discovery
# vocabulary token-level IMPOSSIBLE under constrained decoding -- caught while
# wiring the discovery role (a mocked test can never see this; the grammar
# lives in the real llama-server call). Discovery gets its own closed grammar:
# conversation-only, no edit, no shell -- capability absent by construction at
# the DECODER, not just by prompt.
DISCOVERY_TURN_SCHEMA = {
    "type": "object", "required": ["thought", "action"],
    "properties": {
        "thought": {"type": "string"},
        "action": {
            "type": "object", "required": ["kind"],
            "properties": {
                "kind": {"type": "string", "enum": ["ask", "propose_story", "finish"]},
                "question": {"type": "string"},
                "title": {"type": "string"}, "narrative": {"type": "string"},
                "notes": {"type": "string"}, "message": {"type": "string"},
            },
        },
    },
}


def turn_schema_for(role_cfg: dict) -> dict:
    """The constrained-decoding schema this role's turns are held to --
    selected by the role's `turn_schema` config key ('discovery' or the
    default work-lane protocol)."""
    return DISCOVERY_TURN_SCHEMA if role_cfg.get("turn_schema") == "discovery" else TURN_SCHEMA


SYSTEM_PROMPT = """You are an agent working inside a code workspace. Each turn, respond with EXACTLY ONE JSON object:
{"thought": "<brief reasoning>", "action": { ... }}

action.kind is one of:
- read   {"kind":"read","path":"file.py","offset":0,"limit":200}   view a file window. You MUST read a file before editing it.
- grep   {"kind":"grep","pattern":"regex","path":"."}
- edit   {"kind":"edit","path":"file.py","old_string":"<EXACT text to replace>","new_string":"<replacement>"}   old_string must match the file exactly.
         To CREATE a new file: edit with old_string:"" and the full file content as new_string (the path must not exist yet).
- shell  {"kind":"shell","argv":["python3","-c","print(1)"]}   argv LIST only — no shell string, no pipes/redirects.
- finish {"kind":"finish","message":"<what you did>"}   when the task is complete.

Rules:
- Emit ONE action per turn. The harness executes it and returns the REAL result (a computed diff, a real exit code, real file content). Never assume success — read the result before continuing.
- To change code: read the file, then edit with an exact old_string. If the harness says the edit produced no change or the anchor was not found, fix your old_string and retry.
- Finish only when the task is actually done, as shown by the results the harness returned."""


# Story #486: the search_replace turn protocol. A local coder produces far fewer
# broken edits when it writes a fenced SEARCH/REPLACE block (raw newlines/quotes,
# no JSON escaping) than when it JSON-escapes a multi-line patch into old_string
# (measured #447: search_replace 12/12 vs json 11/12). Non-edit actions stay a
# one-line JSON object -- they carry no multi-line code to escape. The kernel parses
# both into the SAME {thought, action} the loop already consumes.
SYSTEM_PROMPT_SEARCH_REPLACE = """You are an agent working inside a code workspace. Each turn: a brief thought, then EXACTLY ONE action.

For read / grep / shell / finish, emit a single JSON object:
- read   {"kind":"read","path":"file.py","offset":0,"limit":200}   view a file window. You MUST read a file before editing it.
- grep   {"kind":"grep","pattern":"regex","path":"."}
- shell  {"kind":"shell","argv":["python3","-c","print(1)"]}   argv LIST only — no shell string, no pipes/redirects.
- finish {"kind":"finish","message":"<what you did>"}   when the task is complete.

To EDIT a file, do NOT use JSON — emit a fenced SEARCH/REPLACE block so you never escape a newline or quote:

```edit path/to/file.py
<<<<<<< SEARCH
<the exact existing text to replace, copied verbatim from a prior read>
=======
<the replacement text>
>>>>>>> REPLACE
```

Rules:
- Emit ONE action per turn — one JSON object OR one fenced edit block, never both. The harness executes it and returns the REAL result (a computed diff, a real exit code, real file content). Never assume success — read the result before continuing.
- The SEARCH text must match the file's real content exactly (read the file first). If the harness says the anchor was not found or the edit produced no change, fix your SEARCH text and retry.
- Finish only when the task is actually done, as shown by the results the harness returned."""


def system_prompt_for(role: str) -> str:
    """The system prompt for a role, chosen by its edit_format (Story #486). A
    "json" role gets the original JSON-turn prompt unchanged; a "search_replace"
    role gets the fenced-edit prompt. Any future format falls back to JSON."""
    return SYSTEM_PROMPT_SEARCH_REPLACE if config.ROLES.get(role, {}).get("edit_format") == "search_replace" else SYSTEM_PROMPT


class ModelError(RuntimeError):
    pass


class ModelPlane:
    def __init__(self, url: str | None = None):
        self.url = url or config.LLAMA_SWAP_URL

    def call(self, role: str, messages: list[dict], temperature: float | None = None) -> tuple[dict, dict]:
        """Return (turn_obj, meta). turn_obj is {"thought","action"}; meta carries
        context-integrity signals. temperature overrides the role default (used by
        candidate sampling for generation diversity). Raises ModelError on failure."""
        rc = config.ROLES[role]
        edit_format = rc.get("edit_format", "json")
        body = {
            "model": rc["model"], "messages": messages,
            "temperature": rc["temperature"] if temperature is None else temperature,
            "max_tokens": rc["max_tokens"],
        }
        if edit_format == "json":
            # constrained decoding for the JSON turn protocol (Phase-0: 100% parseable).
            # A dialect role (search_replace) emits free fenced text, so no constraint.
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "turn", "strict": True,
                                                       "schema": turn_schema_for(rc)}}
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
        parsed = self._parse(content) if edit_format == "json" else self._parse_dialect(content, edit_format)
        return parsed, meta

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

    def _parse_dialect(self, content: str, edit_format: str) -> dict:
        """Parse a dialect turn (Story #486) into the SAME {thought, action} the loop
        consumes. An EDIT is a fenced block parsed by animal.dialect (raw text, no
        JSON escaping); every other action stays a JSON object. Falls back to the JSON
        parse for non-edit turns, and tolerates a BARE {"kind":...} action (the dialect
        prompt asks for the action alone, not the {thought, action} wrapper)."""
        edits = dialect.parse(edit_format, content)
        if edits:
            e = edits[0]                                   # one action per turn: take the first block
            thought = content[:content.index("```edit")].strip()
            action = {"kind": "edit", "path": e["path"],
                      "old_string": e["old_string"], "new_string": e["new_string"]}
            return {"thought": thought, "action": action}
        # no fenced edit -> a read/grep/shell/finish JSON action (bare, or wrapped)
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise ModelError(f"dialect turn had neither a fenced edit block nor a JSON action: {content[:200]!r}")
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise ModelError(f"dialect non-edit action was not JSON: {e}: {content[:200]!r}") from e
        if isinstance(obj, dict) and "action" in obj:      # a full {thought, action} wrapper
            return obj
        if isinstance(obj, dict) and "kind" in obj:        # a bare action object
            return {"thought": content[:m.start()].strip(), "action": obj}
        raise ModelError(f"dialect turn's JSON was neither an action nor a wrapper: {obj!r}")
