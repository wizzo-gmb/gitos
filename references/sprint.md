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

## What it refuses

Each refusal is one sentence on the screen, nothing is launched, and the exit status is 2:

- no gitos home in the repo;
- a hub-routed repo (`board-route.json` says mode `hub`) or a `board-route.json` that does not parse: sprint mode does not
  support them yet (mode `local` is a repo with its own board and is fine);
- no owner board in the home (the Stop card needs it);
- the repo is not trusted in your `~/.claude.json`: open Claude in the repo once and accept the trust dialog (a prompt would
  otherwise wait behind it with no one there). The driver only reads that file;
- a `STOP` file from an earlier sprint: read `<home>/sprint/STOP`, then delete it;
- `--autocompact` below 200k, or above the model's context window (a window that small makes the session compact again and
  again);
- a `--model` that is not the ceiling model of the repo's model-optimization mapping (checked only when that mapping is on);
- an `--orders` entry that is not an open work-order (resolved, parked or missing), named in the sentence;
- an `--orders` entry marked `sprint: no`, named in the sentence; and, with no `--orders`, a repo with no open order marked
  `sprint: ready` (prepare orders in a normal orchestrator window, or pass `--orders`);
- an `--add-dir` that is not a folder, a platform other than Windows, or no `claude.exe` on `PATH`.

A file the driver reads that is malformed is refused the same way, before anything is launched: `worktrees.json`, `board/board.json`,
`board-route.json`, `model-optimization.json`, or an order's `sprint:` value other than `ready` or `no`. The refusal names the file and
the problem, and the driver writes a `Sprint refused` note into RESUME's *In flight* section. The same happens if a file goes bad during
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
  and the sprint finishes the order it is on, writes RESUME and ends (stop id `stop-card`). The card works once: every sprint
  posts its own, and the driver closes it with the outcome at the end.
- **Ctrl-C in the terminal.** Press it twice, the way Claude asks. The session ends at once, the driver notes the interruption
  under *In flight* in RESUME (the last order in progress, and that nothing was checkpointed) and logs an error.
- **A file.** Creating `<home>/sprint/STOP` yourself closes the session after its log has been still for a few seconds
  (`/exit`, then the process tree is killed if it has not left within 20 s). That ends mid-order; the card is the clean stop.
  A hand-written `STOP` while the session is mid-turn (its log still being written after the quiet wait) is a hard kill:
  the driver does not type `/exit` into a session that may be showing a dialog, it kills the process tree at once. The Stop
  card avoids this, because the orchestrator finishes its order and writes `STOP` as its last action.
- **The sprint ends on its own** when the orchestrator writes `STOP` (a decision only you can make, an outward action, a
  blocked worker, a failed verification twice, a NO-GO probe, no open order left, the Stop card), when two rotations in a row
  show no progress (`stuck`: no order opened or resolved, no `wo-*` branch moved (nor any branch your `<home>/worktrees.json` lists under
  `integration` or `branches`), and no commit beyond `RESUME.md`, `INDEX.md` and the board; the checkpoint commit before every
  rotation does not count), when `--max-rotations` is passed, or when the session exits with no
  signal (a crash, or `/exit` typed in it). A `STOP` file is left for you; read it, then delete it before the next sprint.

## Rotation

The orchestrator checkpoints and writes `<home>/sprint/ROTATE` at the second compaction of a session (the compaction hook
tells it so in a sprint). The driver then closes that session, confirms nothing it started is left running, deletes `ROTATE`
and starts a fresh session, which reads RESUME and carries on.

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
`<home>/sprint/` and `<home>/board/local/sprint.html` are git-ignored through the repo's own `.git/info/exclude`, so no `.gitignore` is edited. The child session's environment is yours without any `CLAUDE*` or `MCP_*` variable (a leftover marker from an
outer Claude session would turn transcripts off and an inherited compaction window would beat the flag); your own settings
`CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_GIT_BASH_PATH`, `CLAUDE_CODE_USE_BEDROCK` and `CLAUDE_CODE_USE_VERTEX` are kept. The session gets `GITOS_SPRINT=1`.

Hooks and the router run the **installed** skill, so a sprint is as current as the install.
