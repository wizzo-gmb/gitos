# Orchestrator step: sprint mode

Read this when your start prompt says **sprint mode**: an unattended run started by the sprint driver (launched by an interactive orchestrator at the operator's request, or by hand), with the operator away.
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
- **State goes in `<home>/sprint/STATE.md`, never in `RESUME.md`.** RESUME stays the interactive orchestrator's file: a sprint
  does not read it as its own state, refresh it or commit it, and every checkpoint step below that says "write the state" means
  STATE.md. The driver writes the same file (its interrupted, refused and guard notes) and never RESUME. <!-- rule:sprint-state-not-resume -->

## The state file

`<home>/sprint/STATE.md` is replaced wholesale at every checkpoint, short and pointer-only like RESUME, with these sections and
a `Refreshed:` line: **In flight** (each worker running: what it is, its branch or worktree and the reattach or verify line),
**Last order** (the order in progress or just finished and where it stands), **Stop or rotate** (the stop id or the rotation
reason, and the exact next step) and **Notes for the operator** (what the person who folds it must know; the driver puts its notes
here, only while no session is running). It is local and git-ignored, like the log. A sprint never commits it; an interactive
window folds it into RESUME at its first action and moves it to `<home>/sprint/archive/` (`first-action.md`), and the driver
refuses a new sprint while one is left unfolded. Within one sprint a rotation keeps it: the next session reads it.

## In a named sprint

Your start prompt says so when the sprint has an id (`--id`). Several named sprints may run in this home at once, each in its
own terminal, on disjoint orders. Differences from the above:

- **Your session runs in your own worktree**, `<repo>.worktrees/sprint-<id>` on branch `sprint-<id>` (`GITOS_SPRINT_WORKTREE`).
  Your workers branch from it, and an order's merge lands on it, never on the main branch. Tracked ledger edits (orders, brain,
  `INDEX.md`) are yours and are committed there.
- **Your state is in the main checkout's home.** The driver gives it as `GITOS_SPRINT_HOME` (absolute) and your id as
  `GITOS_SPRINT_ID`, with `GITOS_SPRINT_PID` (the driver's pid). Write `STATE.md`, `STOP` and `ROTATE` under
  `$GITOS_SPRINT_HOME/sprint/<id>/`, never `sprint/` itself and never your worktree. Your signals are `sprint/<id>/STOP` and
  `sprint/<id>/ROTATE`; where this page says `sprint/STOP` or `sprint/ROTATE`, read that path. The Stop card is yours alone: it
  stops only this sprint. Act only on it: read it with
  `board.py answer-for $(cat $GITOS_SPRINT_HOME/sprint/<id>/stop-card.id) --tab sprint` (the driver writes that id file). Never act
  on the tab's other cards, and never run a plain `board.py list`, which would read another sprint's answers and lock them. Your board commands (`board.py`, from your worktree's copy) and approvals use `$GITOS_SPRINT_HOME`'s board
  automatically.
- **You cannot edit the repo's other trees.** Edit and Write are refused in the main checkout, other worktrees and the main home
  outside your `sprint/<id>/`. Your own worktree, your workers' area and `sprint/<id>/` are open. Do not edit those trees through
  Bash either: it is not guarded, and `land`'s clean-main check is the only backstop.
- **Only your orders.** Each `--orders` entry is claimed by this sprint (`<home>/sprint/claims/WO-NNN.json`) while the driver runs.
  Take no other order.
- **Landing is a tool.** After you resolve an order on your branch, run `python <skill>/scripts/worktree.py land --wait 600` from
  the sprint worktree. It first refuses if the main checkout is dirty or off the main branch, then reaps your own merged, clean
  workers, then takes the per-home merge lock (`--wait` waits for another sprint's land), merges the main branch into
  yours, regenerates the indexes, runs the gate (the canary, then the repo's `<home>/sprint-gate.json` command if it has one)
  and fast-forwards the main branch. **A refusal is a Stop card and a stop** (a conflict outside the generated files, a failed
  gate, a lock that stays held, a main checkout that is dirty or not on the main branch): never retry blindly, never merge by
  hand, never force.
- **The stuck cap is yours.** The driver ends a sprint that rotates twice with none of its own orders, branches or workers moving
  (`stuck`); another sprint's progress does not count for it.

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
| `guard-failed` | the repo's guard command (`<home>/sprint-guard.json`) did not exit 0 before a launch or after a close: written by the driver only, with a STATE.md note; you never write it |

Check for the last at first action and at every step 8 (`board.py list --open`; the file; in a named sprint, the `answer-for` command in *In a named sprint*). It ends the sprint **after the current
order is resolved or left open with its finding written**: do not start another order, and do not abandon a landing half verified.
A `STOP` file you find at your very start: end the session at once and write nothing.

## Exit sequence (a stop)

In this order, and nothing between them:

1. **STATE.** Checkpoint (`checkpoint.md`): commit the verified state, regenerate the board, and replace
   `<home>/sprint/STATE.md` wholesale (never `RESUME.md`). It names the stop id, the order it stopped on and the exact next step.
   A worker still running has its reattach line there, or you wait for it first.
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

1. Checkpoint, as in step 1 of the exit sequence (STATE.md with the reattach lines of any worker in flight, and the next step;
   never RESUME).
2. Write `<home>/sprint/ROTATE`: one line, the reason (`second compaction` or `marker slip`).
3. End the session as in step 4 of the exit sequence: the marker line and the one-line reason of the ROTATE file.

The hook's line also tells you to tell the operator a fresh window is ready: in a sprint, do not. The driver closes the session
and starts a fresh one, which reads STATE.md (and RESUME for the rest) and carries on. Never delete `ROTATE` or `STOP` yourself; a `ROTATE` file you find at
your start is the driver's to clear, and you ignore it.

## First action in a sprint

Run first action as written (`first-action.md`), with these differences:

- **Skip the fold** of an unfolded sprint state: that step is for interactive windows. Read `<home>/sprint/STATE.md` if it exists
  (your own earlier session's checkpoint, after a rotation) and carry on from it, then RESUME for the rest. Write your
  checkpoints to STATE.md and never to RESUME.
- Run the board `ensure` and read the new answers and notes: an answered Stop card is `stop-card`, and any other answer is the
  newest instruction you have.
- **Report to no one.** The first-action report has no reader. Act on what it would say: fix a red canary finding that blocks
  resolving, drain a `loose-ends-stale` list, reap a merged worktree; leave engine drift, the federation heartbeat, intake and
  System One alone (nothing foreign becomes an order here).
- Log progress with `python <skill>/scripts/sprint_log.py add KIND MESSAGE --ref WO-N`, where KIND is `start` when you begin an order, `done` when you resolve it, or `note`, and MESSAGE is one short line. The driver sets `GITOS_SPRINT_HOME`, so the log finds the home from any directory, a worktree included.
- No git repository: stop (`operator-decision`), do not `git init`.
- Verify the claims of STATE.md (and of RESUME, as far as they still hold) as usual; a dead worker is dispatched again from its order, notes and diff (`dispatch.md`).
- Then take the first open order that is sprint-eligible (*Which orders a sprint takes*) and that the dispatch rules allow, in board order, honouring the order's own sequencing notes and
  folder orders' `slice.py next`.

## Output

Every reply in a sprint is the role marker line alone: no prose, no summary, no menu, no offer, no next-step suggestion. The
canary depends on the marker. The one exception is the last reply of the exit sequence (and of a rotation): the marker line,
then the one-line reason on the next line, the same text as the STOP or ROTATE file. Progress goes only where the operator
reads it: the sprint log (`sprint_log.py add`), the commits, `STATE.md` and the board. <!-- rule:sprint-reply-marker-only -->
