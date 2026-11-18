# Orchestrator step: brain stewardship (the maintenance loop)

Read this before a brain write, a page retire, a reconcile or a lint at a checkpoint.

The brain is your memory, and keeping it **true and non-redundant** is part of your
job — a brain that sprawls with duplicates is worse than no brain. Follow the loop in
`references/brain-schema.md` §5–6. The short version:

- **The write test (every write).** Before recording anything: can this be found in a work order, the git log, the code
  or CLAUDE.md? If so, do not write it. The brain holds only why, what was rejected, non-obvious conventions and traps.
- **Inline upsert.** If it passes: *search the brain first*
  for an existing page on this atom; UPDATE it (don't create a near-duplicate); only
  CREATE when genuinely distinct. If the atom is *actionable*, it's a work-order, not
  a brain page — link it. Note contradictions. There is no log: git keeps the brain's history.
- **Record decisions.** Whenever you and the operator make a non-trivial choice, write a
  **decision page** (`wiki/decisions/`, ADR-style). This is the single highest-value
  thing you put in the brain — it captures the *why* that the code can't, and it's
  what onboards the next session after compaction.
- **Checkpoint reconcile.** At a verified work-order, end of session, or **before a
  likely compaction**: reflect on what was learned/invalidated, capture the deltas,
  **merge near-duplicates** (canonical page wins; the loser becomes a
  `see [[Canonical]]` stub), mark a replaced decision `status: superseded` with `superseded_by` (a decision is never
  rewritten; a reversal is a new page), fix broken `[[links]]`, regenerate the index.
- **Generated index.** `wiki/index.md` is built from page front matter: run
  `python <home>/tools/brain_lint.py <home>/brain --write-index` after a page is added, retitled or retired; never edit
  it by hand. Each page carries `type`, `description`, `status`, `updated` (`references/brain-schema.md` §3).
- **The brain audit is an upgrade step.** `/gitos upgrade` step 4u (run by the active adoption step 4v) applies the write test to every page of an
  old brain (grep the cited order before deleting a page; a decision made in conversation passes by definition; a
  page named `engine-upgrade-v<N>` is deleted or renamed for its why) and step 4p has the descriptions written by
  reading each page. Run it for a repo whose canary reports `brain-upgrade-diary` or placeholder `brain-schema` items.
- **Lint backstop.** Run `python <home>/tools/brain_lint.py <home>/brain` at checkpoints to
  catch dup/near-dup, stale pages (age, `rests_on`, `superseded_by`), broken links, cross-layer redundancy, schema
  and index drift. Small fixes inline; large restructures → a consolidation work-order.
- **Forward-positive check (reflection pass).** Because `brain_lint` is structural, the
  reflection pass also enforces the **forward-positive** invariant — pages stay factual
  (cause + correction), with no dwelling/blame — per `references/brain-schema.md` §6.

**The anti-redundancy invariants you enforce** (full statements in `brain-schema.md`
§6): one atom = one page (link, never copy); knowledge (brain) ≠ work (INDEX) ≠
birth-record (handoff) ≠ what-the-code-does (code); the brain *maps into* code, it
doesn't mirror it; prefer update over create.
