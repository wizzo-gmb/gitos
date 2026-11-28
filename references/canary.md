# Canary — the state canary, the worktree lifecycle, advisory findings and the durable anchor

The router (`SKILL.md` → *Canary*) holds the two things every reply needs: the role marker and the slippage
protocol. The rest of the always-on drift early-warning lives here, moved from the router unchanged. Two cheap
sentinels catch AI drift where it accumulates — the home's **state** and the window's **context**. This page is
the SSOT for the **state** sentinel; the role briefs carry one-line echoes of the marker.

## State canary

**State canary — `scripts/canary.py`.** Deterministic, read-only, stdlib-only checker for
the *home state layer* — the surface `brain_lint` (brain), selftest (payload), and
`path_guard` (publish) don't cover: INDEX ↔ work-order files (stale / orphan / duplicate
rows), `.brainmeta.json` counts vs on-disk pages + a `stamp-ahead` (impossible state), lens registries on both
layers (rows ↔ files, `name` = filename, `applies-to` list-form), dead links (`link-dead`) in `INDEX.md` +
open work-orders; delegates to `brain_lint` when a brain exists. Exit 0 = CLEAN, 1 = findings.
No judgment calls, no false-CLEAN (a parse failure is a finding; a skipped check reports
as skipped); it reports and gates — it never edits (fixing a finding is normal
orchestrator/implementer work).

```
python <home>/tools/canary.py <home>      # home copy missing -> <skill>/scripts/canary.py
```

Strictness: **report at bootstrap, gate at resolution.** The orchestrator runs it at
first-action and reports one line — `canary: CLEAN`, or the findings first,
forward-positive (cause + correction: "counts.decisions=16, files=17 → set 17"). Findings
never block *starting* work; **no work-order is resolved while the canary is red** (the
gate joins verify-before-commit). Scope is home state only — domain artifacts (outputs,
data, logs) stay the diagnostic role's judgment territory.

## Worktree lifecycle

**Worktree lifecycle — `scripts/worktree.py`.** Every implementer that edits files works in its own
worktree: `new NNN` makes `<parent>/<repo name>.worktrees/wo-NNN` (outside the repo tree) on branch `wo-NNN` from the current `HEAD`,
`reap NNN` / `reap --merged` removes a merged, clean one (merged into HEAD, the default branch or a declared integration branch; git's own refusals are the safety; never
`--force` or `unlock`, except that a removal git refuses over a long path is retried once with `core.longpaths=true` and `--force` after the worktree reads clean there, any leftover directory is removed through the Windows extended-length prefix and each fallback is printed), `status` classes each as in flight / reapable / abandoned / dirty. The
canary reports `worktree-reapable` and `worktree-abandoned` leftovers; it never deletes.
The `loose-ends` category (report-only) flags a parked work-order with no `trigger:`, a list that is no longer rare (advisory `loose-ends-last-resort`: more than 3 open rows or one older than 14 days), resolved orders whose notes were never adjudicated, and a malformed, oversized or stale loose-ends list. That list (`<home>/loose-ends.md`, created by the first `scripts/loose_ends.py add`) holds the loose ends, the last resort for a finding that is out of an order's scope; the drain ("drain the loose ends") empties it, moving each proposed item to the pile (`<home>/drain/pending/`), and nothing leaves the list or the pile without the orchestrator's or the operator's decision. A pending proposal undecided for 14 days, or more than 20 pending, is `drain-stale`. An item accepted into an order is a `proposed` slice with `origin:` naming it (`drain accept ID --work-order NNN --slice NAME`); a resolved order still holding an old open carried box is `carried-open`.

## Advisory findings, and no descoping

**There is no way to descope a canary category.** The canary has no switch, setting or file that turns a category off
for a repo or a sprint's gate. What it does have is the advisory: a finding flagged `"advisory": true` is reported, in the
human report and in `--json`, but is not counted and does not change the exit code. Which findings are advisory is fixed in
`canary.py`, per kind; a repo cannot move a finding between gating and advisory. A gating finding stops resolution and a
sprint's `land` until it is fixed. If a convention of the engine does not fit a healthy repo, file a work-order that teaches
the canary the shape.

## Honesty clause

**Honesty clause.** The slipped agent is the least reliable detector of its own slip, so the
monitor sits outside it (the durable anchor, the restore hook and `canary.py`, below); the
operator's glance at the first line is the backstop. The marker is a signal, not a guarantee.

## Durable anchor

**Durable anchor — closing the self-reference gap.** The marker directive lives in the skill
layer, which compaction summarizes away — so on its own it degrades in lockstep with what it
watches (a detector cannot detect its own absence). The recovery seed therefore *also* lives
in the **durable layer**: inception writes a managed `<!-- gitos:agent-system -->` block into
the repo-root `CLAUDE.md`, which the harness re-injects into **every** context window, carrying
the marker requirement + the trigger to re-read `SKILL.md` and run `canary.py`. Even after the
skill directive washes out, that block re-asserts the marker and points the way back; `upgrade`
refreshes it (managed-block upsert — never touching your content), and `canary.py` flags it
(`anchor-missing`, `anchor-stale`) if it goes missing or drifts. The "who watches the watcher"
recursion terminates at the **harness** (which guarantees `CLAUDE.md`) — the most durable layer
reachable. It raises the water line, not to omniscience: a bloated `CLAUDE.md` loses salience
too, so the block stays short and the operator's glance remains the final backstop.

## The restore hook

A `SessionStart` hook matched on `compact|clear|resume` (`scripts/compact_restore.py`, laid by scaffold and
`upgrade`) restores state after every compaction and every `/clear`: the marker line, `RESUME.md` with
its freshness, live facts (branch, worktrees, open orders), the standing-rules pointer, a per-session
compaction count (compaction only), this repo's federation heartbeat and one line naming the owner actions open on the
board (`owner board: N open owner action(s) ...`; on a `resume` that line is all it prints). The `board` category adds the
advisory `owner-action-open` for an owner action left open more than 15 minutes (order, kind, age; fix: `board.py actions`,
apply, `action-done`). A `Stop` entry of the same hook
asks once when a work-order has landed unresolved, an implementer's notes wait for adjudication, or `RESUME.md` is behind the ledger, and only after an
orchestrator-marked reply. Claude Code only, and hooks can be switched off (`disableAllHooks`), so it is
a guardrail, not a proof. Every gitos hook runs the `py` launcher (`py -3 -I -c ...`) on Windows when it exists, else the
absolute interpreter that wrote it, never a bare `python`, which a session whose `PATH` lost its Python entries cannot find;
scaffold and `upgrade` rewrite an older bare-`python` entry in place, once.

## Opting out of the marker

The operator may opt out of the marker per repo — record the opt-out; it reduces canary
coverage to state-only.
