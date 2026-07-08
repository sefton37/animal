# Edit-format eval — 2026-07-06

Measured, not asserted (this project's "measure before load-bearing" discipline,
per `phase0/PREREGISTRATION.md`). Story #447 adds a per-model edit-format
registry (`animal/dialect.py`) alongside the existing JSON action path. Before
migrating any role's `config.ROLES[role]['edit_format']` off the default
`"json"`, this run measures whether the fenced dialects actually help the
resident **coder** seat (Qwen3-Coder-30B-A3B-Instruct, `--n-cpu-moe 48`, per
`phase0/results/model-roster.md`), live, over llama-swap
(`http://127.0.0.1:8890`) — not a synthetic/offline stand-in.

## Method

12 synthetic single-file edit tasks (`f1.py`..`f12.py`), each a small Python
snippet deliberately containing a double-quote and/or a backslash — the exact
content class a JSON `old_string`/`new_string` field can mangle via
escaping/quoting bugs (the story's named failure mode) — with a one-line
change requested (rename a function, swap a substring inside a quoted
literal, add a guard clause, etc).

Each task was sent to the live `coder` seat three ways, temperature 0.2:

1. **`search_replace`** — `animal.dialect.SEARCH_REPLACE_PROMPT` appended to
   the system prompt, plain-text completion (no `response_format`), parsed
   with `animal.dialect.parse_search_replace`.
2. **`whole_file`** — `animal.dialect.WHOLE_FILE_PROMPT`, plain-text
   completion, parsed with `animal.dialect.parse_whole_file`.
3. **`json`** — the existing path: `animal.model.ModelPlane.call("coder", ...)`
   with the same `response_format: json_schema` (`TURN_SCHEMA`) constrained
   decoding the kernel uses today.

**Success signal** (not just "did a block parse" — did the model's own
proposed anchor actually hold against the real source): for `search_replace`
and `json`, success = the parsed/returned `old_string` is a genuine,
byte-exact substring of the task's real file content. For `whole_file`
(which names no anchor — see `dialect.parse_whole_file`'s docstring),
success = a well-formed, non-empty whole-file block was parsed for that path.

Script: `phase1/bench/edit_format_eval.py`, committed alongside this doc (not
a scratchpad artifact) so the numbers below are re-runnable, not asserted --
re-run it (with llama-swap already serving) via:

```
python3 phase1/bench/edit_format_eval.py > phase1/results/edit-format-eval.json
```

Raw per-task PASS/FAIL lines are committed at
`phase1/results/edit-format-eval.txt` (stderr) and the full JSON summary at
`phase1/results/edit-format-eval.json` (stdout) -- both are the actual output
of the run this table reports, not a transcription.

## Results

| Format | n | parse/anchor-success | rate |
|---|---:|---:|---:|
| `search_replace` | 12 | 12 | 100% |
| `json` (existing path) | 12 | 11 | 92% |
| `whole_file` | 12 | 10 | 83% |

Wall time: 126.8s for all 36 calls (12 tasks x 3 formats) --
`phase1/results/edit-format-eval.json`'s `elapsed_s`.

Per-task detail (only failures noted; every other cell is a pass):

- `f3.py` (nested-quote task: `print("warning: \"" + msg + "\"")`) — **both**
  `whole_file` and `json` failed here; `search_replace` did not. This is the
  single task where JSON's escaping/quoting risk actually showed up in this
  small run, and it is also the hardest task in the batch (a doubly-escaped
  quote inside a quoted literal).
- `f7.py` (add-a-guard-clause task, no quoting involved) — `whole_file` failed
  (the model did not emit a parseable whole-file block for that task);
  `search_replace` and `json` both passed.

## Interpretation

On this small (n=12), single-seat run, `search_replace` matched or beat both
alternatives, and was the only format with zero failures on the one task
built specifically to stress JSON-escaping (`f3.py`) — directionally
consistent with the story's premise (Aider's own field measurement: ~9x fewer
edit errors from a fenced dialect vs JSON tool-calling). It is **not** proof at
scale: n=12 on one seat, one temperature, one prompt phrasing each. `json`'s
92% here is also already quite good, because `model.py`'s `response_format:
json_schema` constrained decoding (Phase 0's own measurement: ~100%
*structurally* parseable JSON) already prevents most of the failure class this
story targets — the story's remaining lever is the fraction of that 92%..100%
where the JSON parsed fine but `old_string` still didn't anchor, which is
exactly what `f3.py` isolated once at this sample size.

## Decision this run informs

No role is migrated off `edit_format: "json"` by this story (`config.ROLES`
still defaults every role to `"json"` — see `animal/config.py`). This eval
is the measurement a future story should point to before flipping the coder
seat's `edit_format` to `"search_replace"` — a real number, not a prose claim,
per this project's own discipline for exactly this kind of decision.
