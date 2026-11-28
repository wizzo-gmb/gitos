# Sprint mode (operator guide)

A sprint works through a repo's open work-orders in a visible Claude session while you are away. You start it with one
command in a Windows terminal; a driver script keeps the session going, replaces it with a fresh one when it has compacted
twice, and ends it when a stop signal appears. The rules the orchestrator follows inside the session are in
`references/orchestrator/sprint.md`; the reasons for the design are in the repo's brain (`wiki/decisions/sprint-mode.md`).
Nothing in a repo changes until you run the command there.

## Start

```
python <skill>/scripts/gitos-sprint.py [REPO] [--autocompact TOKENS] [--effort LEVEL] [--model MODEL]
                                       [--add-dir DIR ...] [--max-rotations N] [--orders NUMS]
```

`REPO` is the repo root (default: the current directory; the gitos home is found the way the router finds it). The session
opens in that terminal, in the repo root, and you can watch it and step in. Windows only for now.

| Flag | Default | Meaning |
|---|---|---|
| `--autocompact` | `500k` | the session's auto-compact window in tokens (`500k`, `1M`, `200000`); at least 200k and not above the model's context |
| `--effort` | `medium` | `low`, `medium`, `high`, `xhigh` or `max` |
| `--model` | `opus[1m]` | the orchestrator's model; the default is the 1M-context Opus, which a 500k window needs |
| `--add-dir` | none | an extra directory the session may use (repeatable) |
| `--max-rotations` | `20` | rotations allowed before the sprint ends |
| `--orders` | the open orders marked `sprint: ready` | the candidate orders, as numbers (`253,254`, or `WO-253,WO-254`) |

The flags set the **orchestrator session only**. Workers keep the model and effort the orchestrator dispatches them at under
the repo's model-optimization mapping. There is no config file. Permission mode is never passed: your own Claude setting
applies, and the driver never passes a permission-bypass flag.

## Several sprints at once

`--id NAME` (`[a-z0-9-]{1,32}`, with `--orders`) makes a **named sprint**. Open one terminal per sprint, give each its own
`--id` and disjoint `--orders`, and run them together:

```
python <skill>/scripts/gitos-sprint.py --id a --orders 253,254
python <skill>/scripts/gitos-sprint.py --id b --orders 260
```

Start them a few seconds apart. This is advice only; the engine does not depend on it.

- **Its own state.** A named sprint keeps `STATE.md`, `log.jsonl`, `STOP`, `ROTATE`, `BUSY` and `archive/` under
  `<home>/sprint/<id>/`, and has its own Stop card (the board's *Sprints* view shows it). A card names its sprint and stops
  only that one. The session reads only its own card (`board.py answer-for <its stop-card.id> --tab sprint`), never the tab's
  other cards, and its signals are `<home>/sprint/<id>/STOP` and `ROTATE`. The stuck cap counts only that sprint's own orders and branches.
- **Its own worktree.** The driver makes `<repo>.worktrees/sprint-<id>` on branch `sprint-<id>` from the main branch's tip and
  starts the session there. Its workers go to `<repo>.worktrees/sprint-<id>.worktrees/`. The session gets `GITOS_SPRINT_ID`,
  `GITOS_SPRINT_PID` (the driver's pid), `GITOS_SPRINT_WORKTREE` and `GITOS_SPRINT_HOME`. At the end the worktree and branch are
  removed only when the branch is in the main branch and the tree is clean; otherwise both stay and `STATE.md` says so.
- **The main home is the meeting point.** Claims, each sprint's folder, `EXCLUSIVE`, the merge lock and the board live in the main
  checkout's home, whichever worktree a session runs in. `GITOS_SPRINT_HOME` must name a real home. The session's board commands
  and approvals use that home's board, so an answer you give on your real board is the one the sprint sees.
- **What a named session may edit.** Its Edit and Write tools are refused in the repo's other trees: the main checkout, other
  worktrees, the main home outside its own `sprint/<id>/`, and other sprints' worktrees. Its own worktree, its workers' area and
  its own `sprint/<id>/` are open, and so are files outside the repo. Edits made through Bash are not guarded, so the check
  `land` makes on the main checkout is the backstop.
- **Order claims.** Each `--orders` entry is claimed in `<home>/sprint/claims/WO-NNN.json` while the driver runs. A sprint is
  refused when another live sprint holds one of its orders, or when its own `STATE.md` is unfolded. Another sprint's unfolded
  state does not block it. A claim whose process is gone (or whose pid now belongs to another process) is stale: a new sprint
  takes it over and says so in its `STATE.md`, and the canary reports it (`sprint-claim-stale`).
- **Landing.** The session lands each resolved order with `worktree.py land --wait S`. First `land` checks that the main checkout
  is clean and on the main branch, and refuses at once if not (before the lock and the gate). It then reaps the sprint's own
  merged, clean workers, so the canary does not meet them. Under the per-home merge lock
  (`<home>/sprint/merge.lock`, one holder at a time; `worktree.py lock acquire|release|status`) it merges the main branch into the
  sprint branch, regenerates the indexes, runs the gate and fast-forwards the main branch. The gate is the canary, then the
  command in `<home>/sprint-gate.json` (`{"command": ["argv", ...], "timeout_s": N}`) if the repo has one. A refusal (a
  conflict, a failed gate, a dirty or off-branch main checkout, a lock that stays held) is a Stop card, never a guess. Keep
  your own checkout on the main branch and clean while sprints run.
- **Your own merges.** The interactive orchestrator wraps its merge in `worktree.py lock acquire` and `lock release`. The lock is
  held by its Claude session. On Windows a session hosted by `node.exe` is not recognised: pass `--pid N` of a process that
  lives through the merge, or the command refuses.
- **The exclusive sprint.** A sprint without `--id` keeps today's paths and runs in the main checkout. It is refused while any
  named sprint runs, and every named sprint is refused while it runs (`<home>/sprint/EXCLUSIVE`).

Leftovers after a crash are reported, never removed: the canary's `sprint-claim-stale`, `merge-lock-stale`,
`sprint-exclusive-stale`, `sprint-state-unfolded`, `sprint-worktree-left` and `sprint-workers-left` (the last one is cleared with
`worktree.py reap --merged` in the main checkout). The first action of the next interactive window folds every unfolded state.

## What it refuses

Each refusal is one sentence on the screen, nothing is launched, and the exit status is 2:

- no gitos home in the repo;
- a hub-routed repo (`board-route.json` says mode `hub`) or a `board-route.json` that does not parse: sprint mode does not
  support them yet (mode `local` is a repo with its own board and is fine);
- no owner board in the home (the Stop card needs it);
- the repo root is not trusted in your `~/.claude.json`: open Claude in the repo once and accept the trust dialog (a prompt would
  otherwise wait behind it with no one there). Claude Code does not inherit trust from a parent folder, so a trusted parent is
  not enough. This holds for every sprint, the exclusive one too. The driver only reads that file;
- a `STOP` file from an earlier sprint: read `<home>/sprint/STOP`, then delete it;
- a `<home>/sprint/STATE.md` left by an earlier sprint (*State*): fold it in a normal orchestrator window first;
- `--autocompact` below 200k, or above the model's context window (a window that small makes the session compact again and
  again);
- a `--model` that is not the ceiling model of the repo's model-optimization mapping (checked only when that mapping is on);
- an `--orders` entry that is not an open work-order (resolved, parked or missing), named in the sentence;
- an `--orders` entry marked `sprint: no`, named in the sentence; and, with no `--orders`, a repo with no open order marked
  `sprint: ready` (prepare orders in a normal orchestrator window, or pass `--orders`);
- a `--model` and `--effort` that leave the lead no worker below it under the repo's dispatch rule (a worker on the lead's
  model runs at lower effort, a lower model at up to `high`), for example haiku at low: the lead could dispatch nothing. Raise
  `--effort` or use a higher model;
- a `GITOS_SPRINT_HOME` that is not a gitos home (no `INDEX.md` beside `work-orders/` or `sprint/`), so a log is never written
  into a repo root;
- an `--add-dir` that is not a folder, a platform other than Windows, or no `claude.exe` on `PATH`.

A file the driver reads that is malformed is refused the same way, before anything is launched: `worktrees.json`, `board/board.json`,
`board-route.json`, `model-optimization.json`, `sprint-guard.json` (*The guard command*), or an order's `sprint:` value other than `ready` or `no`. The refusal names the file and
the problem, and the driver writes a `Sprint refused` note into the sprint's `STATE.md` (*State*). The same happens if a file goes bad during
a sprint: the sprint ends at the rotation instead of relaunching. Fix the file in a normal orchestrator window ("prepare for sprint"
clears these first), then rerun. The canary also reports `sprint-mark-unknown` and `worktree-layout-unparseable` when no sprint runs.

## Which orders it takes

A sprint is the middle of a loop: **prepare** the orders in a normal orchestrator window ("prepare for sprint": the orchestrator
settles what is in flight, asks once what in this repo must stay operator-only and records it in the standing rules, checks each
open order against the sprint criteria, offers fixes, and with your agreement marks the passing orders `sprint: ready`; it ends
with the command to run, `references/orchestrator/sprint-prep.md`), **run** the script in a terminal, **watch** the `sprint` tab,
then come back to a normal window to review what landed and push.

The candidates are fixed when the sprint starts and named in the start prompt of every session and in the first log line
(`orders=WO-253,WO-254`):

- with `--orders`: exactly that list (an order you name need not be marked);
- without `--orders`: only the open orders marked `sprint: ready` in their front matter. **An unmarked order is never taken
  unattended.** `sprint: no` marks an order that never runs in a sprint, for any reason: it is not a candidate, and naming it in
  `--orders` is refused.

Among the candidates the orchestrator re-checks every order when it takes it and takes only the **sprint-eligible** ones
(`references/orchestrator/sprint.md`, *Which orders a sprint takes*): open, a candidate, probe done with GO (or read-only), no
operator decision open on it, no action a sprint may not take (the outward and shared-state actions the rules list, and anything
this repo's own rules make operator-only), and no `sprint: no`.

An order that fails a criterion is **skipped, not a stop**: the log gets a `note` line, `skipped WO-N: <the failed criterion>`,
and the sprint takes the next order. When no eligible order is left the sprint ends `no-open-order`, and the `STOP` reason says
how many were skipped. An order that turns out to need an action a sprint may not take, or your decision, while it is being
worked is still a stop (`outward-action`, `operator-decision`).

## Stopping

- **The Stop card.** At the start the driver posts one card on the board's `sprint` tab: *Stop after the current WO*. Press it
  and the sprint finishes the order it is on, writes its state and ends (stop id `stop-card`). The card works once: every sprint
  posts its own, and the driver closes it with the outcome at the end.
- **Ctrl-C in the terminal.** Press it twice, the way Claude asks. The session ends at once, the driver notes the interruption
  in `STATE.md` (the last order in progress, and that nothing was checkpointed) and logs an error.
- **A file.** Creating `<home>/sprint/STOP` yourself closes the session after its log has been still for a few seconds
  (`/exit`, then the process tree is killed if it has not left within 20 s). That ends mid-order; the card is the clean stop.
  A hand-written `STOP` while the session is mid-turn (its log still being written after the quiet wait) is a hard kill:
  the driver does not type `/exit` into a session that may be showing a dialog, it kills the process tree at once. The Stop
  card avoids this, because the orchestrator finishes its order and writes `STOP` as its last action.
- **The sprint ends on its own** when the orchestrator writes `STOP` (a decision only you can make, an outward action, a
  blocked worker, a failed verification twice, a NO-GO probe, no open order left, the Stop card), when two rotations in a row
  show no progress (`stuck`: no order opened or resolved, no `wo-*` branch moved (nor any branch your `<home>/worktrees.json` lists under
  `integration` or `branches`), and no commit beyond `RESUME.md`, `INDEX.md` and the board; a checkpoint commit before a
  rotation does not count), when `--max-rotations` is passed, or when the session exits with no
  signal (a crash, or `/exit` typed in it). A `STOP` file is left for you; read it, then delete it before the next sprint.

## Rotation

The orchestrator checkpoints and writes `<home>/sprint/ROTATE` at the second compaction of a session (the compaction hook
tells it so in a sprint). The driver then closes that session, confirms nothing it started is left running, deletes `ROTATE`
and starts a fresh session, which reads `STATE.md` (and RESUME for the rest) and carries on. `STATE.md` stays through every
rotation of one sprint.

## State

A sprint keeps its own state in `<home>/sprint/STATE.md` and never writes `RESUME.md`, which stays the interactive
orchestrator's. The session checkpoints there (what is in flight with each worker's reattach line, the last order, the stop or
rotation reason, notes for you) and the driver puts its own notes there too: an interruption, a refusal at a rotation, a failed
guard. The file is local and git-ignored, like the log.

When you next open a normal orchestrator window, its first action **folds** `STATE.md` into RESUME (RESUME is replaced
wholesale, as always) and moves the file to `<home>/sprint/archive/STATE-<timestamp>.md`. Until then the file exists, and the
driver **refuses a new sprint** (one sentence, exit status 2): fold it in a normal window first. A sprint session never folds.

## The guard command

A repo may declare a check that says whether it is safe to run unattended, in `<home>/sprint-guard.json`:

```
{"command": ["python", "scripts/safe_to_run.py"], "timeout_s": 120}
```

`command` is an argv list run with no shell, in the repo root, with the environment the driver gives the session (it carries
`GITOS_SPRINT=1`). `timeout_s` is optional: default 120, at most 900. Two more optional keys, `settle_s` and `busy_max_s`, are
described under *The BUSY lease and the settle wait* below. The driver runs it **before every launch** (the first and
each relaunch after a rotation) and **after every close** (a STOP, a ROTATE, an exit, Ctrl-C, and a session it had to kill).
Only exit status 0 passes. Anything else, a non-zero exit, a timeout (the process tree is killed) or a command that is not
found, launches nothing more: the sprint ends with the stop id `guard-failed` (exit status 1; 2 when nothing had been launched yet),
a log line, a `STOP` file (unless one is there already) and a `STATE.md` note with the command, how it ended and the last lines
of its output. A file that does not parse or has the wrong shape is a refusal like any malformed input; no file changes nothing.
The file is read when the sprint starts, and checked again at each rotation. The engine ships no guard and gives it no
meaning: what it checks is the repo's.

## The BUSY lease and the settle wait

A repo whose steps have outside effects (an action sent somewhere whose result arrives later) can keep the driver from closing a
session between sending the action and seeing its result. Both parts are opt-in through two more keys of
`<home>/sprint-guard.json`, validated like the others (a wrong type or range is a malformed input, refused and reported back);
a file without them behaves exactly as before.

```
{"command": ["python", "scripts/safe_to_run.py"], "settle_s": 30, "busy_max_s": 600}
```

- **`busy_max_s`** (1 to 3600) turns the lease on and is the longest any one lease may hold a close. Without it a `BUSY` file is
  ignored, so a stray file never stalls a sprint.
- **The lease file** is `<home>/sprint/BUSY`. The repo's own tooling writes it before an action with outside effects and removes
  it once the outside state is settled; the model and the engine never write it. One line, an ISO-8601 UTC deadline
  (`2026-11-22T14:05:00Z`). The driver reads it fresh on every check. <!-- rule:sprint-busy-lease-repo-tooling -->
- **Deferral.** When a `ROTATE` or a `STOP` file asks for a close and a lease is live, the driver does not close: it logs one
  `note` (`close deferred: BUSY until <deadline>`) and checks again at its normal poll. A lease is live while the file exists and
  parses, its deadline is in the future and the close has been held back for less than `busy_max_s`. It ends when the file is
  removed, the deadline passes, `busy_max_s` is reached or the session's process has exited; the close then goes ahead as usual,
  with a second `note`. A `BUSY` file that does not parse is not a lease: the driver logs that and closes as usual.
- **A lease left behind is the engine's to handle.** A lease that ends by its deadline or by `busy_max_s` is spent: the driver
  remembers that file (its content and modification time) for the rest of the sprint and never defers on it again, so it holds
  one close at most; a `BUSY` the tooling rewrites is a new lease. Before each launch (the first and every relaunch) a spent
  `BUSY`, or one whose deadline has passed, is moved to `<home>/sprint/archive/BUSY-<timestamp>` with a sprint-log `note`, and each
  such lease adds one line to the `STATE.md` notes (a lease was left behind and ended by its deadline or `busy_max_s`; the repo's
  tooling should remove it when its action settles). The tooling removing `BUSY` stays the normal path.
- **Never deferred:** Ctrl-C (your interrupt), the driver's own stuck and `--max-rotations` stops, and a session that has already
  exited. A deferral does not count as a rotation and never extends a cap.
- **`settle_s`** (0 to 600, default 0) is a wait after **every** close (a graceful `/exit`, a kill, a deferred close, a session
  that exited by itself), logged, before the after-close guard runs, so the guard reads the outside state after it has settled.
  Ctrl-C during the wait does not cut it short: the guard runs after it and the sprint ends. Ctrl-C twice stops at once, with a
  `guard-failed` note that the guard did not run.
- **Survivors.** When a close leaves processes running, the after-close guard still runs after the settle wait, and the `STATE.md`
  note carries both the guard's result and the survivors; the sprint still ends as an error.

## What you see

**In the terminal.** The orchestrator's replies are the role marker line alone (`references/orchestrator/sprint.md`, *Output*);
the last reply before a stop or a rotation adds the one-line reason. Everything else goes to the places below.

**On the board.** Open the board and its `sprint` tab: a header (started, orders done this sprint and open now, rotations, cost from
`cost_report.py` for this sprint's sessions, state) and the log newest first, reloading itself every 10 seconds. Cost is an
approximation. The log is `<home>/sprint/log.jsonl` (time, kind `start|done|note|stop|rotate|error`, order, a message of at
most 140 characters); the previous sprint's log is moved to `<home>/sprint/archive/`. The orchestrator adds lines with
`python <skill>/scripts/sprint_log.py add KIND MESSAGE [--ref WO-N]`.

## What it touches

On the first run in a repo: `sprint` is added to `tabs` in `<home>/board/board.json` (no other key changes), and
`<home>/sprint/` (the log, the Stop card id and `STATE.md` among it) are git-ignored (the driver also keeps the old `board/local/sprint*.html` page names on that list; it writes no such page now) through the repo's own `.git/info/exclude`, so no `.gitignore` is edited. The child session's environment is yours without any `CLAUDE*` or `MCP_*` variable (a leftover marker from an
outer Claude session would turn transcripts off and an inherited compaction window would beat the flag); your own settings
`CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_GIT_BASH_PATH`, `CLAUDE_CODE_USE_BEDROCK` and `CLAUDE_CODE_USE_VERTEX` are kept. The session gets `GITOS_SPRINT=1`.

Hooks and the router run the **installed** skill, so a sprint is as current as the install.
