# gitos

**The discipline layer for AI-assisted development.** gitos turns any repository into a
self-driving, multi-agent workflow with a memory that compounds — and installs as a single
Claude Code skill.

You just create. gitos runs the orchestration, the memory, and the context hygiene underneath.

---

## The gap it closes

The last couple of years of agent research keep converging on the same handful of ideas:

- **Agents should prompt agents.** Decomposing work across specialized agents — an orchestrator
  conditioning workers — is more robust than one model doing everything, or you hand-prompting
  every step.
- **Grounding beats priors.** An agent reasons far better over a project's *actual* artifacts, logs,
  and vocabulary than over generic assumptions — and a claim checked against logged evidence is
  reproducible where a narrated one is not.
- **Agents need memory, not just a context window.** The shift the field now calls *context
  engineering* is about durable, external, curated knowledge — *what enters the context* matters
  as much as the model.
- **Orchestration has to be deterministic.** Long-horizon work drifts without a ledger, role
  boundaries, and verification between steps.
- **Framing is load-bearing.** A model is conditioned by whatever sits in its context. A growing
  thread in agent practice finds that *correcting* a model in-context — negative, "you got this
  wrong" framing — can reinforce the very failure it's trying to fix and drag down the rest of the
  session. The guidance is to frame **forward**: what to do next, not what went wrong.

Each idea is powerful alone. The part nobody hands you is the **wiring** — turning all four into
one discipline that runs automatically, every session, without you assembling it by hand.

That wiring is gitos.

## What it bakes in

**Agents prompting agents — a defined role system.**
gitos gives any repo five roles: an **Orchestrator** that drives the work and dispatches, a
read-only **Diagnostic** finder that produces evidence-first work-orders, **Implementers** each
dispatched to edit exactly one scoped task, and a read-only **Assessor** you call in for an outside
judgment of direction — all bootstrapped once by **Inception**. You don't hand-prompt each step; the
orchestrator conditions the workers. *Finding is separated from fixing*, so a finder is never
pressured into a careless edit.

**Grounded in the project's own vocabulary and evidence.**
Before an agent reasons about your project, gitos makes it *learn the project*. The diagnostic
role's first move is to build a **vocabulary** — a dictionary of the project's real artifacts, logs,
and outputs: what produces each, what consumes it, its fields, its sane ranges, the shapes that
signal trouble. From then on agents speak the project's own language instead of generic priors. They
work against **logged evidence** — recomputing values from the artifacts and quoting exact bytes
rather than narrating — and the brain keeps an append-only op-log of how its knowledge accreted. That
vocabulary-plus-logging substrate is what makes the problem-solving loop **deterministic**: the same
artifacts, read the same way, yield the same verdict — and it's the ground the brain and the roles
stand on.

**A brain, not a context window.**
Every gitos repo carries a **brain** — a per-repo knowledge base of typed, cross-linked pages
(sources / entities / concepts / decisions), seeded at inception and grown as the work proceeds,
kept honest by a deterministic linter. Every session starts *primed* by what the project already
knows: its constructs, its decisions, its gotchas. Memory compounds instead of resetting to zero.

**Deterministic orchestration.**
A work-order ledger tracks every open thread; each change traces back to a recorded decision (an
ADR). The orchestrator dispatches and then *verifies* — trust-but-verify, not fire-and-forget.
This is what keeps a multi-agent system coherent over weeks instead of drifting after an afternoon.

**Forward framing, as an automatic contextual filter.**
Because a model is conditioned by its context, gitos's brain is built as a **forward-positive
filter**. It records problems as *cause + correction* — the fuel for the next action — and prunes
blame, dwelling, and "look what went wrong" editorializing. Issues are never ignored; they're
captured as the lesson that moves the work forward. So the memory that primes every future session
is, by construction, framed for forward movement — the positive-framing practice the research
points to, made *structural* rather than something you have to remember to do.

## Why it works

Priming the context before a model generates — preloading how the pieces relate — makes a cohesive,
robust result far more likely than asking a cold model (or yourself) to nail it in one shot. gitos's
roles and brain *are* that priming, applied automatically on every session. And verification —
find-≠-fix, dispatch-and-verify, the linter — is the counterweight that keeps the priming honest,
so confident-but-wrong output gets caught instead of compounding.

LLMs prompting LLMs, conditioned by a maintained memory, checked by verification. You stay the
operator; gitos is the discipline.

## The model

| Role | When | What it does |
|---|---|---|
| **Inception** | once | Scaffolds the `.gitos/` home + the brain, then hands off. |
| **Orchestrator** | ongoing | Drives the build, owns the work-order ledger, stewards the brain. |
| **Diagnostic** | on demand | Read-only finder: investigates, writes evidence-first work-orders. Never edits. |
| **Implementer** | dispatched | Edits only what a work-order specifies — nothing else. |
| **Assessor** | when you ask | Read-only: judges whether the work serves the goal; leaves a durable report. Never edits. |

The **brain** (`.gitos/brain/`) is the orchestrator's long-term memory, and the thing that makes
the rest compound.

## How it runs

You work in **one window with the orchestrator** — your single point of contact. You tell it what
you want; it proposes work-orders on the ledger **for your confirmation** — nothing runs until you approve the
set. Each confirmed work-order runs **plan-first**: the
worker reads the order, plans the approach for approval, then executes, so scope and approach errors
are caught before any edit. Each typically runs in its own fresh window for a clean budget — though
the orchestrator can batch related work, or sequence it, to optimize context. When the work lands,
control returns to the orchestrator: it verifies the diff, accepts or rejects
the worker's notes, commits the work, updates the ledger and the brain, and moves to the next. One
resident coordinator, many disposable workers — the orchestrator stays authoritative while the edits
happen elsewhere.

## Install

Clone it straight into your skills directory so updates are a simple `git pull`:

```bash
git clone https://github.com/wizzo-gmb/gitos.git ~/.claude/skills/gitos
```

(Prefer to clone elsewhere? Copy the contents into `~/.claude/skills/gitos` instead — then
*Updating* below means re-copying rather than `git pull`.)

In your repo, invoke the skill and let it detect state: a fresh repo routes to Inception; an
initialized one routes to the Orchestrator or the Diagnostic finder by intent. Then just describe
what you want to build.

## Updating

The **engine** and a **repo's adoption** of it are two layers:

```bash
cd ~/.claude/skills/gitos && git pull     # 1. update the installed engine (git-clone installs)
/gitos upgrade                            # 2. per repo, adopt the new directives
```

`/gitos upgrade` reconciles *that repo* against the **installed** engine — and if your install is a
git clone, it **offers to `git pull` the latest for you first**, so step 1 can happen inside the
command. (A bare `/gitos upgrade` with no newer engine installed is a safe no-op.) After a pull,
reload your editor so the agent loads the new skill.

## Commands

`/gitos` detects the repo's state and routes automatically — or you can name the mode:

```text
/gitos                 detect state + route (Inception on a fresh repo; else by intent)
/gitos orchestrator    resume the Orchestrator — drive the project, dispatch + verify work
/gitos upgrade         adopt the latest engine directives (idempotent; a no-op if already current)
/gitos diagnostic      a read-only audit pass → evidence-first work-orders
/gitos assess          an outside read-only assessment: is this the right work for the goal?
/gitos agent import    import your own specialist prompt as a domain-tagged "lens"
/gitos agent list      list the lenses you've imported (the registry)
/gitos optimization    inspect, enable, disable, or configure repo-local model routing
```

To run a single work-order, point a fresh window at it — *"implement `wo_046`"*. That lands as the
**Implementer**, scoped to that one order (plan-first), not the orchestrator.

**Lenses** (`/gitos agent import`) bring your own specialist prompts — a math lens, a niche-research
lens — into the engine. Each becomes a domain-tagged module any of the roles reads and folds into
its work when the domain matches, *within that role's boundary* (a read-only role stays read-only). On
import the orchestrator normalizes your prompt into the engine's voice and you confirm the result, so
imported steering reads like the rest of gitos. It's injected context, not a fifth role.

**Lenses are off until a repo turns them on.** `<home>/lenses.json` holds the switch and names each global
lens the repo uses, so a quant repo never checks design lenses and the other way round. Inception asks;
`/gitos upgrade` asks once, and in a repo that already has lenses it suggests keeping what that repo uses.
`python scripts/lenses.py status` shows what is active.

## Owner board

Every gitos home carries a small local web page, the **owner board** (`<home>/board/`), where you answer what
the agent asks. A plan with several items, a send to an outside party, or a question left while you are away
becomes a card there; a single question while you are in the window is just asked in chat. It is stdlib-only
Python on a loopback address, its answers are files in the home, and any session finds it again after a
compaction, `/clear` or a new window. Start or find it with `python <home>/board/board.py ensure`.

Since v74 the board is a live web app: the work views update as the ledger changes, a merged order shows as
**Awaiting accept** until you accept it, and you can act on an order from the page (set its severity, park, hold,
approve, leave a note), with the agent applying each action at its next step. A repo adds its own views beside
the built-in ones, and a workspace of several repos can share one board (a hub) with an overview of every repo.
The old sandboxed `local/*.html` pages are retired; a repo moves each one to a view as the
[owner board](references/owner-board.md) reference describes under *Migrating a page*.

## Sprint mode — work the ledger while you are away

A sprint works through a repo's open work-orders unattended, in a visible Claude session you can watch and step
into. You start it with one command in a terminal (Windows only for now):

```bash
python ~/.claude/skills/gitos/scripts/gitos-sprint.py [REPO] --autocompact 500k --effort medium
```

- **Same orchestration as a normal window:** parallel implementers, one worktree per order, the same dispatch
  rules and model mapping. The flags set the orchestrator session only; your own permission setting applies.
- **Only the orders you cleared.** Tell a normal orchestrator window "prepare for a sprint": it settles in-flight
  work and marks orders `sprint: ready`. `--orders 12,14` narrows it further. Anything outward or shared-state
  (a push, a deploy, a migration) stops the sprint; it commits, and push stays yours.
- **Rotates itself.** After the session compacts twice, the orchestrator checkpoints and the driver starts a
  fresh session, which resumes from the ledger. The sprint keeps its own state file; your next normal window
  folds it into the resume.
- **Quiet.** Each reply is the role marker line alone; progress goes to the owner board's Sprints view (a
  live log with a cost line), the commits and the ledger.
- **Stops cleanly.** The board's Stop card stops after the current order; a malformed input is refused and
  reported back for your next normal window. Every stop writes the sprint state first.
- **Your own safety check.** A repo with outside state (a running service, open positions, a live job) can name a
  guard command in `<home>/sprint-guard.json`; the driver runs it before every launch and after every close, and
  anything but exit 0 stops the sprint. Its tooling can also hold a `sprint/BUSY` lease while an action with outside
  effects is in flight: the driver then defers a rotation or stop until it settles, and waits a settle time before
  the guard looks.

### Several sprints at once

Give each sprint a name and its own orders, one terminal each:

```bash
python ~/.claude/skills/gitos/scripts/gitos-sprint.py [REPO] --id a --orders 12,14
python ~/.claude/skills/gitos/scripts/gitos-sprint.py [REPO] --id b --orders 15,16
```

- **Its own worktree.** A named sprint works in `<repo>.worktrees/sprint-<id>` on branch `sprint-<id>`, with its
  implementers' worktrees nested under it. Your main checkout stays yours, and a sprint's edits outside its own
  tree are refused.
- **One owner per order.** Each order is claimed by exactly one sprint; a second sprint asking for it is refused and
  told who holds it. A claim whose sprint has died holds nothing.
- **One landing at a time.** A sprint lands through `worktree.py land`: under one merge lock it merges main in,
  runs the gate (the canary, plus your own command in `<home>/sprint-gate.json` if you name one; it is read from
  main, so a sprint cannot change it), then fast-forwards main. A refused land stops that sprint with a board card.
  Your own merges while sprints run take the same lock (`worktree.py lock acquire` / `release`).
- **Its own Stop card.** Each sprint has its own card on the board and its own log; stopping one leaves the others
  running. Each sprint's stuck check counts only its own commits.
- **A sprint without `--id`** is the exclusive sprint: it still runs alone, and no named sprint starts beside it.

Operator guide: [sprint mode](references/sprint.md).


## The assessor — an outside read of direction

The orchestrator wrote the plan, so it is the wrong judge of whether the plan is right. Open a fresh window on the
model you choose and say *"assess this project"* (optionally with a focus: *"is the beta scope right?"*). The
assessor reads the goal and the raw evidence, treats the resume, implementer notes and "landed" stamps as claims to
verify, asks the orchestrator what it needs by direct message (and records the answers as claims too), and writes a
dated report with evidence per claim and numbered recommendations to `<home>/assessments/`. It never edits, never
dispatches work and never runs during a sprint. The orchestrator puts the report to you as one board card, writes its
response beside each item without softening it, and turns only what you approve into work. Earlier reports are kept
but not read by default, so each assessment starts clean. Brief: [assessor](references/roles/assessor.md).

## Model optimization — optional, off by default

Enable through `/gitos optimization` or the initialization/upgrade offer. GitOs maps
light, standard, and deep tasks to available model/effort choices in Codex or Claude,
within the operator-selected orchestrator's configured ceiling. Native harness
controls apply the selection where supported; requested settings remain distinct
from confirmed execution.

When enabled, one session record preserves the initial observed model/effort and
compares fresh observations before dispatch. Changes require checking the current
ceiling; unavailable runtime values stay unknown. This depends on harness or
operator evidence, not an assumption that saved defaults are active.

Existing work-order notes hold outcomes. Normal closeout may retain a useful,
repo-local model-selection lesson in the existing brain for future dispatches.
No advisor or additional ledger is needed, and no lesson is required. Disabling
optimization preserves previous evidence and guidance.

Configuration, harness support, and limits: [model optimization](references/model-optimization.md).

## Loose ends and System One

Loose ends pile up between work orders: a follow-up an implementer named, a remark that was not acted on, a
small gap found while doing something else. gitos writes each one down on the repo's loose-ends list so the
current order stays on track, and a **drain** clears that list between orders, so it never goes stale and nobody
has to read it row by row.

The drain turns every loose end into exactly one proposal: join a related open order, a new order for a group of
related items, park it until an event, ask you, close it, or "read it" when the reader is unsure. Each proposal
carries the items' own text and context gathered by code (the orders they came from, the files they mention,
open orders touching the same files). A proposed item moves off the list into the drain pile, so the list only
ever holds what has not been looked at yet. The orchestrator decides each proposal from the pile: it writes the
order and accepts, declines with a reason, or defers. Questions for you are raised from the pile, and closes wait
for your confirmation. An item accepted into an order becomes a checkbox there (`- [ ] L<n>`), named to the slice
of work that carries it, and the order cannot be resolved while a box is open. Items join only small orders; a
large one gets a new, single-theme order instead.

**By default the drain runs on a small cloud model.** Nothing to set up: the orchestrator exports the drain's
questions to a file, dispatches a helper on the cheapest model the harness offers (Claude Code: Haiku; Codex:
`gpt-5.1-codex-mini`; otherwise you are asked once to pick one) to answer them, and code checks each answer and
writes the proposals. The orchestrator never answers them itself. On the labelled set, Haiku handed back 27% and
got 15 of 16 settled items right. With model optimization on, the helper runs on the repo's light choice.

The drain only does work the main model is not already doing. Decisions made while reading an order, such as
routing implementer notes, what goes into the brain, which lenses apply, or reviewing a diff, stay with the
orchestrator.

### System One: connecting a local model (optional)

If you have a local model, **System One** connects it to the engine and the drain runs on it instead of the cloud
helper: free per call, and the same proposals through the same checks. When it is down (say, while your machine is busy) the drain falls back to the cloud
helper or waits; that is reported once, never as a problem, and never blocks a commit.

```text
system_one.py setup                  find and check a local server; --write saves the machine config
system_one.py repo on|off|status     use it in this repo, or not
system_one.py status --brief         one line: on, off, not chosen, or down
system_one.py drain <home>           drain on the local server (drain accept|decline|defer|status)
system_one.py drain <home> --export F / --answers F   the same drain, answered by the cloud helper
system_one.py helper                 which model the cloud helper runs on
system_one.py uses-check             check every question type against a server after a model change
```

**What it takes.** Any model you can serve locally, behind a server that answers `POST /v1/systemone` (the engine
sends it one small question at a time and checks every answer). The engine does not care which model or hardware
you use; a small instruction-tuned model is enough. The repo ships a reference server
(`assets/system-one/serve_general.py`) you can point at a model directory, or you can put the same endpoint in
front of whatever you already run.

**Connecting it, once per machine.**

1. Start your server so it answers on a local address (the reference server listens on `127.0.0.1:8765`).
2. Run `python scripts/system_one.py setup`, then `uses-check`. `setup` checks that the server is really a System
   One server, shows what it would write, and writes the machine config (endpoint and model label) only with
   `--write`. `uses-check` runs every question type against the server; run it again after any model change.
3. Each repo is then asked once, at inception or on the next `/gitos upgrade`, whether to use it; `system_one.py
   repo on` turns it on directly. A repo that has not chosen it uses the cloud helper.

Auto-start, serving other machines on your network, and the full config: **`references/system-one.md`** → *Machine setup*.

## Federation — optional, off by default

If you run gitos in more than one repo on the same machine, those instances can **find each other**.
An orchestrator that discovers a bug belonging to a sibling repo can file it *there* instead of you
copy-pasting it across; one that needs something a sibling already learned can read that sibling's
brain instead of you opening the folder. Nobody gives up authority over their own repo.

```text
federation offer                         what to do about federation here (read-only; silent if nothing)
federation enable                        opt this repo in (mints an id; writes one ignored file)
federation status                        who else is on this machine, and what they allow
federation set --consultable on          let siblings read this repo's brain  (off by default)
federation consult <target>              read a sibling's brain, if it allows it
federation file <target> --title …       file a finding into a sibling's intake
federation intake                        what siblings have proposed to THIS repo
```

**Two-stage consent.** Opting in is one decision; what you expose is a separate one. `consultable`
is **off** by default — a sibling can see you exist, not read your brain. Groups partition a machine
when one box hosts unrelated domains, so reachability is a set intersection rather than "everyone."
`/gitos upgrade` runs `federation offer` and asks you only when there is something to ask —
and if other repos on your machine have formed groups, it lists them so you can join by
picking one rather than by already knowing its name.

**A proposal is data, never a directive.** A finding filed into your repo lands in `intake/` as a
*proposal*. It becomes work only when **you** accept it — and on accept, your repo authors its own
work-order; the foreign file stays evidence and never becomes an item on your board. The listing
shows metadata only and **cannot render a proposal's body**, because that body is text another
repo's LLM wrote and your orchestrator reads whatever is in that directory. Reading one is a
deliberate act (`intake --show`), and the operator is who does it.

**What it is not.** This is **cooperative, not a sandbox** — machine-local by construction, no
daemon, no network, no privileged process. The flags are policy that participants honor; they reduce
blast radius and noise, and they keep no secrets. The isolation boundary is **the machine**: if two
bodies of work must not see each other, put them on different machines, which is what you'd do
anyway. Opting in is per checkout and reversible (`federation disable`), and a repo that never opts
in is byte-for-byte unchanged — no registry entry, no extra output, no new failure mode.

The full surface, the invariants, and the honest limits: **`references/federation.md`**.

## License

MIT — see [LICENSE](LICENSE).
