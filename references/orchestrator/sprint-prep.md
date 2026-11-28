# Orchestrator step: preparing orders for a sprint

Read this when the operator asks to prepare orders for a sprint ("prepare for sprint", "prepare WOs for sprint", "let's run a
sprint"). You are the normal interactive orchestrator and the operator is in the window: this is **not** sprint mode (the
unattended session reads `orchestrator/sprint.md`). The result is a set of orders marked `sprint: ready` and, when the operator
asked for the sprint, the sprint launched by you in a visible PowerShell window. An unmarked order is never taken by a sprint that has no `--orders` list.

1. **Settle what is in flight first.** Read RESUME and `python <SKILL_DIR>/scripts/worktree.py status`. No unfolded sprint state is
   left: `<home>/sprint/STATE.md` was folded into RESUME at first action and moved to `sprint/archive/` (a sprint is refused while
   it exists). Every running or abandoned worker, unmerged worktree branch and integration branch is landed, parked, or left with
   an exact reattach line in RESUME, so an unattended sprint never has to guess. Anything that needs the operator is asked in
   chat. A `Sprint refused` or guard note carried in from STATE.md, or a canary finding `sprint-mark-unknown` or
   `worktree-layout-unparseable`, is fixed (the named file or order's `sprint:` value) and its note removed before anything is
   marked ready.
2. **Write down what is operator-only.** Criterion 5 relies on this repo's own standing rules naming what must never run
   unattended. Ask the operator, once: does anything in this repo beyond the generic list in `sprint.md` (*What changes*) have to
   stay operator-only (for example actions touching external systems or real data)? Record the answer in the repo's
   `standing-rules` brain page (`authoring.md`) before you mark any order ready. A page that already answers it is read back to
   the operator, who changes only what is wrong. This repo's own "is it safe to run unattended right now" check, if it has one,
   belongs in `<home>/sprint-guard.json` (`{"command": ["argv", ...], "timeout_s": N}`, `references/sprint.md`): the driver runs
   it before every launch and after every close, and only exit 0 lets the sprint go on. The engine ships none and names no
   venue; what it checks is the repo's to define. A repo whose work has outside effects also sets `busy_max_s` and `settle_s` in
   that file and has its own tooling write `<home>/sprint/BUSY` around each such action (`references/sprint.md`).
3. **Check every open order** against the six criteria in `orchestrator/sprint.md`, *Which orders a sprint takes* (refer to
   them, do not restate them): read the order, its Part-0 and notes, and its board cards (`board.py list --open`). For a folder
   order read its slices too (`slice.py next WO-N <home>` names what is dispatchable and what waits on what): the sprint
   dispatches slices, so an order is only as ready as its slices.
4. **Offer the fix for an order that fails a criterion you can fix.** Dispatch its Part-0 probe; ask the operator in chat to pin
   an Option or to answer a pending decision; or propose splitting the operator-only part into its own order (an order is
   created only with the operator's confirmation, as always). An order nobody fixes stays unmarked.
5. **Mark.** A folder order is marked only when at least one of its slices is `ready` with every dependency landed; slices still
   `proposed`, or whose Scope or Verification still reads "(to be written)", are written and set `ready` first (an order is never
   marked to be written later), or the order stays unmarked. The launch refuses a listed folder order with no such slice, and
   skips a marked one. With the operator's agreement set `sprint: ready` in the front matter of each order that passes, and `sprint: no`
   where the operator says an order never runs in a sprint; record it in the ledger in the same turn and commit by explicit
   path. Remove `sprint: ready` from an order whose state later makes it ineligible (a new decision card, a wait, new scope).
   A mark records that this check was done and the operator agreed; the sprint still re-checks every candidate when it takes it.
6. **Launch.** End with one line per open order, `WO-N ready` or `WO-N excluded: <why>`. When the operator asked for a sprint in this
   window, launch it yourself, from the repo root, with the `--window` form:
   `python <SKILL_DIR>/scripts/gitos-sprint.py --window [--orders 253,254] --effort <e> --max-rotations <n>`. The driver runs every
   check here first, so a refusal comes back to you (report it and fix it like any other, do not hand it over), and on success it
   opens a visible PowerShell window with Claude's install folder on its PATH and prints one line naming the window and the sprint id:
   report that line. Do not hand the command to the operator, and launch only when the operator asked for a sprint in this window,
   never on your own initiative. Without `--orders` it takes exactly the orders marked ready that have something to dispatch (it
   prints `sprint: skipped WO-N: <why>` for one that has not, and refuses when none is left). The repo root itself must be trusted: open Claude Code once in it and accept the trust
   dialog (a trusted parent folder is not enough), or the script refuses. Choose a model and effort that leave the lead a lower
   worker pair (haiku at low is refused). A sprint commits and merges locally and never pushes; the push stays the operator's.

   **Watch for the stop.** A launched sprint ends without telling you, so arm a watch for each launch in the background (Bash with
   `run_in_background`; it ends when a sprint stops, which wakes you):
   `python <SKILL_DIR>/scripts/sprint_log.py wait-stop --id a --id b --timeout 7200` (no `--id` for the exclusive sprint; run it from the
   repo root; add `--since <the launch time, ISO>` when a log of an earlier sprint may still be there). It reads only. It exits 0 and
   prints one line, `<sprint> <time> stop|error <order> <reason>`, when any listed sprint logs a `stop` or `error`; exit 3 means the
   timeout passed with every sprint still running, so arm it again. On the line, read that sprint's `STATE.md` and act: a stop you can fix
   (a stale mark, a refused order, a guard) is fixed and the sprint relaunched; a finished sprint is folded into RESUME at your next
   first action; anything that needs the operator is told to the operator in chat, with the reason.

**Several sprints at once.** To run more than one, split the ready orders into disjoint sets (no order in two sets) and launch
each set yourself with its own call, a few seconds apart (advice; the engine does not depend on it): `gitos-sprint.py --window --id <name> --orders <set>` (`<name>` is `[a-z0-9-]{1,32}`; `--orders` is
required), one window per sprint. Each named sprint works in its own worktree and branch, `sprint-<name>`, and lands on the main branch one at a time
through `worktree.py land`. The main checkout must be clean and on the main branch for a land to go through. A sprint started
without `--id` is the exclusive sprint: it runs alone, and no named sprint starts while it runs. If this repo's gate is more than
the canary, put it in `<home>/sprint-gate.json` (`{"command": ["argv", ...], "timeout_s": N}`): `land` runs it in the sprint
worktree before every land. The gate is read from the main branch only; a sprint's own copy of the file is ignored. Your own merges while sprints run take the same lock: `worktree.py lock acquire`, merge and gate,
then `lock release`. The lock belongs to your Claude session; on Windows a session hosted by `node.exe` is not recognised, so
pass `--pid` of a process that lives through the merge (it fails closed without one).
