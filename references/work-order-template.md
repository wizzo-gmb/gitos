# Work-order template

A work-order lives at `<home>/work-orders/WO-<NNN>-<slug>.md` — e.g.
`.gitos/work-orders/WO-044-federation-adoption-and-docs.md` — and moves to
`<home>/work-orders/resolved/` when the orchestrator resolves it. Numbering is sequential from the
highest existing work-order in that home, open and resolved together. The slug is 2–4 kebab-case
words naming the subject (`state-resets-on-restart`, `tenant-id-frozen-to-placeholder`,
`federation-consult`).

A work-order opens with a flat front matter block between `---` lines (`key: value`, a value is a bare string
or `[a, b]`; nothing else): `severity`, `title` and `evidence` are what `scripts/ledger_index.py` writes into the
INDEX's Open row. With none, the row is built from the H1 and the first word of `## Severity`, and evidence
reads `—`. At resolution the orchestrator adds `summary`, `landed` (the version) and `result` (the selftest
line), and `ledger_index.py` writes the Resolved row.

Legacy homes carry the same file as `outputs/debug/bug_<NNN>_<slug>.md`; that path still reads
correctly and needs no retrofit. New work-orders use the `<home>/work-orders/` convention above.

---

## The folder form (two or more slices)

An order with one slice is the single file above. **The second slice makes it a folder**, never by hand: run
`python <SKILL_DIR>/scripts/slice.py add WO-NNN NAME <home>`, which converts the file with `git mv` (the existing scope
becomes `S1`, the rest stays `order.md`) and writes the new slice as `proposed`. The canary gates a single file with
more than one `### S<n>` slice section and names this fix.

    <home>/work-orders/WO-NNN/order.md              the spec, frozen at accept; amended only by appended, dated amendments
    <home>/work-orders/WO-NNN/slices/SN-<name>.md   one slice: front matter, scope, verification, notes, adjudication
    <home>/work-orders/WO-NNN/log.md                append-only: one dated line per event

A slice file opens with front matter (same flat `key: value` block as an order):

    ---
    status: proposed        # proposed | ready | in-progress | implemented | landed | dropped
    depends_on: [WO-NNN/S1] # slice ids, or []
    commit:                 # the merge sha, set by the orchestrator when it lands the slice
    origin:                 # where the slice came from (a drain item, an order), or empty
    ---

then `## Scope`, `## Verification`, `## Implementer notes` (the five labels, under `###` headings) and
`## Adjudication`. `slice.py next` picks the first `ready` slice whose dependencies are all `landed`; `slice.py brief
WO-NNN/SN` prints what the worker reads. Only the orchestrator moves a slice to `landed` or `dropped`. `INDEX.md`
reads the order from `order.md`'s front matter; a resolved folder order moves as a whole directory to `resolved/`.

---

## Which form to write

The engine runs **two** work-order forms. Both are first-class, and the occasion picks between them.

- **Bug work-order** — *evidence-first*. Write this when an anomaly is **observed** and traceable to
  a file and line: there is a log, a diff, or an output to quote. It leads with `## Evidence`, so a
  reader can verify the finding without re-running anything. Originates in the diagnostic role.
- **Forward work-order** — *objective-first*. Write this when work is **commissioned** and there is
  nothing to quote: a feature to build, a design to pin, a hypothesis to test. It leads with
  `## Objective`, and states the design it rests on in place of the evidence it came from. Authored
  by the orchestrator.

Both terms are the glossary's (`references/glossary.md` → *Core terms*). One read of the occasion
picks the form: **something broke → bug form; something is wanted → forward form.** When an observed
anomaly is large enough to need a design decision, keep the bug form and add
`## Authoritative design` — the lead section is the choice, not the whole section list.

Four sections are **common to both forms** and carry identical guidance: `## Severity`,
`## Discipline notes`, `## Implementer notes`, `## Revisions`. Each template below shows them in
position so it stays copyable; their guidance is stated once, under *Shared sections*.

---

## Template — bug work-order (evidence-first)

```markdown
---
severity: critical | high | medium | low | unconfirmed
title: <Short Title>
evidence: <primary file:line>
---

# WO-<NNN> — <Short Title>

> **▶ Role on direct open.** Opened this work-order in a fresh window to *do the work* (or were
> dispatched to it)? You are the **Implementer** (`references/roles/implementer.md`), **not** the
> orchestrator: read this WO in full, **plan first → then execute**, edit **only** what
> `## Proposed fix scope` names, and fill `## Implementer notes` on completion. Driving the whole
> repo / deciding what's next instead? That's the orchestrator — `references/roles/orchestrator.md`.

## Severity
critical | high | medium | low | unconfirmed
[Shared — *Shared sections* → Severity, plus *Severity calibration*.]

## Evidence

[5–15 lines of actual log output, with source file path and line numbers,
timestamps, and surrounding context. Show enough that the reader can verify
the anomaly themselves without re-running anything. Quote literally — do not
paraphrase.]

> ```
> <quoted log lines with timestamps>
> ```

[Brief prose explaining what the evidence shows and why it's wrong.]

## Suspected cause

File: `<absolute or repo-relative path>`
Lines: <range>

[Why you think this is the cause, traced from log to source. If the cause is
across multiple files, list all of them. If the cause depends on lifecycle
ordering (e.g., "X runs before Y is set"), state the ordering explicitly with
line numbers.]

## Proposed fix scope

[Concrete enough that the implementer can scope the change without
re-diagnosing. Two patterns:

For LOW-uncertainty fixes — provide a diff sketch:

    ```
    - old line
    + new line
    ```

For HIGH-uncertainty fixes — describe the investigation the implementer must
do first, then the candidate solution paths (Option 1 / Option 2 / etc.) with
the trade-offs of each.

If the work-order lists multiple Options, the dispatcher should pin which one
the implementer agent must use. State that explicitly here.

**This section is the implementer's hard boundary** (full role + boundary:
`references/roles/implementer.md`) — the implementer edits only what is specified here;
anything outside requires a new work-order or explicit operator authorization.]

## Verification

[Exact commands or log lines to re-check after the fix. The operator should
be able to confirm the fix worked without re-reading the entire work-order.

For Python/repo-tracked fixes: include the exact command to re-run, plus the
log line or output that proves the fix landed (e.g., "the new
`[X] floor applied` WARNING fires").

For vendor / in-place / no-git edits (e.g. a plugin recompiled in an IDE, a
hosted config change): include the rebuild/reload step and the log line that
proves the fix is live.

Spot-check evidence is acceptable: "restart the service, inspect line N of the
next log, confirm <X>".]

## Discipline notes

[Shared — *Shared sections* → Discipline notes.]

## Implementer notes (fill on completion — the orchestrator reads and adjudicates this)

[Shared — *Shared sections* → Implementer notes.]

## Revisions (post-landing — the verify→revise loop)

[Shared — *Shared sections* → Revisions.]

## Carried loose ends (only when items were accepted into this order)

[Shared — *Shared sections* → Carried loose ends.]
```

---

## Template — forward work-order (objective-first)

```markdown
---
severity: critical | high | medium | low | unconfirmed
title: <Short Title>
evidence: <the design or decision page it rests on>
---

# WO-<NNN> — <Short Title>

> **▶ Role on direct open.** Opened this work-order in a fresh window to *do the work* (or were
> dispatched to it)? You are the **Implementer** (`references/roles/implementer.md`), **not** the
> orchestrator: read this WO in full, **plan first → then execute**, edit **only** what
> `## Proposed scope` names, and fill `## Implementer notes` on completion. Driving the whole
> repo / deciding what's next instead? That's the orchestrator — `references/roles/orchestrator.md`.

## Severity
critical | high | medium | low | unconfirmed
[Shared — *Shared sections* → Severity, plus *Severity calibration*. Here the question reads:
what breaks if this work is skipped, or built to the wrong shape?]

## Objective

[2–6 lines. The outcome this order buys, stated so the implementer can hold the whole landing
against it. Name the end state; the steps belong in Proposed scope.]

## Authoritative design

[The SSOT this work rests on: the design already pinned, where it lives, and the decision the
operator already made. Quote the governing clause or table rather than re-deriving it. Anything an
earlier order settled is carried here as settled, so the implementer builds on it instead of
relitigating it. When the design is new in this order, state it in full — this section is what the
implementer treats as true.]

## Part-0 probe (read-only; GO/NO-GO before building)

[A cheap read-only check the implementer runs FIRST, before any edit, that can still invalidate the
plan. Name the reads, then state both verdicts:

**GO** if <the condition that confirms this order's assumptions>.
**NO-GO — stop and report** if <the finding that means this plan is wrong>, so the orchestrator
re-scopes and the implementer never improvises a new one.]

## Proposed scope

[The deliverables, enumerated. Name every file the implementer owns, and the section within it
where that sharpens the boundary. Then name what stays untouched — adjacent files, other
work-orders, the ledger, the brain — so an "obvious" neighbouring fix stays out.

Deliver:
1. <deliverable>
2. <deliverable>

If this order offers Options, the dispatcher pins which one the implementer builds. State that here.

**This section is the implementer's hard boundary** (full role + boundary:
`references/roles/implementer.md`) — the implementer edits only what is specified here;
anything outside requires a new work-order or explicit operator authorization.]

## Acceptance

[The checklist the landing is judged against, each line checkable by reading the diff or running a
command. Include the home's gates verbatim, e.g.

- <the behavioural claim, stated so a reader can confirm it>
- `python <home>/tools/selftest.py` → N/N ALL PASS
- `python <skill>/scripts/canary.py <home>` → CLEAN, exit 0
- `git diff --check` clean]

## Discipline notes

[Shared — *Shared sections* → Discipline notes.]

## Implementer notes (fill on completion — the orchestrator reads and adjudicates this)

[Shared — *Shared sections* → Implementer notes.]

## Revisions (post-landing — the verify→revise loop)

[Shared — *Shared sections* → Revisions.]
```

---

## Shared sections

Stated once; both forms use them unchanged.

### Severity

One of `critical | high | medium | low | unconfirmed`, with a line of justification. Calibration
rules and worked examples: *Severity calibration* below.

### Discipline notes

[Reproducibility — how confident are you this is reproducible? Was it observed once or N times
across logs? On a forward order, give the command that re-derives this order's own claims.]

[Blast radius — what's at stake if this is NOT done? Live trades? User-facing output?
Internal-only? Payload that ships to every repo that upgrades?]

[Scope boundaries — what NOT to change in the same landing. List the related work-orders that stay
independent.]

[Related work — point at adjacent work-orders, brain pages, or session notes the implementer should
also be aware of.]

### Carried loose ends

Written by `system_one.py drain accept ID --work-order NNN --slice NAME` (section `## Carried loose ends`, created
when missing). One box per item, naming the slice that carries it (`--slice` is required on every accept into an order):

    - [ ] L<n> (slice: <name>) <text>
    - [x] L<n> (slice: <name>) <text> -> <sha>

A slice is whatever names a unit of the order's work: a Proposed fix scope item, a Revision, or the repo's own
slice name. The orchestrator closes each box when its slice lands (`-> <sha>`), or moves it: `-> L<n>` (back on the
list, re-added there), `-> P<n>`, `-> WO-NNN`, `-> rejected: <why>`. The canary gates a resolved order with an open box (`carried-open`).

### Implementer notes

Filled by the **implementer** when the work-order lands, not by the author. This is the feedback
channel back to the orchestrator: capture what's worth knowing that the diff and the commit message
won't show. The orchestrator ACCEPTs or REJECTs each note — accepted notes go to the brain or change
how work is dispatched; rejected notes are discarded with a reason — so be honest and specific.
Everything here is **proposed**, never self-executed: surface follow-ups and out-of-scope
observations, and the orchestrator decides and acts on them.

- **Deviations** — where you departed from the Proposed scope / Proposed fix scope, and why.
- **Surprises** — anything that contradicted the work-order's assumptions (the code wasn't where it
  said; a guard already existed; the fix revealed a second issue).
- **Durable facts** — reasons, limits, rules and traps a later change must know (why something is
  done this way, a limit found, a rule that holds across files, what must not be done). **Not** a
  description of what was built or where it is: the code and the work-order already hold that. Brain
  candidates.
- **Process notes** — anything about HOW the work went that could improve future dispatch (an
  under- or over-scoped work-order, a missing precondition, a faster path).
- **Follow-ups** — work this surfaced that should become its own work-order (name it; do NOT fix it
  here).

Write the notes **under these five labels** (a bold or heading label above a run of bullets, or a
label at the start of a bullet); the labels help the orchestrator read them. One top-level bullet per
point; nested bullets belong to their parent.

"Nothing notable" is a valid and useful answer.

#### Adjudication

Written by the **orchestrator**, never the implementer, as a `### Adjudication` sub-block under
`## Implementer notes` when it adjudicates them. One line per open point, deviation, caveat or
follow-up, each ending in exactly one destination:

- `→ WO-NNN` — becomes (or already is) that work-order;
- `→ P<n>` — deferred: a row in the INDEX `## Parked` list, with its restart trigger;
- `→ brain: <page>` — a durable fact, upserted to that brain page;
- `→ rejected: <one-line reason>` — discarded;
- `→ L<n>` — a follow-up moved to the loose-ends list (`<home>/loose-ends.md`), to be drained with the rest.

The canary's `loose-ends` category reads it: a resolved order (engine v44 or later) with notes
and no block is `notes-unadjudicated` (any content other than a "nothing notable" answer counts,
whatever the headings), and a destination that does not exist is
`adjudication-dangling`. Orders resolved before v44 are exempt and are not backfilled.

Only when model optimization was enabled at dispatch: add one compact model/outcome entry —
requested model/effort; confirmed effective values or an explicit unknown; acceptance, revisions, or
escalation with a material reason. Observed usage is optional. The orchestrator adjudicates any
model-selection lesson at normal closeout; no lesson is required. SSOT:
`references/model-optimization.md`.

### Revisions

Empty when the work-order is authored. After it lands and the operator verifies it, requested
changes go HERE — not into a new work-order. The **orchestrator** writes the operator's ask as a
scoped change; the **implementer** handles it on a re-dispatch (a fresh window on this WO) and
records the result. Repeat per round until the operator is satisfied, then the orchestrator resolves
the work-order. A genuinely *new* direction — not a tweak to this landing — is a follow-up
work-order raised through Implementer notes, not a revision. Format per round:

```markdown
### Revision 1 — <date>
- **Requested (orchestrator):** <the operator's change, scoped — same boundary as the scope section>
- **Done (implementer):** <what changed + any notes; left blank until handled>
```

---

## Severity calibration

When picking a severity, ask: *if this is wrong, what breaks?*

- **`critical`** — user-facing safety, data corruption, production-down, money/PHI at risk. (E.g. a safety throttle silently disabled because its guard never fired.)
- **`high`** — silent wrong numbers in outputs that drive decisions; isolation/security boundaries broken; multi-tenant data leak; auth bypass. (E.g. per-tenant state written to a shared file → cross-tenant isolation broken.)
- **`medium`** — misleading log output that prevents diagnosis; drift between calibration and deployment; latent risk that isn't currently firing. (E.g. a threshold shipped as `0.0` degenerates a magnitude filter into a sign-only filter.)
- **`low`** — cosmetics, defensive cleanup, fragile contracts that aren't currently broken. (E.g. index-by-position parsing that's fragile to schema evolution.)
- **`unconfirmed`** — anomaly observed but proof requires reproduction the agent cannot run. ALSO appropriate for "needs operator decision" or "depends on judgment about prior work that's still contested". (E.g. a deployment decision that needs a fresh-eyes review of a contested prior verdict.)

Don't inflate to get attention. Don't downgrade to seem reasonable.

---

## Writing patterns

### Bug form

**Evidence section** — always lead with the raw log line, quoted verbatim with
its file path and line number. Then explain. Example:

```
## Evidence

```
logs/worker_default_20260521.log:3
2026-05-21T21:46:20.900Z [worker] state: no persisted state — starting fresh path=.../state/state_default.json
```

Every restart logs the state-file path containing the `default` placeholder even
though the real tenant id (`acme-prod`) is known once the runtime reaches its
READY phase. Reproducible in all 5 log files from May 17–21.
```

**Suspected cause section** — quote the source code that causes the bug, with
line numbers. Example:

```
## Suspected cause

File: `src/worker/lifecycle.py`
Lines: 120-135 (init path), 160-165 (path construction)

```
src/worker/lifecycle.py:120-128
    elif phase == Phase.LOADED:
        ...
        load_state()                      # ← called here, before READY
    elif phase == Phase.READY:
        self.tenant = ctx.tenant or None  # ← set here
```

load_state() in the LOADED phase runs BEFORE self.tenant is assigned in READY.
The path string at line 162 falls through to the `or "default"` placeholder
permanently.
```

**Proposed fix scope** — be specific about which file and which lines. Example
of low-uncertainty:

```
## Proposed fix scope

Move the `load_state()` call from the LOADED phase to the READY success branch,
after `self.tenant` is assigned (inside the `if self.tenant:` block, ~line 164).

Add a backward-compat migration: if `state_default.json` exists and
`state_<tenant>.json` does not, move the old file to the new and log
`[worker] state: migrating default → <tenant>`.

Wrap migration in try/except — IO failures should log a warning but not block
the rest of load_state().
```

### Forward form

**Objective section** — one end state, no steps. Example:

```
## Objective

Give `upgrade` a federation offer, so a repo with siblings can opt in at the moment it already has
the operator's attention. The offer presents the choice; enabling stays the operator's action.
```

**Part-0 probe** — name the reads, then both verdicts, so the implementer has a
stated exit. Example:

```
## Part-0 probe (read-only; GO/NO-GO before building)

Read the current `upgrade` flow end to end and confirm the prompt point exists where this order
assumes. **GO** if the offer lands without moving an existing prompt. **NO-GO — stop and report**
if the offer would have to gate a step that already runs unattended.
```

**Acceptance** — each line checkable by diff or command, gates included
verbatim. Example:

```
## Acceptance

- `upgrade` offers federation and never enables it; declining leaves the config untouched.
- `python .gitos/tools/selftest.py` → 27/27 ALL PASS
- `git diff --check` clean
```

---

## Index entry

Both forms take the same ledger row. After writing a work-order, append it to the pipeline home's
`INDEX.md` (`<home>/INDEX.md` — e.g. `.gitos/INDEX.md`, or `outputs/debug/INDEX.md` on a legacy
home) in the "Open work-orders" section:

```markdown
| <NNN> | <severity> | <Title> | <primary evidence file:line> |
```

The last column is the file the order anchors to: the evidence `file:line` on a bug order, and on a
forward order the primary file the work targets.

When the work-order is resolved, MOVE the file to `<home>/work-orders/resolved/` and move its INDEX
entry to the "Resolved" section with a "Fix landed in" reference (commit hash for repo files,
`(no git)` for files outside any repo).
