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
gitos gives any repo four roles in two tiers: an **Orchestrator** that drives the work and
dispatches, a read-only **Diagnostic** finder that produces evidence-first work-orders, and
**Implementers** each dispatched to edit exactly one scoped task — all bootstrapped once by
**Inception**. You don't hand-prompt each step; the orchestrator conditions the workers. *Finding
is separated from fixing*, so a finder is never pressured into a careless edit.

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
```

To run a single work-order, point a fresh window at it — *"implement `wo_046`"*. That lands as the
**Implementer**, scoped to that one order (plan-first), not the orchestrator.


## License

MIT — see [LICENSE](LICENSE).
