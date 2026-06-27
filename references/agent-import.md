# Lenses — import & management

A **lens** is operator-imported specialist context that any role can fold into its own
thinking on demand. This page is the canonical procedure for importing, normalizing, and
cataloguing lenses. It is home-agnostic: `<home>/` is the project's home (default `.gitos/`).

## What a lens is

- **Operator-imported specialist context** — a math lens, a niche-research lens, a
  domain-framing prompt. The operator brings the expertise; the engine stores and serves it.
- **Injected, not dispatched.** A lens is not a fifth role. Any of the four roles
  (inception, orchestrator, implementer, diagnostic) reads a matching lens and folds it into
  its reasoning, *within its own boundary*. A lens changes how a role **thinks**, never what
  it is **allowed to do**.
- **Distinct from the brain.** The brain holds the project's **facts**; a lens holds **how to
  approach** a domain. Facts go in the brain; approach goes in a lens.
- Lives in `<home>/agents/<name>.md`; catalogued in `<home>/agents/index.md`.

## `/gitos agent import <path> [<path> ...]`  (orchestrator-run)

The orchestrator runs this. Its core is the **normalize-on-ingest** step — raw operator
prompts are *never* stored as-is.

1. **Gather** the prompt location(s) from the operator — files on disk, or text pasted into
   the chat.
2. **For each prompt:**
   a. **Read** it.
   b. **NORMALIZE INTO THE GITOS IDIOM — the load-bearing step.** Preserve the operator's
      domain substance and intent exactly; rewrite only the *framing* to the engine's
      standard:
      - **forward-positive voice** — cause + correction, no dwelling or blame (the same rule
        the brain follows, `references/brain-schema.md`);
      - **role-boundary-aware phrasing** — the lens advises; it never grants permissions;
      - **gitos vocabulary** — speak in the engine's terms (roles, work-orders, brain, home);
      - **concise directive tone** — the imperative voice of the rest of `references/`.

      Raw prompts are never stored. What lands on disk is always the reframed lens.
   c. **Extract / interview** for the frontmatter: `name`, `domain`, `tags`, `when-to-apply`,
      `applies-to`, `source`. Ask the operator for anything the prompt doesn't supply.
   d. **CONFIRM with the operator.** Show the normalized lens + frontmatter and have the
      operator sign off — it is their expertise, so they own the reframe. Revise and re-show
      if they object. Do not write until they confirm.
   e. **Write** `<home>/agents/<name>.md` (frontmatter + normalized body). If `<name>` already
      exists, confirm overwrite or pick a new name — **no silent clobber**.
   f. **Catalogue** — add or refresh the row in `<home>/agents/index.md`.
3. **Report** what was imported (names, where they landed, the registry rows added).

## `/gitos agent list`

Print the `<home>/agents/index.md` registry — name · domain · when-to-apply · applies-to. If
the registry is empty, say so (no lenses imported yet).

## Boundary rule (load-bearing)

**A lens never expands a role's permissions.** It steers reasoning; it does not unlock
actions. A read-only diagnostic that pulls a math lens stays **read-only**. A scoped
implementer that pulls a domain lens stays **scoped to its work-order**. The lens advises
*how* to think within the boundary the role already has — it cannot move that boundary.

## Frontmatter schema

Each lens file `<home>/agents/<name>.md` carries this frontmatter, then the normalized prompt
as body:

```
---
name: <kebab-case-name>
domain: <short domain label, e.g. "quantitative-math">
tags: [<tag>, <tag>]
when-to-apply: <one line — the trigger a role checks its current work against>
applies-to: any            # or an explicit list, e.g. [orchestrator, diagnostic]
source: <where it was imported from — path/URL, for provenance>
imported: <YYYY-MM-DD>
---

<the operator's prompt, normalized into the gitos idiom — domain substance preserved, framing
standardized: forward-positive (cause + correction, no dwelling/blame), role-boundary-aware,
gitos vocabulary, concise directive tone>
```

## Relationship to the brain

Lenses are operator-authored **approach**, cross-linkable from the brain but never stored as
brain pages — the brain holds facts, a lens holds how to work a domain.
