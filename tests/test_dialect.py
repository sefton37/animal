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


def test_config_roles_default_every_role_to_json_edit_format():
    # Preserves today's behavior for every role that exists right now -- this
    # story adds a path, it does not migrate anything onto it.
    roles = config.ROLES
    assert len(roles) >= 4
    for name, rc in roles.items():
        assert rc["edit_format"] == dialect.JSON, f"role {name} unexpectedly migrated off json"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
