"""Tests for the per-model edit-format registry (Story #447). Runnable
directly (`python3 tests/test_dialect.py`) or under pytest. Proves the fenced
dialect path survives content a JSON-embedded old_string/new_string could not
carry without escaping, and that it feeds the SAME EditAction the loop already
consumes -- with zero change to the existing JSON action path.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal import dialect, config
from animal.types import action_from_dict, EditAction


def test_registry_exports_named_formats():
    assert dialect.SEARCH_REPLACE == "search_replace"
    assert dialect.WHOLE_FILE == "whole_file"
    assert set(dialect.EDIT_FORMATS) == {dialect.SEARCH_REPLACE, dialect.WHOLE_FILE}
    assert "SEARCH" in dialect.prompt_for(dialect.SEARCH_REPLACE)
    assert "whole-file" in dialect.prompt_for(dialect.WHOLE_FILE)


# A raw model-response fixture: prose around a fenced SEARCH/REPLACE block
# whose SEARCH and REPLACE bodies each carry an embedded newline (the block
# is inherently multi-line) AND an embedded double-quote character -- the
# exact content a JSON old_string/new_string field would need to escape.
_FIXTURE_OLD = 'def greet(name):\n    print("hello, " + name)'
_FIXTURE_NEW = 'def greet(name):\n    print(f"hello, {name}!")'
RAW_MODEL_RESPONSE = f"""Sure, here's the fix:

```edit greet.py
<<<<<<< SEARCH
{_FIXTURE_OLD}
=======
{_FIXTURE_NEW}
>>>>>>> REPLACE
```

Let me know if that works."""


def test_search_replace_roundtrip_survives_newlines_and_quotes():
    parsed = dialect.parse(dialect.SEARCH_REPLACE, RAW_MODEL_RESPONSE)
    assert len(parsed) == 1
    d = parsed[0]
    assert d["path"] == "greet.py"
    # BYTE FOR BYTE against the fixture -- no JSON round-trip involved
    assert d["old_string"] == _FIXTURE_OLD
    assert d["new_string"] == _FIXTURE_NEW
    assert '"' in d["old_string"] and "\n" in d["old_string"]
    assert '"' in d["new_string"] and "\n" in d["new_string"]

    # feeds straight into the SAME codec the JSON action path uses
    action = action_from_dict({"kind": "edit", **d})
    assert isinstance(action, EditAction)
    assert action.path == "greet.py"
    assert action.old_string == _FIXTURE_OLD
    assert action.new_string == _FIXTURE_NEW


def test_parse_search_replace_direct_matches_dispatch():
    direct = dialect.parse_search_replace(RAW_MODEL_RESPONSE)
    dispatched = dialect.parse(dialect.SEARCH_REPLACE, RAW_MODEL_RESPONSE)
    assert direct == dispatched


def test_search_replace_finds_multiple_blocks():
    two_blocks = (
        "```edit a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n```\n"
        "some prose in between\n"
        "```edit b.py\n<<<<<<< SEARCH\ny = 1\n=======\ny = 2\n>>>>>>> REPLACE\n```\n"
    )
    parsed = dialect.parse_search_replace(two_blocks)
    assert [d["path"] for d in parsed] == ["a.py", "b.py"]
    assert parsed[0]["old_string"] == "x = 1" and parsed[0]["new_string"] == "x = 2"
    assert parsed[1]["old_string"] == "y = 1" and parsed[1]["new_string"] == "y = 2"


def test_whole_file_parses_full_content():
    content = 'line one\nline two with a "quote"\nline three'
    raw = f"```whole-file calc.py\n{content}\n```"
    parsed = dialect.parse_whole_file(raw)
    assert len(parsed) == 1
    assert parsed[0]["path"] == "calc.py"
    assert parsed[0]["old_string"] is None            # no anchor named by the dialect itself
    assert parsed[0]["new_string"] == content
    assert dialect.parse(dialect.WHOLE_FILE, raw) == parsed


def test_unknown_format_raises():
    try:
        dialect.parse("nope", "irrelevant")
        assert False, "expected ValueError for an unregistered edit_format"
    except ValueError as e:
        assert "nope" in str(e)


def test_json_is_not_in_the_parser_registry():
    # "json" stays on model.py's existing response_format path; it must never
    # be dispatchable through this module's parse() (that would imply this
    # story silently added a parser nothing asked for).
    assert dialect.JSON not in dialect.EDIT_FORMATS


def test_search_replace_wired_but_coder_flip_held():
    # #486: the search_replace turn protocol is fully wired + parse-tested, but the
    # production coder flip is HELD. A live smoke test showed the SR coder REGRESSES
    # end-to-end (the json coder solves a one-line bug in 3 turns; the SR coder lands
    # 0 edits -- it guesses a SEARCH and edits without reading, so read-before-edit
    # blocks it). #447's parse-success metric measured the wrong thing (parseability,
    # not landed edits). Roles stay on json until the SR coder's read-first behavior
    # is fixed; the dialect path exists and is ready.
    assert dialect.SEARCH_REPLACE in dialect.EDIT_FORMATS       # the path exists
    for name, rc in config.ROLES.items():
        assert rc["edit_format"] == dialect.JSON, f"role {name} flipped off json prematurely"


# --- #486: the search_replace turn protocol wired into model.py ---

def test_parse_dialect_fenced_edit_becomes_edit_action():
    from animal.model import ModelPlane
    mp = ModelPlane()
    turn = ("fix it\n\n```edit calc.py\n<<<<<<< SEARCH\ndef add(a, b):\n    return a - b\n"
            "=======\ndef add(a, b):\n    return a + b\n>>>>>>> REPLACE\n```")
    t = mp._parse_dialect(turn, "search_replace")
    assert t["action"]["kind"] == "edit" and t["action"]["path"] == "calc.py"
    assert t["action"]["old_string"] == "def add(a, b):\n    return a - b"   # raw, no JSON escaping
    assert t["action"]["new_string"] == "def add(a, b):\n    return a + b"
    assert t["thought"] == "fix it"


def test_parse_dialect_bare_json_action_and_wrapper():
    from animal.model import ModelPlane
    mp = ModelPlane()
    bare = mp._parse_dialect('look\n{"kind":"read","path":"calc.py"}', "search_replace")
    assert bare["action"] == {"kind": "read", "path": "calc.py"} and bare["thought"] == "look"
    wrapped = mp._parse_dialect('{"thought":"x","action":{"kind":"finish","message":"d"}}', "search_replace")
    assert wrapped["action"]["kind"] == "finish"


def test_system_prompt_selected_by_role_edit_format():
    from animal.model import system_prompt_for, SYSTEM_PROMPT, SYSTEM_PROMPT_SEARCH_REPLACE
    assert "SEARCH/REPLACE" in SYSTEM_PROMPT_SEARCH_REPLACE and "SEARCH/REPLACE" not in SYSTEM_PROMPT
    # system_prompt_for dispatches on the role's edit_format (proven by toggling it)
    saved = config.ROLES["coder"]["edit_format"]
    try:
        config.ROLES["coder"]["edit_format"] = "search_replace"
        assert system_prompt_for("coder") is SYSTEM_PROMPT_SEARCH_REPLACE
        config.ROLES["coder"]["edit_format"] = "json"
        assert system_prompt_for("coder") is SYSTEM_PROMPT
    finally:
        config.ROLES["coder"]["edit_format"] = saved


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
