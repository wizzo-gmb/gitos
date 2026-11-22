# Orchestrator step: sprint mode

Read this when your start prompt says **sprint mode**: an unattended run started by the sprint driver, with the operator away.
Sprint mode is never entered on your own initiative, and a session whose start prompt does not say it is interactive: none of
this applies, and the work loop reads as written. The design and its reasons: `.gitos/brain/wiki/decisions/sprint-mode.md`.

A sprint is the **same work loop** (`references/roles/orchestrator.md`) with one gate relaxed and a few behaviours changed. You
orchestrate as usual: parallel implementers, one worktree per order, the dispatch rules in `dispatch.md` and the
model-optimization mapping. Where this file and another step file differ, this file wins for the sprint.

## What changes, and what does not

- **Step 4 (verify the landing) is the one gate that relaxes.** You accept your own verified landing when the self-acceptance
  criteria below all hold. The operator's acceptance is not asked for, and the `dispatch.md` line "do not resolve a WO the
  operator hasn't accepted" does not apply.
- **Every other gate stands.** Step 2: a sprint works the orders that are already open (the board's *Open* section); it
  proposes, creates, activates or reopens no order. Step 3: an open order is already operator-confirmed, so the plan the
  implementer writes into the order's notes before it executes is the plan, and no one is asked to approve it; you still pin
  disjoint files, state the scope bound and match the lenses. Steps 5, 6, 7 and 8 are unchanged: every note adjudicated in
  writing, commit by explicit path, canary green before resolving, no advance on an unverified diff.
- **A question is a card and a stop.** The operator is not in the window. Never ask in chat, with a popup, or with an
  Artifact. When you need an answer, put the card on the board (*Ask on the board*) and stop (*Stop triggers*).
- **Commits only.** Commit and merge a worktree branch locally. **Never push**, and never run an outward or shared-state action:
  a push or tag push, `federation file`, a deploy, a migration, a data regeneration, a release (`VERSION` bump, sync, publish),
  a send, or anything else that leaves this working tree and `.git`. An order or a note that calls for one is a stop, not a
  step.

## Self-acceptance (step 4)

Accept an order only when **all four** hold, each checked by you, not read from the worker's report: (1) the diff matches the
order's `## Proposed fix scope` (`system_one.py scope <home> NNN` lists forbidden and out-of-scope files, and you read every
hunk); (2) the order's own `## Acceptance` checks pass, run by you; (3) `canary.py` is green; (4) every implementer note is
adjudicated, in writing (`resolve.md`). <!-- rule:sprint-self-acceptance-criteria -->

Any failure is **not accepted**: the order stays open and you write the finding into the order's `## Revisions` (scoped, as in
`dispatch.md`). The first failed verification of an order: re-dispatch a revision and verify again. The second failed
verification of the same order: stop (`verify-failed-twice`). A failure no revision can fix (it needs the operator or an outward
action) is a stop at once. A deferral from adjudication that would need a new or parked order is the operator's call: write the
item into the order, leave it open and stop (`operator-decision`); a loose end that passes the five tests (`resolve.md`) is
still yours to write. <!-- rule:sprint-self-acceptance -->

## Which orders a sprint takes

A sprint works only **sprint-eligible** orders. Check an order before you take it; it is eligible only when all six hold:

1. It is open: not parked, and no `pending:` key.
2. It is a candidate: your start prompt lists the candidate orders (the operator's `--orders` list, else the open orders marked
   `sprint: ready`). An order not on that list is never taken.
3. Its Part-0 probe is done with GO recorded, or the probe is read-only and a worker can run it without the operator.
4. No operator decision is open on it: no unanswered board card with its `--ref`, no `waiting:` question, and no "operator
   decides" or Option left unpinned in the order.
5. Its scope and acceptance need no action a sprint may not take: none of the outward or shared-state actions listed under
   *What changes*, and none of the actions this repo's own rules make operator-only (its standing rules in the brain, its
   production contract if it has one).
6. Its front matter does not carry `sprint: no`.

An ineligible order is **skipped, not a stop**: log `note` with `skipped WO-N: <the failed criterion>`
(`sprint_log.py add note MESSAGE --ref WO-N`) and take the next order. When no eligible order remains, the sprint ends
`no-open-order`, and its STOP reason says how many orders were skipped. A criterion that turns false *during* an order (the
work reveals an action a sprint may not take, or a decision only the operator can make) is not a skip: it is the stop
`outward-action` or `operator-decision`.

## Stop triggers

A trigger is one of the ids below. Each stops the sprint after the exit sequence; none is waived.

| Id | When |
|---|---|
| `operator-decision` | a decision only the operator can make, or an answer you need |
| `outward-action` | the work needs a push or any outward or irreversible action (*What changes*) |
| `implementer-blocker` | an implementer hands back blocked, or without the order done and no revision can unblock it |
| `part0-no-go` | an order's Part-0 probe is NO-GO |
| `verify-failed-twice` | verification failed twice on one order |
| `no-open-order` | no eligible open order is left to work (*Which orders a sprint takes*) |
| `stop-card` | the sprint Stop card is answered, or `<home>/sprint/STOP` exists |

Check for the last at first action and at every step 8 (`board.py list --open`; the file). It ends the sprint **after the current
order is resolved or left open with its finding written**: do not start another order, and do not abandon a landing half verified.
A `STOP` file you find at your very start: end the session at once and write nothing.

## Exit sequence (a stop)

In this order, and nothing between them:

1. **RESUME.** Checkpoint (`checkpoint.md`): commit the verified state, regenerate the board, and replace `<home>/RESUME.md`
   wholesale. It names the stop id, the order it stopped on and the exact next step. A worker still running has its reattach
   line there, or you wait for it first.
2. **A board card, only when the operator must answer** (`operator-decision`, `outward-action`, `implementer-blocker`,
   `part0-no-go`, `verify-failed-twice`): `board.py add-decision`, with `--ref WO-NNN`, written for the owner (what you need and what
   each option does). Not for `no-open-order` or `stop-card`.
3. **`<home>/sprint/STOP`.** Create the directory if missing. The file is one line of plain text, `<id>: <reason>`, at most 200
   characters, naming the order when there is one. It is written **last**: the driver acts on its existence, so nothing may
   follow it. A `STOP` file that already exists is left as it is.
4. **End the session.** Your last reply is the marker line, then the same one-line reason on the next line (the STOP file's, or the ROTATE file's in a rotation). Make no further tool call.

## Rotation

Rotation in a sprint rides the second compaction and the marker slip only; the other rotation triggers in `checkpoint.md`
(an order resolved, an unrelated next task, a day boundary) do not rotate a sprint, and two failed corrections is
`verify-failed-twice`.

On the compaction hook's rotation line (the second compaction in this window), or a **second marker slip** in this window:

1. Checkpoint, as in step 1 of the exit sequence (RESUME with the reattach lines of any worker in flight, and the next step).
2. Write `<home>/sprint/ROTATE`: one line, the reason (`second compaction` or `marker slip`).
3. End the session as in step 4 of the exit sequence: the marker line and the one-line reason of the ROTATE file.

The hook's line also tells you to tell the operator a fresh window is ready: in a sprint, do not. The driver closes the session
and starts a fresh one, which reads RESUME and carries on. Never delete `ROTATE` or `STOP` yourself; a `ROTATE` file you find at
your start is the driver's to clear, and you ignore it.

## First action in a sprint

Run first action as written (`first-action.md`), with these differences:

- Run the board `ensure` and read the new answers and notes: an answered Stop card is `stop-card`, and any other answer is the
  newest instruction you have.
- **Report to no one.** The first-action report has no reader. Act on what it would say: fix a red canary finding that blocks
  resolving, drain a `loose-ends-stale` list, reap a merged worktree; leave engine drift, the federation heartbeat, intake and
  System One alone (nothing foreign becomes an order here).
- Log progress with `python <skill>/scripts/sprint_log.py add KIND MESSAGE --ref WO-N`, where KIND is `start` when you begin an order, `done` when you resolve it, or `note`, and MESSAGE is one short line. The driver sets `GITOS_SPRINT_HOME`, so the log finds the home from any directory, a worktree included.
- No git repository: stop (`operator-decision`), do not `git init`.
- Verify RESUME's claims as usual; a dead worker is dispatched again from its order, notes and diff (`dispatch.md`).
- Then take the first open order that is sprint-eligible (*Which orders a sprint takes*) and that the dispatch rules allow, in board order, honouring the order's own sequencing notes and
  folder orders' `slice.py next`.

## Output

Every reply in a sprint is the role marker line alone: no prose, no summary, no menu, no offer, no next-step suggestion. The
canary depends on the marker. The one exception is the last reply of the exit sequence (and of a rotation): the marker line,
then the one-line reason on the next line, the same text as the STOP or ROTATE file. Progress goes only where the operator
reads it: the sprint log (`sprint_log.py add`), the commits, `RESUME.md` and the board. <!-- rule:sprint-reply-marker-only -->
