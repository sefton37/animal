"""Story #457: the product-owner role — a model AUTHORS a Spec (JSON) from a raw,
plain-language user story, instead of a maker hand-writing DoDCheck objects for
every piece of work.

The model gets NO shortcut around Gate 0: `author_spec` feeds its own output back
through the EXACT SAME machinery a hand-authored spec goes through --
`Spec.from_dict` (structural validation: argv-only checks, known comparators,
non-empty user_story) and `dod.validate_check` (authoring-time lints + the
negative-control that rejects a check that already passes on the pre-work tree,
i.e. a vacuous check) -- run against the REAL target repo via the sandbox. A
model-authored spec that is vacuous or malformed is rejected exactly as a
hand-authored one would be; this module does not weaken or bypass
`dod.validate_spec` / `worklane.run_work`'s Gate 0 in any way.

If validation fails, the SPECIFIC failure reasons are fed back to the model as a
corrective message and it gets another attempt, up to `max_retries`. If it still
can't produce a valid spec, `author_spec` raises `ProductOwnerError` -- it never
silently returns a vacuous/invalid spec (the harness's evidence-over-prose stance
applies to the product-owner's own output too).
"""
from __future__ import annotations
import json, re, urllib.request, urllib.error
from . import config
from .spec import Spec, SpecError, Comparator
from .dod import validate_check
from .sandbox import Sandbox

_SPEC_SCHEMA = {
    "type": "object",
    "required": ["user_story", "intent", "out_of_scope", "dod"],
    "properties": {
        "user_story": {"type": "string"},
        "intent": {"type": "array", "items": {"type": "string"}},
        "out_of_scope": {"type": "array", "items": {"type": "string"}},
        "dod": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "argv", "comparator"],
                "properties": {
                    "name": {"type": "string"},
                    "argv": {"type": "array", "items": {"type": "string"}},
                    "comparator": {"type": "string", "enum": [c.value for c in Comparator]},
                    "expected": {"type": "string"},
                },
            },
        },
    },
}

#  Story #457 fix iteration: a live, non-monkeypatched round-trip against a real
#  "thinking" model (Qwen3-30B-A3B-Thinking, the "architect" seat) showed this
#  prompt originally induced MINUTES of chain-of-thought per call -- not a hang,
#  confirmed by streaming the raw completion (tokens kept flowing, coherently,
#  the whole time) and by host `uptime` (load average 21-73, fluctuating, on a
#  48-core box, from Bastion's own CPU-pinned local-Ollama security monitor +
#  other resident processes contending for the SAME CPU cores this seat's
#  `--n-cpu-moe`-offloaded MoE experts need). A thinking model given a long,
#  discursive system prompt reasons at length before it ever emits the
#  schema-constrained JSON, and the ORIGINAL 2048-token max_tokens measured
#  EMPTY content (finish_reason=length, all budget spent on reasoning) on a
#  real call. This terser version + config.ROLES["product_owner"]["max_tokens"]
#  raised to 8192 together bring a real call to a genuine, non-vacuous Spec --
#  measured 410s end-to-end on this contended host (see the module's live
#  smoke test / DoD verification). That is still MINUTES, not seconds: this is
#  a slow, occasional operation, and `_chat`'s `timeout` default (600s) and this
#  test's override (900s) are sized for that reality, not for interactive use.
_SYS = ("Product owner. Turn the user story into JSON {user_story, intent, out_of_scope, dod}. "
        "intent: 1-3 short bullets decomposing the story. out_of_scope: 0-3 short bullets of what "
        "this spec does NOT cover. dod: 1-2 argv-only shell checks (argv is a list of strings, "
        "never a shell string) that PROVE the story is done -- falsifiable by construction: each "
        "MUST fail against the repo as it exists today and only pass once the story is actually "
        "implemented. A check's argv[0] MUST be a real, invokable program (e.g. 'python3', 'grep') "
        "-- NEVER the name of a function or feature as if it were a shell command. Example of a GOOD "
        "check: argv ['python3','-c','import calc; assert calc.add(2,3)==5'], comparator exit_zero. "
        "Never emit a check that already passes today (e.g. 'print(1)', 'true') -- it would be "
        "rejected. Keep any reasoning brief. Output ONLY the JSON object "
        "{user_story, intent, out_of_scope, dod}, no other prose.")


class ProductOwnerError(RuntimeError):
    """Raised when author_spec cannot produce a valid, non-vacuous Spec within
    max_retries corrective attempts. Never bridged with a silent fallback."""


def _chat(role: str, messages: list[dict], url: str | None = None, timeout: int = 600) -> str:
    """The model call, isolated in its own function so tests can substitute it
    offline (same monkeypatch pattern as animal.panel.run_seat). `timeout` default
    (600s) matches animal.model.ModelPlane's real-call timeout -- a spec-authoring
    turn on a thinking-model seat is a slow, occasional operation (not a fast
    interactive loop call), and a contended host (Bastion's local-Ollama monitor,
    other resident load) can legitimately push one turn to several minutes; see
    the comment above _SYS for the measured cause and the module's live smoke test."""
    rc = config.ROLES[role]
    body = {"model": rc["model"], "messages": messages,
            "temperature": rc.get("temperature", 0.2), "max_tokens": rc.get("max_tokens", 2048),
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "spec", "strict": True, "schema": _SPEC_SCHEMA}}}
    req = urllib.request.Request((url or config.LLAMA_SWAP_URL) + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"].get("content", "") or ""


def _parse(content: str) -> dict:
    m = re.search(r"\{.*\}", content, re.S)   # tolerate fences/prose around the JSON
    raw = m.group(0) if m else content
    obj = json.loads(raw)                     # json.JSONDecodeError on bad JSON
    if not isinstance(obj, dict):
        raise ValueError(f"product-owner output was not a JSON object: {obj!r}")
    return obj


def author_spec(user_story: str, repo: str, role: str = "product_owner",
                max_retries: int = 2, url: str | None = None, timeout: int = 600) -> Spec:
    """Model-authors a Spec for `user_story`, then runs it through the SAME
    validation a hand-authored spec faces: Spec.from_dict (structural) + a
    from_dict(to_dict()) round-trip + dod.validate_check per DoD check (lints +
    negative-control) against `repo`. Returns the first attempt that comes back
    clean; on any failure, feeds the SPECIFIC reasons back to the model and
    retries up to max_retries times. Raises ProductOwnerError, never returns a
    vacuous/invalid spec, if every attempt fails. `timeout` (seconds, per model
    call) defaults to 600 -- see _chat's docstring for why a real call can
    legitimately take minutes on a contended host."""
    sb = Sandbox()
    messages = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": f"USER STORY:\n{user_story}\n\n"
                                     "Return JSON {user_story, intent, out_of_scope, dod}."},
    ]
    last_reason = "no attempt made"
    for _attempt in range(max_retries + 1):
        try:
            raw = _chat(role, messages, url, timeout)
            d = _parse(raw)
            d.setdefault("user_story", user_story)
            spec = Spec.from_dict(d)                       # structural validation (Gate 0, unchanged)
            Spec.from_dict(spec.to_dict())                  # round-trip proof
        except (SpecError, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            last_reason = f"spec malformed: {e}"
            messages.append({"role": "user", "content":
                f"[rejected] {last_reason}. Re-emit a corrected, complete JSON spec."})
            continue
        bad = [validate_check(c, sb, repo) for c in spec.dod]
        bad = [b for b in bad if not b["ok"]]
        if not bad and spec.dod:
            return spec                                    # clean: grounding/approval still to come, unchanged
        last_reason = ("no DoD checks emitted" if not spec.dod else
                       "; ".join(f"{b['name']}: {b['reasons']}" for b in bad))
        messages.append({"role": "user", "content":
            f"[rejected] the DoD failed authoring validation: {last_reason}. Fix these SPECIFIC checks "
            "(each must be falsifiable: fail on the pre-work repo, pass once implemented) and re-emit "
            "the full JSON spec."})
    raise ProductOwnerError(
        f"author_spec: could not produce a valid spec for {user_story!r} in {max_retries} retries; "
        f"last failure: {last_reason}")
