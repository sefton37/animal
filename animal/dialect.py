"""Per-model edit-format registry (Story #447, M1-execution-craft): fenced
plain-text edit dialects a coder can emit natively, instead of JSON-escaping a
multi-line code patch inside old_string/new_string turn-schema fields.

Local coder models measurably produce fewer broken edits from a plain-text
fenced dialect than from JSON tool-calling (Aider's own field measurement:
~9x fewer errors) -- because a fenced SEARCH/REPLACE or whole-file block never
requires a model to escape a newline, a double quote, or a backslash inside a
JSON string; the harness just splits text on literal marker lines instead of
running it through json.loads.

Each named format below is a (PROMPT, parser) pair:
  - PROMPT   the instructions a model sees for that fenced syntax (appended
             to a role's system prompt by whatever wires config.ROLES[role]
             ['edit_format'] to a non-JSON call path).
  - parse_*  turns raw model text into a list of canonical
             {"path", "old_string", "new_string"} dicts -- the SAME shape
             animal.types.action_from_dict already expects for
             {"kind": "edit", ...}, so a dialect-parsed edit becomes a real
             EditAction with ZERO changes to types.py or the loop's dispatch
             (EditAction's own docstring already names this: "per-model
             dialects ... normalize to this before execution").

This module only parses text; it never executes anything, and it does not
change model.py's existing JSON/response_format call path. config.py's
edit_format defaults every current role to "json", so nothing is migrated by
this story -- see the dated eval markdown alongside this module for the
measured parse-success numbers (against a live resident model) a future story
would use to decide which role, if any, to actually flip.
"""
from __future__ import annotations
import re

# --- registry keys -----------------------------------------------------

JSON = "json"                 # the original TURN_SCHEMA/response_format path in model.py -- untouched,
                               # and deliberately NOT a key in EDIT_FORMATS below (there is no
                               # parser here for it; a role configured "json" never calls parse()).
SEARCH_REPLACE = "search_replace"
WHOLE_FILE = "whole_file"

# --- prompt instructions (the fenced syntax a model is asked to emit) --

SEARCH_REPLACE_PROMPT = """To edit a file, emit a fenced SEARCH/REPLACE block -- NOT JSON:

```edit path/to/file.py
<<<<<<< SEARCH
<the exact existing text to find, verbatim -- copy it from a prior read>
=======
<the replacement text>
>>>>>>> REPLACE
```

Rules:
- The fence's first line is the literal word `edit` followed by the file path.
- <<<<<<< SEARCH, =======, and >>>>>>> REPLACE must each be alone on their own line.
- The SEARCH text must match the file's real content exactly (read the file first).
- Never JSON-escape this block -- write real newlines and real quote characters."""

WHOLE_FILE_PROMPT = """To edit a file, emit its ENTIRE new content in a fenced whole-file block -- NOT JSON:

```whole-file path/to/file.py
<the complete new content of the file, from its first line to its last>
```

Rules:
- The fence's first line is the literal word `whole-file` followed by the file path.
- Emit the WHOLE file, not a fragment -- this replaces the file's full content.
- Never JSON-escape this block -- write real newlines and real quote characters."""

# --- parsers -------------------------------------------------------------

_SEARCH_REPLACE_RE = re.compile(
    r"```edit[ \t]+(?P<path>\S+)\n"
    r"<{7} SEARCH\n(?P<old>.*?)\n={7}\n(?P<new>.*?)\n>{7} REPLACE\n"
    r"```",
    re.S,
)

_WHOLE_FILE_RE = re.compile(
    r"```whole-file[ \t]+(?P<path>\S+)\n"
    r"(?P<content>.*?)\n"
    r"```",
    re.S,
)


def parse_search_replace(text: str) -> list[dict]:
    """Extract every fenced SEARCH/REPLACE block in `text` into canonical
    {"path", "old_string", "new_string"} dicts, preserving embedded newlines
    and quote characters BYTE FOR BYTE -- there is no JSON round-trip to
    mangle them, just a split on the literal marker lines."""
    return [{"path": m["path"], "old_string": m["old"], "new_string": m["new"]}
            for m in _SEARCH_REPLACE_RE.finditer(text)]


def parse_whole_file(text: str) -> list[dict]:
    """Extract every fenced whole-file block into canonical
    {"path", "old_string", "new_string"} dicts. old_string is None here -- a
    whole-file dialect names no prior anchor in the model's own text; an
    executor applying this action supplies the file's current content as
    old_string itself (out of this module's scope: this module only parses
    model text, it never reads the workspace)."""
    return [{"path": m["path"], "old_string": None, "new_string": m["content"]}
            for m in _WHOLE_FILE_RE.finditer(text)]


EDIT_FORMATS = {
    SEARCH_REPLACE: {"prompt": SEARCH_REPLACE_PROMPT, "parse": parse_search_replace},
    WHOLE_FILE: {"prompt": WHOLE_FILE_PROMPT, "parse": parse_whole_file},
}


def parse(edit_format: str, text: str) -> list[dict]:
    """Dispatch to the named format's parser. Unknown formats (including
    "json", which has no parser here at all -- it stays on model.py's
    existing response_format path and never reaches this function) raise, so
    a config typo is a loud error, never a silently-empty edit list."""
    try:
        handler = EDIT_FORMATS[edit_format]
    except KeyError:
        raise ValueError(f"unknown edit_format: {edit_format!r} (known: {sorted(EDIT_FORMATS)})") from None
    return handler["parse"](text)


def prompt_for(edit_format: str) -> str:
    """The fenced-syntax instructions for a given format (appended to a
    role's system prompt by whatever wires that role to a non-JSON
    edit_format)."""
    return EDIT_FORMATS[edit_format]["prompt"]
