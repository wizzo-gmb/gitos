# Glossary

The engine's lexicon and its source of truth: one meaning per word. The docs and the scripts follow it; where a
word keeps two senses, its entry says so. Definitions are domain-agnostic.

---

## Core stores

**Home** (`<home>`)
The directory that holds everything gitos keeps for a repo: `.gitos/` by default; a legacy `.pipeline/` or
`outputs/debug/` is adopted in place (detection order: `SKILL.md` → *First action*). It holds the ledger,
`HANDOFF.md`, `RESUME.md`, the brain, the role pointers, `tools/` and the subsystems' opt-in files.

**Engine**
The skill's shipped text and scripts (`SKILL.md`, `references/`, `scripts/`, `assets/`), versioned by `VERSION`.
A repo's **stamp** (`engine_version`) is the version it last adopted. The **payload** is what ships: no private
names in it, comments included. **Tools** are byte-copies of engine scripts in `<home>/tools/`, refreshed by upgrade.

**Ledger**
The work: `<home>/INDEX.md` plus `<home>/work-orders/`. The INDEX is the board: a generated header (engine version,
counts, pointers) and two tables, Open and Parked (the orders with `status: parked`). `ledger_index.py` writes the whole
file from the order files; nobody types into it, and its size follows the open work only. History is the order file in
`work-orders/resolved/` and `git log`; live state and next steps are in RESUME.

**Brain**
The orchestrator's long-term memory: typed, cross-linked pages (sources, entities, concepts, decisions) under
`<home>/brain/wiki/`, kept true by the maintenance loop (write test, upsert, checkpoint reconcile, `brain_lint.py`).
It holds only what the code, git, CLAUDE.md and the orders cannot say (why, what was rejected, traps). Its index is
generated from page front matter and it has no log. The brain holds knowledge, the ledger holds work, the handoff
holds the birth record: nothing is in two places. A federation
consult reads another repo's brain; nothing is copied into this one.

**Decision page** / **decisions page**
Two artifacts. A *decision page* is a brain ADR in `wiki/decisions/` (why a choice was made). The *decisions page*
is the optional private HTML page (`assets/decisions-page.html.tmpl`) that puts a large round of operator choices
on one screen.

**Handoff** (`<home>/HANDOFF.md`)
The birth record (also "birth certificate"): identity, acceptance criteria, hold-out, outcome, lifecycle stages,
parity status, production target and predecessor lessons, filled once at inception. Never edited afterwards, except
the `engine_version` stamp that upgrade writes in a repo with no brain. Not the production-handoff contract, and
not the thesis's verb "hand off".

**RESUME** (`<home>/RESUME.md`)
The live session pointer: what is serving or running and how to stop it, what is in flight and how to reattach,
who is waited on, the next three steps, pointers to the standing rules. Replaced wholesale at every checkpoint
and deletable without loss: a line that would still be true in a fresh clone belongs in the brain, the ledger or
the handoff, and RESUME only points at it.

**Standing rule**
An operator rule, written to the brain (`concepts/standing-rules.md`) in the turn it is given; RESUME points at it.

**Footprint**
The paths a landing's commit touched: `git show --name-only <sha>`. An *out-of-scope footprint* is a touched path the
order did not name; it is a defect and is reverted. Nothing records it elsewhere.

**Log vocabulary** (`<home>/log_vocabulary.md`)
The diagnostic's catalog of the project's own log and output formats. Not a brain event log (the brain has none: `git log -- <home>/brain`)
and not a per-order event log (folder orders have none: the slice files hold the state, `git log -- work-orders/WO-NNN` the history).

---

## Roles and the operator

**Operator**
The human who runs gitos: the thesis's *director*, never its runtime. The operator sets intent and adjudicates;
the engine detects, coordinates and verifies. Only the operator: confirms which work-orders exist; accepts a
landing or asks for a revision; authorizes outward-facing or irreversible acts (cross-filing, deploys, migrations,
data regeneration, deletions); consents to an opt-in subsystem or a harness change; and settles what the drain
raises as an ask. Everything else is the orchestrator's. The owner board's "owner" is the operator.

**User**
A product's end user ("user-facing"), or a Claude Code settings scope ("user scope", a user skill). Never the
operator, except in the skill's trigger text, which speaks the harness's language.

**Role**
One of five: inception, orchestrator, diagnostic, assessor, implementer (`SKILL.md` calls it the *mode*). The first four are
**repo-entry**: reached by detecting the repo's state and the operator's intent. The implementer is entered on one
work-order, by dispatch or by the operator opening a window on it. ("Operator-entry" is the retired name.)

**Inception**
The one-time bootstrapper: the interview, `scaffold.py`, the brain seed and `HANDOFF.md`, then control passes to
the orchestrator. Writes no application source.

**Orchestrator**
The persistent coordinator. Proposes and sequences work-orders, dispatches implementers, verifies each landing,
adjudicates the notes, resolves orders and stewards the brain. Never edits code: it writes only markdown and state.
("Front-line builder" is the retired name: the orchestrator coordinates, it does not build.)

**Diagnostic**
The read-only finder: builds the log vocabulary, scans the anomaly families, writes evidence-first work-orders. It
never edits code and never dispatches; asked for fixes, it hands its work-orders to the orchestrator.

**Assessor**
The read-only judge of direction: asks whether, given the goal, the project is doing the right work and what it is
fooling itself about (the diagnostic asks what is broken). Started only by the operator in a fresh window, never
dispatched; refuses while a sprint runs or `sprint/STATE.md` is unfolded. Reads the goal, the work and the claims, asks the
live orchestrator by direct message (an answer is a claim), and writes one *assessment*. Edits nothing else, writes no
work-order; its one allowed dispatch is a read-only helper for an earlier assessment's follow-through, only when needed.

**Assessment**
The assessor's durable report, `<home>/assessments/<YYYY-MM-DD>-<slug>/report.md`: focus, findings with evidence, numbered
recommendations, the questions asked and the answers as claims. Never pruned. The orchestrator puts it to the operator as
one board card and answers below the assessor's text under `## Orchestrator response`; only operator-approved items
become work. Earlier assessments are not read by default (`references/roles/assessor.md`).

**Implementer**
Lands one work-order or one slice, then returns. It edits only what the Proposed fix scope names and reports in
its Implementer notes; the orchestrator verifies and adjudicates. A *worker* is a dispatched implementer.

**Find ≠ fix**
The engine's first boundary: the role that finds a defect never fixes it or dispatches its fix, and the role that
fixes never marks its own landing done. Diagnostic finds, orchestrator coordinates and verifies, implementer fixes.

**Dispatch**
The orchestrator handing one work-order or slice to an implementer, with its scope, its pinned Option and, with
model optimization on, its tier.

**Helper**
The cheapest-tier agent that answers a drain export when no local model is available (down, off or not configured):
the drain is the local model's or a helper's, never the orchestrator's by hand. Not an implementer.

**Lens**
An operator-imported domain technique pack (`<home>/agents/`, or the global library `<skill>/agents/`) that a role
reads when its work matches, within its own boundary. It implements disciplines and says which; it is never a role.
Off unless `lenses.json` turns it on. `agents/` and `/gitos agent import` name lenses.

**Profile**
A *domain profile*: the gates, contract values and extra anomaly families a downstream product layers on the engine
(`references/profiles.md`). A *load profile* (traffic shape in a benchmark) is always written in full.

**Role marker** (context canary)
The first line of every reply, `[gitos · <role> · <focus>]`, with `<focus>` recomputed each reply. A missing, wrong
or stale marker is evidence of context loss. Canonical text: `SKILL.md` → *Canary*.

**Reinjection** (slippage protocol)
On a slipped marker: re-read the role brief and `SKILL.md`, restate role and focus; a second slip in one window
means a checkpoint and a fresh window.

**Durable anchor**
The managed `<!-- gitos:agent-system -->` block in the repo-root `CLAUDE.md`, which the harness re-injects every
window; it re-seeds the marker rule after compaction.

**Role pointer** / **memory pointer**
A role pointer is `<home>/roles/<role>.md`, naming the role brief for this repo. The memory pointer is
`~/.claude/projects/<dir>/memory/gitos_role_brief.md`, naming the home and default role.

**First action**
The orchestrator's start-of-session sequence (`references/roles/orchestrator.md` → *First action*).

**Work loop**
The orchestrator's numbered steps per work-order (propose, dispatch, verify, adjudicate, commit, resolve), each
closed by a `*Gate:*` it may not skip.

**Checkpoint**
Commit, refresh INDEX and RESUME, reconcile the brain. **Rotation** hands the orchestrator role to a fresh window
at a checkpoint.

---

## Work-order lifecycle and slices

**Work-order** (WO, order)
The unit of tracked work: `<home>/work-orders/WO-NNN-<slug>.md`, or a folder `WO-NNN/` once it has two slices.
Front matter `severity`, `title`, `evidence`; at resolution also `released` (the engine version). Lifecycle: open
(confirmed by the operator) → implemented → verified → accepted → resolved, or DISPROVED. Legacy
`bug_NNN_<slug>.md` and `wo_NNN` names still read.

**Bug work-order** / **forward work-order**
Two forms, chosen by the occasion: something broke → bug form, led by `## Evidence` (usually from the
diagnostic); something is wanted → forward form, led by `## Objective` (from the orchestrator). Both carry the same
`## Proposed fix scope`.

**Proposed fix scope** (`## Proposed fix scope`)
The implementer's hard boundary, in both forms: every file it may edit, and what stays untouched. A slice's
`## Scope` plays the same part. (The forward form's old heading `## Proposed scope` is retired.)

**Part-0 probe**
A cheap read-only GO/NO-GO the implementer runs before any edit; NO-GO stops the order for re-scoping ((c)).

**Severity**
`critical | high | medium | low | unconfirmed`: consequence if unfixed, not certainty. *Severity calibration* is the
rule set for choosing one.

**Risk notes** (`## Risk notes`)
The shared order section: reproducibility, blast radius, the discipline letters that apply, scope boundaries,
related work.

**Slice**
A unit of an order's work. In a folder order it is a file `slices/SN-<name>.md` with id `WO-NNN/SN` and a status
(`proposed | ready | in-progress | implemented | landed | dropped`); `drain accept --slice NAME` writes a follow-up
as a new `proposed` slice. A data partition is a *split*, never a slice.

**Folder order** / **single-file order**
An order with one slice is one file; `slice.py add` converts it into `WO-NNN/{order.md, slices/}` when a
second slice arrives.

**Landing** / **landed**
A *landing* is an implementer's returned change (status `implemented`), a claim until verified. Slice status
`landed` means the orchestrator merged it; the commit is in the slice's `commit:` and `git log`. The engine version
an order resolved in is the front-matter key `released:` (renamed from `landed:` in v57, which still reads).

**Verify** / **accept**
The orchestrator *verifies* a landing against the disk and the running system ((g)); the operator *accepts* it or
asks for a revision. Neither stands in for the other.

**Resolved**
Verified, accepted, adjudicated and committed; the order moves to `<home>/work-orders/resolved/`. The canary must be
clean first.

**DISPROVED**
A hypothesis ruled out by evidence, recorded on a brain decision page so nobody runs it again ((f)).

**Revision** (`## Revisions`)
A change the operator asks for after a landing, written into the same order and re-dispatched; a new direction is a
new order instead.

**Implementer notes**
The implementer's only write-back, under five labels: Deviations, Surprises, Durable facts, Process notes,
Follow-ups. Each note is a claim until adjudicated.

**Adjudication** (`### Adjudication`)
The orchestrator's written ruling on each note, one of three verdicts: ACCEPT (`→ WO-NNN`, `→ WO-NNN/SN` or
`→ brain: <page>`), DEFER (`→ WO-NNN`, a new or parked work-order; `→ L<n>` only as the last resort) or REJECT
(`→ rejected: <why>`; a deferral with no out-of-scope reason is rejected and goes back into the order as a revision). The same arrows are the one
routing grammar of `loose_ends.py drop --to` and `drain decline --route` (`closed: <reason>` in place of a verdict).

**Worktree**
The implementer's own git checkout, `<parent>/<repo>.worktrees/wo-NNN` on branch `wo-NNN` (`wo-NNN-sN` for a slice), reaped once merged and
clean. A **slice marker** in a slice worktree's git dir arms the `slice_guard` hook.

**Scope bound**
What the implementer may edit is what its order specifies, never what it designs; an approved plan of its own is not
a substitute.

**In-scope fix** (finish what you find)
A finding the implementer makes while working an order and fixes in that order because it sits within the order's
scope of work, however many lines: listed under *Deviations*, covered by the order's checks, reviewed like scope.
Only a finding clearly out of scope, or crossing into a new scope (another subsystem, a design or operator decision,
a file another in-flight order owns), is deferred, with that reason. Nothing is dropped. An unlisted out-of-scope
edit is a defect.

---

## Loose ends and the drain

**Loose end** (`L<n>`)
The last resort and the rarest form of deferred work: one row of `<home>/loose-ends.md` (*the list*). A finding is
fixed in its order; only one out of scope becomes a work-order or a parked work-order; a loose end is what is left,
and it passes all five tests: **concrete** (names a file, command, message or behaviour); **fix known and small** (no
investigation, root cause, design or operator decision); **self-contained** (actionable from the row alone); **not
owned** (not in an open order's scope, not fixed, not a duplicate); **a stated reason** it is out of scope now (e.g.
a parallel slice owns the file). Ideas, experiments and trigger-waits are not loose ends. `loose_ends.py add` refuses
a row without `--fix` and `--why-not-now`, and stores both in it. Its **State** is one of `new`, `proposed: <kind>`,
`waiting: <question>` or `declined: <reason>`; a State that cannot be read is reported, never read as `new`. Routed or
closed, it leaves the list: not on the list means routed. The canary says (advisory `loose-ends-last-resort`) when
the list holds more than 3 open rows or one older than 14 days.

**Drain**
The pass that turns `new` rows into proposals (`system_one.py drain` on the local model, or a dispatched helper
when it is down, off or not configured; never the orchestrator by hand): after an order
resolves, at each checkpoint, on `loose-ends-stale`, or when the operator asks ("drain the loose ends").

**Pile** (`<home>/drain/pending/`)
One file per drain proposal: the attachment of its `proposed:` rows (what was asked and found), removed when the
proposal is accepted, declined or withdrawn. The row is the authority.

**Drain proposal**
One pile file, of kind `join`, `new-order`, `ask`, `park`, `close` or `read`. Not a federation proposal.

**Ask**
A drain proposal for the operator; accepted, its row reads `waiting: <question>`. Generally, any question put to the
operator: a `waiting:` row, a popup, an owner-board card. The tool computes the ask; the orchestrator asks it.

**Parked work-order**
Deferred, out-of-scope work that waits on a named event: an order file with front matter `status: parked` and
`trigger: <restart trigger>`. The INDEX `## Parked` table is generated from these orders; at each checkpoint the ones
whose trigger fired are opened. The loose-end state `parked:` (v57) and the hand-kept `P<n>` row are retired;
`ledger_migrate.py` turns both into parked orders.

**Pending work-order**
An open order that waits on a live proof or a run: front matter `pending: <what it waits on>`. The board marks its title
`[pending: ...]`, the canary lists it once as the advisory `order-pending` and does not advise closing it; the orchestrator
removes the key when the proof lands. Not parked (parked is deferred work with a trigger).

**Carried box** (retired)
A `- [ ] L<n> (slice: <name>)` row in an order's `## Carried loose ends`, retired in v57: a follow-up into an order is a
`proposed` slice. A resolved order still holding an open one is `carried-open`.

**Join**
Adding an item to an open order; allowed only when the order's join test holds (`references/orchestrator/drain.md`).

**Defer**
The exception, written down in the same turn (the deferral rule): only a finding clearly out of the order's scope,
or crossing into a new scope, is deferred, as a work-order, a parked work-order or, last, a loose end. `intake
--defer` keeps a foreign proposal pending; `drain defer` leaves a pile file as it is.

**Close** / **decline** / **drop** / **withdraw** / **reject**
Close: the item is done (a drain kind). Decline: refuse with a reason (drain, intake; a loose end then reads
`declined: <reason>`). Drop: route a loose end off the list, or abandon a slice. Withdraw: set a proposal's rows back
to `new`. Reject: the adjudication verdict.

---

## Disciplines and verification

**Discipline**
An agnostic principle with a letter, cited by that letter (`references/disciplines.md`): (a) gate-math-is-code,
(b) precondition-guards, (c) cheap-probe-before-expensive-sweep, (d) check-the-path-not-the-schedule,
(e) copy-without-rename leak, (f) disproofs-are-deliverables, (g) trust-but-verify-the-landing,
(h) a-check-must-be-able-to-fail, (i) no-answer-is-not-a-pass, (j) a-null-needs-a-positive-control,
(k) attack-your-own-win, (l) name-the-clock, (m) evidence-or-name-the-gap, (n) a-rule-needs-a-mechanism.
A lens implements disciplines for a domain; a profile packages a domain.

**Gate**
A check that blocks: an acceptance gate, the canary at resolution, a selftest gate, a work-loop `*Gate:*`, the
publish guard, the OUTBOUND CONFIRM. Every gate owes a negative control.

**Negative control**
Plant a defect and confirm the check goes red; a check that cannot fail is not a check ((h)).

**Positive control**
Plant a known effect and confirm the instrument sees it; only then does a null result count ((j)).

**Known-answer test**
A test that pins a check's arithmetic to a hand-computed verdict, one passing and one blocking case ((a)).

**Acceptance criteria**
The project's promotion gates, with six properties: precommitted, measurable, evaluated on a hold-out, compared to
a null baseline, gate math tested, a negative control per gate (`references/acceptance-criteria.md`).

**Hold-out**
Data, traffic or an evaluation surface designated at project start and never used to build, tune or debug; read
once, or under attestation, with every read logged. One spelling: not "held-out", not "test set".

**Baseline**
Always qualified. A *null baseline* is the simplest alternative a candidate must beat. A *parity baseline* is the
proven implementation a port must match (`HANDOFF.md` → *Parity status*). A *benchmark baseline* is a reference
measurement. The *harness baseline* is what user scope may carry for every repo; the *session baseline* is model
optimization's first observation.

**Calibration**
Three senses, always qualified: *severity calibration* (how to choose a severity), *model calibration* (predicted
probabilities match observed frequencies, e.g. ECE) and *calibration drift* (anomaly family 8, the offline artifact
and the live system disagree).

**Lifecycle stages**
The project's own stage labels, declared in the handoff (e.g. draft → candidate → promoted).

**Production-handoff contract**
What was decided before the system went live (IO contract, environment, rollback, observability, prod-vs-dev
deltas), filled at promotion into `<home>/production-contract.md` from `references/production-handoff-contract.md`.

**Staged rollout**
Releasing to a small cohort or for a set window before everyone. (The deployment sense of "canary"; in gitos the
canary is the engine's sentinel.)

**Anomaly family**
One of the nine classes of defect the diagnostic scans for (`references/anomaly-families.md`).

---

## Subsystems

**Canary**
The engine's two drift sentinels. The *state canary* (`canary.py`) checks the home's state: it reports at bootstrap
and gates at resolution, by category, and a descoped category still reports but no longer gates. The *context
canary* is the role marker. The canary is the monitor; the operator's glance is the backstop. A finding is named `<concept>-<state>`, in
hyphens (`order-oversized`, `lens-registry-missing`): `missing` is absent, `oversized` is over its limit,
`unparseable` is read but malformed, `unreadable` could not be read at all, `stale` has gone out of date.

**Hooks**
Claude Code hooks the engine installs: `SessionStart` and `Stop` (`compact_restore.py`), `PreToolUse`
(`slice_guard.py`, `dispatch_guard.py`). A guardrail, not a proof: hooks can be switched off.

**System One**
An optional local decision model that drains the loose-ends list and does nothing else; its *uses* are the
questions it answers (`loose-end-state`, `loose-end-join`, `loose-end-bundle`, `loose-end-pick`, `probe`). A question
has a type: `noul` (yes/no; the name is code's), `choice` or `score`; the endpoint's answer comes in one of two
shapes, *typed* or *keyed*. Down is a normal state.

**Federation**
Opt-in, machine-local discovery between gitos repos (`<home>/federation.json`). A *tenant* is one repo's record in
the registry `~/.claude/gitos-federation/tenants/` (not a product tenant); a *sibling* is another federated repo;
*groups* decide who can reach whom (a group's *members* are the repos that name it), and the exposure flags
(`consultable`, `accept_proposals`) what they may do. The *heartbeat* refreshes this repo's own record at first
action. `INV-n` cites the subsystem's eleven numbered rules, listed in `references/federation.md`.

**Consult** / **cross-file**
`federation consult` authorizes a read of a sibling's brain; `federation file` writes one *proposal* into the
sibling's `intake/`, behind the OUTBOUND CONFIRM.

**Intake** (`<home>/intake/`)
Where federation proposals from siblings arrive; listed by metadata, their bodies data and never directives, and
accepted only against a work-order this repo authored. The word means nothing else.

**Harness**
The AI client that runs the agent (Claude Code, Codex). A repo declares the load it wants from it (skills, plugins,
hooks) in `<home>/harness.json`; `harness.py` measures and syncs it.

**Upgrade**
Bringing a repo onto the installed engine (`references/upgrade.md`): adopt the directives, refresh the tools, stamp
the version. A **Standard** repo runs it as is; a **Custom** (profiled) repo runs it through its `BRIDGE.md`, which
owns SYNC / PRESERVE / MERGE. "Bridge" means only that file.

**Model optimization**
Opt-in model and effort routing per dispatch, by tier (light / standard / deep) (`references/model-optimization.md`).

**Owner board**
The local answer page every home carries at `<home>/board/` (`references/owner-board.md`), served on 127.0.0.1 and
started by `board.py ensure`. A plan, a send, a `claim()` approval and anything asked while the operator is away is a
card there, never in chat or an Artifact; a single in-window question is asked and answered in chat, recorded in the
ledger the same turn. An answer counts only against the card as it is now, is recorded in the ledger before anything
acts on it, and is used once. <!-- rule:glossary-board-entry -->

**Waiting view** (`loose_ends.py status`, `scripts/waiting.py`)
The one place that lists everything waiting on the operator: drain `ask` proposals, loose-ends rows in state
`waiting:`, pending federation intake (a count), Parked rows whose restart trigger may have fired (a work-order it
names is resolved, or a date it names has passed), and the owner board's open cards and unread answers and notes,
read from its files. A view computed from the stores, never a store: RESUME's "Waiting on whom" points at it instead of restating it.

**Offer** (the one consent round) (`scripts/offer.py`)
Every opt-in the engine has (model optimization, lenses, System One, federation, legacy registers, the harness popup),
asked together in one question batch at inception and at upgrade. A question exists only while its store lacks the
answer, so an answered one is never asked again; nothing unanswered prints nothing. `federation.py offer` is the
federation part of it and still runs on its own.
