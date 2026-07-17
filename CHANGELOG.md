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

## v20 — 2026-07-16
breaking: no

**The canary identifies a work-order by a RULE, not by a list of forms** (WO-033). Three work-orders,
one error, three altitudes: the check hardcoded the engine's own filename regex (*"they were one
sample"*), the remedy enumerated three samples (*"a four-item list is still a list of samples"*), and
v18 folded the underscore forms but still enumerated **prefixes**. Enumeration is a strategy that
**fails once per novel downstream**, and each failure costs that repo its resolution gate until the
engine ships — so the next ledger writing `task_007_x.md` or `WO007-x.md` was already scheduled to land
in the same place. This ends the class instead of lowering its rate.

**The rule: the directory is the scope.** Files under `<home>/work-orders/` are work-orders by
construction, so a filename does not have to prove it is one — it only has to yield an **identity**: an
optional letter prefix and separator, then **exactly three digits**, then a separator and a slug. The
prefix carries no meaning and is no longer inspected. `WO-007-x.md`, `wo_007_x.md`, `bug_007_x.md`,
`task_007_x.md`, `WO007-x.md`, `007-x.md` and whatever the next repo invents all resolve, with no engine
release. Measured against **every ledger reachable from the engine's environment (312 files)**: the new
rule and the old list agree on **all 312** — the change buys no existing repo anything, and that is the
honest claim. Its entire value is that the next novel form costs nothing.

**Tolerance, never blindness — both halves tested.** `IDENT_NNN` is now the engine's single notion of
"exactly three digits, closed", shared by the filename rule and the prose-row rule so the two cannot
drift; a name with no readable identity is still reported (`wo_1234_x.md` four digits, `wo1234_x.md` the
backtrack trap — the rule's prefix is letters-only precisely so a digit cannot be backtracked out of it
into a phantom WO-234, `WO-1-x.md` one digit, `notes.md` none, `wo_029b_x.md` a suffixed identity this
ledger model cannot represent and therefore reports rather than flattening onto its sibling). The two
identity rules share a core but **not** a prefix policy, deliberately: a filename is scoped by its
directory, a prose line by nothing but its anchor, so an open prose prefix would read `**Fixed 240
findings**` as row 240. Gate 11 now bites in **both** directions — narrowing to any prefix enumeration,
widening to `\d{3,4}`, tolerating digits in the prefix, re-importing enumeration from the other end (a
`notes_` exclusion), or "unifying" the two rules by opening the prose prefix each turn it red.

**The blindness risk, pinned rather than wished away.** A non-work-order carrying an identity
(`notes_007_draft.md`) **is** adopted as WO-007; no filename signal separates it from `task_007_real.md`,
and a name-shaped heuristic to tell them apart would re-import the enumeration just removed. What is
guaranteed is that adoption is never **silent** — with no INDEX row it surfaces as `orphan-file`, against
a real WO-007 as `duplicate-file` naming both. The cost is a finding with a different **label**, never a
missed one, bounded by a directory that holds nothing but work-orders. The probe found **zero**
non-work-order `.md` files across every reachable ledger, and the one near-miss — a memo deliverable
named after its own work-order — **already** matched v18's enumeration, so the prefix list never
protected against this class in the first place.

`breaking: no` — the rule is strictly more tolerant (nothing v18 accepted is now rejected, proved on all
312 real files); no migration action is required. Two caveats named rather than buried: a ledger holding
an identity-carrying non-work-order will see that finding change **label** (`nonconforming-wo-filename` →
`orphan-file`/`duplicate-file`), and the module constant `WO_FILE_FORMS` is gone, replaced by
`WO_FILE_RE` + `IDENT_NNN` (a plural "forms" name would have preserved the framing this WO removes).

---

## v19 — 2026-07-16
breaking: no

**`upgrade` never refreshed a home tool, so no tool fix reached any repo that had the tool**
(WO-032). Step 4 read *"copy `brain_lint`/`canary.py` into the home if missing — never clobber an
existing copy"*. So a repo that adopted a tool at v14 kept the **v14 tool forever**. v16, v17 and v18
were each, in substance, a `canary.py` fix; through the documented path, all three reached **zero**
adopting repos. The engine had been fixing a checker its own upgrade could not deliver — and two
downstream adoptions each had to declare a **deliberate deviation** to receive the last fix. A rule
adopters must knowingly break to get value is not a rule; it is a bug with a paper trail.

- **The distinction the old rule missed: engine artifacts are not operator content.**
  `<home>/tools/*.py` are byte-copies of the engine's own scripts — a *cache of the installed skill*,
  which the briefs invoke by home path. They are not project state. The never-clobber instinct came
  from the right place (never overwrite state) and was aimed at something that is not state. Contrast
  `<home>/agents/` — the lens library, genuinely operator content, correctly report-and-**ask** since
  v12/v13 and **untouched by this change**. The line is the category, not the folder.
- **Step 4 now delivers, and says so** (`references/upgrade.md`): **missing** → copy; **byte-identical**
  → silent no-op (no churn, no false "updated"); **different** → **report it, then refresh it**. A
  byte-compare proves *different*, not *why* — so the report says exactly that (stale or hand-modified,
  the tool cannot tell which) and notes the prior bytes are recoverable from git.
  **Never silently skip; never silently overwrite** — the two are the same failure wearing different
  clothes, and the old rule traded one for the other.
- **One rule over `<home>/tools/`, not one bullet per tool.** The predecessor enumerated two tools; any
  future tool laid in the home would have inherited the trap by default. WO-031's lesson applied at the
  point of authorship rather than one iteration later: a convention is written as a rule, not as a list
  of its current samples.
- **No new engine state.** A manifest of previously-shipped tool versions would positively separate
  "pristine but stale" from "hand-modified" — and costs a permanent, per-release bookkeeping surface
  that can itself go stale, to resolve a case that has one right answer anyway. Rejected as out of
  proportion. The refresh is not asked-about either: a prompt per tool per upgrade trains the operator
  to skip the very fix the upgrade exists to deliver.
- **Seeding still is not delivering** (`scripts/scaffold.py` — unchanged, deliberately). Laying a tool
  into a *fresh* home and delivering a fix to an *existing* one are different acts; scaffold keeps its
  `SKIP exists`, and its idempotency gate ("second run writes 0") still passes.
- **New gate 13** (`.gitos/tools/selftest.py`) pins the rule and both boundaries: the shipped directive
  must express all three branches, forbid silence in both directions, stay one rule over the folder, and
  claim no authority over `<home>/agents/`; behaviourally, scaffold must still *refuse* to refresh a
  stale tool and must leave operator lenses byte-untouched. The gate states plainly which half it
  executes and which half it asserts — an upgrade step is prose an orchestrator performs, and prose is
  what regressed here.

`breaking: no` — it removes no directive and demands no migration action: adopting it *is* the whole
change, and an un-migrated repo keeps behaving exactly as it did. It only makes an upgrade deliver what
it always claimed to. **One thing to know before you run it:** if you have hand-edited a
`<home>/tools/` copy, the next upgrade will refresh it and tell you — that is the intended correction,
not a migration burden (a forked tool copy was never a supported surface; descope a canary category or
file a work-order instead), and your bytes remain in git.

## v18 — 2026-07-16
breaking: no

**The canary's work-order filename list was short by one form** (WO-031) — and it was the form the
engine's own template implies. v16 replaced a hardcoded filename regex with a list of three known
forms; the list covered an underscore `work_` form and a diagnostic `bug_` form, but not the forward
`wo_` sibling that sits alongside `bug_` in any ledger following that template. A repo naming its
work-orders `wo_NNN_<slug>.md` therefore had every one of them reported as nonconforming, and any
ledger row whose file could not be resolved to an NNN reported as missing its file — the v16 fix
reproduced, one iteration in, the exact failure v16 named: **loud *and* blind** on the repo it was
meant to serve. A category that must be descoped to be usable does not gate.

- **Underscore forms are now ONE pattern, not an enumeration** (`scripts/canary.py`):
  `<prefix>_NNN_<slug>.md` is a *convention*, so it is written as one regex covering `wo_`/`work_`/
  `bug_` rather than a fourth sample beside three others. Adding a fourth line would have re-armed
  the same trap at a lower rate. The operator-facing "rename to one of them" advice now names every
  accepted form.
- **Tolerance, never blindness — unchanged and now pinned harder.** This widens tolerance by one
  prefix; it removes no report. A name matching no form is still reported, including the near-misses
  the widened pattern must *not* swallow: a 4-digit `wo_1234_x.md` is not an NNN.
- **The relaxation keeps its true-positive test** (`.gitos/tools/selftest.py`): the external-validity
  gate now carries a `wo_` fixture reproducing both original findings, and asserts that a duplicate-NNN
  collision **across two forms** is still caught — the exact defect the enumeration exists to expose.
  Reverting the pattern turns the gate red.
- **Recorded, not decided:** enumerating forms — even one level up, as a list of prefixes — is still a
  strategy that fails once per novel convention. Deriving NNN by a general identity-position rule, or
  letting a repo declare its form, is deliberately left to an operator decision; this buys back the
  gate for the conventions that exist today. Noted in the code so the next author does not mistake the
  pattern for the destination.

Additive and strictly more tolerant: every ledger clean at v17 stays clean (a repo with no
nonconforming filenames cannot be newly flagged by a wider pattern).

## v17 — 2026-07-16
breaking: no

**Payload hygiene, made structural** (WO-030). The publish gate scanned for private filesystem
*paths* only — so a private **name** (a repo, product, client, or domain) written into a payload
file sailed straight through it. That is not hypothetical: a dispatched implementer put private
repo names into `scripts/` comments, and the only thing that caught them was the operator reading
the diff. The engine's own thesis applies to the engine: **an invariant that depends on someone
remembering eventually fails.**

- **Publish gate — names, not just paths** (dev tooling): the guard now carries a private-*name*
  denylist beside its path patterns, word-boundary and case-insensitive, reported the same way
  (file + line + the rule that fired) and halting the publish identically. The list is dev-only and
  is structurally unable to ship — it lives under `.gitos/`, which the payload enumeration excludes.
- **Precision over coverage.** A guard that cries wolf gets switched off, taking the useful patterns
  with it — so ambiguous names are matched only in their distinctive hyphenated/underscored form
  (generic spaced prose still passes), and a name that cannot be told apart from ordinary
  vocabulary is *deliberately not covered*, recorded in the file with its reason rather than shipped
  as a false-positive generator.
- **A new acceptance gate proves the detector detects** (positive *and* negative): innocent payload
  prose passes; real private names are caught; the original leak scenario is reproduced end-to-end
  and halts.
- **Directive** — `references/roles/implementer.md` now pins the boundary: private names belong in
  `.gitos/**` (work-order, notes, INDEX, brain); payload text — **comments included** — describes
  the **shape**, never the **source**. The trap is that the honest motivation for a change usually
  *is* "repo X does Y", which makes writing it down feel natural.

## v16 — 2026-07-16
breaking: no

Canary **external validity** (WO-029) — the canary encoded the engine's *own* conventions as if they
were the schema. They were one sample. On an independently-evolved downstream repo the ledger check was
**loud *and* blind**: hundreds of findings, nearly all false, while a real duplicate-NNN collision sat
in front of it unseen. Fixed as *tolerance, never blindness* — every relaxation keeps its true-positive
test:

- **Work-order filenames** (`scripts/canary.py`): the hardcoded `WO-NNN-<slug>.md` regex became a list
  of known forms — the engine's hyphen form plus an underscore `work_NNN_` form and a diagnostic
  `bug_NNN_` form — each yielding NNN, so duplicate / orphan / row→file detection **actually runs** on a
  ledger that doesn't use the engine's naming. A name matching no known form is still reported.
- **Ledger section headings**: matched by prefix, not by a literal — the heading's tail (e.g. a
  `(by severity)` parenthetical) is legitimate variation. When a section carries no table, a
  **prose/blockquote ledger** is parsed via each item's identity-position NNN plus a top-up from linked
  work-order files. A section that is neither remains `cannot-parse`.
- **Link resolution**: a target now resolves against the containing file's dir **or** the repo root, and
  is reported only when **neither** resolves. Flagging a path that demonstrably exists was a false
  positive against the tool's purpose (it detects drift; it does not lint markdown).
- **Lens registries**: a Lens cell may be a bare stem **or** a markdown link (the target's stem is the
  name) — a link cell used to double-report one condition as two findings. Lens provenance accepts
  `imported:` **or** `authored:`: a distilled lens should not have to record false provenance.
- **Managed-block data loss** (`scripts/scaffold.py`): `ensure_claude_section` replaced the block's
  contents wholesale, silently destroying anything inside it — on a refresh the engine itself
  recommends, while the docs pointed a profile pointer *into* that file without saying to keep it
  outside the markers. It now carries unrecognized in-block lines through the refresh and **reports**
  them (status `preserved`); ordinary drift is still replaced. Silence was the defect. The docs
  (`assets/CLAUDE-section.md.tmpl`, `references/bridge.md`, `references/upgrade.md`) now pin `_meta` and
  anything repo-owned **outside** the markers.
- **Gate escape** (`SKILL.md`): a convention mismatch must never freeze a healthy ledger. An operator or
  a repo's BRIDGE may **descope a canary category**, recording the deviation; a descoped category
  **reports but does not gate**. The gate binds on *actionable* findings.
- **Root cause — fixture bias** (`.gitos/tools/selftest.py`): the prior gate's fixtures were hand-built
  to match the canary's assumptions, so a green suite proved internal consistency, not external
  validity. A new gate runs the canary against shapes observed in real downstream repos and asserts both
  directions: legitimate shapes are silent, and the seeded real collision **is** caught.

Additive and strictly more tolerant: every shape that passed at v15 still passes (a repo clean at v15
had no nonconforming filenames by definition, so the widened forms cannot newly flag it), and the block
refresh now preserves what it used to delete.

## v15 — 2026-07-14
breaking: no

Durable context anchor (WO-028) — closes the v14 canary's **self-reference hole**. The per-reply
marker and its own absence-detector both lived in the skill directive layer, which compaction
summarizes away, so the detector degraded in lockstep with what it watched. The recovery seed now
*also* lives in the **durable layer**: inception writes a managed `<!-- gitos:agent-system -->` block
into the repo-root `CLAUDE.md` — which the harness re-injects into every context window — carrying the
marker requirement + the trigger to re-read SKILL.md and run `canary.py`. Even after the skill directive
washes out, that block re-asserts the marker and points the way back. `scripts/scaffold.py` gains
`ensure_claude_section()` (idempotent managed-block **upsert**, creates the file if absent, never
clobbers content outside the markers — replacing the old append-once behavior); `upgrade` refreshes it;
`canary.py` gains an `anchor` category (`anchor/missing`, `anchor/stale`); selftest grows a 10th gate
(the upsert's create / no-clobber / idempotency) and gate 9 now covers the anchor. Custom repos treat
the block as a **MERGE** (engine-managed section inside a profile-owned `CLAUDE.md`). Also fixes
cold-start drift + the misroute class — the repo self-announces through the durable layer. Additive — a
repo without the anchor simply lacks the durable backstop.

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
