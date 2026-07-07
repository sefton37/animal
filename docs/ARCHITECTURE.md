# animal — Architectural Plan

**An experiment in local-first, multi-model agentic coding-and-ops harness
design, built on the foundation and legacy of the Resonance engine.**

Version: v3 (folds in a five-lens design critique, a 522-check corpus audit, and
a consistency/logic red-team of this plan against its own objectives).
Status: design phase; no runtime yet. This document is the primary artifact.

> **Thesis.** The harness computes reality; models propose, judge, and explain.
> Diverse-family panels do the judging — but the failure that started this
> (three copies of one model agreeing on a fiction) is caught by *evidence*, not
> diversity. Panels earn their tokens on the residual judgment classes the
> incident record actually assigns them: false premises and metric blind spots.

This plan is written so that every mechanism traces to an objective and every
objective is served by a mechanism. The [Objective traceability](#objective-traceability)
matrix near the end makes that mapping explicit; it is the spine a reader (or a
red-team) should use to check the plan against its own goals.

---

## Objectives

Eight objectives. The rest of the document is accountable to them.

- **O1 — Sovereignty.** Runs entirely on local hardware with no cloud inference
  path, no telemetry egress, and no dependency that phones home. Every model
  source is whitelisted; the operator itself is auditable by the machine's own
  security tooling; untrusted input is tagged and screened before it reaches a
  model.
- **O2 — Evidence over prose.** No load-bearing claim about what happened enters
  the record unless the harness computed it. Models never self-report the
  outcome of a deterministic check, never report their own diff, and never
  supply the number a decision turns on. *(This is a design invariant, not a
  hypothesis under test — see [What this experiment tests](#what-this-experiment-tests).)*
- **O3 — Structural elimination of mechanizable failures.** The failure classes
  that a harness *can* make impossible — non-persistence hallucination,
  verifier rubber-stamping of deterministic checks, serialized-data rot,
  tool-argument corruption, shared-state races, stale world-models, silent
  misdelivery — are eliminated by construction, not warned against in a prompt.
  *(Also an invariant; its enforcement is verified by seeded adversarial attacks,
  not assumed.)*
- **O4 — Diversity as a measured reliability strength.** Judgment (not
  measurement) is done by panels of decorrelated model *families*; the
  decorrelation is verified by on-box co-failure measurement, not assumed from a
  brand label; and diversity is understood as a constant-factor improvement that
  multiplies with evidence-grounding and never substitutes for it. *(This is the
  primary experimental bet.)*
- **O5 — Learning that compounds (the Resonance legacy).** The harness learns
  from verified outcomes it observed, tracks per-model calibration, reinforces
  and decays lessons by outcome arithmetic, and compiles earned lessons into
  enforced checks — closing the gap between "warned in memory" and "cannot
  happen again" that killed Resonance's usefulness.
- **O6 — Human authority and attention.** Two paired sub-goals: the human is the
  final authority on perception and on irreversible action, reachable over a
  channel no model output can forge (*authority*); and the harness spends that
  attention sparingly — ranked, batched, never re-reported, with its own
  ceremony held to the same precision budget as everything else (*economy*). The
  authority half is a safety invariant; the economy half is a design discipline.
- **O7 — Fits this machine, honestly.** Runs on one box (RTX 4070 Ti SUPER,
  16 GB VRAM; 251 GB RAM; 48 cores) with VRAM, swap, and wall-clock budgets that
  are arithmetic, not aspiration — and with every borrowed benchmark number
  treated as directional until re-measured on-box. *(The tiering/wall-clock bet
  is the second experimental bet.)*
- **O8 — Ops is first-class, not an afterthought.** The harness operates the
  fleet as well as it writes code (the stated purpose is "agentic coding, ops,
  etc."): a typed service registry, decay-tracked runbooks, a live-state differ,
  and a write-back contract are *owned* mechanisms, and the ops lane is co-equal
  with the work lane rather than a borrowed sub-behavior.

### What this experiment tests

The plan has two tiers, and only one of them is a hypothesis:

**Design invariants (verified, not tested).** The evidence-native core — O2, O3,
and the kernel that enforces them — is not a claim that could turn out false; a
harness that computes the diff instead of trusting the prose *does* eliminate the
non-persistence class, by construction. What is not free is that the
*implementation actually enforces the invariant*, so it is **verified by seeded
adversarial attacks**: Phase 1 injects a claimed-but-non-persisted edit and a
fabricated pass on a deterministic check and requires the harness to flag each as
a tool error, with the ledger showing the catch. If a seeded attack of a
mechanizable class reaches the record, that is a shipping-blocking implementation
bug, not a falsified thesis — but the kernel does not ship until the seeded
battery is green.

**Experimental bets (can fail, with pre-registered consequences).**

1. **Diversity (O4).** *Hypothesis:* decorrelated-family panels are a cheaper,
   more honest reliability lever than one larger model, where judgment (not
   measurement) is required. *Exit:* if a cross-family panel does not catch
   ≥ 80% of ≥ 20 seeded bad premises at ≤ 10% false-positive on ≥ 20 clean
   controls (thresholds pre-registered at Phase 0, confirmed before Phase 3),
   the panel layer is wrong — fall back to a single strong judge plus a human and
   move the diversity budget to candidate selection, where the evidence is
   already solid.
2. **Tiering (O7).** *Hypothesis:* the full chain is usable at local-model
   speeds. *Exit:* if *interactive-tempo* full-chain latency exceeds a
   pre-registered ceiling (Phase-0 set), the interactive value proposition is
   declared dead and that work is confined to overnight — a real conclusion about
   where `animal` is useful, distinct from a tuning knob. (Overnight slowness is
   free by design and is *not* a falsifier.)

Neither bet failing invalidates the invariant kernel, which is independently
valuable and ships first for exactly this reason (see [Build phases](#build-phases)).
This is not a product. It competes with nothing — its comparative advantage is
unattended overnight work on otherwise-idle hardware, where the alternative is
not a better harness but *no work at all*.

---

## Doctrine: six laws

Every subsystem obeys these. They are the compressed form of the objectives.

1. **Evidence is computed, never narrated.** Every mutating action returns
   harness-computed facts (diff, hashes, exit codes, receipts). Every agent run
   returns an envelope the harness assembled. Every OBSERVED claim in a report
   or verdict must cite a ledger artifact id the harness resolves; unresolvable
   claims are neutralized, not trusted. A non-persisted edit is a tool error.
   *(O2, O3)*
2. **The harness runs the checks; models author and interpret.** Definition-of-
   Done checks are typed objects (argv + comparator + pinned environment +
   nondeterminism flag) executed only by the harness runner. No model declares
   pass/fail on a deterministic check. This deletes the *fabricated*-pass/fail
   subclass by construction; check-redefinition and rationalization remain
   judgment-bound and route to panels. *(O2, O3, O4)*
3. **Gates are capability transitions, not exhortations.** Write capability is
   granted by task state, per lane, at the tool-dispatch layer. There is nothing
   to bypass because the gate is the *absence* of the capability. The harness's
   own control plane is read-only inside every agent sandbox — kernel-enforced.
   *(O1, O3)*
4. **Human input is a transport, not a token.** Approval and human-verification
   confirmations arrive over a channel no model can write to. Text that says
   "APPROVED" is just text. Never approve-by-retry. The channel carries a
   liveness probe. *(O6-authority)*
5. **Panels judge; determinism measures; families decorrelate — and
   decorrelation is measured.** Diverse-family panels spend tokens only on
   judgment, always fed harness-computed ground truth, never each other's
   narratives. Independent votes, one round, no debate. Family separation is
   verified by on-box co-failure measurement. A unanimous pass is evidence, not
   proof. *(O4)*
6. **Everything keeps score, and fails loud.** Every model claim is scored
   against verified outcomes; every gate logs what it caught with full context;
   every lesson reinforces or decays by outcome arithmetic. A gate that never
   fires is a finding; an enforcement path that errors fails closed and loud;
   every long-lived plane has a heartbeat watched by the others. *(O5, O6-economy)*

---

## Architecture at a glance

```
 Clients        TUI · CLI · overnight runner · phone approvals (Tailnet)
                thin clients of one protocol; interrupt/steer/inject frames
                     │  NDJSON control protocol (schema-versioned)
                     ▼
 animald core   one agent loop · lane router · task state machine · session
                leases · human-channel service (separate privilege domain) ·
                orchestration strategies (single-loop / phased-pair / panel /
                pipeline) — none of them model-visible
                     │  typed actions only (argv arrays)
                     ▼
 Action layer   typed action schema · round-trip-validated codec · per-model
                dialect adapters · prompt assembly with a declared cache
                boundary · edit pipeline (parse → invariants → blocking syntax
                lint → cascade → computed diff) · tool inventory (windowed read,
                summarized search, argv-only shell) · DoD executor · sandbox
                spawner (bwrap; control-plane read-only; deny→justify→escalate) ·
                policy rules with embedded tests · content trust-tier tagging +
                injection screen
                     │  evidence envelopes up · assembled prompts down
                     ▼
 Model plane    llama-server behind llama-swap (Ollama adapter as fallback) ·
                VRAM arbiter (phase-aware, exogenous-tenant-aware) · CPU-pinned
                triage-jury tier · roster seats by lineage · quirks table ·
                context auditor · constrained decoding for envelopes
                     │  everything reads/writes the ledger
                     ▼
 State plane    append-only event ledger (NDJSON + SQLite, versioned events,
                typed error taxonomy) · product DB (extended) · calibration +
                lessons + incidents + eval + co-failure matrices · FTS +
                read-only inspection surface · Bastion tap adapter
```

The **kernel** is the ledger, the typed action layer, the evidence envelopes,
the sandbox, and — so it can stand alone — a minimal lane router and a
TUI-keypress approval surface. Everything above it is a client; everything beside
it is a projection of the ledger. The kernel alone prevents the founding-incident
class and is the first thing that ships.

---

## The planes

### The ledger

The spine is an append-only event log — one file per session (NDJSON,
zstd-rotated) indexed in SQLite: every prompt, model output, typed action,
evidence envelope, gate decision (*with* its triggering input — the old
verdict-only logging that made false-positive analysis impossible is not
repeated), approval event, and check execution.

- Every event is stamped with a schema version and the emitting `animal`
  version; projection code upcasts on read and never rewrites the log, so
  replay, fork-at-turn-N, and rebuild survive format changes across build
  phases.
- Compaction is itself a ledger event. Any claim that references pre-compaction
  evidence is **tainted** and must be re-proven by fresh harness execution
  before it counts — this matters *more* on local models than it did under
  Claude Code, because small context windows force compaction far more often.
- Everything else — product-DB rows, calibration counters, the security feed —
  is a projection. Projections can be rebuilt; the ledger is the truth. A
  read-only inspection surface (CLI/TUI, FTS-backed) over the lessons,
  calibration, and incident projections is a first-class affordance, inherited
  from Resonance's read-only inspection instinct.

Build it before the TUI. *(serves O2, O3, O5)*

### Actions, tools, and the edit pipeline

**Fork 1 (adjudicated) — typed tools vs. fenced-bash actions.** The bash-only
simplicity of a mini-swe-agent-shaped loop demonstrably works; three studied
harnesses instead put all enforcement in typed tools. These answer different
questions. Resolution: the *model-facing syntax* is a per-model choice from eval
data (native tool-JSON for high-fidelity models, fenced-text extraction for the
rest), but everything normalizes into **one typed action schema — argv arrays
end-to-end, string-assembled shell not representable** (this closes the
tool-argument-corruption class), and every serialized submission passes through a
**round-trip-validated typed codec** so a non-round-trippable payload is a tool
error, not silent data rot. Every invariant lives at that layer. The
mini-swe-agent lesson survives in the loop's *shape*: linear history, stateless
execution, hard step/cost/time limits, exit on repeated format errors.

**The model-facing tool inventory** (the read side buys the most for weak
models): a *windowed* file viewer (~100 lines/page), *summarized-only* search
(iterative search measured worse than none), a shell tool that **executes an argv
vector with no shell interpreter** (no `sh -c`; pipes, redirects, and globs are
offered as typed harness operations, so the "not representable" guarantee above
holds through the shell too), with overflow-to-file beyond N characters, the edit
tool, and an observation-collapse policy (keep the last ~5 tool outputs verbatim,
summarize older). Correct use of this inventory is itself an eval-battery task.

**The edit pipeline, end to end:**

1. **Emission** — patch body in the model's best *measured* plain-text format
   (whole-file / search-replace / udiff, pinned per model), always via
   fenced-text extraction even under a JSON envelope (a JSON-escaped patch body
   is a measured failure mode).
2. **Parse → typed EditAction** with structured, actionable parse errors.
3. **Invariants** (enforced, not prompted) — the acting agent read the file this
   session and it is unchanged on disk since; the target is inside the writable
   grant; scope/size sanity.
4. **Blocking syntax lint** — a syntax-breaking edit is rejected *before it
   lands* with a structured error (the measured "interface beats scaling" result
   is for lint-*gated* edits; an advisory lint would let the bad edit start the
   documented failure-momentum spiral). Semantic diagnostics (LSP / tsc / ruff /
   cargo-check) stay advisory, appended to the result.
5. **Apply** via a fuzzy replacer cascade with a disproportionate-match guard
   (fuzziness that could rewrite half a file is refused); a shadow-git checkpoint
   lands before and after. Whole-file format, when pinned, uses its own
   max-delta-vs-file-size guard.
6. **Evidence** — the harness computes the diff. The diff object *is* the report.
7. **Recovery** — after N failed attempts on a target, auto-revert to the
   checkpoint and resample fresh; doom-loop detection (3 identical actions →
   interrupt) and cross-call variants are native.

**Content trust-tiers.** Every tool-output event carries an origin and a trust
tier in the ledger schema from Phase 1. Untrusted spans (fetched web content,
external files, untrusted command output) are structurally marked in prompt
assembly and routed through the resident utility-tier model as an
injection/anomaly screen before they reach the primary model. This is a
probabilistic *reduction*, not a by-construction elimination — it belongs to the
sovereignty boundary (O1), not the O3 impossible-by-construction list. Without
it, `animal` would ship with *less* injection defense than the system it
replaces, while running more-injectable local models. *(serves O1, O2, O7)*

### Enforcement: sandbox first

**Fork 2 (adjudicated) — kernel sandbox vs. permission pipeline as the primary
layer.** Sandbox-first. Weak local models running unattended *will* do something
dumb, and bubblewrap does not care how convincing the prose was; the operating
record shows prompt-layer gates leak and regex guards trade real friction for a
0.23% block rate of unmeasured value; and one machine means no portability tax —
roughly 200 lines against system bubblewrap plus a fixed seccomp profile, not a
ten-crate confinement layer. Per-agent defaults: workspace-writable, network off
at the syscall, and — the load-bearing decision — **`animal`'s own control plane
(ledger, product DB, gate config, policy, lessons) read-only inside every agent
sandbox**, so a verifier cannot be lobotomized by the thing it verifies.

**The escalation loop** is what makes sandbox-first livable (all three studied
harnesses have one), and it terminates in Phase 1's minimal approval surface, not
a Phase-2 dependency. A kernel-denied action is not a dead end: denial detection →
the agent emits a `justify-and-escalate` action → routed through the human
channel (a TUI keypress from Phase 1; the full phone flow later) → an approval can
persist as a narrow policy rule (with broad prefixes hardcoded-unproposable).
**Egress:** bubblewrap network namespacing is binary, so a per-task *host
allowlist* needs a loopback proxy — that is Phase 2; until then egress is on/off
and defaults off. Command classification for crossings uses prefix rules with
load-time unit tests (two years of guard regexes become testable, diffable
files), each with tracked precision and a budget: a gate below threshold gets
fixed or retired. *(serves O1, O3, O6-authority)*

### The work state machine

**Fork 5 (adjudicated) — keep the lanes, delete the bypasses.** A lane is a
session *capability manifest* chosen up front (deterministic router, human
override, recorded): **work** (state-machined, gated), **ops** (registry-scoped
grants, runbook-first, no spec — a co-equal lane per O8), **muse** (read/research
tools mounted; write tools and issue-creation *absent*), and **trivial** (direct
small edits under a cumulative session budget that forces escalation). Nothing
inside a session widens its own grants; there is no classifier to leak because
there is no gate to bypass. Muse discipline is literal: the harness *names* a
buildable thing in prose and stops — it instantiates a task object only when the
human says "file it." A minimal lane router ships in Phase 1 so the trivial lane
and the ops/work split exist from the start.

Within the work lane, a task moves
`draft → grounded → approved → building → verifying → needs-human → done`, and
capability follows state:

- **Gate 0 (native).** A spec-author role produces the spec as a
  schema-constrained object; DoD checks in a validated comparator grammar,
  **dry-run twice at authoring time** (auto-detect instability → mark
  nondeterministic → N=3 all-pass at run time) **and negative-controlled against
  the pre-work tree** (a check that passes before the code exists is vacuous and
  rejected — see the corpus-audit finding below). Authoring lints catch the
  recurring bug classes (regex alternation without `-E`, always-exit-0
  comparators, missing helper scripts, non-round-trippable JSON). Any
  positive-premise check ("must emit ≥1 spill face") must carry a companion probe
  that measures the ground truth it assumes. The harness grounds every referenced
  symbol (hash + snippet, recording *misses*), and re-grounds at build-start and
  audit. A cross-family **premise panel** then does two distinct tasks —
  *construct a failure that passes every check but violates the story*, and
  *enumerate every ambiguous term/boundary and state which reading the checks
  assume* — the enumeration surfaced in the approval request so the human
  adjudicates the *reading*, not the prose. Approval is a human-channel event.
- **Building.** Architect/editor as an implement-phase technique (Fork 6);
  checkpoints per step; deviation-notes are a structured field, and any deviation
  **halts** and routes to an adjudicator. For *interactive* tasks the default
  adjudicator is the human; for *unattended/overnight* tasks the default is a
  cross-family oracle/panel and the branch queues its decision to the morning
  readout, with human adjudication reserved for irreversible or high-stakes
  deviations — so O6's attention-economy and the unattended-overnight value both
  hold. A human rejection — including an interactive "no, try again" — mints a
  standing negative check in the rejected-artifact registry, scoped to the
  subsystem.
- **Verifying.** The harness runs 100% of DoD checks in the pinned environment,
  N=3 for flagged-nondeterministic, recording every execution. Continuous cheap
  checks during building double as a progress bar, phase-tagged so
  pre-implementation fails render as "not yet." A cross-family **audit panel**
  does only judgment: red-team the checks, trace the user story to a production
  path, halt-with-no-user-story.
- **Needs-human.** `HUMAN_CHECK` checks block here; the harness runs the scripted
  setup (serve, drive a headless browser, capture) and delivers the rendered
  artifact for one-tap pass/fail. Data-shaped deliverables get a receipt variant:
  a sample of real output (one day's rollup, with timestamps) travels with the
  done-transition. No model transitions this state.
- **Escape hatch.** Retroactive ratification is a real action with its own state
  and audit trail. Commit is a transactional tool call requiring structured
  issue/spec references — no trailer-regex archaeology.

**Fork 6 (adjudicated) — planner: biggest lever vs. dead ceremony.** Prune the
ceremony; keep the capability split. The mid-chain planner/verifier *gates* died
of disuse in the prior system; Gate 0 and the audit gate caught everything worth
catching. But the architect/editor split is the largest measured quality lever
available to a local rig. Reconciled: architect/editor is a *generation
technique inside building* — a reasoning model plans, a coder applies,
phase-major so they never thrash the GPU — while verification is harness-run
checks plus the audit judgment panel. No standing mid-chain roles; instrument
invocation-vs-catch from day one and let data prune or add. *(serves O2, O3, O4,
O6)*

### The model plane

**Backend.** `llama-server` instances orchestrated by `llama-swap`, with an
Ollama adapter kept as a fallback behind a provider abstraction from day one. The
three capabilities the design leans on — expert-aware MoE CPU offload (which
turns the 251 GB of RAM into the box's superpower), grammar-constrained decoding,
and durable prefix caches — are absent or buggier in Ollama. Sovereignty:
whitelist local model sources (Ollama now ships cloud-hybrid tags) and verify the
inference layer is egress-free. All backend claims are re-measured on-box in
Phase 0 before they are load-bearing — including two named correctness risks (a
prefix-cache-reuse regression report and a hybrid-model CUDA fault under agentic
tool-call patterns), which need a multi-turn *soak* per candidate, not just a
latency number.

**Fork 3 (adjudicated) — VRAM residency (phase-aware).** The naive "always-
resident utility tier + primary slot + co-resident jury" does not fit 16 GB (the
box already evicts a 13 GB judge model and a small model when co-loaded).
Corrected, phase-aware doctrine:

- **Build phases:** one primary slot (coder/architect, ~9–11 GB including KV
  cache) plus a small resident router/embedder (~3.5 GB at 8k context).
- **Judge/audit phases:** the primary *and* the small resident router/embedder
  are evicted for the judge seat, so the ~13 GB judge model owns the card (the
  intro's measured 13 GB + small-model co-load failure is respected, and the
  16 GB budget closes); the two extra swaps are *priced into the wall-clock
  model*, not hidden.
- **The interactive triage jury (3–4 B seats) runs CPU-pinned** — the design's
  own proven pattern (a `num_gpu=0` background service on this box was
  contention-immune; 3–4 B models do ~15–25 tok/s on 48 cores, fine for short
  structured verdicts), so it costs zero VRAM and never evicts the primary. **Full
  family panels, the judge/audit seat, and the offloaded escalation oracle run on
  GPU**, evict the primary, and incur the swaps the wall-clock model prices — a
  cost deliberately confined to *overnight* and to *on-demand interactive
  escalation*, where latency is affordable.
- The arbiter inventories the GPU's compute-apps every scheduling decision and
  treats **exogenous tenants** (a local image-generation service; any other model
  consumer — one evicted a research run mid-benchmark) as first-class capacity
  constraints, degrading to CPU placement under external pressure. Effective KV
  type per architecture is a Phase-0 exit check (KV quantization can silently
  fall back and double the budget).

**Fork 4 (adjudicated) — roster: seats, not tags.** Family-diverse *seats*
defined by lineage + capability requirements, provisionally filled from the
installed models, upgraded only through the eval battery. Lineage means *training
ancestry*, not brand: the registry carries a distillation/synthetic-data field,
and the same-family refusal enforces against ancestry (a GPT-4o-distilled model
does not count as an independent lineage from a GPT-lineage judge; a Qwen 4 B
juror does not judge a Qwen coder). The bet is *lineage spread verified by
co-failure measurement*, not brand labels, and the escalation oracle is
deliberately a distinct lineage from the generator whose disputes it settles.

**Prompt assembly with a declared cache boundary.** Prefill dominates wall-clock
at local speeds, so the assembler defines what is byte-stable prefix (system
prompt + schemas + standing lessons) versus appended dynamics (per-task lessons,
re-injected invariants, history) — lesson injection sits *after* the boundary so
it never invalidates the KV cache. This is the one convergent plumbing lesson the
field study surfaced that a naive design would skip.

**Context is a hard-audited resource.** Client-side token counting; per-role
pinned windows; assert the server-reported prompt token count matches expectation
on every response — silent truncation is the local twin of the founding
hallucination. Refuse any role whose fixed prompt exceeds ~50% of its window.
Overflow-to-file for big tool outputs; extraction routes through the resident
utility model, never the primary's context. Deterministic pruning before
generative summarization; guidance re-injects from disk after compaction. Small
models get harness-owned state: fresh contexts per gate, invariants re-injected
every turn (multi-turn tool use collapses; single-turn stays respectable).

**The quirks table is data.** Per-family: tool-call dialect, leaked-call-as-text
extractors, reasoning-channel handling, edit format, prompt dialect, temperature,
context ceiling, capability flags *enforced in dispatch*, and panel-rendering
discipline (plain-language fact sheets, one artifact per call for CPU jurors,
per-run finding caps). *(serves O1, O4, O7)*

### Panels: where diversity pays

**Fork 7 (adjudicated) — panel tempo and placement.** Gates get panels; tempo
picks the tier; the interactive jury runs on CPU. Interactive: resident-model
checks plus a CPU-pinned triage jury (three lineage-distinct 3–4 B models — no
VRAM cost, no primary eviction, no prefix-cache loss) that escalates to a full
GPU panel only on disagreement. Background/overnight: full family panels
default-on (on GPU, priced in swaps), since tokens cost electricity and nobody
waits. Panels are per-*gate*, never per-message, and batch per-model to amortize
swaps.

Where panels sit:

- **Gate 0 premise review** — highest ROI (bad premises are the residual
  frontier) — with a typed **PROBE output** the harness executes and returns
  before approval (the canonical false-premise incident's catch required
  *measuring* geometry; a text-only judge could not, a probe can), plus the
  interpretation-enumeration task.
- **Audit judgment** — red-team the checks, blind-spot review, failure
  interpretation; never re-running checks.
- **Candidate selection** — sample k, filter by harness-run tests, cross-family
  selector picks from the top 3 (the strongest-evidence use of a panel).
- **Escalation** — disagreement routes to a non-Qwen offloaded oracle or to the
  human; unanimity on low-stakes auto-proceeds.

**Aggregation** (reconciled so the rules do not undercut each other): independent
votes, one round, no debate. Majority for advisory judgments. *Veto reserved for
genuinely irreversible crossings* (push/publish/deploy/delete — **not** commit,
which is reversible via shadow-git and frequent; OR-ing 3–5 judges at ~10% false
positive each would falsely block a quarter of commits and recreate the pressure
that turned the old gates into theater). A veto must cite a harness-computed fact
or auto-downgrade to advisory-with-escalation; a chronically false-vetoing seat
loses veto power below a precision threshold. Dissent path: queue to the morning
readout with the dissenter's cited evidence; unblocked branches proceed.

**Calibration and decorrelation are measured, not assumed.** The eval battery
runs all seats on identical replays and emits a pairwise co-failure matrix; panel
composition is chosen to maximize joint detection, and a seat change must not drop
joint recall on seeded defects — because more-accurate models correlate *more*,
so selecting seats on individual accuracy alone drifts toward monoculture. The
calibration label source is **continuous seeded-defect injection** (known-bad
premises and known-clean specs interleaved with real work). **Judge/panel seats
are ranked on seeded-defect detection value from the first evals** — recall on
seeded-bad, precision on seeded-clean, never raw accuracy, because under a low
base rate the always-PASS judge wins on raw accuracy and would be selected into
the panel. The raw-pass-rate cold-start fallback applies only to generation/coder
seats; only the *magnitude* of vote-weighting waits for a calibration cell to
reach n ≥ 30, not the choice of metric for judges.

**The honest limits, stated because they bound the design:** two wrong models
agree ~60% of the time; excess correlated failure is measured at ~3.7× what
independence predicts; **no panel catches an ambiguity every member resolves
identically** (which is why interpretation-enumeration and the data-deliverable
receipt exist — a UTC-vs-local day boundary that story, checks, and every model's
shared prior agree on would ship past a pure construct-a-failure panel).
Diversity multiplies with evidence-grounding and never substitutes for it.
Cross-family verification would probably not have caught the founding incident —
that fix was ground truth. Build the structural fix first; spend diversity on
judgment. *(serves O4, O2)*

### The learning plane — Resonance's second incarnation

Resonance's necropsy dictates the rebuild: keep the schema instincts, abandon the
LLM distillation tower and the static injection block. The learning plane ships
last (Phase 4b) precisely because it *requires* the kernel's verified-outcome
substrate to learn from — it is the culmination the kernel exists to enable, not
a bolt-on. Each of Resonance's four documented failure modes maps to a concrete
inversion:

- **Commit prose → run outcomes.** Every run records `claimed_outcome` (parsed
  from the structured report) and `verified_outcome` (harness-executed). The
  delta is the signal. *(Resonance learned platitudes from commit messages.)*
- **Static session-start injection → dispatch-time injection + compilation.**
  Two delivery modes, not one (Resonance delivered only advisory prose, which the
  record shows has no discriminating power, and froze on months-old seed content
  by an `ORDER BY id` bug): (a) *injection* at dispatch by relevance
  (embedding × confidence × recency, path/keyword-triggered, FTS-backed) for
  context; and (b) **compilation** — a lesson whose support crosses a threshold
  mints a project-scoped standing check or diff-lint, executed by the DoD executor
  / post-edit diagnostics under the same precision budget. Rules like "verify the
  merged manifest," "consumers of visible ground use the surface-height helper"
  become *enforced*, not remembered. The gap between memory-warned and
  harness-enforced is where every repeat offense lived.
- **Confidence set once → running posterior.** Lessons upsert and decay;
  confidence reinforces on verified-good application, decrements on
  contradiction, decays on age, retires below a threshold. Human gating survives
  at exactly one point: creation of new always-injectable lessons
  (auto-*reinforcement* is safe arithmetic; auto-*creation* filled Resonance with
  noise within weeks of removing its gate).
- **Silent daemon death → planes watch each other.** Standing invariant checks
  over the ledger — learning rows written within N runs, injected-lesson content
  actually varying over a window, human-channel heartbeat, security-adapter
  liveness — surfaced in the morning readout. Resonance died silently for two
  weeks; nothing here dies quiet.

Kept from Resonance, mapped rather than assumed: **calibration is a first-class
table** — (model × role × claim-type) → claims vs. verified-true — the routing
function *and* the panel vote-weight, with a closed error taxonomy on every
check/envelope (model-claim-false / model-format-error / harness-fault /
env-mismatch / flake-retry-passed) that keeps non-model faults out of the
arithmetic (a majority of the old audit "failures" were environment mismatch).
**Provenance is harness-stamped** (timestamp, session id, evidence links); the
model fills only narrative fields (Resonance's newest "moment" was model-dated
three years into the past). **The incident ledger is the successor to Resonance's
moment schema**, extended into a typed forensic 6-tuple (claim / reality /
detection / root-cause / class / countermeasure — where *what-was-learned* maps
to *countermeasure* and *what-happened* to *claim + reality*), written by a
schema'd session-end flow, tombstoning superseded records at write time; the
existing hallucination corpus is ingested as the seed. **World facts carry
probes** re-run at retrieval. SQLite + FTS + read-only inspection CLIs are kept
wholesale (see [the ledger](#the-ledger)). *(serves O5, O2, O6)*

### The human channel

The keystone subsystem. A small approvals service runs in its own privilege
domain (agent sandboxes cannot reach it), owning approvals, human-verification
confirmations (rendered artifact + one-tap), data-deliverable receipts, and
attention-batched readouts. A minimal TUI-keypress surface ships in Phase 1 (so
the escalation loop has a terminus and the kernel stands alone); the phone flow
and richer surfaces come in Phase 2. The genuine novelty is the *privilege
domain* and the human-check-as-outcome-type — the approval-as-protocol-callback
shape is adopted from the studied harnesses, not reinvented (the engine blocks on
a request, fail-closed on timeout). Authenticity is transport, not content: a TUI
keypress, or an authenticated request over the private mesh network from the
phone. The phone leg carries a liveness probe — because a phone VPN can die
silently on an app auto-update — and on failure the channel falls back to a local
surface and surfaces "phone channel down" in the readout, rather than degrading
unnoticed (which would be the design's own stale-world-model failure,
self-inflicted). Timeouts respect real working habits: pending items queue,
unblocked branches proceed, overnight runs batch into the morning readout. Ranked
by severity, batched, never re-reported. *(serves O6, O1)*

### Concurrency, ops, and delivery

**Concurrency.** Sessions take leases (issue, file-set, repo); the scheduler
enforces one-writer-per-file-per-phase and serializes primary-slot ownership
across concurrent sessions on the one GPU; parallel sessions get harness-owned
worktrees whose paths are always surfaced — the founding incident's invisible
worktree becomes unrepresentable, because "where did the bytes land" is a
mandatory envelope field. No ambient single-slot state. *(serves O3)*

**Ops (O8).** The registry/runbook triad goes native: a typed service registry
(inventory + capability grants + destructive-ops list per service), runbooks with
schema'd frontmatter (decay class, last-verified), a decay scheduler that refuses
expired docs — the most literal fit for the *stale-world-model* class in O3 — a
live-state differ (registry vs. actual), and a write-back contract enforced as a
required transition before an ops task closes. Destructive-ops lists
auto-generate their commands' approval policies. The ops lane is co-equal with
the work lane, not a borrowed sub-behavior. *(serves O8, O3, O6)*

**Delivery receipts.** Publish/deliver are typed actions with computed evidence
envelopes: push computes a *reachable-history* diff — what commits and blobs
become public — not the working tree (identifiers once leaked through history that
a working-tree scan called clean); orphan-initial-commit is the default for
open-sourcing. A `deliver` config whose route resolves to nobody is a *tool
error* (a misconfigured deliver target once reached nobody for weeks). Delivered
artifacts get a post-delivery probe at the recipient endpoint, and rendered ones
a human check. *(serves O3, O6)*

---

## The wall-clock model

A model, not a measurement — Phase 0 times the real thing. Panel cost is
`swaps + Σ(bundle_tokens / prefill_rate + verdict_tokens / gen_rate)` per member,
and **batch prefill rate is the single largest unmeasured input** (a named
Phase-0 exit), because prefix caches die on every swap. The table below is valid
for the installed 14 B-class models only; the target 2026 roster (30–80 B MoE,
thinking traces, higher swap cost for RAM staging) trends toward the higher
projections.

| Tier       | Chain                                                                 | installed zoo | target roster (proj.) |
|------------|-----------------------------------------------------------------------|--------------:|----------------------:|
| Trivial    | Direct edit + checks, resident model, no panels                       |      1–3 min  |              1–3 min  |
| Short      | Spec-lite + build + harness checks + CPU jury                         |    10–25 min  |            15–35 min  |
| Full       | Gate 0 + premise panel + architect/editor + checks + audit + human    |    35–90 min  |           60–120 min  |
| Patch farm | k-candidate sampling + test filter + cross-family select              |        hours  |  hours (validation-bound) |

Check time is seconds-to-minutes, repo-dependent (a gradle build is
multi-minute; a patch farm multiplies suite time by k). Replan ping-pong in
architect/editor costs two MoE-class swaps per iteration — budgeted explicitly.
The known runner-wedge health-check runs *pre-swap* (verify VRAM actually freed
before loading), so a wedge costs one restart, not minutes of crawling calls. The
**interactive-tempo latency ceiling** is pre-registered at Phase 0 as the O7
falsifier: exceed it and the interactive value proposition is declared dead
(distinct from relocating work to overnight, which is free). *(accountable to O7)*

---

## Build phases

Kernel first; learning plane last; each phase ends in a **named** dogfood
workload. Security visibility (the operator being auditable, per O1) is present
from Phase 1, not deferred. The kernel (Phase 1) is scoped to stand alone: it
includes a minimal lane router and a TUI-keypress approval surface so its exit
criterion does not depend on later phases.

| Phase | Contents | Exit criterion (dogfood) |
|-------|----------|--------------------------|
| **0 — Measure** | `llama-server` + `llama-swap`; re-measure swap / prefill(batch, 8k+32k) / tok-s / prefix-cache on the real stack; confirm real memory bandwidth; multi-turn soak per hybrid candidate; grammar-vs-plain-text A/B; co-failure matrix across seats; jury-on-CPU latency; time one full-chain dry run; stand up the eval battery; **pre-register the panel thresholds (recall/FP) and the interactive-latency ceiling** | Numbers replace the wall-clock model; roster seats have measured occupants; the grammar and decorrelation questions are settled by data; the two experimental bets have written thresholds |
| **1 — Kernel** | Versioned event ledger + SQLite; typed action layer (argv) + round-trip codec + adapters + prompt-assembly/cache-boundary; sandbox spawner + escalation loop; **minimal lane router (trivial/work/ops split)**; **minimal TUI-keypress approval surface (escalation terminus)**; edit pipeline (cascade + guard + blocking syntax lint + checkpoints); tool inventory; trust-tier tagging; evidence envelopes; headless NDJSON core (interrupt/steer frames) + CLI; **security ledger consumer** | `animal` does real trivial-lane work on a live repo standing alone; every run leaves a replayable ledger with computed envelopes; **the security tap sees `animal` sessions**; **a seeded non-persistence edit and a fabricated deterministic-check pass are each flagged as a tool error, with the ledger showing the catch** (the invariant is verified, not assumed) |
| **2 — State machine** | Full task lifecycle + lane manifests; spec objects + grounding + DoD executor (pinned env, N=3, negative-control + authoring lints); approval service + phone flow + liveness + human-check + data receipts; rejected-artifact registry; delivery receipts; egress proxy; transactional commit | One full-chain task lands end-to-end with human gates over the real channel; a seeded vacuous check is rejected at authoring |
| **3 — Model plane** | VRAM arbiter (phase-aware, tenant-aware) + scheduler; roster seats + quirks table + capability enforcement; context auditor; CPU triage jury + gate panels (probe + enumeration) + candidate-sampling lane | A cross-family panel catches **≥ 80% of ≥ 20 seeded bad premises at ≤ 10% false-positive on ≥ 20 clean controls** (thresholds from Phase 0; miss either → fall back to single-judge + human per Risks); a **distinct sub-exit seeds shared-prior ambiguities** (e.g., a UTC-vs-local day boundary) and measures whether interpretation-enumeration + the data-deliverable receipt surface them; an overnight patch farm completes a batch on a real scoped backlog |
| **4a — Ops + concurrency** | Ops registry/runbooks native; concurrency leases; live-state differ; write-back contract | An ops task run daily executes with write-back enforced |
| **4b — Learning** | Calibration + error taxonomy; lesson upsert/decay + injection + *compilation*; typed incident ledger (existing corpus ingested); read-only inspection CLI/TUI; seeded-defect label loop; plane watchdogs | Routing reads calibration; a compiled lesson blocks a regression on a real diff; gated on Phase 1–3 telemetry actually existing to learn from |

---

## What animal refuses to build

- **No cloud path, anywhere.** Local tags whitelisted; inference verifiably
  egress-free; no share features. *(O1)*
- **No multi-round debate, no LLM-judge tower, no learned router** — independent
  votes, outcome arithmetic, failure-triggered escalation. *(O4)*
- **No model-visible workflow graph.** The model always sees one flat loop;
  harness-side orchestration strategies (single-loop / phased-pair / panel /
  pipeline) are chosen by state, never by the model — a control structure the
  model cannot see is a manipulation surface it cannot game. *(O3)*
- **No portability.** One machine, one kernel, system bubblewrap. *(O7)*
- **No per-message judging, no always-on panels in interactive tempo** —
  precision budgets and attention discipline apply to the machine's own ceremony
  too. *(O6-economy)*
- **Nothing heavier than SQLite.** An 11 MB SQLite file carried the equivalent
  workload with zero operational drama.
- **No speculative scaffolding.** Every phase ends in dogfood on a *named*
  workload; vote-weighting is not built until a calibration cell reaches n ≥ 30;
  the patch farm is not built until it has a real backlog to farm. *(O5)*

---

## Risks and open questions

- **Panel ROI on judgment is the primary experimental bet.** The quantitative
  wins in the literature are for code generation, not premise review. Phase 3's
  pre-registered exit (≥ 80% recall on ≥ 20 seeded bad premises, ≤ 10% FP on
  ≥ 20 clean controls) is the first real test. Fallback if missed: single strong
  judge + human; diversity budget to candidate selection. *(tests O4)*
- **The shared prior is the hardest failure, and it has its own sub-exit.** An
  ambiguity every family resolves identically survives a construct-a-failure
  panel by design; interpretation-enumeration and data-deliverable receipts aim
  at it, and Phase 3's shared-prior sub-exit measures whether they actually
  surface it. If they cannot be tested yet, that is stated rather than implied
  caught.
- **The 2026 model generation is unverified on-box**; every benchmark number is
  web-sourced; memory bandwidth itself is inferred. Phase 0 confirms it. *(O7)*
- **Wall-clock is a model** with prefill as its largest unknown, and the
  interactive-tempo latency ceiling is the O7 falsifier — exceed it and the
  interactive proposition is dead (overnight relocation is not a get-out). *(tests O7)*
- **Grammar-vs-text is genuinely open** — the only measured evidence favors plain
  text for edits; constrained envelopes are well-motivated but locally unproven.
  Phase-0 A/B.
- **Some field-study internals are docs-derived** (one studied harness is
  closed-source); `animal` reimplements documented semantics, copies nothing
  verbatim, and load-bears only on open measurements plus the operating record.
- **No strong Llama-family model is on-box**, so the one published cross-family-
  critic recipe is not directly reproducible; lineage spread across other
  families is the bet, verified by co-failure measurement — directional.
- **Push-approval reverses a prior operator preference** (auto-push chosen for
  convenience under supervised Claude Code). Making push a boundary crossing is
  deliberate for *unattended weak local models* — named here, not silent — and is
  per-lane/per-repo: auto-push after the audit gate for repos under an existing
  grant; approval only for first-push/publish/new-remote.
- **Scope is the meta-risk.** The phases are ordered so the kernel — now scoped
  with its own minimal lane router and approval surface — is independently
  valuable and *verified* (Phase 1's seeded-attack exit) even if nothing else
  ships.

---

## Objective traceability

Every objective is served by named mechanisms; every major mechanism serves an
objective. This is the matrix a consistency review should walk.

| Objective | Primary mechanisms |
|-----------|--------------------|
| **O1 Sovereignty** | local `llama-server` backend, model-source whitelist, egress-free inference, sandbox network-off default, Tailnet-only human channel, content trust-tier tagging + injection screen, security tap from Phase 1, "no cloud path" refusal |
| **O2 Evidence over prose** | Law 1; computed diff envelopes; harness-run DoD (Law 2); artifact-id citation requirement; compaction-taint rule; "no diff = no work"; verified by Phase-1 seeded-attack exit |
| **O3 Structural elimination** | typed argv actions + argv-only shell + round-trip codec (tool-arg + data-rot); read-before-edit invariants + computed diffs (non-persistence); harness-run checks (rubber-stamping); session leases (races); world-fact probes + ops decay scheduler (stale model); delivery receipts + reachable-history diff (misdelivery); model-invisible orchestration (manipulation surface) |
| **O4 Measured diversity** | Law 5; cross-family panels at Gate 0 / audit / candidate-selection; co-failure matrix; ancestry-aware same-family refusal; seeded-defect detection-value calibration; veto/majority aggregation; honest-limits section; pre-registered Phase-3 thresholds |
| **O5 Compounding learning** | the learning plane; calibration table; lesson upsert/decay; lesson→check *compilation*; typed incident ledger; read-only inspection CLI; plane watchdogs; "no speculative scaffolding" gating |
| **O6 Human authority + attention** | Law 4 + human channel in a separate privilege domain + `HUMAN_CHECK` state + liveness probe (*authority*); batched severity-ranked readouts + muse lane + per-gate precision budgets + overnight-oracle deviation default (*economy*) |
| **O7 Fits the machine** | phase-aware VRAM arbiter; CPU-pinned jury; exogenous-tenant awareness; context auditor; wall-clock model + Phase 0 measurement; pre-registered interactive-latency ceiling; tier reassignment fallback |
| **O8 Ops first-class** | typed service registry; decay-tracked runbooks; live-state differ; write-back contract as a required transition; ops lane co-equal with work lane; destructive-ops auto-generated approval policies |

Two tensions are resolved deliberately rather than averaged. **O4 (spend tokens
on diverse judgment)** versus **O6-economy (protect attention) and O7 (fit the
machine):** the interactive triage jury runs on CPU so it costs no VRAM, while
full family panels and the judge seat run on GPU and incur swaps — a cost
deliberately confined to overnight and on-demand escalation where latency and
attention are free; interactive tempo escalates to a GPU panel only on triage
disagreement. And **O2 (evidence) subordinates O4 (diversity)** everywhere they
meet: the founding incident is caught by computed evidence, not by a panel, and
the plan says so in its own thesis. Ops (O8) and the two human sub-goals of O6
are the objectives this v3 promoted from implicit to first-class after the
consistency red-team found them under-represented.

---

## Provenance

This plan is synthesized from eleven adversarially fact-checked research tracks
(field study of Claude Code / Codex CLI / OpenCode from documentation and source;
the current state of local inference sized to this hardware; and the literature on
model-diversity as a reliability strategy), a review of the operating record
itself (the verification chain, the product database, the hallucination-incident
corpus, and the Resonance engine), a 522-check corpus audit of real
definition-of-done checks, and two adversarial red-team passes — a five-lens
critique of the design (VRAM feasibility, lesson coverage, architecture soundness,
fit, and a dedicated panel-design red-team) and a five-lens consistency/logic
audit of this plan against its own objectives.

Corrections already applied from fact-checking: a cross-family-critic training
figure (~21K trajectories, not 80K); long-horizon-decay citations remapped;
studied-harness hook-event counts corrected; the empirical span stated honestly
as three months (not "two years"); the VRAM residency arithmetic reworked after
it failed to close; the learning plane's advisory-only delivery corrected to add
compilation; injection defense and delivery receipts given owners; and the panel
motivation restated so it does not claim credit for catching the founding
incident (which evidence, not diversity, catches).

Corrections applied from the consistency red-team (this v3): the evidence half of
the thesis reclassified as a verified invariant (with a Phase-1 seeded-attack
exit) rather than a shielded hypothesis; ops promoted to a first-class objective
(O8); O6 named to cover both human authority and attention; the CPU-vs-GPU juror
contradiction resolved (CPU only for the interactive triage jury; GPU panels
priced in swaps, confined to overnight/escalation); the kernel re-scoped with a
minimal lane router and approval surface so Phase 1 stands alone; panel exit
thresholds pre-registered; the argv-only-shell contradiction closed; judge seats
ranked on detection value from day one (not raw pass-rate at cold-start); and the
Resonance moment-schema and read-only-inspection claims mapped to concrete
mechanisms.

Claims that remain **directional** — flagged wherever they appear — are the 2026
model-generation benchmarks (web-sourced, unverified on-box), the wall-clock
projections (a model pending Phase-0 measurement, with prefill as the dominant
unknown), and the lineage-spread bet (no strong Llama-family model on-box, so the
one published recipe is not directly reproducible).

The design is deliberately falsifiable where it makes a bet and deliberately
verified where it states an invariant: the risks section names the exits with
pre-registered thresholds, and the phasing guarantees the kernel is worth
building — and provably correct on the founding-incident class — even if the
diversity thesis does not survive contact with measurement.
