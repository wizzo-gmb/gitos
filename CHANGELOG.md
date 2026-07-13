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

## v14 — 2026-07-13
breaking: no

The canary system (WO-027) — cheap, always-on early-warning for the two places AI drift
accumulates. **State:** new `scripts/canary.py` (payload; stdlib-only, read-only, the
`brain_lint` invocation/report contract) deterministically checks the *home state layer* none of
the existing watchers cover — INDEX ↔ work-order files (stale / orphan / duplicate rows),
`.brainmeta.json` counts vs on-disk pages + ahead-stamps, lens registries on both layers
(rows ↔ files, `name` = filename, `applies-to` list-form), link rot in `INDEX.md` + open WOs —
and delegates to `brain_lint` when a brain exists; parse failure = finding, skipped checks report
as skipped, never false-CLEAN. Exit 0 = CLEAN / 1 = findings (a deliberate divergence from
`brain_lint`'s reporter semantics: the gate needs red/green). Strictness: **report at bootstrap,
gate at resolution** — the orchestrator runs it at first-action (one line: `canary: CLEAN`, or
findings-first, forward-positive) and may not resolve a work-order while it is red (joins
verify-before-commit). **Context:** `SKILL.md` gains a `## Canary` section (the SSOT) + a
one-line echo in all four role briefs — every reply opens with the **stateful marker**
`[gitos · <role> · <focus>]` (recomputed each reply: WO + work-loop/lifecycle step / phase /
interview stage), so a missing, wrong-role, or stale marker is live evidence of context
degradation; slippage → directive reinjection, a second slip in the same window → checkpoint +
fresh window; honesty clause (the slipped agent is the least reliable detector of its own slip —
the operator's first-line glance is the primary monitor). An operator may opt out per repo
(reduces coverage to state-only). `/gitos canary` runs both on demand. `scripts/scaffold.py`
lays `<home>/tools/canary.py` on fresh scaffolds and `upgrade` step 4 copies it into existing
homes (the `brain_lint` pattern; never clobber); selftest gains gate 9 (seeded clean home
silent, six seeded defect classes each caught — dev-only). Additive — a repo that ignores the
marker just has no context canary.

## v13 — 2026-07-02
breaking: no

Lens distribution model (WO-026; completes v12). `/gitos agent import` now writes each lens to **both
layers by default** — the current repo's `<home>/agents/` (git-tracked, travels with the repo) *and*
the global `<skill>/agents/` (the machine-wide distribution hub) — with repo-only / global-only on
request. `/gitos upgrade` gains a **lens-refresh step**: for each repo lens that also exists globally,
byte-compare and report-and-ask to refresh the repo copy from the global (a deliberately-forked local
variant survives by declining — never a silent clobber), then offer any global lens not yet in the
repo. Read-time collision rule unchanged (repo wins). Scaffolded lens-registry template mentions the
global layer. Additive — no global library / no repo lenses → the new steps no-op.

## v12 — 2026-07-02
breaking: no

Global lens library (WO-025). Lenses now resolve from **two layers**: the repo's own `<home>/agents/`
(v11) plus an operator-maintained **global library** at `<skill>/agents/` — the installed skill's own
`agents/` directory, catalogued in `<skill>/agents/index.md` — whose lenses apply in *every* repo the
skill runs on, no per-repo copying. Roles check both registries; on a name collision the repo's lens
wins (more specific). Same boundary rules on both layers. `/gitos agent import` gains a global
destination ("import globally"); `list` prints both registries labeled by layer. The global library is
**operator content**: engine updates never ship, overwrite, or delete it (the dev→live sync's mirror
mode now explicitly protects `<live>/agents/`). SKILL.md Lenses section + the four role-brief echoes
extended. Additive — a skill install with no `agents/` behaves exactly as v11.

## v11 — 2026-06-27
breaking: no

Steering lenses (WO-023). Operators can import their own specialist prompts as domain-tagged **lenses**
(`/gitos agent import <path>`), stored under `<home>/agents/` and catalogued in `<home>/agents/index.md`.
Any of the four roles reads a lens whose domain matches its current work and folds the guidance in
**within its role boundary** — injected context, not a dispatched role: a read-only role stays read-only,
a scoped implementer stays scoped. On import the **orchestrator normalizes** each prompt into the gitos
idiom (forward-positive framing, role-boundary-aware phrasing, standard vocabulary), preserving the
operator's domain substance; the operator confirms the reframe (raw prompts are never stored as-is), and a
`source` field keeps provenance. A new `references/agent-import.md` brief + an `assets/` index template ship
with the engine; `scripts/scaffold.py` creates the `<home>/agents/` library + registry. Distinct from the
brain (a lens = how to approach a domain; the brain = the project's facts). Additive — a repo with no lenses
behaves exactly as before (empty registry = no-op); Custom repos preserve imported lenses across upgrades via
their BRIDGE PRESERVE set. Downstream adopts on upgrade.

## v10 — 2026-06-27
breaking: no

`upgrade` offers to pull the latest engine first (WO-022). `/gitos upgrade` reconciles a repo against
the **installed** engine (`~/.claude/skills/gitos/`), not GitHub — so a public user on a git-clone
install had to `git pull` the engine by hand before upgrading, and a bare `/gitos upgrade` would
no-op ("did it upgrade?"). v10 closes that: `references/upgrade.md` step 2 ("live-read the installed
engine") becomes **"refresh + live-read"** — if `~/.claude/skills/gitos/` is a git clone, the
procedure **reports intent and asks the operator** to `git -C ~/.claude/skills/gitos pull` before
reading the VERSION/briefs (never auto-pulls; notes that a session reload is what reloads the agent;
on "no" or a non-clone copied install it skips and upgrades as-installed). `SKILL.md`'s upgrade blurb
gains the same one-line note. Additive — the reconcile steps are unchanged; it front-loads an optional
engine refresh so "upgrade" can fetch-then-apply in one prompt. (Pairs with the README install moving
to a direct clone + an *Updating* section.)

## v9 — 2026-06-25
breaking: no

Post-landing revision loop (WO-021). A landed work-order had a channel *up* — **Implementer notes**
(implementer → orchestrator) — but none *back down* for the common case the operator flagged: a WO
lands, the operator verifies it, and wants a small change. With no in-WO place for that, a tweak meant
an out-of-band ask or a near-duplicate WO. v9 adds the return path, additively:
- `references/work-order-template.md` gains a **`## Revisions (post-landing)`** section: after a WO
  lands and the operator verifies it, the **orchestrator** writes the requested change as a scoped
  item, the **implementer** handles it on a re-dispatch (a fresh window on the same WO) and records the
  result — repeat per round until satisfied. A genuinely new direction stays a follow-up work-order,
  not a revision (the bloat guard).
- `references/roles/orchestrator.md` work-loop step 4 becomes **"verify → accept or revise"**: on
  revise, write the change into the WO's Revisions section and re-dispatch; don't resolve a WO the
  operator hasn't accepted.
- `references/roles/implementer.md` lifecycle step 1: on entry, **open `## Revisions` are your scope
  for this round** (else the Proposed fix scope is).
Additive — turns a landed WO into an iterable artifact (land → verify → revise → re-land) without a new
work-order for every tweak. Downstream adopts on upgrade (new WO files carry the section).

## v8 — 2026-06-23
breaking: no

Implementer is operator-enterable (WO-020). The implementer role was modeled as **dispatch-only**
("never entered, never invoked by user phrasing"), but the canonical workflow opens a *fresh window
on one work-order* and says "implement this" — which `SKILL.md`'s intent-routing fell through to the
**orchestrator**, so the agent assumed it drove the ledger. v8 reframes the implementer as entered on
**one work-order** — by orchestrator dispatch OR by an operator pointing a fresh window at it — and
adds the routing + signage to land there:
- `SKILL.md` First-action gains an **implementer-entry branch** ("implement/do THIS work-order" →
  Implementer: read that WO + plan-first, **not** the full orchestrator bootstrap); the role table and
  the "four-role" framing shift from "operator-entry / dispatched" to **repo-entry / work-order-entry**.
- `references/work-order-template.md` gains a **role-pointer banner** at the top of every WO file
  (opened to do the work → you are the Implementer; plan-first; scope = `## Proposed fix scope`).
- `references/roles/implementer.md` + `references/agent-system.md` reframe "dispatched, not entered"
  → "entered on a work-order, not on the repo" (dispatch or operator-pointed; same boundary).
Additive: the dispatch path and the implementer's scope boundary are unchanged — it only adds the
operator-direct entry the workflow already used. Downstream repos adopt on upgrade (new WO files carry
the banner; the routing fix covers WOs already on disk).

## v7 — 2026-06-22
breaking: no

No-fork directive for the diagnostic role (WO-017). `references/roles/diagnostic.md` gains a
**"Don't fork this role"** discipline rule (echoed in the Role-boundary "You DO NOT" column): the
diagnostic role is owned by the engine brief + the repo's profile `prompts/diagnostic_agent.md` (Custom
repos) + an optional in-home `<home>/DIAGNOSTIC_AGENT_BRIEF.md`, and must **not** be re-implemented
outside those homes — not as a project-local `.claude/skills/*` debug/triage skill, a repo-root
`*_AGENT_BRIEF.md`, or a stray duplicate `diagnostic_agent.md`/`debug_agent.md` that splits the role's
source of truth. When a fork exists, **migrate its durable knowledge into the profile/brain FIRST, then
retire it** (reversible via a branch); never delete load-bearing contracts before they are migrated.
`references/roles/orchestrator.md` gains a one-line intake watch that opens a migrate-then-retire
work-order when a fork is spotted. Additive — no existing directive/contract is removed, and a repo that
already doesn't fork is a no-op (WO-013's repos already comply). Promotes WO-013's spawned consideration.

## v6 — 2026-06-22
breaking: no

Hardened orchestrator work loop (WO-016). `references/roles/orchestrator.md` gains an explicit
**"The work loop"** section (after *First action*) — an ordered, gated spine that makes the role's
previously-implicit per-session / per-work-order cadence checkable. The gates are non-skippable
operator-control + correctness points: **the operator confirms proposed work-orders before any are
activated/dispatched** (the brake on runaway work-order creation), plan-approved + disjoint-files +
scope-bound before any edit, verify-the-diff before commit, and never-advance-with-anything-half-done.
**Window topology** (fresh-per-WO vs. batching similar work vs. sequence/parallel) is explicitly left
to the orchestrator's judgment — an optimization, not a rule. Additive: it makes existing-good
behaviour explicit and harder to skip; no role behaviour is removed, so a repo on an older engine
keeps prior behaviour until it upgrades. Adopted cleanly on upgrade.

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
