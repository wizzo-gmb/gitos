# Work-order template

A work-order lives at `<home>/work-orders/WO-<NNN>-<slug>.md` — e.g.
`.gitos/work-orders/WO-044-federation-adoption-and-docs.md` — and moves to
`<home>/work-orders/resolved/` when the orchestrator resolves it. Numbering is sequential from the
highest existing work-order in that home, open and resolved together. The slug is 2–4 kebab-case
words naming the subject (`state-resets-on-restart`, `tenant-id-frozen-to-placeholder`,
`federation-consult`).

A work-order opens with a flat front matter block between `---` lines (`key: value`, a value is a bare string
or `[a, b]`; nothing else): `severity`, `title` and `evidence` are what `scripts/ledger_index.py` writes into the
board's Open row (evidence is cut at 100 characters there). With none, the row is built from the H1 and the first word of
`## Severity`, and evidence reads `—`. At resolution the orchestrator adds `released` (the engine version; the older key
`landed` still reads); nothing else is written for a resolved order and no row is added anywhere. At merge, before resolution, a
single-file order gets `landed: <sha>` (the merge commit); only the owner board reads it, to show Awaiting accept.

**A parked work-order** is deferred work that waits on a named event: an ordinary order file in `work-orders/`
whose front matter adds `status: parked` and `trigger: <restart trigger>` (and `origin: L<n>` when it took items).
`ledger_index.py` writes it into the board's `## Parked` table instead of Open; the canary gates one with no trigger
(`parked-no-trigger`), and `loose_ends.py status` lists one whose trigger names a resolved order or a passed date.
When the trigger fires, remove `status: parked` and write its Proposed fix scope.

**A pending work-order** is an open order held for a wait that is not work: a live proof, a run. Its front matter (a
single file, or a folder's `order.md`) adds `pending: <what it waits on>`. The board marks the title
`[pending: <what>]`; the canary lists it once as the advisory `order-pending` with the text and does not advise
`order-ready-to-close` for it. `order-split-advice` and `slice-oversized` stay: they are about the order's shape. The
orchestrator removes the key when the wait is over, then closes the order.

**Sprint marks.** An order's front matter may carry the optional key `sprint`: `ready` means an interactive orchestrator checked
the order against the sprint eligibility criteria and the operator agreed (an unattended sprint with no `--orders` list takes only
`ready` orders); `no` means never in a sprint, for any reason. Neither is set by a sprint; remove the key to clear it
(`orchestrator/sprint-prep.md`).

Legacy homes carry the same file as `outputs/debug/bug_<NNN>_<slug>.md`; that path still reads
correctly and needs no retrofit. New work-orders use the `<home>/work-orders/` convention above.

---

## The folder form (two or more slices)

An order with one slice is the single file above. **The second slice makes it a folder**, never by hand: run
`python <SKILL_DIR>/scripts/slice.py add WO-NNN NAME <home>`, which converts the file with `git mv` (the existing scope
becomes `S1`, the rest stays `order.md`) and writes the new slice as `proposed`. The canary gates a single file with
more than one `### S<n>` slice section and names this fix. A slice number may carry one lower-case letter to insert a slice
between two numbered ones (`S9b` sorts after `S9` and before `S10`; its file is `S9b-<name>.md`, its worktree branch `wo-NNN-s9b`).

    <home>/work-orders/WO-NNN/order.md              the spec, frozen at accept; amended only by appended, dated amendments
    <home>/work-orders/WO-NNN/slices/SN-<name>.md   one slice: front matter, scope, verification, notes, adjudication

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

Both terms are the glossary's (`references/glossary.md` → *Work-order lifecycle and slices*). One read of the occasion
picks the form: **something broke → bug form; something is wanted → forward form.** When an observed
anomaly is large enough to need a design decision, keep the bug form and add
`## Authoritative design` — the lead section is the choice, not the whole section list.

Four sections are **common to both forms** and carry identical guidance: `## Severity`,
`## Risk notes`, `## Implementer notes`, `## Revisions`. Each template below shows them in
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
> orchestrator: read this WO in full, **plan first → then execute**, edit **only** what the
> Proposed fix scope section names, and fill the Implementer notes section on completion. Driving the
> whole repo / deciding what's next instead? That's the orchestrator — `references/roles/orchestrator.md`.

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
next log, confirm <X>".

On an order that touches a gate, check or filter, add a **negative control** (plant the defect it exists
to catch and show it go red, (h)) and a **prove the change bit** check (the changed step observably did
something, (b)). Disciplines: `references/disciplines.md`.]

## Risk notes

[Shared — *Shared sections* → Risk notes.]

## Implementer notes (fill on completion — the orchestrator reads and adjudicates this)

[Shared — *Shared sections* → Implementer notes.]

## Revisions (post-landing — the verify→revise loop)

[Shared — *Shared sections* → Revisions.]
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
> orchestrator: read this WO in full, **plan first → then execute**, edit **only** what the
> Proposed fix scope section names, and fill the Implementer notes section on completion. Driving the
> whole repo / deciding what's next instead? That's the orchestrator — `references/roles/orchestrator.md`.

## Severity
critical | high | medium | low | unconfirmed
[Shared — *Shared sections* → Severity, plus *Severity calibration*. Here the question reads:
what breaks if this work is skipped, or built to the wrong shape?]

## Objective

[2–6 lines. The outcome this order buys, stated so the implementer can hold the whole landing
against it. Name the end state; the steps belong in the Proposed fix scope.]

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

## Proposed fix scope

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
- <the home's own gates: each command and its expected result>
- a negative control for any gate the order touches: the planted defect and the red it produces (h)
- `git diff --check` clean]

## Risk notes

[Shared — *Shared sections* → Risk notes.]

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

### Risk notes

[Reproducibility — how confident are you this is reproducible? Was it observed once or N times
across logs? On a forward order, give the command that re-derives this order's own claims.]

[Blast radius — what's at stake if this is NOT done? Live money or users? User-facing output?
Internal-only? Payload that ships to every repo that upgrades?]

[Disciplines — the letters from `references/disciplines.md` that apply to this order, e.g. (a) (h); "none" is a valid answer.]

[Scope boundaries — what NOT to change in the same landing. List the related work-orders that stay
independent.]

[Related work — point at adjacent work-orders, brain pages, or session notes the implementer should
also be aware of.]

### Follow-ups taken into an order

An order carries no loose-end boxes (retired in v57). `system_one.py drain accept ID --work-order NNN --slice NAME`
writes a follow-up as its own `proposed` slice with `origin:` naming the items (`slice add`; a single-file order
becomes a folder); an order authored from a proposal names the items in its own front matter (`origin: L3, L5`). A
resolved order that still holds an old open box is `carried-open` for the canary; an open order's boxes move to the
list with `ledger_migrate.py`.

### Implementer notes

Filled by the **implementer** when the work-order lands, not by the author. This is the feedback
channel back to the orchestrator: capture what's worth knowing that the diff and the commit message
won't show. The orchestrator ACCEPTs, DEFERs or REJECTs each note — accepted notes go to the brain or change
how work is dispatched; rejected notes are discarded with a reason — so be honest and specific.
Everything here is **proposed**, never self-executed: surface follow-ups and out-of-scope
observations, and the orchestrator decides and acts on them.

- **Deviations** — where you departed from the Proposed fix scope, and why; every finding you fixed in this
  order because it sat within its scope of work.
- **Surprises** — anything that contradicted the work-order's assumptions (the code wasn't where it
  said; a guard already existed; the fix revealed a second issue).
- **Durable facts** — reasons, limits, rules and traps a later change must know (why something is
  done this way, a limit found, a rule that holds across files, what must not be done). **Not** a
  description of what was built or where it is: the code and the work-order already hold that. Brain
  candidates.
- **Process notes** — anything about HOW the work went that could improve future dispatch (an
  under- or over-scoped work-order, a missing precondition, a faster path).
- **Follow-ups** — only what is clearly out of this order's scope or would cross into a new scope (a
  different subsystem, a design or operator decision, a file another in-flight order owns), each with that reason
  in one line. Anything within scope is fixed here, not listed; nothing is dropped.

Write the notes **under these five labels** (a bold or heading label above a run of bullets, or a
label at the start of a bullet); the labels help the orchestrator read them. One top-level bullet per
point; nested bullets belong to their parent.

"Nothing notable" is a valid and useful answer.

#### Adjudication

Written by the **orchestrator**, never the implementer, as a `### Adjudication` sub-block under
`## Implementer notes` when it adjudicates them. One line per open point, deviation, caveat or
follow-up, each ending in exactly one destination:

- `→ WO-NNN` — becomes (or already is) that work-order;
- `→ WO-NNN/SN` — becomes (or already is) that slice of a folder order;
- `→ brain: <page>` — a durable fact, upserted to that brain page;
- `→ rejected: <one-line reason>` — discarded;
- `→ L<n>` — the last resort: a loose end (`<home>/loose-ends.md`) that passes the five tests (glossary *Loose
  end*). Deferred work that waits on a trigger is `→ WO-NNN`, a parked work-order. (`→ P<n>`, the INDEX Parked row,
  is retired: in an open order the canary still checks it against the rows imported from Parked.)

A deferred point without its out-of-scope reason is `→ rejected:` and goes back into this order as a revision.

The canary's `loose-ends` category reads it: a resolved order (engine v44 or later) with notes
and no block is `order-notes-unadjudicated` (any content other than a "nothing notable" answer counts,
whatever the headings), and a destination that does not exist is
`adjudication-dangling`. Orders resolved before v44 are exempt and are not backfilled.

Only when model optimization was enabled at dispatch: add one compact model/outcome entry —
requested model/effort; confirmed effective values or an explicit unknown; acceptance, revisions, or
escalation with a material reason. Observed usage is optional. The orchestrator adjudicates any
model-selection lesson at normal closeout; no lesson is required. SSOT:
`references/model-optimization.md`.

### Revisions

Empty when the work-order is authored. Once the orchestrator has verified a landing, the changes the operator
asks for go HERE — not into a new work-order. The **orchestrator** writes the operator's ask as a
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
- a case where the offer would gate an unattended step fails the new check (h)
- `git diff --check` clean
```

---

## Index entry

Both forms take the same board row, and it comes from the front matter: run `ledger_index.py <home>` and type nothing.
An INDEX that is not yet the generated board (no `<!-- gitos:index board -->` line) is converted by `ledger_migrate.py`.

The last column is the file the order anchors to: the evidence `file:line` on a bug order, and on a
forward order the primary file the work targets.

When the work-order is resolved, add `released` to its front matter, MOVE the file to
`<home>/work-orders/resolved/` and run `ledger_index.py`: the order leaves the board. Its file is the record; the commit
is in `git log`.
