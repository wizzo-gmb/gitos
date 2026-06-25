# Work-order template

Every `outputs/debug/bug_<NNN>_<slug>.md` file must follow this exact structure.
Numbering is sequential from the highest existing bug. Slug is 2–4 kebab-case
words describing the bug (e.g., `state-resets-on-restart`, `tenant-id-frozen-to-placeholder`).

---

## Template

```markdown
# Bug <NNN> — <Short Title>

> **▶ Role on direct open.** Opened this work-order in a fresh window to *do the work* (or were
> dispatched to it)? You are the **Implementer** (`references/roles/implementer.md`), **not** the
> orchestrator: read this WO in full, **plan first → then execute**, edit **only** what
> `## Proposed fix scope` names, and fill `## Implementer notes` on completion. Driving the whole
> repo / deciding what's next instead? That's the orchestrator — `references/roles/orchestrator.md`.

## Severity
critical | high | medium | low | unconfirmed

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

[Reproducibility — how confident are you this is reproducible? Was it
observed once or N times across logs?]

[Blast radius — what's at stake if NOT fixed? Live trades? User-facing
output? Internal-only?]

[Scope boundaries — what NOT to fix in the same PR. List related
work-orders that should stay independent.]

[Related work — point at adjacent bug files or session notes the implementer
should also be aware of.]

## Implementer notes (fill on completion — the orchestrator reads and adjudicates this)

[Filled by the IMPLEMENTER when the work-order lands, NOT by the author. This is the
feedback channel back to the orchestrator: capture what's worth knowing that the diff
and the commit message won't show. The orchestrator will ACCEPT or REJECT each note —
accepted notes go to the brain or change how work is dispatched; rejected notes are
discarded with a reason — so be honest and specific. Everything here is **proposed**, never
self-executed: surface follow-ups and out-of-scope observations; the orchestrator decides
and acts on them.

- Deviations — where you departed from the Proposed fix scope, and why.
- Surprises — anything that contradicted the work-order's assumptions (the code wasn't
  where it said; a guard already existed; the fix revealed a second issue).
- Durable facts — things now true about the system the next session should know (a new
  invariant, a non-obvious coupling, a gotcha). Brain candidates.
- Process notes — anything about HOW the work went that could improve future dispatch
  (under/over-scoped WO, a missing precondition, a faster path).
- Follow-ups — work this surfaced that should become its own work-order (name it; do
  NOT fix it here).

"Nothing notable" is a valid and useful answer.]

## Revisions (post-landing — the verify→revise loop)

[Empty when this work-order is authored. After it lands and the operator verifies it, requested
changes go HERE — not into a new work-order. The **orchestrator** writes the operator's ask as a
scoped change; the **implementer** handles it on a re-dispatch (a fresh window on this WO) and records
the result. Repeat per round until the operator is satisfied, then the orchestrator resolves the WO.
A genuinely *new* direction (not a tweak to this landing) is a follow-up work-order via Implementer
notes, not a revision. Format per round:]

### Revision 1 — <date>
- **Requested (orchestrator):** <the operator's change, scoped — same boundary as Proposed fix scope>
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

---

## Index entry

After writing each work-order, append a row to the pipeline home's `INDEX.md`
(`<home>/INDEX.md` — e.g. `.gitos/INDEX.md`, or `outputs/debug/INDEX.md` on a
legacy home) in the "Open work-orders" section:

```markdown
| <NNN> | <severity> | <Title> | <primary evidence file:line> |
```

When the bug is later resolved (someone fixes it), MOVE the work-order file to
`<home>/work-orders/resolved/` and update the INDEX entry to the "Resolved" section
with a "Fix landed in" reference (commit hash for repo files, `(no git)` for
files outside any repo).
