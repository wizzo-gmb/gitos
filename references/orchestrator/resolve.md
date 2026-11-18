# Orchestrator step: adjudicate, commit, resolve

Read this when a landing is verified and you adjudicate its notes (work-loop step 5), commit it (6), resolve it and move it to
`resolved/` (7), or sort a Durable fact.

## Adjudicate the notes (work-loop step 5)

5. **Adjudicate the notes.** Read the Implementer notes; ACCEPT each (→ brain / follow-up work-order),
   DEFER it (→ a new or parked work-order; a loose end last) or REJECT it (one-line reason), and **write it down** as
   a `### Adjudication` block under the notes: one line per point, ending in exactly one of `→ WO-NNN`, `→ WO-NNN/SN`,
   `→ brain: <page>`, `→ rejected: <reason>`, `→ L<n>` (`references/work-order-template.md` → *Adjudication*).
   An in-scope fix the implementer listed under Deviations is reviewed like scope; **an unlisted out-of-scope edit is
   a defect → revert.** → *Dispatch + verify.*
   *Gate:* every note is routed, in writing, before you continue. **Deferral rule (finish what you find,
   `references/disciplines.md` (o)).** The default is **fix it**: a finding made while working an order is fixed in
   that order when it sits within the order's scope of work, however many lines. **Deferral is the exception and
   must be justified:** only a finding clearly out of the order's scope, or one whose fix would cross into a new
   scope (a different subsystem, a design decision, the operator's decision, a file another in-flight order owns),
   is deferred, with that reason in one line. A follow-up without it is `→ rejected:` and goes back into the order
   as scope (a `## Revisions` entry, re-dispatched), not onto a list. **Nothing is dropped.** A justified deferral
   takes one of three forms, all last resorts, written down in the same turn (never only a chat line):
   (1) a **new work-order** when it is out of scope and matters (severity medium or higher, with evidence);
   (2) a **parked work-order** when it is out of scope and waits on a named event (front matter `status: parked`,
   `trigger: <restart trigger>`); (3) last and rarest, a **loose end** (`loose_ends.py add --fix "<the known change>"
   --why-not-now "<the out-of-scope reason, and why not an order>"`), only when it passes the five tests (glossary
   *Loose end*). A remark from the operator that is not acted on now is routed the same way. **Only the orchestrator
   writes the list and the parked orders.** At each checkpoint, read the parked orders whose trigger may have fired
   (`loose_ends.py status` lists them) and open them. The canary's `loose-ends` category checks the list, the notes,
   the parked orders' triggers and that no other store holds an item, and says when the list is no longer rare.
   **Convergence rule.** An order that would be the second follow-up on the same scope is not opened: the open
   order for that scope gets a slice (or a revision) instead. At each checkpoint, report the open count (orders +
   parked orders + loose ends) and whether it went down since the last checkpoint; a count that rises across two
   checkpoints is said to the operator in one line, with the cause.

## Harvest + adjudicate the implementer notes

- **Harvest + adjudicate the implementer notes.** When a work-order lands (you detect it:
  the `Stop` hook reports an order that has landed but is still open and, in one line, an open order or slice whose
  notes are filled and not adjudicated, and `worktree.py status` lists its merged worktree; the operator does not have to tell you), after you verify the diff, READ its **Implementer notes** section and
  decide each note **ACCEPT**, **DEFER** or **REJECT**:
  - **ACCEPT** → route it: a *durable fact* → a code comment where the fact lives, the tool's reference doc, or a brain
    page only when it passes the write test (`references/brain-schema.md` §1); a *process lesson* → fold into how
    you dispatch/sequence (and record a brain decision if it is a lasting workflow change);
    a *follow-up* → open a new work-order.
  - **DEFER** → only with its out-of-scope reason (without it: REJECT, back into the order as a revision): a new
    work-order (`→ WO-NNN`), a parked work-order when a restart trigger is named (`→ WO-NNN`), or, last, a loose
    end (`→ L<n>`) that passes the five tests.
  - **REJECT** → discard with a one-line reason (already known / not durable / incorrect /
    out of scope) and note the rejection in the work-order so the channel stays honest.
  Record every decision in a `### Adjudication` block under the notes, one line per point ending
  in exactly one destination (`→ WO-NNN`, `→ WO-NNN/SN`, `→ brain: <page>`, `→ rejected: <reason>`,
  `→ L<n>`).
  The canary flags a resolved order (v44 or later) with notes and no block; only a "nothing notable"
  answer needs none. Work-orders resolved before engine v44 are exempt and are not backfilled.
  You adjudicate because you own the brain's truth — an implementer's note is a *claim*, not
  a fact, until you accept it (the same trust-but-verify posture you apply to the landing
  itself). This harvest is the main way implementer experience becomes durable memory; it
  is part of the brain maintenance loop below (upsert → reconcile).
- **Enabled model optimization only:** during this same adjudication, optionally
  upsert a reusable model-selection lesson into the existing repo brain, per
  `references/model-optimization.md` → *Normal closeout → next selection*. No lesson
  is required; this adds no general handoff-improvement duty or review stage.

## Commit (work-loop step 6)

6. **Commit.** Commit the verified work; record the sha. **A commit is scoped to one work-order, the
   same way an edit is** — so **stage by explicit path**. Staging is directory-shaped and work-orders
   are not: a bulk stage takes whatever a dispatched agent has in flight, and the disjoint-files gate
   you set at step 3 dies at your own commit. Before committing, read the staged set back
   (`git diff --cached --stat`) and compare it against this work-order's scope — an unexpected path
   there is the same defect as an implementer editing an unnamed file: out-of-scope footprint (step 5).
   Caught there it is **unstaged**, not excused — the gate below forbids committing it. **Disclosure is
   for the sweep you find too late:** once the commit exists, name it in the next one and correct
   forward; never rewrite a published commit to look clean. The ledger is an audit trail, not a tidy
   story — and a sweep you hid is a boundary failure with the evidence deleted. **A worktree
   landing:** merge the `wo-NNN` branch, verify on the merged result, then run
   `worktree.py reap NNN` *before* step 7 resolves the order, so the canary run that closes resolution
   sees no leftover. Never stage a worktree path.
   *Gate:* **nothing is committed before steps 4–5 pass** — no commit of an unverified or
   un-adjudicated landing — and **the staged set matches this work-order's scope.**

## Resolve + maintain the brain (work-loop step 7)

7. **Resolve + maintain the brain.** Adjudicate the notes, stamp `released: v<N>` (the engine version) in the order's
   front matter, move the order to `resolved/` and run `python <SKILL_DIR>/scripts/ledger_index.py <home>`: the order
   leaves the board at that regeneration and nothing is copied anywhere. The order file in `resolved/` is the record,
   `ls work-orders/resolved` the list and `git log` the timeline; a landing's footprint is `git show --name-only <sha>`,
   so there is no footprint log to write. The canary's `index-drift` check gates a board that differs from the files.
   An order held open for a live proof carries `pending: <what>` in its front matter; remove it when the proof lands.
   **Sort each `### Durable facts` item** (judgment, one sentence in the adjudication): a code comment where the fact
   lives (most), the tool's reference doc, a brain page only if it passes the write test, or nowhere.
   Write a decision page on a non-trivial choice only when the order does not already record the why,
   **replace `<home>/RESUME.md` wholesale**, regenerate the brain index and run `brain_lint` + `canary.py`,
   reflection-pass the forward-positive invariant.
   → *INDEX lifecycle · Brain stewardship.*
   *Gate:* the board is regenerated, `brain_lint` is clean, and **the canary is green** before you move
   on — no work-order is resolved while the canary is red (fix the finding first — normal work;
   this gate joins verify-before-commit). **Resolving includes RESUME:** run the canary *after* the
   order moves to `resolved/` and the board is regenerated, and commit only on CLEAN. A resolution
   that skipped RESUME shows as `resume-stale` in that run, and an order merged but still open
   shows as `order-landed-not-resolved`, so the miss is caught in the same step. The check cannot see a
   RESUME refreshed within the last five minutes (its slack), so the habit still has to hold.

## INDEX lifecycle

`INDEX.md` is the board and nothing else: **Open** (by severity) and **Parked** (the orders with `status: parked`), fully
generated by `ledger_index.py`, bounded by the open and parked work and read whole. You never type into it. An order
resolves by adjudication, a `released:` stamp, a move to `resolved/` and a regeneration (step 7); history is looked up
on demand (the order file, `git log`), never copied. Live state and next steps live in `RESUME.md`; a disproved
finding or a release-shaping decision goes to a brain decision page when it passes the brain's write test, else it is
dropped (git keeps it). The canary advises when INDEX.md passes 16 KB: that is hand-written content.
Move each item open → implemented → verified → accepted → `resolved/` as it progresses.
