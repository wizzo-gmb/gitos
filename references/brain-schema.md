# Brain schema — the orchestrator's memory (canonical)

This is the single source of truth for the per-repo **brain**: a self-contained,
code-adapted knowledge vault the orchestrator reads, queries, and grows as it
builds with the user. It is the orchestrator's long-term memory — the thing that
lets a fresh or post-compaction session resume without re-learning the repo.

The brain is **self-contained**: every repo carries its own brain under
`.gitos/brain/`. There is no external service, registry, or shared vault. (The
schema's lineage is a Zettelkasten-style "second brain"; the
implementation here is standalone and depends on nothing outside the repo.)

## Table of contents

1. Directory layout
2. Page types (source / entity / concept / decision)
3. Wikilink + frontmatter conventions
4. Index and log
5. The maintenance loop (how the orchestrator keeps it true and non-redundant)
6. Anti-redundancy invariants
7. `brain_lint.py` — the deterministic backstop

---

## 1. Directory layout (inside each repo)

```
<root>/.gitos/brain/
├── BRAIN.md               Brain identity: this repo's domain, default tags, entity types, schema pointer, rules
├── raw/                   Drop-zone for material to ingest (docs, specs, transcripts, exports)
│   └── _extracted/        Cached text from PDFs/binaries (so re-ingest doesn't re-extract)
├── wiki/
│   ├── sources/           One factual summary per ingested document
│   ├── entities/          The repo's "nouns": modules, services, components, external systems, data stores, key deps, people, tools
│   ├── concepts/          Architecture patterns, domain concepts, conventions, invariants — "how this system works"
│   ├── decisions/         ADR-style decision records — WHY things are the way they are
│   ├── index.md           Master catalog (Sources / Entities / Concepts / Decisions)
│   └── log.md             Chronological operation record
└── .brainmeta.json        Cached metadata (last_ingest, counts)
```

`BRAIN.md` is named `BRAIN.md`, **not** `CLAUDE.md`, on purpose: a nested
`CLAUDE.md` would be auto-loaded by Claude Code when the working directory is
inside `.gitos/brain/`, polluting the repo-root context. `BRAIN.md` is read
deliberately by the orchestrator, not ambiently.

There is **no `tasks/` and no `projects/`** page type. Actionable work lives in
the pipeline's work-order ledger (`.gitos/INDEX.md` + `work-orders/`), which is
the single task surface. The brain holds *knowledge*; it links to work-orders for
*action*. (See §6.)

## 2. Page types

Four high-signal types. Each is a markdown file under `wiki/<type>/<slug>.md` with
YAML frontmatter + a body of prose and `[[wikilinks]]`.

### Source page (`wiki/sources/<slug>.md`)

A **factual** summary of one ingested document (a README, a spec, a design doc,
external API docs, the inception handoff). Interpretation does NOT go here — it
goes in concepts/decisions. Frontmatter:

```yaml
---
tags: [domain, tag]
source_type: readme | spec | design-doc | api-doc | handoff | transcript | note
sources: [original/path/or/filename]      # what this page summarizes
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```
Body (recommended): **Summary**, **Key facts**, **Entities mentioned** (as
`[[wikilinks]]`), **Concepts covered** (as `[[wikilinks]]`), **Open questions /
action items** (which become work-orders, linked).

### Entity page (`wiki/entities/<slug>.md`)

A "noun" in the repo: a module/package, a service, a component, an external
system/API, a data store, a key dependency, a person/stakeholder, a tool.
Frontmatter:

```yaml
---
tags: [entity_type, domain]
entity_type: module | service | component | external-system | datastore | dependency | person | tool
maps_to: [src/path/or/symbol]              # where this lives in the code (entities MAP into code)
sources: [[Source Page]]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```
The `maps_to` field is load-bearing: an entity page is a **map into the code**,
not a copy of it (see §6). Link to files/symbols; capture only the cross-cutting
facts that aren't obvious from reading one file.

### Concept page (`wiki/concepts/<slug>.md`)

An architecture pattern, domain concept, convention, or invariant — the "how this
system works" knowledge that spans files. Same frontmatter shape as an entity with
`concept_type: pattern | domain | convention | invariant` instead of `entity_type`.

### Decision page (`wiki/decisions/<slug>.md`) — the highest-value type

An ADR-style record of a non-trivial choice made with the user: what was decided,
the context, the options weighed, and **why** this one won. This is the knowledge
that most reliably survives compaction and onboards the next session — code shows
*what*, decisions explain *why*.

```yaml
---
status: accepted | superseded | revisited
decided: YYYY-MM-DD
supersedes: [[Prior Decision]]             # optional
superseded_by: [[Later Decision]]          # optional
work_order: [WO-007]                       # optional — the WO that implements it
tags: [domain]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Decision: <imperative summary>

## Context
## Options considered
## Decision + why
## Consequences / what to watch
```

## 3. Wikilink + frontmatter conventions

- Every reference to another wiki page uses `[[Page Name]]` (human-readable form;
  the file is the slugified name). **Never** use raw file paths for internal
  references in body prose — that's what breaks when pages move and what `brain_lint`
  flags.
- Links to the *code* (not other wiki pages) DO use real paths/symbols — that's the
  entity↔code map, and it's intentional.
- Keep `created` fixed and bump `updated` on every edit. Stale `updated` is how
  `brain_lint` finds rot.

## 4. Index and log

- `wiki/index.md` — a categorized catalog of every page (Sources / Entities /
  Concepts / Decisions). Refreshed during the reconcile pass and by `brain_lint`.
- `wiki/log.md` — a chronological one-line-per-op record (`ingest`, `page-add`,
  `page-update`, `decision-record`, `merge`, `reconcile`, `lint`). Append on every
  operation; it's the audit trail of how the brain came to hold what it holds.

## 5. The maintenance loop (self-feedback, keeps the brain true and lean)

The orchestrator doesn't just *seed* the brain at init — it **feeds its working
experience back into the brain as it builds**, and prunes redundancy. Three layers:

### Layer 1 — Inline capture (continuous): the UPSERT protocol

Whenever you learn or decide something worth remembering, before writing anything:

1. **Search first.** Read `wiki/index.md` and grep `wiki/` for an existing page on
   this atom (entity / concept / decision / source). This search-before-write step
   is the *primary* defense against duplication — most "new" facts belong on a page
   that already exists.
2. **Upsert.** UPDATE the existing page (revise the relevant section, bump
   `updated`, add `[[wikilinks]]`). CREATE a new page ONLY when the atom is
   genuinely distinct from every existing page.
3. **Route by kind.** If the atom is *actionable* ("we should refactor X", "fix the
   retry logic"), it is a **work-order**, not a brain page — file it in the INDEX and
   have the relevant brain page *link* it. If it's *why / what-is-true*, it's a brain
   page.
4. **Reconcile contradictions.** If the new fact contradicts the page, update the
   page and note both readings with a dated marker so the change is auditable.
5. **Log.** Append one line to `wiki/log.md`.

### Layer 2 — Checkpoint reconcile (periodic): REFLECT → RECONCILE

At natural checkpoints — a work-order verified, end of a working session, **before a
likely context compaction**, or roughly every N captured atoms — run a short pass:

- **Reflect.** Ask: "what did this session establish that the brain doesn't hold
  yet, and what did it *invalidate*?" Look for decisions made, new entities touched,
  concepts that got clearer, and assumptions that died.
- **Capture** the deltas via the Layer-1 upsert protocol.
- **Reconcile.** Re-read the pages you touched. **Merge near-duplicates**: pick the
  canonical page, fold in the other's content, and replace the loser with a
  `see [[Canonical]]` redirect stub (or delete it after re-pointing inbound links).
  Mark superseded content `superseded_by [[X]] (date)`. Fix broken `[[links]]`.
- **Refresh** `wiki/index.md` and `.brainmeta.json`.

This is the self-feedback loop: working experience becomes durable memory, then gets
pruned so the brain stays small and true rather than sprawling.

### Layer 3 — Deterministic backstop

Run `<home>/tools/brain_lint.py <home>/brain` at checkpoints (the diagnostic
role can also run it — it's a read-only audit, no new role). It flags structurally
what reflection misses (§7). Small fixes happen inline in the reconcile pass; large
restructures become a consolidation **work-order** in the INDEX — knowledge
maintenance flows through the same work ledger, never a parallel system.

## 6. Anti-redundancy invariants (what the loop enforces)

These rules are *why* the loop above works. They kill the main sources of brain
bloat at once, and keep what remains forward-useful.

- **One atom, one page.** Each fact / entity / concept / decision has exactly one
  home page; everything else *links* to it and never copies its content. (This is
  the copy-without-rename discipline applied to prose: a duplicated paragraph drifts
  out of sync exactly like a duplicated code identifier does.)
- **Knowledge ≠ work ≠ birth-record.** A fact lives in exactly ONE layer:
  - the **brain** (`why` / `what is true`),
  - the **INDEX** work-orders (`what work is open`),
  - the frozen **handoff** (`the birth record`).
  Brain pages *link* work-orders; they never restate them. The handoff is never
  edited after inception — anything that evolves moves into a brain page, and the
  handoff stays the immutable record of what was true at birth.
- **The brain maps into code; it does not mirror it.** Entity/concept pages link to
  files/symbols (`maps_to`) and capture the cross-cutting *why*; they never paste
  code or restate a docstring. The code is the source of truth for *what*; the brain
  is for *why* and for the connections no single file shows.
- **Prefer update; create only when distinct.** Enforced at write-time by Layer-1
  search-before-write and audited by Layer-3 lint.
- **Forward-positive (no self-pollution).** Every page serves forward movement.
  Record issues, errors, and failures *factually* — their **cause + the
  corrective/forward action** — because that is what prevents recurrence. Valid
  issue-records STAY: diagnostic findings, bug work-orders, predecessor lessons,
  and war-stories are *forward-fuel*, not clutter. What gets pruned is the
  **dwelling**: no blame, no negative editorializing about people, no enshrining a
  conversational aside as a durable fact, no logging "wrongness" for its own sake.
  Test each line: *does it drive the next action, or just dwell on the last
  problem?* Keep the cause and the correction; drop the longing. This one is
  **semantic** — `brain_lint` can't enforce it, so it lives in the reflection pass
  (§5).

## 7. `brain_lint.py` — the deterministic backstop

`python <home>/tools/brain_lint.py <brain-dir> [--stale-days N] [--json]` scans the brain
and reports, by class:

- **duplicate / near-duplicate pages** — same slug-stem, or high overlap in title
  tokens + shared `[[wikilink]]`-target sets (two pages "about the same thing").
- **orphans** — pages with no inbound `[[links]]` and not in `index.md` (unreachable
  knowledge).
- **stale** — pages whose `updated` is older than `--stale-days` (default 60).
- **broken wikilinks** — `[[targets]]` with no matching page.
- **cross-layer redundancy** — a brain page that names/echoes a work-order id, or
  whose body is mostly a fenced code block (mirroring code instead of mapping it).

It is read-only: it reports, it never edits. The orchestrator acts on the report in
the reconcile pass (small) or via a consolidation work-order (large).
