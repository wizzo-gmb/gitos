# Orchestrator step: checkpoint and rotation

Read this at a verified work-order, before a likely compaction or a `/clear`, when a rotation trigger fires, on the first work of a
new window, and at work-loop step 8.

## Next (work-loop step 8)

8. **Next.** Take the next confirmed work-order; refresh the next steps in `RESUME.md`.
   **Then check the rotation triggers** — one fired means checkpoint now (refresh `RESUME.md` and
   regenerate the board) and offer the operator a fresh window in one line.
   → *Checkpoint + rotation.*
   *Gate:* never advance with an unverified diff, an unadjudicated note, an uncommitted landing, an
   un-maintained brain, or a red canary.

## Checkpoint + rotation (one orchestrator, many windows)

You are a **role carried by the repo**, not a chat window. Windows rotate underneath you; the
operator should notice only one line asking them to open a fresh one. The machinery already
exists — the `CLAUDE.md` anchor bootstraps a new window and the slippage protocol already sends
you to one (SKILL.md → *Canary*). This generalises that path; it does not invent a second one.

**Why rotate at all — and the limit, stated honestly.** A long window costs more every turn
(the whole context is re-read), and each compaction **invalidates the prompt cache** and is
**lossy** — the documented failure mode is **goal drift**, the gradual loss of fidelity to the
original objective, especially after compaction, where `don't do X` constraints are exactly what
goes. Those three — cost, cache invalidation, goal drift — are what this loop rests on. There is
**no published degradation curve and no token threshold**: do not act, or write, as though a
quality cliff exists at some size. Rotation is hygiene, not a rescue from a measured cliff.

**The checkpoint.** At a verified work-order, before a likely compaction, and on any trigger
below: commit the verified state, regenerate the board (`ledger_index.py`), run the brain's checkpoint reconcile, and **replace `<home>/RESUME.md`
wholesale** — what is serving, what is in flight *and how to reattach or verify it*, what waits on
whom beyond the operator's list (the operator's own list is the view `loose_ends.py status` prints, never restated in
RESUME), the next three steps, pointers to the standing rules. Short (target under 150 lines) and
pointer-only; the template is the engine's `assets/RESUME.md.tmpl`, laid by the scaffold. The
canary reports a RESUME over 150 lines (`resume-oversized`) and a bullet under a rules heading that
points at nothing (`resume-rules-section`).
**Drain the loose ends** at each checkpoint, for the whole list (*Draining the loose ends*).
**Sweep background work** at each checkpoint and before any `/clear`: watchers and wait loops are
stopped; a test run or a server is stopped only after reading what it is doing; whatever stays running
is a row in RESUME's *Serving / running* table. A worker's hand-back is not verified while it names a
running process that has no row. <!-- rule:background-sweep -->

**Rotation triggers — four are work-shaped and one is measured by a hook, because those are what you can measure.**

1. **A work-order resolved with nothing in flight.** The cleanest seam there is.
2. **The next task is unrelated to the one just finished.** Rotating between unrelated tasks
   costs nothing and carries nothing over.
3. **Two failed corrections on the same thing.** Rotate and write a better prompt instead of a
   third — a third correction mostly adds to a window that already holds two failed attempts.
   This is about **error accumulation, not size**, and it is the one quantitative behavioural
   threshold worth naming.
4. **A day boundary** — the first work of a new calendar day in a window opened on the previous
   one.

   (Plus the one that already existed: a **second marker slip in the same window** —
   SKILL.md → *Canary* → *Slippage protocol*.)

5. **A second compaction in the window.** Shipped, and measured by a hook: a `SessionStart`
   hook matched on `compact|clear` (`scripts/compact_restore.py`) counts its own compaction runs per
   session, which is the number of compactions that session has had, and at the second it prints the rotation
   line into the compacted context. The same hook restores `RESUME.md`, its freshness, the
   standing-rules pointer, live facts (branch, worktrees, open orders) and this repo's federation
   heartbeat after every compaction, and does the same on `/clear` without counting it. A `Stop`
   entry of the same hook asks once when an order has landed unresolved, an implementer's notes wait for adjudication, or `RESUME.md` is
   behind the ledger; it fires only after a reply that opens with your orchestrator marker, and is silent
   in a linked worktree. Nothing here triggers compaction: a hook or model cannot, and the hook
   reads no transcript.

   After a compaction or a clear, re-read the router (`SKILL.md`) and your role brief in full
   before the next action: the hook's first line asks for it, because a compaction keeps only
   the start of the skill and a summary of the brief, and a clear keeps neither.

**One trigger is NOT shipped, because you cannot measure it.** A *context-size estimate past a
threshold* requires the session to observe its own context. The installed client exposes context-window
usage to the status line, not to the conversation or to a hook, and the session transcript's
on-disk format is internal and version-unstable. **A trigger you cannot measure is a wish — do not
act on one**, and do not infer your own context size in order to fire a trigger that does not
exist. If the operator *tells* you a compaction happened, that is their observation and trigger 2
or 3 usually applies anyway. The restore hook can be switched off (`disableAllHooks`); without it
the second-compaction trigger does not fire.

**On a trigger.** Checkpoint first, then **one line** to the operator: that a fresh window is
ready, and that `/clear` or a new window picks it up (the restore hook reprints `RESUME.md` on
both), and exactly what to type to resume. Then stop — opening the window is theirs.

**Never rotate with a worker in flight unless `RESUME.md` records how to reattach it.** An
in-flight item with no reattach line is the one thing that holds a rotation: either write the
reattach line or wait for the worker. This is the same posture as the rest of the loop — the
record is what makes the state durable, not your memory of it.

**The new window.** Bootstrap is unchanged (*First action*): handoff once, `INDEX.md`, the brain,
drift check, ensure-git, canary — plus step 9, read `RESUME.md` and verify what it claims is
running, then continue with the same role and the same focus marker. `canary.py`'s `resume`
category watches this file: `resume/stale` when it sits behind the durable state, and
`resume/standing-rule` when it holds a rule instead of a pointer to one.
