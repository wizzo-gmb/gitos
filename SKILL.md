---
name: gitos
description: >-
  Bootstrap, coordinate, or investigate work on ANY software repo (web, CLI, ML,
  data pipeline, library, service). Use this whenever the user wants to (a) set up
  / initialize / "bootstrap" a repo's working pipeline or agent system — "init this
  repo", "set up the work-order system", "establish the orchestrator", "give this
  project a brain", "scaffold the debug system"; (b) coordinate or drive ongoing
  development — "start working on this repo", "what should I do next", "drive this
  project", "plan and dispatch the next steps", prioritize work; or (c) run a
  read-only diagnostic pass — "audit this", "find bugs in X", "diagnose this
  system", "inspect the logs", "what's wrong with our pipeline". It stands up a
  3-role system (inception bootstrapper, orchestrator coordinator + front-line
  builder, read-only diagnostic finder) plus a per-repo brain (memory), under a
  `.gitos/` work-order ledger. Trigger even when the user doesn't say
  "gitos" or "pipeline" but is clearly starting, driving, or auditing a repo.
  Do NOT trigger for a single known-bug fix ("why is this variable null"), a narrow
  review of one small diff, or a pure design discussion with no repo work. PIPELINE
  ONLY — it sets up the working SYSTEM, not your application's source code.
---

# GitOS

A project operating-system skill. It bootstraps and runs a four-role agent system (three repo-entry roles + an implementer entered on a single work-order)
on any repo, backed by a per-repo **brain** (the orchestrator's memory). SKILL.md is
the **router**: it tells you what mode you're in and which reference to open. All the
detail lives in `references/` — keep this file lean and follow the pointers.

## The roles + the brain

| Mode | When you're in it | Read |
|---|---|---|
| **Inception** | The repo has no pipeline yet — first-time setup | `references/roles/inception.md` |
| **Orchestrator** | A pipeline exists; you're building / driving / deciding *with* the user | `references/roles/orchestrator.md` |
| **Diagnostic** | You're investigating read-only — auditing, finding bugs, cataloging anomalies | `references/roles/diagnostic.md` |
| **Implementer** | You're handed **one work-order** to land — by an orchestrator dispatch *or* by the operator pointing a fresh window at that WO ("implement this", "do `wo_046`") | `references/roles/implementer.md` |

The **brain** (`.gitos/brain/`) is the orchestrator's long-term memory — a
self-contained knowledge vault of typed, cross-linked pages (sources / entities /
concepts / decisions). It's seeded at inception and grown by the orchestrator as it
works. Schema + the maintenance/anti-redundancy protocol: `references/brain-schema.md`.

`references/agent-system.md` is the one-page map of how the roles + the brain
relate. Read it if the picture isn't clear.

## First action: detect state, then route

Whatever the user said, resolve it to exactly one mode by detecting whether the repo
is initialized. This is the single entry point — "start working on this repo" always
lands somewhere.

```dot
digraph route {
  detect [shape=diamond, label="pipeline scaffolded?"];
  inception [shape=box]; orchestrator [shape=box]; diagnostic [shape=box];
  brain [shape=box, label="seed brain"]; handoff [shape=box, label="write handoff"];

  detect -> inception   [label="no (.gitos/, .pipeline/, outputs/debug/ all absent)"];
  inception -> brain -> handoff -> orchestrator;
  detect -> intent      [label="yes — read INDEX + handoff + brain/wiki/index"];
  intent [shape=diamond, label="user intent?"];
  implementer [shape=box];
  intent -> orchestrator [label="build / drive / plan / 'what next'"];
  intent -> diagnostic   [label="audit / find bugs / investigate"];
  intent -> implementer  [label="\"implement / do THIS work-order\" (pointed at one WO)"];
  orchestrator -> diagnostic [label="invoke read-only finder for evidence"];
  diagnostic -> orchestrator [label="return work-orders"];
  orchestrator -> implementers [label="dispatch + verify"];
  orchestrator -> brain [label="read / query / update (maintenance loop)"];
}
```

Detection procedure (deterministic, in order):
1. `<root>/.gitos/` exists → **initialized**. The home is `.gitos/` (the unified default).
2. else `<root>/.pipeline/` exists → **initialized (legacy home)**. The home is
   `.pipeline/`; everything below works unchanged.
3. else `<root>/outputs/debug/INDEX.md` exists → **initialized (legacy home)**. The
   home is `outputs/debug/`; everything below works unchanged.
4. else a memory pointer exists at `~/.claude/projects/<project-dir>/memory/` named
   `gitos_role_brief.md` **or** the legacy `diagnostic_role_brief.md` → read
   it; it names the home and default role.
5. else → **uninitialized** → Inception.

On an initialized repo, before acting, read `<home>/INDEX.md` (work state),
`<home>/handoff.md` (the birth record, once), and — if a brain exists —
`<home>/brain/wiki/index.md` (knowledge state). Then route on intent.

**Implementer entry — the common "fresh window on a work-order" case.** If the operator points you
at *one specific work-order to execute it* ("implement `wo_046`", "do this WO", a new window opened on
a single work-order file), you are the **Implementer**, not the orchestrator. Do **not** bootstrap the
full orchestrator context or assume you drive the ledger — read **that work-order in full** (plus any
brain page it cites), **plan first → then execute**, edit **only** its `## Proposed fix scope`, and
fill its `## Implementer notes`. The orchestrator is the *persistent* window that coordinates; an
implementer window lands one order and returns. Full brief: `references/roles/implementer.md`.

## Role: Inception (one-time)

Bootstrap an uninitialized repo. Briefly: run a short interview (project identity,
acceptance criteria, hold-out discipline, outcome definition, production target y/n,
predecessor lessons, **brain ingest depth**), run `scripts/scaffold.py` to lay the
`.gitos/` tree + the brain, **seed the brain** at the chosen depth (minimal /
moderate / aggressive), fill `handoff.md`, ensure version control (auto-init git if
absent, after reporting intent), then hand control to the orchestrator in the same
session. It does NOT write application source. Full procedure:
`references/roles/inception.md`.

## Role: Orchestrator (ongoing — the front-line builder)

The agent that builds *with* the user and coordinates the work. Each session it reads
the handoff (once), `INDEX.md`, and the brain. It owns the four INDEX sections + the
work-order lifecycle; authors forward work-orders; invokes the diagnostic finder for
evidence; dispatches + verifies implementer agents; and **stewards the brain via the
maintenance loop** (inline upsert → checkpoint reconcile → `brain_lint.py`), recording
a decision page on every non-trivial choice. It MAY authorize edits (unlike the
read-only diagnostic). Full brief: `references/roles/orchestrator.md`.

## Role: Diagnostic (read-only finder)

Investigate without editing. Three phases: build the log/output **vocabulary** →
**scan** the anomaly families (`references/anomaly-families.md`) → write evidence-first
**work-orders** (`references/work-order-template.md`). Full brief:
`references/roles/diagnostic.md`.

## Role-boundary table

The most important invariant is that *finding* is separated from *fixing* — so the
read-only finder can never be pressured into edits mid-investigation.

| Role | May edit code? | Owns | Read this for the full table |
|---|---|---|---|
| Inception | scaffolds once, then hands off | the initial `.gitos/` + brain | `references/roles/inception.md` |
| Orchestrator | no — dispatches all code edits; writes only markdown/state (stewards the brain) | INDEX lifecycle + brain | `references/roles/orchestrator.md` |
| Diagnostic | **no** — read-only, work-orders only | the vocabulary + open findings | `references/roles/diagnostic.md` |
| Implementer (dispatched) | yes — but only the files its work-order's Proposed fix scope names | its specified edits + the Implementer notes | `references/roles/implementer.md` |

## Severity calibration (shared by diagnostic findings + orchestrator triage)

- **critical** — user-facing safety, data corruption, production-down, money/PHI at risk.
- **high** — silent wrong outputs that drive decisions; broken isolation/security boundaries.
- **medium** — misleading logs, drift between calibration and deployment, latent risk.
- **low** — cosmetics, defensive cleanup.
- **unconfirmed** — anomaly seen but proof needs reproduction the agent can't run; also "needs operator decision".

Severity is about *consequence, not certainty*. Don't inflate to get attention; don't
downgrade to seem reasonable.

## Canary (always-on drift early-warning)

Two cheap sentinels catch AI drift where it accumulates — the home's **state** and the
window's **context**. This section is the SSOT; the four role briefs carry one-line echoes.

**State canary — `scripts/canary.py`.** Deterministic, read-only, stdlib-only checker for
the *home state layer* — the surface `brain_lint` (brain), selftest (payload), and
`path_guard` (publish) don't cover: INDEX ↔ work-order files (stale / orphan / duplicate
rows), `.brainmeta.json` counts vs on-disk pages + ahead-stamps, lens registries on both
layers (rows ↔ files, `name` = filename, `applies-to` list-form), link rot in `INDEX.md` +
open WOs; delegates to `brain_lint` when a brain exists. Exit 0 = CLEAN, 1 = findings.
No judgment calls, no false-CLEAN (a parse failure is a finding; a skipped check reports
as skipped); it reports and gates — it never edits (fixing a finding is normal
orchestrator/implementer work).

```
python <home>/tools/canary.py <home>      # home copy missing -> <skill>/scripts/canary.py
```

Strictness: **report at bootstrap, gate at resolution.** The orchestrator runs it at
first-action and reports one line — `canary: CLEAN`, or the findings first,
forward-positive (cause + correction: "counts.decisions=16, files=17 → set 17"). Findings
never block *starting* work; **no work-order is resolved while the canary is red** (the
gate joins verify-before-commit). Scope is home state only — domain artifacts (outputs,
data, logs) stay the diagnostic role's judgment territory.

**The gate binds on *actionable* findings — category descoping.** The canary encodes the
engine's own conventions as its defaults, and a healthy repo may legitimately differ. A
convention mismatch must never freeze a healthy ledger, so an operator (or a repo's BRIDGE,
under *Profile deviations*) may **descope a canary category** for that repo — recording the
deviation and its reason where the deviation lives. **A descoped category still reports; it
does not gate.** The finding stays visible (no false-CLEAN, nothing is silenced) while
resolution proceeds. Descoping is a local, recorded workaround for a convention the engine
does not yet tolerate — not a way to hide a real defect: descope the *category*, never the
individual finding, and the right durable fix is an upstream work-order that teaches the
canary the shape. A descoped category is a standing debt — re-scope it once the engine
tolerates the shape.

**Context canary — the role marker.** The first line of EVERY reply, in every role:

```
[gitos · <role> · <focus>]
```

Lowercase `gitos`, spaced middle dots (`·`), square brackets — one greppable pattern.
`<focus>` is **stateful: recomputed each reply, never copied forward**:

| Role | `<focus>` |
|---|---|
| orchestrator | current WO + work-loop step |
| implementer | current WO + lifecycle step |
| diagnostic | current phase (vocabulary / scan / work-orders) |
| inception | current interview stage (then phase, as inception proceeds) |

Compliance is trivial while the directive layer is intact — so a missing, wrong-role, or
stale marker is live evidence of context degradation (compaction loss, attention dilution,
role misroute). Rote copying shows up as staleness (wrong WO / wrong step): itself a
canary signal.

**Slippage protocol** — on a missing / wrong-role / stale marker, operator-noticed or
self-noticed:
1. **Directive reinjection.** Re-read your role brief + this file's routing, re-state your
   role + current focus, resume marking.
2. **Second slip in the same window** → recommend a checkpoint (commit state, update
   `INDEX.md`) and a **fresh window** — the context is degrading; reinjection alone may
   not restore fidelity.

**Honesty clause.** The slipped agent is the least reliable detector of its own slip; the
operator's one-glance check of the first line is the primary monitor. The marker is a
signal, not a guarantee.

**Durable anchor — closing the self-reference gap.** The marker directive lives in the skill
layer, which compaction summarizes away — so on its own it degrades in lockstep with what it
watches (a detector cannot detect its own absence). The recovery seed therefore *also* lives
in the **durable layer**: inception writes a managed `<!-- gitos:agent-system -->` block into
the repo-root `CLAUDE.md`, which the harness re-injects into **every** context window, carrying
the marker requirement + the trigger to re-read this file and run `canary.py`. Even after the
skill directive washes out, that block re-asserts the marker and points the way back; `upgrade`
refreshes it (managed-block upsert — never touching your content), and `canary.py` flags it
(`anchor/missing`, `anchor/stale`) if it goes missing or drifts. The "who watches the watcher"
recursion terminates at the **harness** (which guarantees `CLAUDE.md`) — the most durable layer
reachable. It raises the water line, not to omniscience: a bloated `CLAUDE.md` loses salience
too, so the block stays short and the operator's glance remains the final backstop.

The operator may opt out of the marker per repo — record the opt-out; it reduces canary
coverage to state-only.

**`/gitos canary`** — run both on demand: directive reinjection (re-read role brief +
routing, re-state role + focus) **and** `canary.py`; report context + state health in one
block.

## Scaffolding

```
python <SKILL_DIR>/scripts/scaffold.py <PROJECT_ROOT> [--brain {on,off}] [--domain <hint>] [--git {ensure,offer,skip}]
```
Idempotent — fills missing pieces, never overwrites state files. Confirm the detected
project root with the user before running; `--git ensure` (default) reports its intent
then runs `git init` if the repo isn't already under version control (`--git skip` opts
out). Detail: `references/roles/inception.md`.

## Upgrade (bring a repo onto the latest engine)

When the user says **"upgrade this repo's engine"**, **"update the gitos directive"**, or
runs the `upgrade` command, route to `references/upgrade.md`. It is the single, canonical
upgrade procedure: detect the repo's home + stamped `engine_version`, **offer to `git pull` the installed
engine first if it's a git clone** (so the latest is what gets applied), live-read the skill's
`VERSION`, and — if the skill is ahead — direct the orchestrator to adopt the latest
directives, re-point stale pointers, stamp the new version, and record an ADR. It changes
the *directive*, never the folder layout, and is idempotent (no upstream change → no-op).
Downstream products with a domain profile wrap this procedure rather than duplicating it.
The procedure's **Step 0** first classifies the repo: a **Standard** (engine-only) repo
falls straight through steps 1–7; a **Custom** (profiled) repo is routed to its `BRIDGE.md`,
which owns SYNC / PRESERVE / MERGE and then finishes via the same steps. A repo that looks
Custom but has no bridge **halts** — see `references/bridge.md` for the BRIDGE contract and
the `_meta.bridge` pointer convention.

## Lenses (operator-imported steering)

A repo may carry operator-imported **lenses** in `<home>/agents/` (default `.gitos/agents/`) —
domain-tagged specialist context the operator brought in (a math lens, a niche-research lens, …),
catalogued in `<home>/agents/index.md`. A lens is **injected context, not a dispatched role**:
whatever role you are in, when your current work matches a lens's `domain` / `when-to-apply`, read that
lens and fold its guidance into your work — **within your role's boundary**. A lens changes how you
*think* about a domain; it never changes what your role is *allowed to do* (a read-only role stays
read-only; a scoped implementer stays scoped). Lenses are operator-authored *approach* — distinct from
the brain, which holds the project's *facts*.

Lenses resolve from **two layers**: the repo's own `<home>/agents/` and the operator's **global lens
library** at `<skill>/agents/` — the installed skill's own `agents/` directory (registry
`<skill>/agents/index.md`), whose lenses are available in *every* repo the skill runs on with no
per-repo copying. Check both registries; on a name collision the repo's lens wins (more specific). The
same boundary rules govern both layers. The global library is **operator content**: engine updates
never ship, overwrite, or delete it. `agent import` writes to **both layers by default** (repo-only /
global-only on request), and `upgrade` **refreshes a repo's lens copies from the global library** —
report-and-ask, so a deliberate local variant survives by declining.

Manage them via `references/agent-import.md`:
- `/gitos agent import <path>` — import a prompt as a lens. The **orchestrator normalizes** it into the
  gitos idiom before storing (forward-positive framing, role-boundary-aware phrasing, standard
  vocabulary), preserving the operator's domain substance; the operator confirms the reframe. Raw
  prompts are never stored as-is.
- `/gitos agent list` — print the lens registry.

## When the user authorizes fixes / implementers

On "fix bug NNN" or "launch agents for these fixes": dispatch implementer agents,
each reading its work-order in full, scoped to **disjoint files** (different sections
of one file is not safe). When a work-order lists Options, pin which one each agent
uses. Each implementer edits **only what its work-order's Proposed fix scope specifies** —
full role + boundary in `references/roles/implementer.md`. Don't run shared-state-mutating
scripts from an implementer — verification is the operator's. After a fix lands: trust-but-verify (`git diff` / grep / read), move
the work-order to `resolved/`, update `INDEX.md` with the fix reference. The diagnostic
role's read-only invariant snaps back when the fix-scope is exhausted. Tell each
implementer to fill the work-order's **Implementer notes** section on completion; when
it lands, **harvest and adjudicate** those notes — ACCEPT each (route durable facts to
the brain, process lessons into your dispatch, follow-ups into new work-orders) or REJECT
it with a one-line reason.

## Reference index (read on demand)

- `references/roles/{inception,orchestrator,diagnostic}.md` — the three operator-entry role briefs.
- `references/roles/implementer.md` — the dispatched implementer (its boundary's SSOT).
- `references/agent-system.md` — the role + brain map and bridge diagram.
- `references/brain-schema.md` — brain layout, page types, the maintenance/anti-redundancy protocol.
- `references/work-order-template.md` — the `bug_<NNN>` / forward work-order format.
- `references/anomaly-families.md` — the nine anomaly families + per-domain adaptations.
- `references/acceptance-criteria.md` — generic promotion/acceptance gates (project-defined).
- `references/production-handoff-contract.md` — generic production-handoff contract skeleton.
- `references/profiles.md` — how a downstream product layers a domain profile on top of the engine.
- `references/upgrade.md` — the canonical `upgrade` procedure (adopt the latest engine directives).
- `references/bridge.md` — the BRIDGE contract: how a Custom (profiled) repo wraps `upgrade` (SYNC / PRESERVE / MERGE).
- `references/agent-import.md` — the `agent import` / `agent list` procedure (import + normalize operator lenses into `<home>/agents/`).
- `references/disciplines.md` — the transferable engineering disciplines (the war-stories, with the why).
- `references/glossary.md` — terminology (domain-agnostic).
- `scripts/scaffold.py` — lays the `.gitos/` tree + brain (idempotent).
- `scripts/brain_lint.py` — deterministic brain health/redundancy detector (read-only).
- `scripts/canary.py` — deterministic home-state canary (read-only; report at bootstrap, gate at resolution).
