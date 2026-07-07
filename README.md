# animal

> An experiment in local-first agentic harness design — built on the foundation
> and legacy of the [Resonance](#the-resonance-lineage) engine.

**Status:** Phases 0–3 complete. The kernel does harness-verified work on a live
repo (P1); the work lane adds a gated `draft→…→done` state machine, human-gated,
with Gate 0 rejecting vacuous DoD checks at authoring (P2); and the cross-family
panel (P3) catches subtle bad premises at **95% recall / 0% false-positive**
(majority vote of gpt-oss/mistral/qwen), with interpretation-enumeration surfacing
shared-prior ambiguities 6/6, and the patch-farm lane (sample-k + test-filter +
cross-family select) solving 6/6 vs 5/6 single-attempt — the diversity thesis (O4)
validated in running code, on both the judgment and generation sides.
See [`phase0/PHASE0-EXIT.md`](phase0/PHASE0-EXIT.md), [`phase1/`](phase1/README.md),
[`phase2/`](phase2/README.md), [`phase3/`](phase3/README.md). Next: Phase 4
(calibration + learning plane), per [`docs/ARCHITECTURE.md` §Build phases](docs/ARCHITECTURE.md#build-phases).

```bash
# backend (Phase 0) up, then:
python3 -m animal.cli run "Fix add() in calc.py to return a+b" --repo REPO --check "python3 check.py"
```

---

## What this is

`animal` is a from-scratch agentic **coding-and-ops** harness that runs
**multiple local models** — different model families for different roles — on a
single sovereign machine. It is not a fork of an existing harness and not a
wrapper around a cloud API. It is a deliberate experiment with one thesis:

> **The harness computes reality; models propose, judge, and explain.**

Every agentic harness has to decide what it *guarantees* versus what it *trusts
the model to tell it*. The three best-in-class harnesses studied here
(Claude Code, OpenAI Codex CLI, OpenCode) converged on the same skeleton — one
flat loop, typed tools, subagents as context firewalls, an append-only session
log — and differ almost entirely on where that trust boundary sits. `animal`
puts the boundary as far toward *computed evidence* as it will go: the harness
applies the edits and owns the diff, runs the checks and owns the verdict,
holds the human's approval channel and owns what counts as "done." Models are
asked to do only what models are good at — propose changes, judge ambiguous
things, and explain failures — and the judging is done by **panels of
decorrelated model families**, because the failure that started all of this was
three copies of *one* model agreeing on a fiction.

## Why it exists — the experiment

This is framed honestly as two tiers, because only one of them is a bet:

- **The invariant (verified, not tested).** That a harness which computes the
  diff instead of trusting the prose eliminates the non-persistence class is not
  a claim that could turn out false — it is true by construction. What is not
  free is that the *implementation actually enforces it*, so it is **verified by
  seeded adversarial attacks**: the kernel does not ship until an injected
  claimed-but-non-persisted edit and a fabricated check-pass are each caught and
  flagged as tool errors, with the ledger showing the catch.
- **The bets (can fail, with pre-registered consequences).** (1) *Diversity* —
  that on a 16 GB-VRAM / 251 GB-RAM box a panel of **diverse local model
  families** is a cheaper, more honest reliability lever than one larger model,
  precisely where judgment (not measurement) is required. (2) *Tiering* — that
  the full verification chain is usable at local-model speeds. Both have written
  exit thresholds and named fallbacks in
  [`docs/ARCHITECTURE.md` §What this experiment tests](docs/ARCHITECTURE.md#what-this-experiment-tests)
  and [§Risks](docs/ARCHITECTURE.md#risks-and-open-questions). The two that would
  most change the shape of the thing: if diverse-family panels don't catch seeded
  bad-premise specs at the pre-registered recall/false-positive bar, the panel
  layer is wrong and the diversity budget moves to candidate selection (where the
  evidence is already solid); and if the interactive chain runs slower than a
  pre-registered ceiling, the interactive value proposition is declared dead and
  that work is confined to overnight.

Neither bet failing invalidates the invariant kernel (ledger + typed actions +
computed evidence + sandbox + a minimal lane router and approval surface), which
is independently valuable and ships — and is proven correct on the
founding-incident class — first, for exactly this reason.

This is not a product. It has no roadmap promises, no users to please, and it
competes with nothing — its comparative advantage is unattended overnight work
on hardware that is otherwise idle, where the alternative is not a better
harness but *no work at all*.

## The Resonance lineage

`animal` is the second incarnation of an idea that began as **Resonance**, a
five-stage experiential-learning engine that watched Claude Code sessions and
tried to distill patterns, principles, and "moments" back into future sessions.
Resonance's instincts were right and its loop was wrong, and both halves are the
inheritance here:

- **What Resonance got right, and `animal` carries forward:** a local SQLite
  archive with real provenance columns, idempotency keys, full-text search,
  atomic promotions, and JSONL telemetry of every learning interaction; the
  moment schema (*what happened / what was learned / the correction*), which
  becomes the typed incident ledger; and read-only inspection as a first-class
  affordance.
- **What Resonance got wrong, and `animal` inverts:** it learned from *commit
  prose* (and distilled platitudes), delivered lessons through a *static*
  session-start block that silently froze on months-old seed content, set each
  lesson's confidence *once* and never updated it from outcomes, and — the
  quiet killer — its daemon died cleanly one day and the whole learning loop
  stopped for two weeks with nobody noticing.

The learning plane is the **culmination the kernel exists to enable** — it ships
last (Phase 4b) precisely because it *requires* the kernel's verified-outcome
substrate to learn from. It is not the through-line (that is evidence-over-prose)
and not a decorative add-on either: it is what Resonance becomes when the engine
that was supposed to learn from the harness finally has real ground truth to
learn from. `animal` learns from **verified outcomes the harness observed** (not
prose it was told), reinforces and decays lessons by outcome arithmetic, tracks
**per-model calibration** (which family, in which role, claims success and is
actually right), and — its one genuinely new move — *compiles* a lesson that has
earned enough support into an enforced check, so the gap between "warned about it
in memory" and "the harness won't let it happen again" finally closes. Resonance
observed; `animal` acts on what it observed. Every plane watches the others'
heartbeats, so nothing dies quiet again.

## Repository layout

```
animal/
├── README.md              you are here
├── LICENSE                MIT
├── .gitignore             local state (ledger, DBs, models) never tracked
└── docs/
    └── ARCHITECTURE.md    the architectural plan — the primary artifact
```

Code directories (`core/`, `actions/`, `models/`, `state/`) are created as their
phases begin; until then the plan is the deliverable.

## Where to start reading

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) is the whole design. Its shape:

1. **Objectives** — the eight things `animal` must achieve (including *ops as
   first-class* and *human authority + attention*), stated so the rest of the
   document can be checked against them, plus what the experiment actually tests.
2. **Six laws** — the doctrine every subsystem obeys.
3. **The planes** — ledger, actions, model plane, learning, human channel — and
   the seven design forks, each adjudicated with the evidence on both sides.
4. **Build phases** — kernel first (scoped to stand alone), learning plane last,
   each ending in a named dogfood workload.
5. **Risks** — the falsifiable exits, with pre-registered thresholds.

## Provenance

The plan is synthesized from a body of adversarially fact-checked research
(field study of Claude Code / Codex CLI / OpenCode from docs and source, the
current state of local inference sized to this exact hardware, and the
literature on model-diversity as a reliability strategy), plus a review of the
operating record itself (the verification chain, the product database, the
hallucination-incident corpus, and Resonance). It has been through two
adversarial red-team passes — a five-lens critique of the design and a five-lens
consistency/logic audit of this plan against its own objectives — plus a
522-check audit of the real definition-of-done corpus. See
[`docs/ARCHITECTURE.md` §Provenance](docs/ARCHITECTURE.md#provenance) for the
full accounting, including corrections applied and claims still marked
directional.

## License

[MIT](LICENSE) © 2026 Kellogg Brengel.
