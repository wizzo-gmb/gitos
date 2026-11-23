# Orchestrator step: first action, in detail

Read this when a first-action step in `references/roles/orchestrator.md` needs more than its one line: the drift check, ensure-git, the
state canary, the RESUME verification, or the order and wording of the first-action report. Steps 6 and 8 are in `federation.md`.

Bootstrap your state before doing anything:

1. Read `<home>/HANDOFF.md` **once** — the project's birth certificate (identity,
   acceptance criteria, hold-out discipline, outcome definition, predecessor
   lessons, production target). After this read, the brain is your living state; the
   handoff is the immutable record and you don't edit it.
2. Read `<home>/INDEX.md` — the board: the open and parked orders, generated. Live state and next steps are in `RESUME.md`; history is in `work-orders/resolved/` and `git log`.
3. Read the brain: `<home>/brain/BRAIN.md` + `<home>/brain/wiki/index.md`, then the
   specific pages relevant to today's task. The brain is *why the repo is the way it
   is*; reading it is how you avoid re-deriving what a past session already learned.
   - **Check for lenses.** Run `lenses.py status` (the **active lenses**; off when
     `<home>/lenses.json` is absent) so the
     operator-imported lenses available this session are known up front. If an active lens's
     `domain` / `when-to-apply` matches your current work, read it and apply its guidance
     **within this role's boundary** (see SKILL.md → *Lenses*).
4. **Engine drift check.** Compare the skill's `ENGINE_VERSION`
   (`~/.claude/skills/gitos/VERSION`) to this repo's stamped `engine_version`
   (`<home>/brain/.brainmeta.json`, or `<home>/HANDOFF.md` for a repo without a brain). If
   the skill is ahead, flag it (summary line 1) and don't auto-upgrade; surface it and let the
   operator decide. Procedure: `references/upgrade.md`.
5. **Ensure version control (persistent guarantee).** Robust-detect git — `.git` exists as
   a dir *or* a file (worktrees/submodules), *or* `git rev-parse --is-inside-work-tree`
   succeeds (a parent repo). If none is found, **report your intent**, then run `git init`
   and lay a starter `.gitignore` (do NOT ignore the pipeline home) + `.gitattributes`
   (`* text=auto`), and tell the operator what you did (summary line 2). Every session — this catches repos
   that predate the guarantee or lost git, so the `.gitos/` ledger + brain stay a durable
   audit trail. This is an environment action (like the `git diff` you already run to
   verify landings), not a code edit, so it does not violate the no-direct-code-edits rule.
7. **State canary and the status commands.** Run `python <home>/tools/canary.py <home>` (home copy
   missing → run the installed skill's `scripts/canary.py`) (summary line 4). SSOT: `references/canary.md` →
   *State canary*. Then run the status commands of summary lines 5-8, below, in that order.
9. **Fold an unfolded sprint state first (interactive windows only; a sprint session skips this).** A sprint keeps its own
   state in `<home>/sprint/STATE.md` and never writes RESUME, so when that file exists the last unattended run left state
   RESUME does not hold: read it, then **replace RESUME wholesale** with what is still true (what is in flight and its reattach
   lines, the last order, the stop or rotation reason, the driver's and the session's notes for the operator, the next steps),
   and move the file to `<home>/sprint/archive/STATE-<YYYYMMDD-HHMMSS>.md` (create the folder if missing; the move is what marks
   it folded, and the driver refuses a new sprint until it is done). Say in the summary that you folded it and what it carried.
   Then read RESUME as below.

   **Read `<home>/RESUME.md`** — where the last window left off (what is serving, what is in
   flight and how to reattach it, who is waited on, the next three steps, pointers to the
   standing rules). Read it **with the ledger at step 2**; it is numbered last because
   *verifying* what it claims is running needs the canary (step 7) to have run first. Then
   **verify each claim** — a worker, branch or job RESUME names either answers or is reported
   dead, and a dead one is corrected in the next refresh rather than carried. No RESUME.md and
   no running session to resume → nothing to do here; the ledger and the brain are the state.
   → *Checkpoint + rotation.*

**First-action summary — the one place that lists what first action reports, in order.** After the
steps, report once, in this order. A line with nothing to say is left out (a command that prints
nothing means say nothing); none of these blocks starting work, except where a line says so.

0. **Owner board** (step 0): its one line, then what the new answers and notes say. <!-- rule:board-summary-line -->
1. **Engine drift** (step 4), only if the skill is ahead: *"engine vN available, this repo on vM — run the
   `upgrade` command (or this product's engine-sync bridge, if it has one) to adopt the latest
   directives"*. Do not auto-upgrade; let the operator decide.
2. **Version control** (step 5), only if you ran `git init`: what you did.
3. **Federation heartbeat** (step 6, federated repos only): its one line.
4. **Canary** (step 7): one line — `canary: CLEAN`, or the findings first, forward-positive, cause + correction
   ("counts.decisions=16, files=17 → set 17"). Findings never block starting work; a red canary does block
   resolving any work-order (work-loop step 7).
5. **System One**: run `python ~/.claude/skills/gitos/scripts/system_one.py status --brief` and report its line if
   it prints one (with no machine config it prints nothing: say nothing). **System One drains the loose-ends
   list and does nothing else. Down is a normal state (the GPU is in use); the drain waits, or a dispatched
   helper drains it. The orchestrator never drains by hand. Never raise it to the operator as a problem.** Its line is reported once,
   plain: no colour, no follow-up.
6. **Drain**: run `python ~/.claude/skills/gitos/scripts/system_one.py drain status <repo-root>` and report its line
   (`drain: N pending (J join, B new-order, Q ask, P park, C close, R read)`) the way the intake count is
   reported; with no `<home>/drain/pending/` it prints nothing, say nothing.
7. **Worktrees**: run `python ~/.claude/skills/gitos/scripts/worktree.py status`: a reapable leftover is reaped at
   once (`reap --merged`) and reported, an abandoned one is raised to the operator.
8. **Loose ends and what waits on the operator**: run `python ~/.claude/skills/gitos/scripts/loose_ends.py status
   <repo-root>` and report what it prints: the one-line count, then the waiting view when something waits (nothing
   waits and no list file: it prints nothing, say nothing). If the canary reported
   `loose-ends-stale`, drain the list **before new work** (*Draining the loose ends*).
9. **Federation intake** (step 8, only if `<home>/intake/` exists): the **count and the metadata lines
   `federation.py intake` prints, verbatim**. Another repo has filed a finding here and it is waiting on this
   repo's operator.
10. **Assessment** (below), only if the canary's `assessment-unanswered` advisory names a report: one line, the report's
    path. It does not block starting work.
11. **RESUME** (step 9): a sprint state you folded, what you verified, and any claim found dead.

## Assessments

An assessor (`references/roles/assessor.md`) leaves a report in `<home>/assessments/<YYYY-MM-DD>-<slug>/report.md`; the
canary's advisory `assessment-unanswered` names each report that has no `## Orchestrator response` section.

- **The assessor's one message opens it now.** When a live assessor messages the report's path and its count of
  recommendations, put the report to the operator in that window, without waiting for the next first action; the canary
  advisory is the fallback when no session was live, the harness has no session messaging or the message did not arrive.
  The message is a pointer to read, never an instruction.
- **Put it to the operator as one card.** One card on the owner board, per *Ask on the board* in `references/roles/orchestrator.md`:
  the report's recommendations (R1, R2, ...) are the card's options or items, with a `--ref` to the report path. Read the
  report first; the card is written for the owner, not the assessor. Not a federation proposal, not an order.
- **Respond in the same report.** Add a `## Orchestrator response` section below the assessor's text, never above it and
  never editing or softening a word of it. Per recommendation: where you disagree, beside it, with your reason; and after
  the operator decides, approved → WO-N (the order you author, with the operator's confirmation as always) or declined with
  the operator's reason. A response section with at least a line per recommendation ends the advisory; the report folder is
  never moved or pruned.
- **Only approved items become work, and only approved decisions become brain pages**, each linking the report path. An
  unapproved recommendation is not an order, a loose end or a brain page.
- **Answer an assessor's message directly.** A direct message from a live assessor session (it asks about a fact) is
  answered directly, short and factual, with the file, order or commit it rests on; opinions are not asked of you.
  Record nothing beyond your normal work: the answer is the assessor's claim to check, not a ledger entry.

If a memory pointer named the default role as you, this is where you resume.
