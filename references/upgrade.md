# The `upgrade` procedure — adopt the latest engine directives

This is the **canonical, single home of the upgrade logic**. It runs inside a live
orchestrator chat session against the **current** repo and brings that repo onto the
latest GitOS engine. It is home-agnostic and idempotent.

> **It changes the *directive*, never the folder layout.** A deployed repo's
> orchestrator already knows where its own state lives. Upgrading delivers the latest
> *behavioral* directives; the orchestrator applies them to whatever home it already has
> (`.gitos/`, `.pipeline/`, or the legacy split `outputs/debug/` + `outputs/brain/`). **No
> file is moved.** For general repos this procedure *is* the upgrade. A downstream product
> with a domain profile wraps this procedure (via its own engine-sync bridge, e.g. a
> `BRIDGE.md`) to add its own sync/preserve/merge — it never re-implements these steps.

## When to run it

- The user asks to "upgrade this repo's engine" / "update the gitos directive" (the
  `SKILL.md` router sends that intent here), or
- the orchestrator's first-action drift check reports the skill's `ENGINE_VERSION` is
  ahead of the repo's stamped `engine_version`.

## Procedure

**0. Classify the repo — Standard or Custom — before doing anything else.**
The generic steps below are safe on a *Standard* repo (engine only). A *Custom* repo
carries a domain profile + deployed project state that the generic path must never touch;
its **BRIDGE** owns what to SYNC / PRESERVE / MERGE. So first decide which you are in.

*Detection (pointer-first, scan-fallback — stop at the first rule that resolves):*

- **a. Pointer.** Read the `_meta.bridge` pointer — from the repo-root `CLAUDE.md` `_meta`
  block and/or `<home>/brain/.brainmeta.json` (the agent fast-path mirror). If it is present
  and resolves to a **readable** file → **Custom** (the bridge is that file). Done.
- **b. Scan.** Else look, **in this order**, for: `<root>/BRIDGE.md`, then
  `<root>/prompts/BRIDGE.md`, then `<home>/BRIDGE.md`. First file that exists → **Custom**
  (record which path matched, for the report). Done.
- **c. Profile markers.** Else check for other signs of a domain profile: a filled
  `_meta.inception_template_version` (non-placeholder), a `prompts/` profile tree, or a
  declared domain profile. If **any** marker is present but **no** bridge was found in (a)/(b)
  → **Custom-but-unbridged** → **HALT** (see the HALT message below). Do not run steps 1–7.
- **d. Standard.** Else → **Standard**.

*On **Standard**:* fall through to steps 1–7 unchanged. This procedure *is* the upgrade.

*On **Custom**:* the engine does **not** itself SYNC, PRESERVE, or MERGE — the BRIDGE owns
those, because only it knows the profile's preserve list and merge seams. Hand control to
the repo's resolved `BRIDGE.md`: it wraps this procedure, performs its SYNC/PRESERVE/MERGE,
and then finishes via steps 1–7 (stamp, ADR + log, report). Do not run the generic steps
yourself first — the bridge calls them. The BRIDGE contract is `references/bridge.md`.

  *Version-gap check (do this once the bridge has resolved, before handing off).* Read the
  skill's `ENGINE_VERSION` (the integer in `~/.claude/skills/gitos/VERSION`) as the target,
  and the bridge's `last_reconciled_engine` + `min_compatible_engine`. If the target equals
  `last_reconciled_engine`, the bridge is a no-op (nothing upstream changed). Otherwise
  consult the skill's `CHANGELOG.md`: **an upgrade crosses a breaking boundary iff some
  `breaking: yes` version exists in the range `(min_compatible_engine, target]`.** If it
  does, **WARN** before proceeding — name the offending `breaking: yes` version(s) and tell
  the operator to re-read those CHANGELOG entries and confirm the bridge's PRESERVE/MERGE
  rules still hold for them. The warning does not halt; it makes the operator look before
  the bridge runs. (A full per-version migration matrix is out of scope.)

*HALT message (print verbatim on a Custom-but-unbridged repo):*

```
HALT — this repo looks like a Custom (profiled) deployment but has no BRIDGE.

Why I stopped: a domain profile and/or project state is present here, but I could not
resolve a BRIDGE.md. The BRIDGE is a hard prerequisite for upgrading a Custom repo: it
is the only place that records what to SYNC (engine files to refresh), what to PRESERVE
(your profile + project state — gates, contract, brain pages, work-order ledger), and
what to MERGE (files that are part profile, part engine). Without it I cannot tell your
deployed state apart from engine scaffolding, so running the generic upgrade could
overwrite profile content and project state. I refuse the generic path.

What I checked:
  - _meta.bridge pointer in <root>/CLAUDE.md and <home>/brain/.brainmeta.json — not set
    (or did not resolve to a readable file).
  - <root>/BRIDGE.md            — not found
  - <root>/prompts/BRIDGE.md    — not found
  - <home>/BRIDGE.md            — not found

To proceed, author and stamp a BRIDGE:
  1. Write a BRIDGE.md following the engine's bridge contract:
     ~/.claude/skills/gitos/references/bridge.md
     (required sections SYNC / PRESERVE / MERGE + the metadata block with
      bridge_schema, profile, last_reconciled_engine, min_compatible_engine).
  2. Put it at one of the scanned paths above, OR set the pointer so I can find it:
     add `_meta.bridge: <repo-relative path to BRIDGE.md>` to <root>/CLAUDE.md's
     _meta block (human-visible), and mirror the same value into
     <home>/brain/.brainmeta.json (the agent fast-path).
  3. Re-run the upgrade. I will classify the repo as Custom and route through the BRIDGE.

If this repo is genuinely Standard (engine-only, no profile/state to protect), the
profile marker I tripped on is a false positive — remove/clear it (e.g. an unfilled
_meta.inception_template_version placeholder) and re-run.
```

**1. Detect the repo's home and read its stamped version.**
Resolve `<home>` by the standard detection order (`.gitos/` → `.pipeline/` →
`outputs/debug/`). Read the repo's stamped `engine_version` from
`<home>/brain/.brainmeta.json` (`engine_version` field) — or, for a general repo without
a brain, from `<home>/handoff.md`. A repo with no stamp is treated as version `0`.

**2. Refresh + live-read the installed engine.**
First, **offer to pull the latest engine from its remote.** If the installed skill is a git clone
— `~/.claude/skills/gitos/.git` exists (a dir or a file) — a newer engine may be available upstream
that this install hasn't fetched. **Report intent, then ask the operator** before running anything
(never auto-pull):

> "Your installed gitos engine is a git clone. Pull the latest from its remote before I upgrade this
> repo? — `git -C ~/.claude/skills/gitos pull`. (Recommended — otherwise I upgrade against the engine
> exactly as installed.)"

On **yes**: run `git -C ~/.claude/skills/gitos pull` and report the result (the `VERSION` delta, or
"already up to date"). If the pull brought a newer engine, note that a **session reload** is what
makes the *agent* load the new skill — but the steps below still adopt the latest by reading the
refreshed files from disk, so the per-repo upgrade applies either way. On **no** — or if
`~/.claude/skills/gitos/` is **not** a git clone (a copied install: nothing to pull; updating means
re-cloning / re-copying, see the README's *Updating*) — skip the pull and proceed.

Then read `~/.claude/skills/gitos/VERSION` (the current `ENGINE_VERSION`) and the canonical brief
(`~/.claude/skills/gitos/SKILL.md` + the role briefs under `~/.claude/skills/gitos/references/`).

**3. If already current → stop (idempotent).**
If the repo's stamp equals the skill's `ENGINE_VERSION`, report **"engine up to date
(vN)"** and stop. Running again with no upstream change is a no-op.

**4. Adopt the latest directives.**
Direct the running orchestrator to:
- **re-read the canonical brief** (`SKILL.md` + `references/roles/orchestrator.md` +
  `references/agent-system.md`) and adopt any new behaviors — for example, the
  **implementer-notes accept/reject loop** (have each implementer fill the work-order's
  `## Implementer notes` on completion; on landing, harvest and adjudicate them: ACCEPT —
  route durable facts to the brain, lessons into dispatch, follow-ups into new
  work-orders — or REJECT with a one-line reason);
- **re-point any stale role pointers** — if a role pointer or the memory pointer still
  names an old skill path or the legacy `project_flow_role_brief.md`, repoint it to
  `~/.claude/skills/gitos/...` and `gitos_role_brief.md`;
- **copy `brain_lint` into the home if missing** — ensure `<home>/tools/brain_lint.py`
  exists (byte-copy from `~/.claude/skills/gitos/scripts/brain_lint.py`); never clobber an
  existing copy.

**5. Stamp the new version.**
Write the skill's `ENGINE_VERSION` back as the repo's `engine_version`:
`<home>/brain/.brainmeta.json` (`engine_version` field) for a repo with a brain, else
`<home>/handoff.md`.

**6. Record an ADR + a log line.**
Add a decision page `<home>/brain/wiki/decisions/engine-upgrade-vN.md` recording: the
from→to versions, which directives were adopted, and any pointers re-pointed. Append a
`wiki/log.md` line (`engine upgrade vM → vN`).

**7. Report.**
Show the `git diff` of what changed (the re-pointed pointers, the stamp, the ADR, any
newly-copied `brain_lint`). The folder layout is unchanged — confirm that explicitly in
the report.

## What it never does

- It never relocates or renames the home (`.pipeline/` and `outputs/debug/` stay where
  they are).
- It never edits a downstream product's domain profile or project state — a wrapper
  (the product's own engine-sync bridge, e.g. a `BRIDGE.md`) owns that and calls this
  procedure for the engine part.
- It is the only copy of the upgrade logic. Wrappers reference it; they do not duplicate
  these steps.
