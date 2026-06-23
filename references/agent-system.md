# Agent System — One-Page Map

A concise reference for how the four roles (three repo-entry + an implementer entered on one work-order) and the brain relate. Read this if the
picture isn't clear after skimming `SKILL.md`. For operating instructions, open the
role briefs listed at the bottom.

---

## The Three-Step Flow

### 1. Inception (once per repo)

Run once on an uninitialized repo. Inception interviews the user to understand the
project, scaffolds the `.gitos/` tree (work-order ledger, brain, work-order
template), **seeds the brain** at the agreed depth (minimal / moderate / aggressive),
fills `handoff.md` — the immutable birth record — and then hands control to the
Orchestrator in the same session.

Inception does NOT write application source code. Its only product is the pipeline
itself: a live brain and a frozen handoff that give every future session a standing
start.

### 2. Orchestrator (every working session after Inception)

The front-line builder. Each session it:

1. Reads `handoff.md` **once** — the frozen birth record; never edited again.
2. Reads `INDEX.md` — the current work state (open / resolved / disproved / next-steps).
3. Reads the brain (`BRAIN.md` + `wiki/index.md`, then the pages relevant to today).
4. Builds with the user: authors forward work-orders, sequences work, makes decisions.
5. Invokes the **Diagnostic** finder (read-only) when evidence needs careful cataloging
   before action is taken.
6. Dispatches and verifies **Implementer** agents for authorized code changes.
7. **Stewards the brain** via the maintenance loop (inline upsert → checkpoint
   reconcile → `brain_lint.py`) — recording a decision page on every non-trivial choice.
8. Closes each session with a prioritized next-steps recommendation in `INDEX.md`.

### 3. Diagnostic (read-only finder — called by the Orchestrator or directly)

Investigates without editing. Three phases:

1. Build the **vocabulary** — catalogue what logs/outputs exist before scanning them.
2. **Scan** across the anomaly families (`references/anomaly-families.md`).
3. Write evidence-first **work-orders** (`bug_<NNN>_<slug>.md`), one per distinct
   finding, and append each to `INDEX.md`.

The Diagnostic never edits source code or configuration. All fixes flow through
work-orders dispatched by the Orchestrator.

### The implementer (entered on a work-order, not on the repo)

The three roles above are **repo-entry** — reached by state detection + user intent on the *repo*.
The **implementer** is the fourth role, entered on a single **work-order**: the orchestrator
dispatches it, **or** the operator points a fresh window at one work-order ("implement this", "do
`wo_046`"). Either way it reads that work-order in full, **plans first**, edits only what its
Proposed fix scope names, fills its Implementer notes, and returns — it lands one order, never drives
the ledger. It holds no long-term state between orders. Full brief: `references/roles/implementer.md`.

---

## Bridge Diagram

```
Inception ──seeds──▶ brain + writes──▶ handoff.md ──read once──▶ Orchestrator
                                                                      │  ⇅ brain (read/query/update)
                                              calls (read-only)       ├──▶ Diagnostic ──▶ work-orders ──▶ INDEX
                                              dispatches + verifies   └──▶ Implementers ──▶ code
```

The handoff is read-only after Inception. The brain is read-write by the Orchestrator
only. The INDEX and code are the Orchestrator's responsibility to keep current and
honest.

---

## When to Use Which Role

| User phrasing | Role |
|---|---|
| "init this repo", "scaffold the pipeline", "give this project a brain", "set up the work-order system", "bootstrap the agent system" | **Inception** |
| "start working on this", "what should I do next", "drive the project", "plan the next steps", "prioritize the backlog", "build X" | **Orchestrator** |
| "audit this artifact", "find bugs in X", "diagnose the pipeline", "inspect the logs", "what's wrong with Y", "investigate this anomaly" | **Diagnostic** |

If the repo is already initialized and the intent is build/drive, it's the
Orchestrator — even if the user says "start over" or "what's left". Detection always
runs first; see `SKILL.md §First action`.

The **implementer** is entered differently — on a single **work-order**, not on the repo: the
orchestrator dispatches it, **or** the operator points a fresh window at one work-order ("implement
`wo_046`"). It lands that order and returns. See `references/roles/implementer.md`.

---

## The Four Artifacts — One Atom, One Place

Each fact or artifact lives in exactly one layer. They **link** across layers; they
never copy content into a second home. This is the single most important structural
rule — it's what keeps the system from drifting out of sync as it grows.

| Artifact | What it holds | Location | Editable after inception? |
|---|---|---|---|
| **Brain** | *Why / what-is-true* — decisions, domain concepts, entities, ingested sources | `.gitos/brain/wiki/` | Yes — Orchestrator only, via the maintenance loop |
| **INDEX** | *What work is open* — forward work-orders, bug work-orders, resolved/disproved history, next-steps | `.gitos/INDEX.md` + `work-orders/` | Yes — Orchestrator updates lifecycle; Diagnostic appends findings |
| **Handoff** | *The birth record* — project identity, acceptance criteria, hold-out discipline, outcome definition, predecessor lessons | `.gitos/handoff.md` | No — frozen after Inception; evolution goes into brain pages |
| **Code** | *What the system does* — the actual implementation | `src/`, `tests/`, etc. | Yes — Implementers only (never the orchestrator directly); the orchestrator authorizes + dispatches + verifies |

**The one-atom-one-place rule:** if a fact is *why something is true*, it belongs in
the brain. If it is *what work is open*, it belongs in the INDEX. If it was true at
birth and should never drift, it belongs in the handoff. If it is *what the system
does*, it belongs in the code. A brain page may link to a work-order; it never
restates it. The handoff is never edited; anything that evolves migrates to a brain
page. Full invariant statements: `references/brain-schema.md §6`.

---

## Role Reference

| Role | Full brief |
|---|---|
| Inception | `references/roles/inception.md` |
| Orchestrator | `references/roles/orchestrator.md` |
| Diagnostic | `references/roles/diagnostic.md` |
| Implementer (work-order entry) | `references/roles/implementer.md` |
| Brain schema + maintenance loop | `references/brain-schema.md` |
