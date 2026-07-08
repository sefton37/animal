# animal — Roadmap: the local agentic software studio

> The app you **talk to** to make games and personal software — on your own machine.

**Epic [#32]** in the product DB · builds on the engine (**epic #31**, phases 0–4) · **229 story points** across **41 stories** · 8 milestones.

## What animal becomes

animal codifies three things Kel already runs into **one sovereign local app**:

- **Talking Rock product DB** → the backlog: epics, user stories, specs, machine-checkable DoD, **Fibonacci** story points, velocity, commit tracking.
- **Claude Code infrastructure** → the agentic engine: the flat loop, typed tools, and the **gated, deterministic, verified + audited, test-driven** verification chain — on **local LLMs**.
- **Resonance** → learning from **verified outcomes**: estimate accuracy, calibration, lessons compiled into checks.

**The lifecycle:** you *converse* through a discovery process that surfaces user stories and forms epics → animal *sizes* them in Fibonacci and prioritizes → it *executes* each through the gated TDD chain → iterating against a *deadline* (when you'll review) → you *review* harness-computed evidence → it *learns*.

## The arc, engine → app

animal today (verified on disk 2026-07-07, `~/dev/animal`) is a proven engine, not yet a product: Phases 0-4 are complete and 38 tests are green — an evidence-native kernel (ledger + shadow-git diffs), a human-gated work-lane state machine, cross-family judge panels measured at 95% recall / 0% FP, a patch-farm generator, and a learning plane that routes on real calibration and compiles lessons into regression-blocking checks. But there is no product DB, no conversational front door, and no app a maker opens — the M1-M8 roadmap is the second build, turning that engine into the single `python3 -m animal.cockpit` the framing describes. Every milestone's "builds on" claim checked out against the actual repo this session: config.py:28's `MAX_EDIT_RETRIES = 3` genuinely has zero other references anywhere in the tree; workspace.py's `_locate` cascade is genuinely just two tiers (exact match, then whitespace-normalized regex) rather than the richer cascade the milestone names; and worklane.py:91 genuinely auto-transitions `task.transition("done" if all_pass else "needs_human")` with no human in the loop today. These are real gaps, not invented ones.

M1 (coder-quality floor) and M2 (product-spine) belong at the front and are largely independent of each other, which is why they form the first sprint together. M1 hardens the exact loop.py/workspace.py/model.py that every later milestone's automated writing routes through — the product-owner's spec drafting (M3), the TDD implementer (M3), the sprint runner (M6) all inherit whatever reliability M1 buys or fails to buy. M2 embeds the Talking-Rock-shaped product DB (epics, stories, specs, DoD checks, commit links) that becomes the one substrate M4, M5, M6, M7, and M8 all need to persist into — provided the roadmap resists a temptation visible in the JSON itself: M4, M5, M6, and M8 each independently describe building a "new" backlog/story store rather than extending M2's. Left uncorrected, that is exactly the class of orphaned/duplicated-wiring failure this project's own hallucinations.md catalogs repeatedly; the single highest-leverage correction in this roadmap is enforcing "extend M2's productdb.py" at each of those milestones' spec-authoring time, not discovering the drift at M8 integration.

M3 is the true critical-path gate. It upgrades today's plain `worklane.run_work` into a fully composed `run_tdd_work` — product-owner drafts, tester writes red, implementer goes green, verifier records calibration, auditor red-teams before done — and this composed chain is literally what M6's sprint runner iterates against a deadline. M4 (discovery) and M5 (sizing) have no hard code dependency on M3 and can develop in parallel with it, but both need M2's spine already in place to persist into. M6 then turns the gated engine into the actual "iterate against a deadline, maker reviews" lifecycle the project is named for, and M7 closes the loop the learning-plane thesis depends on by replacing worklane.py's confirmed-live auto-approval bypass with a real human gate wired into calibration and lesson-compilation.

M8 is rightly last: it contributes almost no new engine capability and is instead a UI shell over four things that must already work standalone — the product DB, discovery, the running-work ledger projection, and the review-queue approval flow — unified behind one command. Its own exit criterion (`test_cockpit_e2e.py` driving all four panes in one run, including unblocking a backgrounded `run_work` through a review-pane approval) is the load-bearing proof that M2 through M7 actually compose into one app rather than four disconnected demos, which is exactly why nothing before it should be allowed to skip real integration in favor of an isolated fixture.

## Milestones (build order)

| # | Milestone | Stories | Points | Exit criterion (machine-checkable) |
|---|-----------|:------:|:-----:|------------------------------------|
| M1 | M1-execution-craft | 6 | 39 | From /home/kellogg/dev/animal, every existing Phase 1-4 test plus all six new M1 test file… |
| M2 | M2-product-spine | 6 | 21 | `python3 tests/test_product.py` prints 'N tests PASS' with zero failures (mirrors the exis… |
| M3 | M3-gated-tdd-chain | 5 | 37 | `animal.worklane.run_tdd_work(user_story, repo, approver=...)` drives one story through th… |
| M4 | M4-conversational-discovery | 5 | 26 | `cd ~/dev/animal && python3 -m pytest tests/test_discovery_e2e.py -q` exits 0 and reports … |
| M5 | M5-fibonacci-sizing | 6 | 18 | From ~/dev/animal: `for f in tests/test_backlog.py tests/test_poker.py tests/test_estimate… |
| M6 | M6-timeboxed-sprint | 6 | 29 | From a clean checkout: (1) `cd ~/dev/animal && python3 -m pytest tests -q` exits 0 with 0 … |
| M7 | M7-review-learning-loop | 4 | 18 | From ~/dev/animal: (1) `python3 tests/test_phase5.py` exits 0 and defines >=10 `test_` fun… |
| M8 | M8 | 6 | 52 | A single command `python3 -m animal.cockpit` opens the one app. Verify: `for f in tests/te… |

> The **sovereign product store is built once in M2**; M4/M5/M6/M8 depend on it (3 redundant rebuild-stories from the raw decomposition were folded into M2).

## Recommended first sprint — worked one by one

Dependency-correct order; the coder-quality floor (M1) and the product spine (M2) come first.

1. **[#445]** Blocking syntax lint gate on the edit pipeline
2. **[#448]** Rollback-and-resample after repeated failed edits on a target
3. **[#450]** Loop hygiene: stuck-action detection and bounded observation history
4. **[#451]** Embed a sovereign product-store schema (epics/stories/specs/spec_checks/commit_links)
5. **[#452]** Epic + Story CRUD with Fibonacci-validated story points
6. **[#446]** Genuine multi-strategy fuzzy-apply cascade with an ambiguity guard
7. **[#453]** Persist Spec + DoD checks 1:1:N against a story, round-tripping the existing Spec/DoDCheck dataclasses
8. **[#?]** Import a hand-written Spec-shaped JSON file into the backlog

## Critical path

- M1 — Blocking syntax lint gate on the edit pipeline (first hard floor under every future edit; dep of story 2 in the same milestone)
- M1 — Rollback-and-resample after repeated failed edits on a target (activates config.py:28's MAX_EDIT_RETRIES=3, confirmed today via grep to have ZERO call sites; without this, every unattended downst
- M2 — Embed a sovereign product-store schema (epics/stories/specs/spec_checks/commit_links) — the one substrate M4/M5/M6/M7/M8 all read or write; must be built once here
- M3 — Product-owner role → TDD red-green → End-to-end TDD chain composition (run_tdd_work) — this IS the engine M6's sprint runner iterates; nothing after M3 can run unattended without it
- M6 — Deadline-fitting scheduler → Sprint runner (iterates the M3 chain against a scheduled queue) — turns a gated engine into the 'iterate against a deadline' lifecycle stage the product is named for
- M7 — Maker review gate on harness-computed evidence — removes the auto-approval bypass confirmed live today at worklane.py:91 (`task.transition("done" if all_pass else "needs_human")`); until this lan
- M8 — Persist epics/issues/specs in the cockpit's product DB → Launch the one-app cockpit shell (the other four M8 stories all declare this pair as their direct dependency)

## Risks (from synthesis)

- Quadruple product-DB duplication: M2, M4 (story 2), M5 (story 1), M6 (story 1), and M8 (story 1) each independently describe building a 'new' backlog/story/product-DB store instead of extending M2's. Built literally, the cockpit (M8) would have to reconcile 3-
- M7's exit requires removing a currently-live auto-approval bypass (confirmed today: `worklane.py:91` `task.transition("done" if all_pass else "needs_human")`). Earlier milestones' own tests/fixtures (M2 story 4, M3's composition) may implicitly assert `state =
- M1's heaviest story, the per-model edit-format registry (13 pts), touches TURN_SCHEMA/SYSTEM_PROMPT/ROLES/EditAction simultaneously — the same surface Phase 3's panel.py judge seats depend on for constrained JSON. Panel tests are offline-scored on canned respo
- M5's live planning-poker panel repurposes panel.py's boolean-shaped premise-review aggregation (any/majority) for a different task — numeric Fibonacci consensus — that was never part of the Phase 3 measurement (95%/0% FP was on soundness flags, not point estim
- Scope/ceremony creep: 240 points across ~44 stories is large for a solo-maker sovereign tool the project's own memory explicitly frames as 'an EXPERIMENT, not a product — no roadmap promises.' Committing the full M1-M8 backlog up front risks exactly the ceremo
- test_phase5.py is independently specified by both M3's exit (must exist, must pass, accumulates GATE-sequence assertions) and M7's exit (must exist with >=10 test_ functions matching test_phase4.py's pattern). If M3 and M7 are built by different sessions witho
- M8's heaviest single story ('Turn discovery conversation into backlog stories', 13 pts) substantially overlaps M4 (conversational discovery, 26 pts total) inside the UI layer. Estimated at 13 points it likely assumes reuse of M4's flow; if built as a second im

## Full backlog


### M1-execution-craft — Close the ACI (agent-computer-interface) gap the field-scan measured and that Phase 1-4 explicitly deferred: make the re

- **[#445] Blocking syntax lint gate on the edit pipeline** — `3 pts`  
  As a maker, I want an edit that would break a file's syntax rejected before it ever lands on disk, so the coder cannot silently corrupt a working file and then spend its remaining turns compounding a break it doesn't know it made.
- **[#446] Genuine multi-strategy fuzzy-apply cascade with an ambiguity guard** — `5 pts`  
  As a maker, I want the edit pipeline to still find my model's intended anchor when its old_string differs only by whitespace/indentation from the real file, so small, cosmetically-imperfect edits from a local model land instead of bouncing forever as 'old_string not found' - but I want it to refuse, not guess, when the fuzzy match is ambiguous between two candidate spots.
- **[#447] Per-model edit-format registry (fenced-text dialects, not JSON-escaped patches)** — `13 pts`  
  As a maker, I want each resident model to emit its edit in the plain-text patch format it's actually measured to be good at (search-replace fenced block, unified diff, or whole-file) instead of JSON-escaping a multi-line code patch inside old_string/new_string fields, so the coder stops failing edits on escaping/quoting bugs instead of real logic errors - the exact failure mode the field-scan measured and phase1/README.md's own 'Deferred to later phases' section names as still missing ('native per-model dialect adapters beyond the JSON protocol').
- **[#448] Rollback-and-resample after repeated failed edits on a target** — `5 pts`  
  As a maker, I want the loop to auto-revert to the last good checkpoint and force a fresh attempt after a small number of consecutive failed edits on the same file, rather than let the model keep guessing against a target it may not even understand is broken, so a stuck coder doesn't compound errors turn after turn until the whole turn budget is gone.
- **[#449] Tree-sitter (with AST fallback) repo map for file/symbol discovery** — `8 pts`  
  As a maker, I want the coder to see a compact map of the repo's files and top-level symbols before it starts, so it can ask to read the right file by name/symbol instead of guessing paths blind and burning turns on wrong reads.
- **[#450] Loop hygiene: stuck-action detection and bounded observation history** — `5 pts`  
  As a maker, I want the loop to notice when the model repeats the exact same failing action over and over, and to keep the message history from growing without bound by condensing older tool outputs, so a stuck small model doesn't silently burn its whole turn budget on one dead end and doesn't eventually overflow its own context window mid-task.

### M2-product-spine — Give animal a sovereign, embedded, local backlog store — epics -> stories -> specs -> DoD checks (Talking-Rock-shaped: F

- **[#451] Embed a sovereign product-store schema (epics/stories/specs/spec_checks/commit_links)** — `2 pts`  
  As a maker, I want animal to open (and idempotently migrate) a local var/product.db with epics/stories/specs/spec_checks/commit_links tables so my backlog has a durable, sovereign home before any CRUD or projection code touches it.
- **[#452] Epic + Story CRUD with Fibonacci-validated story points** — `3 pts`  
  As a maker, I want to create epics and stories with a Fibonacci-only story_points field, a status, and a priority so sizing follows the same discipline CLAUDE.md already names (1/2/3/5/8/13/21; big/uncertain work is 13+) and I can list/filter my backlog.
- **[#453] Persist Spec + DoD checks 1:1:N against a story, round-tripping the existing Spec/DoDCheck dataclasses** — `5 pts`  
  As a maker, I want to attach one Spec (with its N DoD checks) to a story and load it back byte-for-byte into the SAME Spec/DoDCheck objects worklane.py already runs, so my backlog store replaces hand-authored Python Spec construction without changing Gate 0 or the worklane at all.
- **[#454] Run a backlog story through the unmodified worklane and write its verified outcome back** — `5 pts`  
  As a maker, I want to pick a story off the backlog and run it through the EXISTING gated worklane (grounding -> DoD authoring -> human approval -> build -> harness-verified DoD) so the story's status, timestamps, and a link to the harness evidence that proved it are recorded, without changing worklane.py's contract at all.
- **[#455] Velocity and backlog-report projections, surfaced read-only in the CLI** — `3 pts`  
  As a maker, I want a velocity() projection (story points completed in a trailing window) and a status/priority backlog report so I can see throughput and what's next, the same read-only-inspection way `animal learn` already exposes calibration/lessons/incidents.
- **[#456] Import a hand-written Spec-shaped JSON file into the backlog (replaces ad-hoc Python Spec() construction)** — `3 pts`  
  As a maker, I want to point animal at a JSON file shaped like Spec.to_dict() (title/epic/story_points/priority plus the spec fields) and have it create the epic if new, the story, and attach the spec+DoD checks in one step, so a backlog entry is always born in the store, never as a throwaway Python object in a test file.

### M3-gated-tdd-chain — Close the three gaps phase2/3/4 explicitly left open (hand-authored specs, no TDD, no verifier/auditor gates) by extendi

- **[#457] Product-owner role: model-authored Spec+DoD from a raw user story** — `8 pts`  
  As a maker, I want a product-owner role to turn a plain-language user story into a Spec (intent, out-of-scope, argv-based DoD checks) itself, so that I stop hand-writing DoDCheck objects for every piece of work while the existing Gate-0 grounding/authoring-validation chain still catches a bad spec exactly as it does today.
- **[#458] TDD red-green: tester writes a failing test before the implementer runs** — `13 pts`  
  As a maker, I want a tester role to write a failing test BEFORE any implementation code exists, with the harness proving RED, so that the implementer is provably solving a real falsifiable problem instead of a check that could have passed by accident.
- **[#459] Verifier gate: record claimed-vs-verified task completion into calibration** — `3 pts`  
  As a maker, I want the harness to record whether the implementer's own claim of being finished actually matched the harness-verified DoD result, so the learning plane can route future work away from models that claim success when the evidence disagrees — without the model's claim ever deciding the gate itself.
- **[#460] Auditor gate: fresh DoD re-run + cross-family red-team before done** — `8 pts`  
  As a maker, I want a cross-family auditor to independently re-run every DoD check from scratch and red-team the checks against the user story before a task is allowed to reach done, so a chain that passed every mechanical check still gets a second, adversarial, distinct-lineage look before I trust it.
- **[#461] End-to-end TDD chain: compose product-owner through auditor into one dogfood run** — `5 pts`  
  As a maker, I want one function call that runs product-owner -> tester(RED) -> implementer(GREEN) -> verifier -> auditor -> done for a single story, in one ledger, so the whole gated TDD chain is something I can point at a real bug and watch happen, not five separate pieces I have to wire myself.

### M4-conversational-discovery — Give the maker a conversational front door to animal: a bounded, ledger-audited dialogue that elicits individual user st

- **[#462] Bounded conversational discovery loop elicits raw stories** — `5 pts`  
  As a maker, I want to talk to animal about an idea in a back-and-forth dialogue so that it draws individual user stories out of me without me having to write them myself.
- **[#463] Cluster raw stories into epics and persist to a product-DB projection** — `5 pts`  
  As a maker, I want the stories I mention in one sitting to come back grouped into a real epic (not a flat list) so that animal's backlog reflects how I actually think about a feature or game.
- **[#464] Draft a grounded, Gate-0-valid Spec from a raw story via the architect role** — `5 pts`  
  As a maker, I want each raw story I mention to come back as a real Spec with a clear user story, explicit scope boundaries, and machine-checkable Definition-of-Done checks so that it can go straight into animal's existing approve-and-build pipeline without me writing DoD checks by hand.
- **[#465] Surface and resolve scope ambiguity before finalizing a story** — `3 pts`  
  As a maker, I want animal to ask me about the ambiguous parts of what I said (units, boundaries, what is explicitly out of scope) so that the DoD it writes matches what I actually meant, not its best guess.
- **[#466] End-to-end: one open-ended sentence yields a real Epic with grounded, approvable stories** — `8 pts`  
  As a maker, I want to say one open-ended sentence about a game or app idea and have animal come back with a real epic full of concrete, checkable stories -- ready for me to review and approve -- so that discovery is the actual front door to building, not a separate manual step.

### M5-fibonacci-sizing — Give animal the ability to size and prioritize its own backlog. A new Story/backlog data model holds candidate work item

- ***(folded into M2)* Add Story data model and backlog store** — `3 pts`  
  As a maker, I want a lightweight Story object and a persistent backlog store so that animal has somewhere to hold candidate work items before they become full Specs.
- **[#467] Run a diverse-model planning-poker panel for Fibonacci sizing** — `5 pts`  
  As a maker, I want independent Fibonacci estimates from decorrelated model families for a story so that the estimate reflects diverse judgment rather than one model's opinion (the diversity thesis, O4, applied to estimation instead of premise review).
- **[#468] Escalate high-disagreement estimates to the human channel** — `3 pts`  
  As a maker, I want the panel's disagreement to be resolved by escalating to me, not by letting the models debate each other, so that convergence stays a human decision (O6) and never violates the architecture's explicit 'no multi-round debate' refusal.
- **[#469] Persist panel estimates for future calibration matching** — `2 pts`  
  As a maker, I want every seat's vote and the converged size recorded durably so that a later milestone can compare estimated vs actual effort and feed animal's existing calibration table (Phase 4), closing the sizing loop without animal having to guess at verified-truth today.
- **[#470] Compute value/effort prioritization order for the backlog** — `2 pts`  
  As a maker, I want the backlog ordered by value against effort so that I can see which stories are the best bets to work next, without having to eyeball a flat list.
- **[#471] Wire animal size and animal backlog CLI commands end-to-end** — `3 pts`  
  As a maker, I want to run `animal size <story-id>` and `animal backlog` from the command line so that sizing and prioritization are actually usable, not just library functions.

### M6-timeboxed-sprint — Given a review deadline, animal turns a prioritized, Fibonacci-pointed backlog of already-Approved-or-approvable specs i

- ***(folded into M2)* Local backlog store with Fibonacci points and priority** — `3 pts`  
  As a maker, I want animal to remember each story's Fibonacci size and priority alongside its (existing) Spec, so that a scheduler has something concrete to select from instead of a folder of hand-authored spec files with no ranking.
- **[#472] Velocity tracker derived from ledger timestamps** — `3 pts`  
  As a maker, I want animal to measure how long a given story-point size actually took by reading the harness's own ledger timestamps (never a model's claim or a wall-clock the caller measured), so that the scheduler can convert 'this is a 5' into a real time estimate that gets more honest with every completed story.
- **[#473] Deadline-fitting scheduler (priority + points + velocity)** — `5 pts`  
  As a maker, I want animal to pick, in priority order, exactly the stories that measured velocity says will fit in the time before my review, so that I get a queue I can trust instead of animal starting a story it can't possibly finish and leaving me with nothing reviewable.
- **[#474] Sprint runner: iterate the M3 chain against the scheduled queue** — `8 pts`  
  As a maker, I want animal to actually run the existing gated verification chain (Gate 0 -> human approval -> build -> verify) on every story the scheduler selected, one after another, stopping cleanly at the deadline rather than getting interrupted mid-build, so that a sprint produces real done/needs_human/rejected outcomes I can trust -- not a model's summary of progress.
- **[#475] Review package assembly + `animal sprint` CLI** — `5 pts`  
  As a maker, I want one command that runs a whole sprint against a deadline and hands me back a single reviewable artifact -- here is what I finished, here is what I could not, and why -- so that reviewing animal's overnight work takes minutes, not a ledger archaeology session.
- **[#476] Dogfood: live sprint run and Phase 5 exit writeup** — `5 pts`  
  As a maker, I want to see animal actually run a real deadline-boxed sprint against real specs on real hardware -- not just pass an offline test suite -- so that I can trust the 'here is what I finished, here is what I could not' package before I rely on it unattended overnight, matching every prior phase's discipline of ending in a measured, written-up dogfood run.

### M7-review-learning-loop — Close lifecycle steps 5 (maker REVIEWS) and 6 (system LEARNS) on top of the already-built engine (phases 0-4, ~/dev/anim

- **[#477] Maker review gate on harness-computed evidence** — `5 pts`  
  As a maker, I want every completed build to stop and show me the harness-computed evidence (DoD pass/fail table, real diff stat, turns taken) and require my explicit accept/reject/comment before the task is marked done, so that nothing I never looked at gets called finished.
- **[#478] Wire the maker's accept/reject verdict into calibration and lessons** — `5 pts`  
  As a maker, I want my accept or reject decision (not the harness's raw DoD pass/fail) to be the thing that reinforces a lesson into a standing regression check or contradicts it and files an incident, so that the learning plane only compounds on outcomes I actually verified, and my rejections become the recurring-failure record the auditor incident file already asks for.
- **[#479] Panel vote-weight from calibration (close the named Phase-4 deferral)** — `3 pts`  
  As a maker, I want the cross-family premise panel to weight each judge seat's vote by that seat's own measured verified-track-record (not count every seat equally), so that a seat proven wrong more often (gpt-oss: 27/40, Wilson-lower 0.520) doesn't get the same say as one proven right almost every time (mistral: 39/40, 0.871) -- the exact gap phase4/README.md names as deferred.
- **[#480] Estimate-vs-actual-effort: the sizing-calibration foundation** — `5 pts`  
  As a maker, I want to attach a Fibonacci point estimate to a spec and have the harness record a computed (not self-reported) actual-effort number against it when the work finishes, so that over time I can see how my estimates track reality per point-bucket -- the substrate a future sizing/discovery feature will read, without this milestone having to build that feature itself.

### M8 — Ship the first UI `animal` has ever had: one local, offline app the maker opens that ties together the four surfaces nam

- ***(folded into M2)* Persist epics, issues, and specs in a local product DB** — `5 pts`  
  As a maker, I want animal to keep its own local epics/issues/specs store so the cockpit has one durable, sovereign backlog to read and write instead of the ephemeral in-memory Spec objects `worklane.run_work` uses today (confirmed in animal/spec.py + animal/worklane.py: a Spec exists only as a Python object passed into run_work and a few summary fields in ledger GATE payloads — there is no cross-session table of epics/issues/points/status anywhere in the repo).
- **[#481] Launch the one-app cockpit shell with four navigable panes** — `8 pts`  
  As a maker, I want one command that opens a single app window with four panes — Conversation, Backlog, Running Work, Review — so animal stops being four disconnected entrypoints (cli.py's `run`/`learn` subcommands, human.py's blocking `input()` TUI prompt) and becomes the one thing I open.
- **[#482] Edit the backlog board (epics/stories/points/status) in-app** — `5 pts`  
  As a maker, I want to see and edit my epics/stories/points/status inside the cockpit so I can triage and prioritize without leaving the app or hand-editing SQLite.
- **[#483] Turn discovery conversation into backlog stories** — `13 pts`  
  As a maker, I want to talk through a game/software idea with animal in one pane and have it turn our conversation into real backlog epics and stories, so discovery doesn't require me to hand-author Spec objects the way every prior phase's tests do (tests/test_phase2.py constructs `Spec(...)` directly in Python).
- **[#484] Surface in-flight work state from the ledger** — `8 pts`  
  As a maker, I want to see which backlog items are currently mid-build, and at which gate, inside the cockpit — so I don't have to `grep`/tail NDJSON ledger files by hand (animal/var/ledger/*.ndjson) to know what animal is doing right now.
- **[#485] Approve and resume needs-human work from a review queue** — `13 pts`  
  As a maker, I want a pending-approvals queue and a needs-human review flow inside the cockpit, so approving a build or resolving a failed verification is one screen action instead of babysitting human.py's blocking terminal `input()` prompt, and a `needs_human` task isn't a dead end (task.py's own `_ALLOWED` dict already declares `needs_human -> {done, rejected, building}` as legal transitions, but no code path in worklane.py ever drives them — run_work is a single linear function that stops at needs_human).
