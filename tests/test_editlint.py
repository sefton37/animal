"""Tests for the syntax-lint gate on the edit pipeline (Story #445,
M1-execution-craft). Runnable directly (`python3 tests/test_editlint.py`) or
under pytest."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from animal.workspace import Workspace
from animal.sandbox import Sandbox
from animal.loop import _dispatch
from animal.types import ErrorClass, action_from_dict
from animal import editlint


def _ws_with(name: str, content: str):
    repo = Path(tempfile.mkdtemp(prefix="animal-lint-"))
    (repo / name).write_text(content)
    return repo, Workspace(repo, session_id="t", shadow_root=tempfile.mkdtemp())


def test_syntax_breaking_edit_rejected_before_write():
    pre_edit_content = "def add(a, b):\n    return a + b\n"
    repo, ws = _ws_with("calc.py", pre_edit_content)
    ws.read("calc.py")
    e = ws.edit("calc.py", "return a + b", "return (a + b")  # unmatched paren
    assert e.ok is False
    assert e.error_class == ErrorClass.LINT_REJECTED.value
    assert (repo / "calc.py").read_text() == pre_edit_content


def test_unsupported_extension_edit_is_advisory_only():
    # .md is not a recognized extension -- lint must never reject it, no matter
    # how broken the new content looks to a python linter.
    pre_edit_content = "hello world\n"
    repo, ws = _ws_with("notes.md", pre_edit_content)
    ws.read("notes.md")
    e = ws.edit("notes.md", "hello world", "((( not valid python, but not python")
    assert e.ok is True


def test_syntactically_valid_edit_unaffected_by_the_gate():
    pre_edit_content = "def add(a, b):\n    return a + b\n"
    repo, ws = _ws_with("calc.py", pre_edit_content)
    ws.read("calc.py")
    e = ws.edit("calc.py", "return a + b", "return a - b")
    assert e.ok is True
    assert (repo / "calc.py").read_text().find("a - b") >= 0


def test_lint_function_dispatches_by_extension():
    assert editlint.lint("x.py", "def f(:\n    pass\n") is not None
    assert editlint.lint("x.py", "def f():\n    pass\n") is None
    assert editlint.lint("x.txt", "((( anything goes, unrecognized extension") is None
    assert editlint.lint("x.json", "{not json") is not None
    assert editlint.lint("x.json", '{"a": 1}') is None


# --- Audit 1.5 fix: the census of this repo (git ls-files by extension) is
# 30 .py / 14 .md / 12 .txt / 11 .json / 5 .sh / 1 .yaml / 1 .c -- the prior
# cut only registered .py, so every extension besides .py/.md/.txt sailed
# through both edit() and the shell post-hoc gate untouched. These close that
# scope gap for .json/.sh/.c (real syntax-only checks) and pin .yaml as a
# deliberate, documented advisory-only exception (no stdlib parser exists). ---

def test_json_syntax_breaking_edit_rejected_before_write():
    pre_edit_content = '{\n  "a": 1,\n  "b": 2\n}\n'
    repo, ws = _ws_with("data.json", pre_edit_content)
    ws.read("data.json")
    e = ws.edit("data.json", '"b": 2', '"b": 2,')  # trailing comma -> invalid JSON
    assert e.ok is False
    assert e.error_class == ErrorClass.LINT_REJECTED.value
    assert (repo / "data.json").read_text() == pre_edit_content


def test_json_valid_edit_unaffected_by_the_gate():
    pre_edit_content = '{\n  "a": 1,\n  "b": 2\n}\n'
    repo, ws = _ws_with("data.json", pre_edit_content)
    ws.read("data.json")
    e = ws.edit("data.json", '"b": 2', '"b": 3')
    assert e.ok is True
    assert (repo / "data.json").read_text().find('"b": 3') >= 0


def test_sh_syntax_breaking_edit_rejected_before_write():
    pre_edit_content = "#!/bin/bash\nif [ 1 -eq 1 ]; then\n  echo ok\nfi\n"
    repo, ws = _ws_with("run.sh", pre_edit_content)
    ws.read("run.sh")
    e = ws.edit("run.sh", "fi\n", "")  # drop the closing fi -> unterminated if
    assert e.ok is False
    assert e.error_class == ErrorClass.LINT_REJECTED.value
    assert (repo / "run.sh").read_text() == pre_edit_content


def test_sh_valid_edit_unaffected_by_the_gate():
    pre_edit_content = "#!/bin/bash\necho hello\n"
    repo, ws = _ws_with("run.sh", pre_edit_content)
    ws.read("run.sh")
    e = ws.edit("run.sh", "hello", "world")
    assert e.ok is True
    assert (repo / "run.sh").read_text().find("world") >= 0


def test_c_syntax_breaking_edit_rejected_before_write():
    pre_edit_content = "int main(void) {\n    return 0;\n}\n"
    repo, ws = _ws_with("prog.c", pre_edit_content)
    ws.read("prog.c")
    e = ws.edit("prog.c", "return 0;", "return 0")  # drop the semicolon
    assert e.ok is False
    assert e.error_class == ErrorClass.LINT_REJECTED.value
    assert (repo / "prog.c").read_text() == pre_edit_content


def test_c_valid_edit_unaffected_by_the_gate():
    pre_edit_content = "int main(void) {\n    return 0;\n}\n"
    repo, ws = _ws_with("prog.c", pre_edit_content)
    ws.read("prog.c")
    e = ws.edit("prog.c", "return 0;", "return 1;")
    assert e.ok is True
    assert (repo / "prog.c").read_text().find("return 1;") >= 0


# --- #445 red-team follow-up: a spirit-audit fed a syntax-broken .kt edit through
# edit() and it LANDED on disk while every DoD check passed, because the gate knew
# only .py/.json/.sh/.c. JS is a primary target language (the Stalag codebase); node
# --check now gates .js/.mjs/.cjs. .kt/.ts stay advisory only for want of a toolchain. ---

def test_js_syntax_breaking_edit_rejected_before_write():
    import shutil
    pre_edit_content = "export function add(a, b) {\n  return a + b;\n}\n"
    repo, ws = _ws_with("calc.js", pre_edit_content)
    ws.read("calc.js")
    e = ws.edit("calc.js", "}\n", "\n")  # drop the closing brace -> unbalanced
    if shutil.which("node"):
        assert e.ok is False
        assert e.error_class == ErrorClass.LINT_REJECTED.value
        assert (repo / "calc.js").read_text() == pre_edit_content
    else:
        assert e.ok is True   # advisory-only when node is absent -- no false rejection


def test_js_valid_edit_unaffected_by_the_gate():
    pre_edit_content = "export function add(a, b) {\n  return a + b;\n}\n"
    repo, ws = _ws_with("calc.js", pre_edit_content)
    ws.read("calc.js")
    e = ws.edit("calc.js", "a + b", "a - b")
    assert e.ok is True
    assert (repo / "calc.js").read_text().find("a - b") >= 0


def test_yaml_extension_remains_deliberately_advisory_only():
    # .yaml has no stdlib parser -- deliberately left advisory-only rather
    # than shipping a hand-rolled heuristic that could false-reject valid
    # YAML (see editlint.py module docstring for the reasoning).
    pre_edit_content = "key: value\n"
    repo, ws = _ws_with("config.yaml", pre_edit_content)
    ws.read("config.yaml")
    e = ws.edit("config.yaml", "key: value", "key: [unbalanced")
    assert e.ok is True


def test_missing_binary_falls_back_to_advisory_not_rejection():
    # A missing system tool is an environment fact, never grounds for a
    # rejection -- exercise the subprocess helper directly with a binary name
    # that cannot exist, independent of whether bash/gcc happen to be
    # installed on the machine running this test.
    assert editlint._lint_via_subprocess(["definitely-not-a-real-binary-xyz"], "anything") is None


# --- the lint gate belongs to the edit PIPELINE, not to one action kind --- #
# ShellAction runs argv directly and can write to the workspace without ever
# calling Workspace.edit() -- the same loop dispatches both action kinds, so a
# syntax-breaking write must be blocked there too, not just behind the typed
# edit() call. These exercise the real _dispatch() from animal.loop, unmodified.

def test_shell_action_creating_syntax_broken_file_is_blocked():
    repo = Path(tempfile.mkdtemp(prefix="animal-lint-shell-"))
    ws = Workspace(repo, session_id="t", shadow_root=tempfile.mkdtemp())
    sb = Sandbox()
    action = action_from_dict({"kind": "shell",
                               "argv": ["bash", "-c", 'printf "def f(:\\n" > new_module.py']})
    env = _dispatch(action, ws, sb)
    assert env.ok is False
    assert env.error_class == ErrorClass.LINT_REJECTED.value
    assert not (repo / "new_module.py").exists()   # the broken write never lands


def test_shell_action_overwriting_file_with_broken_syntax_is_reverted():
    repo = Path(tempfile.mkdtemp(prefix="animal-lint-shell-"))
    pre_edit_content = "def add(a, b):\n    return a + b\n"
    (repo / "calc.py").write_text(pre_edit_content)
    ws = Workspace(repo, session_id="t", shadow_root=tempfile.mkdtemp())
    sb = Sandbox()
    action = action_from_dict({"kind": "shell",
                               "argv": ["bash", "-c", 'printf "def add(a, b:\\n    return a+b\\n" > calc.py']})
    env = _dispatch(action, ws, sb)
    assert env.ok is False
    assert env.error_class == ErrorClass.LINT_REJECTED.value
    assert (repo / "calc.py").read_text() == pre_edit_content   # restored, not left broken


def test_shell_action_writing_valid_python_is_unaffected_by_the_gate():
    repo = Path(tempfile.mkdtemp(prefix="animal-lint-shell-"))
    ws = Workspace(repo, session_id="t", shadow_root=tempfile.mkdtemp())
    sb = Sandbox()
    action = action_from_dict({"kind": "shell",
                               "argv": ["bash", "-c", 'printf "def g():\\n    return 1\\n" > good.py']})
    env = _dispatch(action, ws, sb)
    assert env.ok is True
    assert env.error_class == ErrorClass.NONE.value
    assert (repo / "good.py").exists()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} tests PASS")
