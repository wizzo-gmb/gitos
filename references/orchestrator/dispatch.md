# Orchestrator step: dispatch and verify

Read this before dispatching an implementer, and again when its landing comes back to verify. The standing rules an implementer
needs are in `references/roles/implementer.md`; a dispatch points to it and to the order and adds only what is specific to the
order (live processes not to touch, a budget, the pinned Option). The adjudication of its notes is in `resolve.md`.

## Dispatch, plan-first (work-loop step 3)

3. **Dispatch, plan-first.** Plan every work-order for approval before it executes. **You choose the
   topology** — a fresh window per work-order (clean budget, isolation) is the default, but you may
   batch similar/related work into one window, or pick sequence vs. parallel, to optimize context
   usage. Pin disjoint files for anything concurrent + the chosen Option; state the scope bound.
   Name the lenses that match the work-order in the dispatch brief; you match them yourself, always
   (`system_one.py lenses <home> --wo NNN` only lists the active set with each lens's domain and
   when-to-apply; it asks no model). The choice of model and effort is yours, by the standing rule in
   `references/model-optimization.md`.
   **Every implementer that edits files is dispatched into its own worktree, by default and without
   being asked:** `python ~/.claude/skills/gitos/scripts/worktree.py new NNN` makes `<parent>/<repo name>.worktrees/wo-NNN` (outside
   the repo tree) on branch `wo-NNN` from the current `HEAD` and prints the path to dispatch into. Your own state edits
   (INDEX, RESUME, brain, work-orders) stay on the main checkout, and your cwd never enters a worktree.
   **An order with two or more slices is a folder** (`references/work-order-template.md` -> *The folder form*), and a
   dispatch names a slice, not the order. Pick it with `python <SKILL_DIR>/scripts/slice.py next [WO-NNN] <home>` (the
   first `ready` slice whose `depends_on` are all `landed`), make the worktree with
   `worktree.py new NNN --slice SN` (its own worktree and branch `wo-NNN-sN`, one per slice, with the marker the edit hook reads; `reap NNN` takes them all), set the slice `in-progress`, and give the
   worker the output of `python <SKILL_DIR>/scripts/slice.py brief WO-NNN/SN <home>` as its brief: `order.md`, the
   slice, and the Durable facts of each landed dependency, each with its path. A second slice is added with
   `slice.py add WO-NNN NAME <home>`, which converts a single-file order to the folder with `git mv` first; the
   canary gates a single file with more than one slice section. **Only you move a slice to `landed` or `dropped`**
   (and set its `commit`), at adjudication; the worker moves its own slice `in-progress` -> `implemented`. The edit
   hook refuses an implementer's edit to `order.md`, another slice file, `INDEX.md` and that status change; it
   does not cover Bash edits, so your merge review of the diff is the backstop (`references/disciplines.md` (g)).
   The built-in `isolation: "worktree"` is the alternative only for a repo whose settings set
   `worktree.baseRef: "head"`: its default base is the remote's default branch, which lacks the
   unpushed commits a locally authored work-order sits on. Two worktrees may touch the same file; the
   overlap surfaces at merge, so plan the merge order up front and resolve append-only conflicts (a
   gate list, a changelog) by keeping both sides. Parallel dispatch into ONE checkout keeps the
   disjoint-files rule.
   A repo that dispatches its own way declares it in an optional `<home>/worktrees.json` (`root`, `roots`,
   `branches`, `integration`, `archive`, every key optional): worktrees matching `roots` or `branches` are
   managed like `wo-NNN` ones (detached checkouts too), work merged into an `integration` branch counts as
   merged, and `archive` directories are copied to `<home>/worktree-archive/` before a reap. A reap also
   unlinks any symlink or junction inside the worktree that points outside it, so it never deletes through one.
   → *Dispatch + verify.*
   *Gate:* no edit begins until the plan is approved and the scope bound is stated; **anything
   concurrent in one checkout touches disjoint files.**

## Verify the landing (work-loop step 4)

4. **Verify the landing — accept or revise.** On return, read the diff yourself (`git diff` / grep /
   targeted reads; the worker's report is a claim, not evidence), then hand it to the operator. If the
   operator wants changes, **write them into the WO's `## Revisions` section** (scoped, the way you
   author Proposed fix scope) and **re-dispatch** the implementer to that one WO — repeat until the
   operator is satisfied; only then resolve it. A genuinely *new* direction is a follow-up work-order,
   not a revision. → *Dispatch + verify.*
   `system_one.py scope <home> NNN` lists `forbidden` and `outside-scope` files by rule (always; no
   model); it never substitutes for reading every hunk.
   *Gate:* you do **not** proceed on the worker's word (an unread diff is not a verified one), and you
   do **not** resolve a WO the operator hasn't accepted.

## Dispatch + verify

When you delegate implementation to agents:

- **When model optimization is enabled**, consult the repo's applicable routing
  guidance, refresh the actual lead's current model/effort evidence (unknown stays
  unknown; **read effort yourself first** with `model_optimization.py observe` or
  `echo $CLAUDE_EFFORT`, take the model from the system prompt's exact ID or a recorded
  `PostModelSwitch`, and only if effort is unavailable ask with the interactive question UI,
  `AskUserQuestion` offering the levels, never in prose; a numbered list where there is no
  such UI; an `/effort` change shows at the next check, not instantly), compare it with the session baseline, and validate the worker pair within the configured
  ceiling, then use the native dispatcher. **You outrank every worker:** a worker on your
  own model runs at strictly lower effort than your actual effort, a lower-model worker may
  use any effort, and no worker is dispatched above `high` (never `fork`, never an omitted
  effort); `select` refuses a violating pair and names the clause. Include the compact requested/effective
  model entry in the WO; unknown execution settings stay unknown. The policy's SSOT
  is `references/model-optimization.md`; it leaves the scope and acceptance gates intact.
- Each agent reads its work-order **in full** before coding.
- **State the scope bound at dispatch.** An implementer edits what its work-order's Proposed fix scope
  specifies and **fixes what it finds within that scope**, listing it under Deviations; it defers only what is
  out of scope, with the reason. An unlisted out-of-scope edit in the landing is a **defect** (revert it; execute
  the change yourself from the implementer's *proposed* notes). Full role + boundary: `references/roles/implementer.md`. A rule you add to a brief or the
  brain names what enforces it (`references/disciplines.md` (n) a-rule-needs-a-mechanism).
- Parallel agents touch **disjoint files** — different sections of one file is not
  safe; pin them to non-overlapping files.
- When a work-order lists Options, **pin** which one each agent uses.
- **Match the model to the part of the job.** Security- or consent-critical code (a gate, a permission or consent
  path, anything that decides what may run or be sent) goes to the stronger model, because a defect there is silent
  and costs more than the run; wiring, docs and moving tests go to the cheaper one; a mechanical pass (renaming,
  regenerating, a find-and-replace across files) goes to the cheapest. Split one order across tiers rather than
  running all of it on the strongest (the ceiling in `references/model-optimization.md` still binds when it is enabled).
- **A revision of a large-history agent starts a fresh agent.** When the agent that landed an order has a large
  history and the revision is small, brief a new agent on the order, its Revisions section and the diff instead of
  resuming the old one: the old history is re-read at every turn and the revision pays for it, while the order and
  the diff already hold everything the revision needs.
- **Background work has a time limit and an end.** Tell each implementer to run commands in the foreground with a
  time limit, not to stop and wait on background work of its own, and to hand back once at the end. A background
  command it does start gets a time limit and a known log, and it stops it before handing back.
- **Dispatch a worker through its definition, so it carries a turn cap.** Dispatch an implementer with
  `subagent_type: gitos-implementer`, the definition `scaffold.py` lays into
  `<repo>/.claude/agents/`. It holds only `maxTurns`; the soft budget (hand back near it, notes written) is in its body,
  so the brief does not restate either number. Model and effort come from the dispatch: name the pair the order's tier
  maps to (the tier mapping when optimization is on) on the call, as the dispatch guard requires; the definition adds
  only the cap. Agent definitions load at session start, so a definition laid mid-session is not dispatchable until a
  new window. A worker stopped at the cap returns no report, so treat a worker result that says it hit
  its turn limit as a handed-back slice, not a failure: its worktree and the order's notes are intact. Continue with a
  fresh worker briefed on the order, its notes and `git diff` of the worktree (the revision rule above), and review the
  diff as you would any landing. A repo whose `.claude/agents/` lacks the definitions dispatches as before, uncapped; the
  canary says so only for a definition that lost its `maxTurns`.
- **Require the notes-back.** Tell each implementer to fill the work-order's **Implementer
  notes** section on completion (deviations / surprises / durable facts / process notes /
  follow-ups). It is the feedback channel, not optional — without it the orchestrator and
  the brain never learn from the work.
- **Adversarially review before declaring done** — a separate reviewer (or a
  fresh-eyes pass) checks the landing against the work-order, not just "does it run"
  (a positive result gets (k) attack-your-own-win).
- **Trust-but-verify** every landing with `git diff` / grep / targeted reads. The
  agent's report is a claim, not evidence.
- **See where the spend went** (orchestrator window versus workers, by model, before and after a change) with
  `python scripts/cost_report.py --repo <path>` (read-only; dollars approximate, shares reliable).
- **Audit where tokens go, only when the operator asks.** Nothing runs this on a schedule or at a checkpoint. Run
  `cost_report.py`, and `ccusage daily` or `ccusage blocks --active` as well when
  `python scripts/cost_report.py ccusage status` prints `installed`. Read the costliest workers, the opus share and
  the dispatch pairs, then answer in one block: what is using the tokens, and what to change (a smaller slice, a
  fresh worker instead of a resume, a lower tier), each proposed as an order. With ccusage declined or absent,
  `cost_report.py` alone is the audit. The offer round asks about ccusage once per machine and installs it
  (`npm i -g ccusage`) only after the operator says yes.

## Optional model optimization

**Optional model optimization.** During the state read, inspect
`<home>/model-optimization.json` only if present. Absent/disabled → no optimization
helper, discovery, reporting, or learning. Enabled → initialize/resume its explicit
session identity and observed model/effort baseline per
`references/model-optimization.md` (read your own effort first: `observe` or
`echo $CLAUDE_EFFORT`; ask the operator only as a fallback), then use that policy for dispatch and normal closeout. Malformed state
does not enable routing; surface the configuration error without replacing it.
