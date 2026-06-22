# GitOS engine — CHANGELOG

One entry per `VERSION` bump (the integer in `VERSION` at the repo root is the engine
version; each bump adds exactly one entry here, newest first).

**Bump rule.** `VERSION` increments by +1 on any change to engine *directives* (the
behaviour-governing payload: `SKILL.md`, `references/`, scaffold/upgrade behaviour). Pure
doc/cosmetic edits don't bump. (Rule pinned by the engine's version-bump-semantics
decision — WO-002.)

**`breaking:` flag.** Each entry carries `breaking: yes` or `breaking: no`. A version is
`breaking: yes` if adopting it requires a downstream repo to take migration action *beyond*
a clean directive adoption — it changes or removes an existing directive, contract, gate, or
profile-facing interface, so an un-migrated repo would behave incorrectly. `breaking: no` =
additive (new directives/capabilities that don't invalidate existing ones). The `upgrade`
flow reads these flags: an upgrade crosses a breaking boundary iff some `breaking: yes`
version exists in the range `(min_compatible_engine, target_version]`.

---

## v5 — 2026-06-20
breaking: no

Two engine-directive changes.

**Ensure version control (WO-011).** `scripts/scaffold.py --git ensure` (now the default) and the
orchestrator's first-action **auto-init git when none is detected** — robust detection (`.git` as a
dir or file, or a parent work-tree via `rev-parse`), a report printed *before* any git runs, then
`git init` + a starter `.gitignore`/`.gitattributes` (`* text=auto`); the inception agent makes the
baseline commit. `--git skip` opts out; `offer` is the legacy recommend-only mode. **Behavior change:
the engine now RUNS `git init`** (it previously only offered). Additive — a repo already under git is
a no-op, and a fresh init is a safe guarantee, not a migration.

**Forward-positive brain invariant (WO-012).** `references/brain-schema.md` §6 gains a "no
self-pollution" rule: brain pages stay factual and forward-useful (capture cause + correction; valid
issue-records — findings, bug work-orders, lessons — stay), with no dwelling/blame/negative
editorializing. Semantic, so it is enforced in the orchestrator's reflection pass, not `brain_lint`.

Additive overall; downstream repos adopt both directives on upgrade.

## v4 — 2026-06-20
breaking: no

Define the implementer as a fourth, dispatched role (WO-009). Adds
`references/roles/implementer.md` — the single source of truth for the dispatched implementer's
definition + boundary (the `specified-vs-self-designed` rule from v3's WO-007, now with one home).
The three former restatement sites (the SKILL.md dispatch section, the orchestrator brief's
"Dispatch + verify", and the work-order template's "Proposed fix scope") are consolidated to a
one-line application + a pointer to the brief. Reframes the role model to **four defined roles in
two tiers** — three operator-entry (inception/orchestrator/diagnostic) + one dispatched
(implementer) — across `SKILL.md`, `references/agent-system.md`, `references/profiles.md`, and a
new `references/glossary.md` entry. Additive: no implementer *behaviour* changes (definition +
consolidation only); no `.gitos/roles/` pointer and no scaffold change, since you never resume as
an implementer.

## v3 — 2026-06-20
breaking: no

Role-boundary hardening (WO-006 + WO-007) — extends the find/fix separation to the
orchestrator and implementer sides so every edit traces back to a specified work-order.
**WO-006:** the orchestrator now writes **no code, ever** — every executable change
(application source AND pipeline tooling under `.gitos/tools/`, `scripts/`) is dispatched to
an implementer; the orchestrator writes only markdown/state (work-orders, INDEX, brain, role
pointers, handoff). Removes the prior "you write code" / "may edit code" authorization from the
orchestrator brief and the SKILL.md role-boundary table, and tightens the agent-system
Four-Artifacts map (`Code` = Implementers only, never the orchestrator). **WO-007:** an
implementer edits **only what its work-order's Proposed fix scope specifies** — out-of-scope
edits (INDEX, brain, other work-orders, directives) are the orchestrator's, surfaced by the
implementer as proposed notes/follow-ups, never self-executed; stated in the SKILL.md dispatch
section, the orchestrator brief's "Dispatch + verify", and the work-order template. Additive
tightening of directive guidance — adopted cleanly on upgrade with no migration action, so a
repo on an older engine keeps prior behaviour until it upgrades.

## v2 — 2026-06-19
breaking: no

BRIDGE-aware upgrade (WO-005). `references/upgrade.md` gains a **Step 0** that classifies a repo
as Standard (engine-only) or Custom (profiled product) and routes Custom repos through their
`BRIDGE.md` (SYNC/PRESERVE/MERGE) instead of the generic engine-only path; a Custom-but-unbridged
repo HALTs rather than risk overwriting deployed profile/state. Adds the BRIDGE contract
(`references/bridge.md`), the `_meta.bridge` pointer convention, the Custom-only version-gap
warning (reads `CHANGELOG.md` `breaking:` flags against the bridge's `min_compatible_engine`), and
a gated `scripts/scaffold.py` stamp of `bridge` / `last_reconciled_engine` / `min_compatible_engine`
into `.brainmeta.json` when a profile BRIDGE is present. Additive: Standard repos fall straight
through steps 1–7 unchanged, and the new HALT is a safe refusal — no already-correct repo must
migrate.

## v1 — 2026-06-19
breaking: no

Baseline — the engine state at this repo's inception (the recursive self-bootstrap, when
gitos was first brought under its own pipeline). Includes the three-role system (inception /
orchestrator / diagnostic) plus the per-repo brain, the `.gitos/` home,
`scripts/scaffold.py`, `scripts/brain_lint.py`, and the `references/` directive tree. First
recorded version; no predecessor to migrate from.
