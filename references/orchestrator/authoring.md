# Orchestrator step: authoring orders, prioritization, rules go to files

Read this when you propose or write an order (work-loop step 2), choose what comes next, move work toward production, or the operator
states a standing instruction.

## Propose work-orders (work-loop step 2)

2. **Propose work-orders.** Decompose the ask into *proposed* ledger entries (Objective +
   Part-0 probe + Acceptance), in disjoint units. Scope from what you read; a field you cannot evidence is
   named as a gap, never filled (`references/disciplines.md` (m) evidence-or-name-the-gap). **You propose; the operator confirms the set before
   any become active or get dispatched** — the brake on runaway work-order creation. Watch for a
   newly-grown **diagnostic fork** (a project-local `.claude/skills/*` debug/triage skill, a repo-root
   `*_AGENT_BRIEF.md`, or a stray duplicate `diagnostic_agent.md`/`debug_agent.md`) and propose a
   **migrate-then-retire** work-order per the no-fork directive in `references/roles/diagnostic.md`.
   → *Authoring work-orders · Prioritization policy.*
   *Gate:* **no work-order is created, activated, or dispatched without explicit operator confirmation.**

## Authoring work-orders

You create **forward work-orders** (discovery / build / port / promotion), distinct
from the diagnostic finder's *bug* work-orders. Use the shared format
(`references/work-order-template.md`); a forward work-order adds:

- **Objective** — what done looks like, in one sentence.
- **Part-0 probe** — the cheap, read-only check that precedes any expensive work,
  with an explicit **GO / NO-GO** criterion. (Discipline (c) cheap-probe-before-expensive-sweep,
  `references/disciplines.md` — most NO-GOs are catchable for almost nothing.)
- **Acceptance** — the precommitted criteria that decide done vs. not.

Forward work-orders share the same `NNN` numbering and the same INDEX as bug
work-orders — one ledger, no parallel system.

## Prioritization policy

- **Bugs** by blast radius — use the finder's severity (critical > high > medium > low).
- **Build/discovery** by expected information value — do the thing that most reduces
  uncertainty or unblocks the most downstream work next.
- **Cheap probe before expensive sweep** — never launch a costly build/sweep before
  its read-only Part-0 probe has returned GO. A NO-GO that costs a few reads can save
  a multi-hour effort.
- **Respect dependencies** — and any parity/contract the project declared (don't
  reorder past a hard gate).
- **A green suite is not a verdict.** Never let "the tests pass" substitute for
  confirming the thing actually does what it should — gates and filters are code too,
  and silent no-ops pass tests. (Disciplines (a), (b), (h) in `references/disciplines.md`.)

## The lifecycle you follow

Work moves through generic, project-declared stages — name them in the handoff
(`§Lifecycle stages`). A common shape:

```
idea → forward work-order → implement → verify → {resolved | DISPROVED} → next
```

For work that graduates toward production, the stages are typically **draft →
candidate → promoted**, with the project's **acceptance criteria**
(`references/acceptance-criteria.md`) as the gate between candidate and promoted, and
the **production-handoff contract** (`references/production-handoff-contract.md`)
locked before anything ships. You own moving work through these stages and keeping the
INDEX honest about where each item sits.

## Rules go to files (the moment they are stated)

When the operator states a **standing instruction** — a permission, an authorised account, a
quantity cap, a prohibition ("never mention X to Y"), a preference — write it to a **file in the
same turn**, before doing the work it governs. Not at the end of the task, not at the next
checkpoint: a rule that lives only in the conversation is a rule the next summarization can drop,
and a dropped `don't do X` is indistinguishable from permission. This is one of your gates in
practice, not a tidiness habit.

**Where it goes is decided by one question:** *would this still be true in a fresh clone with no
session running?*

- **Yes** → the **brain** (knowledge: a `standing-rules` concept page, or a decision page when the
  rule changes the *why*), the **ledger** (if it is actually work), or — never retroactively — the
  **handoff** (birth record, immutable).
- **No** → `<home>/RESUME.md`, the live session pointer.

**A standing rule never goes in RESUME.** RESUME is replaced wholesale at every checkpoint, so a
rule written there is destroyed by the rotation mechanism itself — the file meant to outlive
compaction would be the thing that loses the rule. The rule goes to the brain; **RESUME points at
it**. That is also what keeps `references/glossary.md`'s *nothing is in two places* true with a
fifth store present: RESUME holds a reference, not a copy. Built backwards, this loop causes the
failure it exists to prevent, so `canary.py` checks it (`resume/standing-rule`).

Converse, with its own precedent: **nothing volatile goes in the brain.** `brain_lint`'s staleness
model reads a page's `updated:` as a claim about knowledge, so a page holding in-flight state goes
stale constantly and correctly, with no remedy.

## Proposed orders from an upgrade audit

The active adoption step of an upgrade (`references/upgrade.md` 4v) runs each audit the crossed versions name and hands
you findings. You turn them into proposed orders (a title, the evidence with its counts, what it would do) and put them
on ONE owner-board card (`board.py add-decision`, group `decision`: open all, park all, open some with the choice in
the note, decline all). No order is created before the answer; a finding is never left as a silent note. On the answer,
write the opened orders and the parked ones (with their trigger), then close the card with the outcome.

## Out of scope

- Don't push work to a production stage before its acceptance criteria pass.
- Don't weaken a declared gate/contract without explicit operator override.
- Don't write application source during *inception* (that's the build phase, after the
  pipeline + brain exist).
