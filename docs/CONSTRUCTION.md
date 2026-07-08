# animal — The Construction & the Human Loop

Three lenses on one system, and only the first is narrated in lived order. **Part I**
is the loop you *live* as a maker, act by act, in the order you experience it. **Part II**
is the machinery underneath — the anatomy of a turn and the mechanisms that guide every
turn the harness takes (an engine lens, because the prompt also demands the construction
be spelled out). **Part III** is the build sequence — ordered by engineering dependency
to *construct* that lived loop, which is deliberately **not** the human's encounter order.

One thesis holds throughout: **the harness computes and appends reality; you set the
intent and the clock; the local LLMs only ever propose, within gates.**

---

## Part I — The Human Loop (what you live, in order)

You sit down with a pain point and leave, at an agreed time, with reviewed work. Four
acts, strictly in sequence.

### Act 1 — Discovery: a pain point becomes a shaped story

You arrive with a pain or an idea — *"I want a game where…", "this thing I do by hand
is miserable."* animal **converses** (it does not interrogate) to decompose the idea
into the only three things that make work buildable and checkable:

- **The pain** — what is wrong, or what you want that you don't have.
- **The input** — what goes in: the data, the trigger, the starting state.
- **The expected output** — what *good* looks like. This is the seed of the acceptance
  criteria; a story is not shaped until its output is concrete enough to test.

The conversation crystallizes into one or more **user stories** ("As a maker, I want
X so that Y") and groups them into an **epic** — the game, the tool, the thing. Where
the idea is ambiguous, animal **surfaces the ambiguity and asks**, rather than guessing;
and every noun it commits to is grounded against reality (a file, a symbol, a data
source that must actually exist). Discovery ends when *input → expected output* is
sharp enough to become a test.

### Act 2 — Formalization: a story becomes a gated contract

With the LLMs' help, the shaped story hardens into a contract the machinery can execute:

- **Spec** (the product-owner role): intent decomposition, an explicit *out-of-scope*,
  and a **Definition of Done** where each acceptance criterion is a **machine-checkable
  command with a deterministic expected result** — not prose.
- **Gate 0** rejects a *vacuous* DoD: a check that already passes before any work is done
  proves nothing, and is refused at authoring time.
- **Sizing**: a **diverse-model planning-poker panel** assigns a **Fibonacci** point value
  (1/2/3/5/8/13/21). Wide disagreement between the models is surfaced — and escalated to
  you — rather than averaged away.
- **The clock is set**: you and animal agree a **finish time** — when you will next
  review. From here on the scheduler holds the work to that clock.

Now the contract exists: *user story + spec + DoD + size + deadline*. The gates are armed.

### Act 3 — Execution: the harness acts out the cycle

The gated, test-driven cycle runs — each gate a **hard transition**, no role able to act
out of turn:

1. **product-owner** — the spec + DoD from Act 2.
2. **tester** — writes the **failing tests first** (TDD *red*): the DoD made executable.
3. **implementer** — makes them pass (TDD *green*): the many-turn edit loop.
4. **verifier** — claimed-vs-**verified**, the result recorded into calibration.
5. **auditor** — re-runs **every DoD check from scratch**, distrusting the verifier, plus a
   cross-family red-team ("construct a failure that passes every check but violates the
   story"); it can **halt**.

Throughout every one of those turns, the harness **constantly appends reality** — each
action's *computed* diff, each check's *real* exit code — to an append-only ledger, and
**reinforces** it: the model on the next turn always sees what actually happened, never
its own hopeful narration. And all of it is **paced against the clock**: the scheduler
sizes the run to the agreed finish time by story points and measured velocity, and as the
deadline nears it stops starting new work, finishes what is in flight, and assembles the
review package.

### Act 4 — Review & Learning: you look, it learns

At the finish time animal hands you a **review package**: *done* vs *not-done*, each item
backed by **harness-computed evidence** — the real diff, the real check results — not a
prose report. You **accept / reject / comment on the evidence**. The system then **learns
from the verified outcome**:

- estimate-vs-actual → **better sizing** next time,
- per-model/role outcomes → **better routing** and panel vote-weight,
- recurring failures → **lessons compiled into standing checks** that block the mistake
  from ever silently recurring.

The next loop is measurably smarter. That is the whole machine, from the human seat.

---

## Part II — The Construction: the turns beneath the loop

Everything in Part I is produced by **one primitive repeated: the turn.** Understanding
animal *is* understanding what happens in a turn and what guides it.

### The anatomy of a single turn

1. **Assemble context** (harness-controlled, deterministic). The harness — not the model —
   decides what the model sees this turn: the **spec/DoD** (the contract), the **current
   computed reality** (files touched, the running diff, the last check results), the
   **relevant lessons** injected by path/trigger, the **repo map**, a **bounded, condensed
   observation history** (last-N turns; older ones summarized), and the **clock** (turns
   and wall-time remaining against the deadline).
2. **Propose one typed action.** The model emits **exactly one** action —
   `read / grep / edit / shell / finish` — in a constrained per-model format. It *proposes*;
   it does not act.
3. **Guard before acting.** The harness validates the proposal: **read-before-edit**
   (staleness), the **lint/syntax gate** (an edit that would break the file is rejected
   *before it lands*), the **disproportionate-match** guard, and **capability-follows-state**
   (can this role even write in this phase?).
4. **Execute and compute reality.** The harness applies the action in the sandbox against
   **shadow-git** and **computes the envelope** — the *real* diff, the *real* exit code,
   the *real* match location. The model's narration of what it did is discarded; the harness
   owns what happened. **This is the trust boundary**, pushed as far toward computed
   evidence as it will go.
5. **Append to the ledger.** The action + its computed envelope are appended to the
   **append-only NDJSON ledger** — the immutable record of reality. Nothing rewrites it.
6. **Detect pathology.** **Loop/stuck detection** (repeated identical actions or repeating
   content n-grams — mandatory for small models), **non-persistence detection** (a claimed
   edit that did not actually land), and the **budget check** (turns / tokens / wall-clock
   against the clock).
7. **Recover, don't dig.** After repeated failed edits on a target, **roll back to the last
   good checkpoint and resample fresh** rather than letting the model compound a dead end
   (agents "succeed fast and fail slow" — early kill beats persistence).
8. **Feed reality forward.** The computed envelope becomes the next turn's observation. The
   model is *conditioned on what is true*, so it cannot proceed on a fiction.
9. **Advance the gate.** When a phase's **computed** exit condition is met (spec authored /
   tests written-and-failing / tests passing / verified / audited), the state machine
   transitions to the next role. Capability follows state.
10. **Check the clock.** Every turn, elapsed vs the agreed finish time. The scheduler
    decides: continue, wrap this story, or stop and assemble the review package.

### The anatomy of a discovery turn

Discovery (Act 1) is a loop of the *same* primitive with different actions and a different
ground truth — so "conversational" is **constructed**, not merely asserted. Each discovery
turn:

1. **Assemble the partial contract.** The harness shows the model the conversation so far,
   the current *partial* decomposition (whichever of pain / input / expected-output are
   filled), and the results of any grounding run.
2. **Propose one move.** The model emits exactly one of: a candidate *pain / input / output*
   triple (or a refinement of one slot), a **targeted clarifying question** when a slot is
   under-determined, or `finish` when the story is shaped. It proposes to the human; it does
   not decide.
3. **The human supplies the observation.** The maker's reply is this turn's observation —
   in discovery the **human is the ground truth of intent**, exactly as the computed
   envelope is the ground truth of execution. The harness never invents the maker's answer.
4. **Ground every committed noun.** Any file / symbol / data source the decomposition names
   is resolved against the real repo; an unresolved noun is surfaced, not assumed.
5. **Check the exit condition.** The turn advances toward *shaped* only when
   *input → expected-output* is concrete enough to compile into a test — the same evidence
   standard the execution loop enforces, applied at the front door.

The two loops share the spine (one move per turn, grounded, exit on a computed condition)
and differ only in **who supplies the observation** — the human in discovery, the computed
envelope in execution. That symmetry is why discovery is a first-class part of the harness,
not a chat bolted onto it.

### The mechanisms that guide the turns (named, so none is implicit)

- **The contract guides *purpose*.** The spec/DoD is what the turns serve; "finished" is
  defined as *the DoD checks are computed green*, not the model claiming done.
- **The gate state machine guides *who and when*.** `draft → grounded → approved → building
  → verifying → done`; each transition fires only on a harness-computed condition; a role's
  write capability is switched off outside its phase.
- **Context assembly guides *what the model knows*.** The harness curates every turn's
  window — reality + lessons + repo map + condensed history — so a weak local model spends
  its tokens on the task, not on rediscovering state. Older observations are condensed by
  deterministic truncation to the harness-computed facts (diffs, exit codes), never by
  re-narrating them — so condensing never smuggles back the prose the harness distrusts.
- **The envelope guides *truth*.** Computed reality overwrites narration every turn — the
  native fix for the founding failure (three models agreeing on a fiction).
- **The ledger guides *memory*.** Append-only; the product DB, calibration, and lessons are
  all **projections** of it, never separate sources of truth.
- **The guards guide *safety of the step*.** Lint (reject a syntax-breaking edit before it
  lands), staleness (read-before-edit), the **disproportionate-match** guard (an edit whose
  matched span or count far exceeds the intended target is refused as over-broad and likely
  destructive), non-persistence detection, and loop-detection — each can reject a step
  before it corrupts state or burns the budget.
- **Architect→editor phasing guides *quality*.** A reasoning model plans the approach
  (GPU phase 1, loaded then unloaded), then the coder acts out the edits over many turns
  (GPU phase 2) — phase-major on a single 16 GB GPU, which also dodges the runner-wedge on
  this machine.
- **The clock guides *pace and stopping*.** See below.

### How reality is "constantly appended and reinforced"

Two timescales. **Within a run:** the ledger is append-only truth, and *every turn is
conditioned on the computed envelope of the previous one* — the harness replaces the model's
account of what it did with what the harness measured, so the loop can never drift onto a
fiction. **Across runs:** the learning plane reinforces — verified outcomes update the
calibration table (who is actually right), earned lessons compile into standing checks, and
watchdogs ensure the plane itself never dies quiet. Reality is not asserted once; it is
recomputed every turn and re-weighted every run.

### How the clock guides behavior

The agreed finish time from Act 2 is a **hard budget, not a hope.** The scheduler selects
which stories to attempt so their summed points fit the timebox at the measured velocity
(seeded with a conservative default velocity on the very first loop, before any is measured).
Each turn debits the wall-clock budget; each story carries its own turn/time cap. As the
deadline approaches the harness **stops starting new work, finishes in-flight edits, and
assembles the review package** — *"here is what I finished, here is what I could not, here
is the evidence for both."* The realized velocity (points completed per unit time) feeds
back into the next sizing and the next schedule. The clock is a first-class actor in the
loop, checked on every turn, not a wall-clock glanced at the end.

---

## Part III — The build sequence (dependency-ordered to construct the human loop)

The backlog (#445–485, epic #32) re-ordered to **construct the lived loop end to end.**
Stage A is first not because the human meets it first, but because *every* later act rides
on the turn actually being trustworthy — a discovery that produces stories an unreliable
editor cannot build is theater.

- **Stage A — Make the turn trustworthy** (the mechanisms of §II, from M1 *execution-craft*):
  lint-gate **#445**, multi-strategy fuzzy-apply **#446**, rollback-and-resample **#448**,
  loop-hygiene **#450**, the repo map, the per-model edit-format registry. *Extends the
  Phase-1 kernel.*
- **Stage B — The contract store** (M2 *product-spine*): the sovereign local product DB so an
  **epic** / story / spec / DoD / size / status can persist and project — **#451 → #453**.
- **Stage C — Discovery** (Act 1; M4): the conversation that turns a pain point + input +
  expected output into grounded stories and an epic.
- **Stage D — Formalization** (Act 2; M3 product-owner + M5 sizing): story → spec + DoD,
  Gate-0 armed, Fibonacci size assigned, the clock set.
- **Stage E — Execution** (Act 3; M3 tester/implementer/verifier/auditor + M6 the clock &
  sprint): the gated TDD cycle acts out, appending reality, paced to the deadline.
- **Stage F — Review & Learning** (Act 4; M7): the review package + the learning that makes
  the next loop smarter.
- **Stage G — The cockpit** (M8): the single local app that presents all four acts as one
  thing you open.

**First pull, unchanged: #445** — the lint-gate, the first mechanism that makes a turn
trustworthy, and the most direct fix for the weak-editor problem that motivated this whole
construction. The remaining backlog and points are in `ROADMAP.md`.
