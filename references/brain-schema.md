# Brain schema — the orchestrator's memory (canonical)

The per-repo **brain** is what the orchestrator knows that nothing else in the repo says. It lets a fresh or
post-compaction session resume without re-learning the repo, and it is deliberately small: a brain that catalogs
everything the code, git and the work orders already hold makes the next session slower and no wiser.

The brain is **self-contained**: every repo carries its own under `.gitos/brain/`. No external service, registry or
shared vault.

## Table of contents

1. The write test (the rule)
2. Directory layout
3. Page types and front matter
4. The generated index; no log
5. The maintenance loop
6. Anti-redundancy invariants
7. `brain_lint.py`

---

## 1. The write test

**The brain holds only what cannot be found in the code, git, CLAUDE.md or a work order:** why a decision was made,
what was rejected and why, conventions that are not obvious, and traps.

**Before writing a note anywhere: is it something to do?** Then it is a work-order (the open order that covers it,
or a new one) or a loose end (`references/glossary.md` → *Loose end*), never a note.

**Otherwise ask in order. The first "no" decides.**

1. **Will it still be true and needed when this plan and this window are over?** No → a RESUME note (with its
   *until*), or the order if it is that order's scope.
2. **Is it missing from the code, git, CLAUDE.md and every work order?** No → do not write it (a code comment is the
   home of a fact about code; the order is the record of what an order decided).
3. **Would a future window get something wrong without it?** No → do not write it.

All three yes → the brain; if a page already covers it, **update that page**, do not add a second. An owner
instruction that holds from now on ("always", "never", a standing permission) → the brain's `standing-rules` page,
never RESUME. **Unsure → a RESUME note with an *until***: it costs little to lose and is promoted at a checkpoint if
it lasts.

What fails the test: a temporary instruction (it governs this plan or window), what was built (the code says), the
history of events (git says), the order's own adjudication (the order says), a catalog of files or tools, a
restatement of a reference doc. What passes: the reason a design won
over its rejected alternatives, the trap a later change would walk into, the operator's standing rule, a convention
no single file shows.

## 2. Directory layout

```
<root>/.gitos/brain/
├── BRAIN.md               Brain identity: this repo's domain, default tags, entity types, schema pointer
├── raw/                   Drop-zone for material to ingest (docs, specs, transcripts)
│   └── _extracted/        Cached text from PDFs/binaries
├── wiki/
│   ├── sources/           One factual summary per ingested document
│   ├── entities/          The repo's "nouns" that need more than their code says
│   ├── concepts/          Patterns, conventions, invariants, traps spanning files
│   ├── decisions/         ADR-style records: WHY, and what was rejected
│   └── index.md           GENERATED from front matter; never edited by hand
└── .brainmeta.json        Cached metadata (engine_version, counts)
```

`BRAIN.md` is named `BRAIN.md`, **not** `CLAUDE.md`, on purpose: a nested `CLAUDE.md` would be auto-loaded when the
working directory is inside `.gitos/brain/`. There is **no `tasks/` and no `projects/`** type and **no log**:
actionable work lives in the work-order ledger, and the history of the brain is `git log -- .gitos/brain`.

## 3. Page types and front matter

Four types, each a markdown file under `wiki/<type>s/<slug>.md` (directory plural; `type:` singular). The front
matter is the **source of truth**; the body is prose with `[[wikilinks]]` to other pages.

```yaml
---
type: source | entity | concept | decision     # must match the directory
description: one line (at most 140 chars): when to read this page
status: active | superseded
superseded_by: <slug of the page that replaces it>   # required when superseded
updated: YYYY-MM-DD
rests_on: [path/or/commit, ...]                # optional: what the page depends on
---
```

- `description` is what the generated index shows. Write it as "read this when ...", concrete, not a title, by
  reading the page; never derive it from the page's first line (the lint reports `placeholder-description`).
- `updated` is when the page was last changed or checked. For a decision it is the date the decision was made.
- `rests_on` lists repo-root-relative paths (a path may carry `#anchor`) or commit hashes the page depends on. The lint
  reports one that no longer exists, which is the signal that the page may be wrong.
- `historical: true` (optional) opts a page out of the age test (a page transcribing a fixed source).

**Source** — a factual summary of one ingested document that is not itself in the repo (an external spec, API docs).
Never a summary of a file the repo holds. **Entity** — a noun (service, module, external system) whose cross-cutting
facts or traps no single file shows; it maps into code and never copies it. **Concept** — a pattern, convention,
invariant or trap spanning files. **Decision** — the highest-value type: context in a line, options weighed with the
reason each lost, the decision and **why**, and what must stay true. A decision is **never rewritten**: a reversal is a
new decision page, and the old one gets `status: superseded` and `superseded_by` (ADR practice). A decision page
points at its order with one markdown link and does not restate the order's adjudication; if the whole content is
that adjudication, there is no page.

## 4. The generated index; no log

`python <home>/tools/brain_lint.py <home>/brain --write-index` builds `wiki/index.md`: one line per **active** page,
`[[slug]] — description`, grouped by type, superseded pages left out. It is capped at **200 lines / 8 KB**; over the
cap is a lint error that names the longest descriptions. Never edit it by hand: edit a page's `description` and
regenerate (between sessions, so the session start reads a stable file). `brain_lint.py <home>/brain --check` exits 1
when the schema or the committed index is off; an orphan cannot exist because every page is in the index by
construction.

There is no `wiki/log.md`. What changed in the brain, and when, is git's: `git log -- <home>/brain`.

## Core rules and topic pages

Rules that every window reads at session start grow until the read costs more than the work. Split them. In one
measured case this took the read from about 91 KB to about 55 KB.

- **Core rules page**, about 10 KB at most. It holds only what binds all work, then an index of the topic pages. Each
  index line carries that page's "read this when" line. The index opens with "do not read these by default".
- **Topic page**, one per lasting area, about 12 KB at most.
- **A new rule** goes on a topic page by default. It goes in core only if it binds all work, and then something
  moves out so core stays under the cap. A new page is for a lasting area, or for a page over its cap that holds a
  whole sub-area.
- **Adding a page:** create it, add one index line to core, regenerate the brain index (section 4), run the canary.
- **At each checkpoint**, RESUME links only the topic pages the work ahead touches (`references/orchestrator/checkpoint.md`).

## 5. The maintenance loop

### Layer 1 — Inline capture: the write test, then upsert

1. **Write test** (§1). Most facts fail it and are not written. A durable fact from an implementer's notes is sorted
   at resolve: a **code comment** where the fact lives (most), the tool's **reference doc**, a **brain page** only
   if it passes the test, or **nowhere**.
2. **Search first.** Read `wiki/index.md` and grep `wiki/` for a page on this atom.
3. **Upsert.** Update that page and bump `updated`; create a new page only when the atom is distinct from every
   existing page. A decision is updated only by a new decision that supersedes it.
4. **Route by kind.** If it is actionable, it is a work order, not a brain page.
5. Regenerate the index (`--write-index`). No log entry.

### Layer 2 — Checkpoint reconcile

At a checkpoint (an order resolved, end of a session, before a likely compaction): ask what the session established
that the brain does not hold **and passes the write test**, and what it invalidated. Re-read the pages you touched,
merge near-duplicates, mark a replaced decision superseded, fix broken `[[links]]`, regenerate the index.

### Layer 3 — Deterministic backstop

Run `brain_lint.py <home>/brain` at checkpoints (the diagnostic role can too: it is read-only unless asked to write
the index). Small fixes happen inline; a large restructure becomes a consolidation work order.

## 6. Anti-redundancy invariants

- **One atom, one page.** Everything else links and never copies.
- **Knowledge, work, birth record and code are four layers.** The brain holds why / what is true; the INDEX holds
  what work is open; the frozen handoff is the birth record; the code holds what the system does. A brain page links
  an order and never restates it.
- **The brain maps into code; it does not mirror it.** No pasted code, no restated docstring.
- **Prefer update; create only when distinct.**
- **Forward-positive.** Record issues factually as cause plus correction, because that prevents recurrence; no blame,
  no editorializing about people, no conversational aside enshrined as fact. This one is semantic: it lives in the
  reflection pass, not in the lint.

## 7. `brain_lint.py`

`python <home>/tools/brain_lint.py <brain-dir> [--stale-days N] [--root DIR] [--json] [--write-index | --check]`.
Without a mode flag it only reports. Classes:

- **duplicate / near-duplicate pages** — same slug, or high title-token and shared-wikilink overlap.
- **stale** — an active page whose `updated` is older than `--stale-days` (default 90; decision pages and
  `historical: true` pages are exempt from the age test and the exemption is counted in the report), a `rests_on`
  path or commit that no longer exists, a `superseded_by` that does not resolve.
- **broken wikilinks** — `[[targets]]` with no matching page.
- **cross-layer redundancy** — a page naming two or more different work-order ids in prose (a markdown link to an
  order is a pointer and is not counted), or whose body is mostly a fenced code block.
- **schema** — missing or invalid `type`, `description`, `status`, `superseded_by`, `updated`; and a
  `placeholder-description`: a description that is empty, ends in `:`, has an unbalanced bracket or quote (a cut
  line), opens `Read this when you need <title>:`, or equals the page's title or first line. The lint can only see
  the shapes a script leaves; whether a description says when to read the page is judged by reading the page.
- **index** — `wiki/index.md` over its cap, or not equal to the generated index.
- **upgrade_diary** — advisory, not part of `--check`: an active page named `engine-upgrade-v<N>`. Such a page narrates
  one upgrade, which git and the CHANGELOG hold; it is deleted, or renamed for the why, rejected option or trap it
  keeps (upgrade step 4u).
