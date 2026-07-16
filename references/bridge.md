# The BRIDGE contract — how a Custom repo wraps the engine upgrade

A **BRIDGE** is the one-way seam (engine → product) that keeps a downstream product's
*engine* current with the upstream GitOS skill while never touching the product's *profile*
or project state. The engine's `upgrade` procedure (`references/upgrade.md`) classifies a
repo as **Standard** or **Custom**; a Custom repo is one that has a BRIDGE, and the upgrade
hands control to it. This page is the contract every BRIDGE must satisfy.

> **A BRIDGE is a thin wrapper, not a second upgrade.** It adds only the three things the
> generic procedure cannot know — what to SYNC, PRESERVE, and MERGE for *this* product — and
> then calls `upgrade.md`'s closing steps. It never re-implements detection, stamping, the
> ADR, or the report. There is exactly one copy of the upgrade logic; the BRIDGE references
> it.

This is the same invariant as the profile rule (`references/profiles.md`: *a profile adds
content on top of the engine; it never edits the engine*). The BRIDGE is where SYNC /
PRESERVE / MERGE live so the engine itself never has to know about any product.

## Required metadata block

Every BRIDGE opens with a frontmatter/metadata block the upgrade reads:

```yaml
---
bridge_schema: 1
profile: <name>            # the domain profile this bridge serves, e.g. finance
last_reconciled_engine: <N>   # the engine VERSION this repo was last reconciled to
min_compatible_engine: <N>    # the oldest engine VERSION whose directives this bridge still satisfies
---
```

- **`bridge_schema`** — the version of *this contract* the BRIDGE was written against (`1`).
- **`profile`** — the domain profile name (links the BRIDGE to its profile content).
- **`last_reconciled_engine`** — set by the upgrade's stamp step on every successful run; a
  no-op shortcut (target == this → nothing to do). This is the same value the upgrade stamps
  as `engine_version` in `<home>/brain/.brainmeta.json` — see the naming note below.
- **`min_compatible_engine`** — the floor used by the version-gap check. The upgrade WARNS
  when a jump crosses a declared breaking boundary: **an upgrade crosses a breaking boundary
  iff some `breaking: yes` version exists in the range `(min_compatible_engine, target]`** of
  the skill's `CHANGELOG.md`. A full per-version migration matrix is out of scope — this pair
  is the whole version-compat surface.

## The three required sections

A BRIDGE must declare these three, in this order. The finance product's BRIDGE is the
canonical worked example.

1. **SYNC** — the agnostic engine files to refresh from the skill, as a table mapping each
   downstream file to its skill upstream source. The engine briefs are home-agnostic, so this
   is a content copy with no per-folder path surgery (substitute any `<proj>` placeholder with
   the repo's package name). *Finance example:* `prompts/orchestrator_agent.md` ←
   `references/roles/orchestrator.md`, `prompts/AGENT_SYSTEM.md` ← `references/agent-system.md`,
   `prompts/brain_schema.md` ← `references/brain-schema.md`, `<home>/tools/brain_lint.py` ←
   `scripts/brain_lint.py` (byte-copy).
2. **PRESERVE** — the files the BRIDGE must never overwrite, re-sync, or reformat: the domain
   profile and this project's state. *Finance example:* the deployment contract + gate posture
   + finance anomaly families (profile), and the filled handoff, brain pages, `INDEX.md`, the
   work-order ledger (`work-orders/`, `resolved/`), and the operator's imported lens library +
   registry (`<home>/agents/`, `<home>/agents/index.md`) (state) — so an engine re-sync never
   clobbers imported lenses.
3. **MERGE** — the files that are part profile, part shared engine scaffolding, refreshed
   surgically: keep the bespoke profile content, refresh only the shared engine scaffolding,
   and diff before/after to confirm the profile content survived. *Finance example:* the one
   file `prompts/diagnostic_agent.md` — keep its finance anomaly families + Configuration
   block, refresh only the work-order template + `## Implementer notes` section + role-boundary
   table. **Also `CLAUDE.md`:** the repo-root file is profile-owned (it carries `_meta` + project
   instructions), but the `<!-- gitos:agent-system -->` block inside it is engine-managed —
   refresh *only* that block (the canary's durable anchor), preserve everything outside the markers.

## Then the wrapped `upgrade` finishes the job

After SYNC / PRESERVE / MERGE, the BRIDGE hands off to `references/upgrade.md` for the closing
steps — **stamp** the synced version (which writes `last_reconciled_engine`), **ADR + log**,
and **report** the `git diff` (engine files + stamp + ADR only; profile and state untouched;
layout unchanged). If the repo's stamp already equals the skill's `ENGINE_VERSION`, report
"engine up to date (vN)" and stop — the whole BRIDGE is a no-op when nothing upstream changed.

## The `_meta.bridge` pointer convention

So the upgrade can find a BRIDGE deterministically (rather than relying on the path scan), a
Custom repo declares a pointer:

- **Human-visible source of truth:** add `_meta.bridge: <repo-relative path to BRIDGE.md>` to
  the repo-root `CLAUDE.md` `_meta` block — **outside the `<!-- gitos:agent-system -->`
  markers**. That block is engine-managed and is refreshed in place by `scaffold.py` /
  `/gitos upgrade`; only content *outside* the markers is guaranteed untouched. (A refresh
  carries unrecognized in-block lines through and reports them rather than dropping them —
  but the `_meta` block is profile-owned, so keep it out of the engine's block entirely.)
- **Agent fast-path mirror:** copy the same value into `<home>/brain/.brainmeta.json` so an
  agent resolves it without parsing `CLAUDE.md`.

The upgrade reads the pointer first; if it is absent or unreadable it falls back to scanning
`<root>/BRIDGE.md` → `<root>/prompts/BRIDGE.md` → `<home>/BRIDGE.md`. Setting the pointer is
how a deployed repo upgrades from "guessed by scan" to "known by pointer".

> **Naming note (one concept, historical aliases).** "The engine version this repo last
> reconciled to" appears under more than one name: `last_reconciled_engine` (this contract),
> `engine_version` (`.brainmeta.json`, stamped by `upgrade` Step 5), and `_meta.engine_version`
> (some products' `CLAUDE.md`). They are the same value. This contract treats
> `last_reconciled_engine` as canonical for the bridge; deduping the aliases in a product's own
> files is downstream profile work, not an engine change.
