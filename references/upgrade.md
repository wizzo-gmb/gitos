# The `upgrade` procedure — adopt the latest engine directives

This is the **canonical, single home of the upgrade logic**. It runs inside a live
orchestrator chat session against the **current** repo and brings that repo onto the
latest GitOS engine. It is home-agnostic and idempotent.

> **It changes the *directive*, never the folder layout.** A deployed repo's
> orchestrator already knows where its own state lives. Upgrading delivers the latest
> *behavioral* directives; the orchestrator applies them to whatever home it already has
> (`.gitos/`, `.pipeline/`, or the legacy split `outputs/debug/` + `outputs/brain/`). **No
> file is moved.** For general repos this procedure *is* the upgrade. A downstream product
> with a domain profile wraps this procedure (via its own engine-sync bridge, e.g. a
> `BRIDGE.md`) to add its own sync/preserve/merge — it never re-implements these steps.

## When to run it

- The operator asks to "upgrade this repo's engine" / "update the gitos directive" (the
  `SKILL.md` router sends that intent here), or
- the orchestrator's first-action drift check reports the skill's `ENGINE_VERSION` is
  ahead of the repo's stamped `engine_version`.

## Procedure

**0. Classify the repo — Standard or Custom — before doing anything else.**
The generic steps below are safe on a *Standard* repo (engine only). A *Custom* repo
carries a domain profile + deployed project state that the generic path must never touch;
its **BRIDGE** owns what to SYNC / PRESERVE / MERGE. So first decide which you are in.

*Detection (pointer-first, scan-fallback — stop at the first rule that resolves):*

- **a. Pointer.** Read the `_meta.bridge` pointer — from the repo-root `CLAUDE.md` `_meta`
  block and/or `<home>/brain/.brainmeta.json` (the agent fast-path mirror). If it is present
  and resolves to a **readable** file → **Custom** (the bridge is that file). Done.
- **b. Scan.** Else look, **in this order**, for: `<root>/BRIDGE.md`, then
  `<root>/prompts/BRIDGE.md`, then `<home>/BRIDGE.md`. First file that exists → **Custom**
  (record which path matched, for the report). Done.
- **c. Profile markers.** Else check for other signs of a domain profile: a filled
  `_meta.inception_template_version` (non-placeholder), a `prompts/` profile tree, or a
  declared domain profile. If **any** marker is present but **no** bridge was found in (a)/(b)
  → **Custom-but-unbridged** → **HALT** (see the HALT message below). Do not run steps 1–7.
- **d. Standard.** Else → **Standard**.

*On **Standard**:* fall through to steps 1–7 unchanged. This procedure *is* the upgrade.

*On **Custom**:* the engine does **not** itself SYNC, PRESERVE, or MERGE — the BRIDGE owns
those, because only it knows the profile's preserve list and merge seams. Hand control to
the repo's resolved `BRIDGE.md`: it wraps this procedure, performs its SYNC/PRESERVE/MERGE,
and then finishes via steps 1–7 (stamp, ADR + log, report). Do not run the generic steps
yourself first — the bridge calls them. The BRIDGE contract is `references/bridge.md`.

  *Version-gap check (do this once the bridge has resolved, before handing off).* Read the
  skill's `ENGINE_VERSION` (the integer in `~/.claude/skills/gitos/VERSION`) as the target,
  and the bridge's `last_reconciled_engine` + `min_compatible_engine`. If the target equals
  `last_reconciled_engine`, the bridge is a no-op (nothing upstream changed). Otherwise
  consult the skill's `CHANGELOG.md`: **an upgrade crosses a breaking boundary iff some
  `breaking: yes` version exists in the range `(min_compatible_engine, target]`.** If it
  does, **WARN** before proceeding — name the offending `breaking: yes` version(s) and tell
  the operator to re-read those CHANGELOG entries and confirm the bridge's PRESERVE/MERGE
  rules still hold for them. The warning does not halt; it makes the operator look before
  the bridge runs. (A full per-version migration matrix is out of scope.)

*HALT message (print verbatim on a Custom-but-unbridged repo):*

```
HALT — this repo looks like a Custom (profiled) deployment but has no BRIDGE.

Why I stopped: a domain profile and/or project state is present here, but I could not
resolve a BRIDGE.md. The BRIDGE is a hard prerequisite for upgrading a Custom repo: it
is the only place that records what to SYNC (engine files to refresh), what to PRESERVE
(your profile + project state — gates, contract, brain pages, work-order ledger), and
what to MERGE (files that are part profile, part engine). Without it I cannot tell your
deployed state apart from engine scaffolding, so running the generic upgrade could
overwrite profile content and project state. I refuse the generic path.

What I checked:
  - _meta.bridge pointer in <root>/CLAUDE.md and <home>/brain/.brainmeta.json — not set
    (or did not resolve to a readable file).
  - <root>/BRIDGE.md            — not found
  - <root>/prompts/BRIDGE.md    — not found
  - <home>/BRIDGE.md            — not found

To proceed, author and stamp a BRIDGE:
  1. Write a BRIDGE.md following the engine's bridge contract:
     ~/.claude/skills/gitos/references/bridge.md
     (required sections SYNC / PRESERVE / MERGE + the metadata block with
      bridge_schema, profile, last_reconciled_engine, min_compatible_engine).
  2. Put it at one of the scanned paths above, OR set the pointer so I can find it:
     add `_meta.bridge: <repo-relative path to BRIDGE.md>` to <root>/CLAUDE.md's
     _meta block (human-visible), and mirror the same value into
     <home>/brain/.brainmeta.json (the agent fast-path).
  3. Re-run the upgrade. I will classify the repo as Custom and route through the BRIDGE.

If this repo is genuinely Standard (engine-only, no profile/state to protect), the
profile marker I tripped on is a false positive — remove/clear it (e.g. an unfilled
_meta.inception_template_version placeholder) and re-run.
```

**1. Detect the repo's home and read its stamped version.**
Resolve `<home>` by the standard detection order (`.gitos/` → `.pipeline/` →
`outputs/debug/`). Read the repo's stamped `engine_version` from
`<home>/brain/.brainmeta.json` (`engine_version` field) — or, for a general repo without
a brain, from `<home>/HANDOFF.md`. A repo with no stamp is treated as version `0`.

**2. Refresh + live-read the installed engine.**
First, **offer to pull the latest engine from its remote.** If the installed skill is a git clone
— `~/.claude/skills/gitos/.git` exists (a dir or a file) — a newer engine may be available upstream
that this install hasn't fetched. **Report intent, then ask the operator** before running anything
(never auto-pull):

> "Your installed gitos engine is a git clone. Pull the latest from its remote before I upgrade this
> repo? — `git -C ~/.claude/skills/gitos pull`. (Recommended — otherwise I upgrade against the engine
> exactly as installed.)"

On **yes**: run `git -C ~/.claude/skills/gitos pull` and report the result (the `VERSION` delta, or
"already up to date"). If the pull brought a newer engine, note that a **session reload** is what
makes the *agent* load the new skill — but the steps below still adopt the latest by reading the
refreshed files from disk, so the per-repo upgrade applies either way. On **no** — or if
`~/.claude/skills/gitos/` is **not** a git clone (a copied install: nothing to pull; updating means
re-cloning / re-copying, see the README's *Updating*) — skip the pull and proceed.

Then read `~/.claude/skills/gitos/VERSION` (the current `ENGINE_VERSION`) and the canonical brief
(`~/.claude/skills/gitos/SKILL.md` + the role briefs under `~/.claude/skills/gitos/references/`).

**3. If already current → run the one offer round, then stop (idempotent).**
If the repo's stamp equals the skill's `ENGINE_VERSION`, report **"engine up to date
(vN)"**, run **4q** on its own (`python <SKILL_DIR>/scripts/offer.py <repo-root>`; ask what it prints and apply
the answers as 4q says), and then stop. An opt-in that became available after the last upgrade (a machine config
for System One, a new federation group) is offered this way. With nothing on offer 4q is silent, and running again
with no upstream change is the same no-op as before: nothing else in step 4 runs and nothing is re-stamped.

**4. Adopt the latest directives.**
Direct the running orchestrator to:
- **ask every opt-in in ONE round, not one subsystem at a time** — model optimization, lenses, System One,
  federation, legacy registers and the harness popup are never asked separately. **4q** computes which are
  still unanswered and asks them once, after the other steps have run; a step below that used to ask its own
  question says so and points there;
- **re-read the canonical brief** (`SKILL.md` + `references/roles/orchestrator.md` +
  `references/agent-system.md`) and adopt any new behaviors — for example, the
  **implementer-notes accept/reject loop** (have each implementer fill the work-order's
  `## Implementer notes` on completion; on landing, harvest and adjudicate them: ACCEPT —
  route durable facts to the brain, lessons into dispatch, follow-ups into new
  work-orders — DEFER to the loose-ends list, or REJECT with a one-line reason) and the **per-reply canary marker**
  (open every reply with `[gitos · <role> · <focus>]` — SKILL.md → *Canary*);
- **re-point any stale role pointers** — if a role pointer or the memory pointer still
  names an old skill path or the legacy `project_flow_role_brief.md`, repoint it to
  `~/.claude/skills/gitos/...` and `gitos_role_brief.md`;
- **deliver the engine's home tools — refresh them, don't just seed them.** `<home>/tools/`
  holds byte-copies of the engine's own scripts (`brain_lint.py`, `canary.py`, and any future
  tool the engine lays there) — **engine artifacts, not repo content**: a cache of the
  installed skill that the briefs invoke by home path. For **each** tool the engine ships into
  `<home>/tools/`, compare the home copy against the skill's
  (`~/.claude/skills/gitos/scripts/<tool>.py`) — **normalizing line endings first**:
  - **missing** → byte-copy it in (preserve LF) and report it;
  - **identical** → no-op, silently — no churn, no false "updated";
  - **different** → **report it, then refresh it.** The compare proves *different*, not
    *why*: the copy is stale, or hand-modified, and you cannot tell which — so say exactly
    that. Name the tool, state that the home copy differed and was replaced from the skill,
    and note the prior bytes are recoverable from git (the engine requires version control).
    Don't ask: a stale copy has one right answer, and a prompt per tool per upgrade teaches
    the operator to skip the very fix the upgrade exists to deliver.

  *Why line endings are normalized before comparing, and not treated as a difference:* a line
  ending is how git wrote the file out, not part of the tool. `core.autocrlf=true` is the
  Git-for-Windows installer default and `<home>/` is deliberately git-tracked, so a raw
  byte-compare calls **every fresh Windows clone of a compliant repo** stale — and "refreshing"
  it only rewrites bytes that the next clone converts straight back. `canary.py`'s `tool`
  category applies the identical predicate (`same_tool`), so the rule and the check that
  observes it cannot disagree about what a changed tool is. Byte-identity is `sync_to_live`'s
  contract, because a mirror's job is exact bytes; it was never this one's.

  *Stale or edited.* In a home stamped at the install's version a copy that still differs is a local edit, not an older copy:
  the canary reports it as the advisory `tool-locally-edited` (naming the file and the version it forked from), and the
  gating `tool-stale` stays for an older, unstamped or ahead-stamped home. `board/board.py` is judged the same way by its
  `BOARD_VERSION`. The replacement above still applies; the notice is so an edit is re-applied after an upgrade, not lost.

  **Never silently skip; never silently overwrite** — the two are the same failure wearing
  different clothes. The rule this replaced copied a tool only when it was *absent*, which made
  an upgrade whose entire value was a `canary.py` fix a **no-op for exactly the repos that had
  `canary.py`**. To make a tool behave differently, **descope** the category for the repo
  (SKILL.md → *Canary*) or file a work-order upstream — a forked home copy is not a supported
  surface and will be refreshed.

  *Delivery is not seeding:* `scaffold.py` deliberately **skips** an existing tool copy, so
  re-running it never refreshes one — this step is the only thing that does. *And the line is
  the category, not the folder:* `<home>/agents/` (the lens bullet below) is **operator
  content**, and is report-and-**ask** by design;
- **refresh the CLAUDE.md context anchor** — the repo-root `CLAUDE.md` carries the gitos
  `<!-- gitos:agent-system -->` managed block (the canary's durable recovery seed; SKILL.md →
  *Canary*). If `canary.py` reports `anchor-missing` or `anchor-stale`, refresh it: re-run
  `python ~/.claude/skills/gitos/scripts/scaffold.py <root> --git skip` (idempotent — it upserts
  *only* the managed block, creating `CLAUDE.md` if absent, never touching content outside the
  markers; its canary, board and dispatch-tier text is generated from the canonical paragraphs the briefs carry, so the refresh
  picks up a changed rule without a new step), or edit the block by hand between its markers. **Anything the repo owns — project
  instructions, the `_meta` block including `_meta.bridge` — belongs outside the markers: the
  refresh replaces the block's engine text, and while it now carries unrecognized in-block
  lines through and reports them, only content outside the markers is untouched by
  construction.** On a Custom repo this is a **MERGE** (refresh the block, preserve the
  profile) — see `references/bridge.md`;
- **lay the live resume, and migrate per-harness resume files onto it as POINTERS.** The
  session's volatile state has **one** home: `<home>/RESUME.md` (`references/glossary.md` →
  **Resume**; the loop that maintains it is `references/roles/orchestrator.md` → *Checkpoint +
  rotation*). If it is absent, lay it — `python ~/.claude/skills/gitos/scripts/scaffold.py
  <root> --git skip` seeds it from the engine template and never touches an existing one — then
  refresh it from the repo's actual current state at this upgrade's own checkpoint.

  Then look for **per-harness resume files**: a `CLAUDE-RESUME.md`, `CODEX-RESUME.md`,
  `RESUME-<harness>.md` or similar at the repo root or under `<home>/`. Each becomes a **one-line
  pointer** to `<home>/RESUME.md`, because N resume files are N things to go stale independently
  and the observed failure is exactly that — per-harness files weeks behind the repo while the
  ledger moved on. Per file: **report it and ask**, then on the operator's word fold anything it
  still asserts into the right store first — volatile state into `RESUME.md`, anything that would
  still be true in a fresh clone into the **brain** (knowledge) or the **ledger** (work), by the
  one-question test — and only then replace the body with the pointer. **Never silently clobber
  one:** these are hand-written operator files, so this is report-and-ask by design, the same
  category line as `<home>/agents/` above and the opposite of the home tool copies. No such
  files → this half is a no-op; say nothing.

  *What never moves here:* a **standing rule** found in one of those files goes to the brain, not
  into `RESUME.md`. `RESUME.md` is replaced wholesale at every checkpoint, so a rule parked there
  is destroyed by the next rotation — `canary.py`'s `resume/standing-rule` reports it;
- **refresh lens copies from the global library** — lenses are off by default and a repo selects global lenses by
  name in `<home>/lenses.json` (SKILL.md → *Lenses*). Whether to turn them on is a question of the offer round
  (**4q**), not asked here. For each repo copy that is byte-identical to a global lens, suggest selecting the
  global lens instead of keeping the copy; the copy is removed only if the operator agrees. Write the answer with
  `scripts/lenses.py`. Upgrade never turns lenses off silently. The copy refresh stays for deliberate local
  variants: for each lens in `<home>/agents/` whose name also exists globally, byte-compare; where they differ,
  **report-and-ask** to refresh the repo copy from the global (never silently clobber — a deliberately-forked
  local variant survives by declining). Update the repo registry to match what was accepted. No global lenses / no
  `<home>/agents/` → skip, no-op;
- **System One is offered in the one round (4q)**, never here. Do run the data migration below first, so a repo
  with retired keys is not asked about a setting it already has;
- **migrate System One data** — run `python <SKILL_DIR>/scripts/system_one.py migrate <ROOT> --write`.
  It is the upgrade, so there is no question to ask. It removes the keys the engine no longer reads
  (`RETIRED_KEYS` in `system_one.py`) from the machine config and from the repo's `system-one.json`, keeping
  every other key. (A `waiting: user — <question>` row is a valid `waiting:` State again since v57, and carried
  boxes move with `ledger_migrate.py`, step 4m.) It prints nothing when there is nothing to do. Report what it did in one line; with no output, say nothing. Until it has run, System One reports itself down with the retired keys named;
- **federation is offered in the one round (4q)** — the tool computes the ask (`federation.py offer`, which
  `offer.py` calls), you ask it. Federation lets independent gitos instances **on one machine** reach each other,
  so work that belongs to a sibling repo can go there instead of crossing the gap by copy-paste. Its rules
  stand unchanged: `federation.py offer` prints nothing when there is nothing to offer and never writes; the
  operator's answer is the only thing that can write a `federation.json`; **declining stores nothing**, so the
  offer is computed fresh each round and the capability stays discoverable; the two exposure flags are
  asked only after a group is chosen and **never re-asked** on upgrade (changing them is a deliberate act via
  `/gitos federation`). The group pick and the flags are federation's own follow-up (`references/federation.md`
  → *Asking is a PROMPT, not a paragraph*), reached only when the operator chooses to pick a group.

**4h. Harness.**
**Measure on every upgrade, adopted or not.** Run `harness.py offer --measure --home <home>` (the
home's copy, else the skill's own `scripts/harness.py`) and put its few lines in the report. It is
read-only, never gates the upgrade and cannot fail it: an unreadable Claude home, absent session
logs or a parse failure prints `not measured (reason)` and the upgrade continues. This is not the
drift check. The canary asks whether actual matches declared; this asks whether the load is too
much, and a zero-drift repo can still sit multiples over the skill-listing budget. Carry its
qualification into what you tell the operator: the figure assumes a 200,000-token window and the
tool-definition count is a lower bound, so an "OVER BUDGET" line is an estimate to look into, not a
verdict to act on. It runs here, after step 2, because that is the first point at which the
skill's own `scripts/harness.py` is guaranteed to exist. A repo with no `harness.json` then sees
the offer line after the summary.

**Only when `<home>/harness.json` exists and is not `adopted: false`**, also run the maintenance
pass. One update command: run `harness.py update --home <home>` (the `auto` / `review` pass), show
the operator each `review`
diff and let them approve (`update --approve NAME`), then `harness.py sync --home <home>` as a dry
run, show the plan, and apply with `--apply` only on their word. Never move a user skill without
approval; user-scope baseline changes are proposals only. Policy: `references/harness.md`.

**The popup is part of the one round (4q).** `offer.py` includes the popup's questions (`harness.py popup`,
rules: `references/orchestrator/harness-removals.md`, policy: `references/harness.md`) when `audit` holds removal candidates,
and the two claude.ai sync questions come with them. Nothing is pre-selected and silence applies nothing. Only the
ticked candidates go to `sync --confirm NAME`, and only a sync answer of Turn off or Turn back on goes to `sync`
as the flag that `sync_flags` maps it to. Show the dry run first, then `--apply` on the operator's word. On demand,
`harness.py popup --home <home>` still prints the whole popup, sync questions alone included. The popup is
Claude-only: on another harness present the same options as a numbered text list (`offer.py --text`).

**Plugin update channels.** Report the `update` and `sync` lines about channels as they are: an
`auto` plugin's `autoUpdate: true` for its marketplace is a user-scope **proposal**, never applied by
the engine. A `plugin-pinned-auto-updates` finding is the operator's call, and turning the marketplace's
`autoUpdate` off freezes every plugin from it. Also carry `audit`'s machine-wide auto-update line
when an env var turns updates off. Never edit `known_marketplaces.json`.

**4i. Post-compaction restore hook.**
Run `python <SKILL_DIR>/scripts/compact_restore.py install <repo-root>` (scaffold lays the same
entry). It registers a `SessionStart` hook matched on `compact|clear` and a `Stop` hook in the repo's
`.claude/settings.json`, beside whatever is already there, and is idempotent. A repo holding the older
`compact`-only entry has that entry's matcher widened in place (one entry, firing once per event) and
the `Stop` entry added. The canary's `restore` category reports it missing in a scaffolded repo; this
step is the fix. Claude Code only, and `disableAllHooks` switches it off.

**4j. Worktree leftovers.**
Run `python <SKILL_DIR>/scripts/worktree.py status <repo-root>` (read-only). Reap the reapable
leftovers it lists with `reap --merged` (git's own refusals stay the safety: nothing unmerged or
dirty is removed), and raise any abandoned one to the operator, who merges it or removes it by hand.
Scaffold has already made sure `.claude/worktrees/` is in `.gitignore` (new worktrees live outside the repo tree; older ones under that path are still found and reaped).

**4k. Parked section.** Retired: the generated board carries the Parked table (4n lays it). Work-orders resolved before
engine v44 are exempt from the canary's `loose-ends` check; do not backfill adjudications onto them.

**4l. Legacy loose-ends registers.**
The loose-ends list is **lazy**: upgrade does not lay `<home>/loose-ends.md` and a repo with no file has an
empty list. The legacy register question (a work-order or file under the home whose name or `# ` title says loose
ends or register, not yet answered; **at most once per file**) is asked in the one round (**4q**), two files at a
time; `loose_ends.py legacy pending --root <repo-root>` still lists them. Applying the answer: `loose_ends.py
import --root <repo-root> <FILE>` (adds each table row as a `new` item with Source `import:<its id>`; never edits
the file, never imports a row twice; rows that say done, fixed, closed, merged or superseded are listed as
"probably done" and still imported; records `<!-- legacy: <path> imported -->` in the list header) or
`loose_ends.py legacy decline <FILE> --root <repo-root>` (records `declined`; this is the one case the file is
created without an item, and only after the operator answered). After an import, run the drain
(`references/orchestrator/drain.md`). Sections of implementer notes inside a legacy
register are not rows: say so, and adjudicate them by hand in the same pass (facts to the brain, follow-ups by
the deferral rule: a work-order, a parked work-order or, last, `loose_ends.py add`).

**4m. Migrate the ledger: one not-now list, folder orders; retire `history/`.**
Run `python <SKILL_DIR>/scripts/ledger_migrate.py <home>` (a dry run: it writes nothing). Its `not-now:` lines come
first (below). Then it lists each open
single-file order with two or more `### S<n>` slice sections that it would convert to the folder form (`git mv` to
`WO-NNN/order.md`, one `slices/SN-<name>.md` per slice; a slice with an adjudication or `## History` pointer naming a
commit is `landed` with it, the rest `ready` with `depends_on` in order; `history/WO-NNN.md` content becomes the landed
slices' notes), each order it will skip because the text cannot be split with confidence (with the reason: nothing
is guessed), and any `history/` file it cannot fold in. Show the operator that report, and only after the operator
confirms run it again with `--write`. It stages its changes and commits nothing; review the diff, then commit. Single-slice orders and
resolved orders are left alone. `work-orders/history/` is retired: an empty one (a `.gitkeep` only) is removed by
`--write`; a history file left behind is read by hand, then deleted. Scaffold no longer lays the folder, the canary no
longer checks it, and the whole-order size limit (`work-order-oversized`) is gone; the per-file limits of a folder
order stay.

**4n. The board: lay the generated INDEX, delete `footprints.md` and the per-order logs (v61).**
`ledger_migrate.py` (4m) does this in the same dry run, as `board:` lines. An INDEX without the `<!-- gitos:index board -->`
line is replaced by the generated board (`ledger_index.py` writes the whole file from the order files: header, Open, Parked).
Nothing is dropped silently: a Resolved row goes when its order file is in `work-orders/resolved/` (an order from engine v44 on
whose file carries no `released:` is stamped from the row's version first); a row with no file, an Open or Parked row no file
regenerates, and every hand-written section (release notes, Findings DISPROVED, next steps) moves to `RESUME.md` under one dated
heading, verbatim in a fenced block, for the operator to sort (live state stays in RESUME, a durable decision goes to a brain
decision page, the rest is deleted; git keeps the old INDEX). It also removes `footprints.md` (a landing's footprint is
`git show --name-only <sha>`) and every `work-orders/**/WO-NNN/log.md`. Commit this in the repo's own commit, then run
`python <SKILL_DIR>/scripts/ledger_index.py --check <home>`. The header carries the engine version stamp, so step 5 regenerates the
board after it writes the stamp. The canary advises `index-oversized` when INDEX.md passes 16 KB.

**4o. Slice-edit hook and folder orders.**
Run `python <SKILL_DIR>/scripts/slice_guard.py install <repo-root>` (scaffold lays the same entry). It registers a
`PreToolUse` hook on `Edit|Write|MultiEdit|NotebookEdit` in the repo's `.claude/settings.json`, beside whatever is
already there, and is idempotent. The hook acts only in a worktree made by `worktree.py new NNN --slice SN` (an
untracked marker in that worktree's git dir); everywhere else it allows. Bash edits are not covered and the
orchestrator's merge review is the backstop. Then run the canary: a single-file order with more than one slice
section is a `order-needs-folder` finding; `slice.py add WO-NNN NAME <home>` converts it with `git mv`.
Claude Code only, and `disableAllHooks` switches it off.

**4t. Follow-ups on orders.**
An order takes no `## Carried loose ends` boxes any more (v57). `drain accept ID --work-order NNN --slice NAME` writes
a `proposed` slice with `origin:` set to the items (a single-file order becomes a folder); without `--slice` the
order must already name the items (`origin: L3, L5`). No order has a whole-order size limit. A folder order has
per-file limits (200 lines for `order.md`, 150 for a slice; `order.md` over its limit refuses new slices). The canary
gates `slice-landed-no-commit` and a dangling or cyclic `depends_on`, and reports `order-ready-to-close`,
`slice-stale`, `order-oversized` and `slice-oversized` and split advice at eight slices (`order-ready-to-close` is withheld from an
order whose front matter says `pending: <what it waits on>`, which the canary lists once as `order-pending`); it reads `ledger_index.py`
from beside itself, the home `tools/` or `<SKILL_DIR>/scripts/`.

**4m, the not-now lines (v57; parked orders v58).**
Every item that is not yet an order becomes a row of `<home>/loose-ends.md` with a State: `new`, `proposed: <kind>`,
`waiting: <question>` or `declined: <reason>`; deferred work with a restart trigger becomes a parked work-order. The dry run of step 4m prints one `not-now:` line
per move: each item a pending drain proposal holds gets its row back as `proposed: <kind>` (the file stays as its
attachment); each `parked: <trigger>` row and each open hand-kept INDEX Parked row (`P<n>`) becomes a parked
work-order (a new order file, `status: parked`, `trigger:`, `origin: L<n>` or `P<n>`; the row leaves the list, a
closed `P<n>` goes) and the INDEX becomes the generated board (4n), whose Parked table has the
columns `NNN | Title | Restart trigger | Evidence`;
each open carried box of an open order goes back on the list as `new` and the box is ticked `-> L<n>`;
`drain/declined/`, `drain/accepted/` and `drain/routed.txt` are removed (a declined item is already a `declined:`
row, an accepted or routed one is off the list); the front-matter key `landed:` of an order becomes `released:`.
What it cannot move with confidence is printed as `LEFT` and stays (a Parked row with no trigger, a pile item whose
row is in another state); settle those by hand, then run it again. A second run prints `not-now: nothing to move`.
Until it has run, the canary prints the advisory `loose-ends-migration`; a fact left in two stores afterwards is the
gating `loose-ends-two-stores`. `drop --to P<n>`, `drain accept --parked P<n>`, the `parked:` State and
`drain accept --trigger` are retired: park by authoring a parked work-order, then `drop L<n> --to WO-NNN` or
`drain accept ID --work-order NNN`.

**4s. Owner board (before 4q).**
Every home uses an owner board (`references/owner-board.md`): its own at `<home>/board/`, or a hub's. **First ask once**, with the
interactive question UI: own board, or a hub (the path of the hub's board dir and a short tab)? Own board: the rest of this
step. A hub: write `<home>/board-route.json` (`{"mode": "hub", "board": "<absolute path of the hub's board dir>", "tab":
"<tab>"}`), run `python <SKILL_DIR>/scripts/scaffold.py <root> --git skip` (it builds no board here, runs `register-tab` on the
hub and writes the two pointers), then `python <hub>/board.py ensure --tab <tab>` and report its line. A repo that already has a
board and moves to a hub: run `python <home>/board/board.py list --open` first and re-ask each open or answered-not-acted card on
the hub (`add-decision ... --tab <tab>`); then `git rm` its `board/board.py` and `board/board.json`, delete its `board/data/` and
ask the operator to stop its server (never stop it yourself). The canary's `board-unrouted` stays until `<home>/board/` is gone.
For an own board, first run `git log --oneline -- <home>/board/board.py`: a commit that is not an engine upgrade is a local edit; read its diff and carry its view into `<home>/board/local/<name>.html` (the board loads each such file as a tab and no upgrade touches the folder). Run `python
<SKILL_DIR>/scripts/scaffold.py <root> --git skip`: it builds `<home>/board/` when absent (`board.py` from the engine's
`assets/board/board.py`, and `board.json` with the port derived from the home's path, bind-tested once), refreshes
`board.py` when its `BOARD_VERSION` is older than the engine's (a copy that differs at the same version is reported and
left), adds `<home>/board/data/` to `.gitignore`, writes the CLAUDE.md block line and inserts the `## Owner board`
section into `RESUME.md` when it lacks one. It never touches an existing `board.json` or anything under `data/`, so
the port and the answers survive every upgrade. Then run `python <home>/board/board.py ensure`, report its line, and when you carried a local view confirm its tab shows.
The canary's `board` category reports a pointer with no board (`board-missing`) and a board nothing points at
(`board-pointer-missing`). The Artifact owner board is retired: if RESUME still names one under `## Waiting on whom`,
remove that line.

**4v. Active adoption: audit the repo against what the new versions introduced (v62; before 4q).**
An upgrade does not end at new files. A version that adds a rule names how the repo is held to it, and the repo is
audited in this upgrade, never left for "the operator's separate audit". Run it before step 5 stamps the version,
after the data migrations and the home tools, and skip it when step 3 found the repo current.
1. **Find the audits.** Read the `CHANGELOG.md` entries of every version above the repo's stamped version up to the
   target (a `## Unreleased` block counts as the next version). A version that adds an audit carries one line in its
   entry under the `breaking:` line, `audit: <name> (<where its procedure is>)`. Collect them all and run each; a repo upgrading across several
   versions runs every audit of every version it crosses, once.
2. **v62's audits are two** (the version after v63 adds a third, last in this list). `audit: brain (references/upgrade.md step 4u)` and `audit: tests (scripts/audit_tests.py)`.
   - *Brain.* Run 4p and then 4u on the repo's brain, for **every** repo whose range holds the line, a repo already
     stamped v61 included (one whose v61 upgrade ran 4p, or ran nothing of the audit, gets 4u now, not by hand
     later). 4u acts inside the upgrade; what it leaves over (the pages it listed as unsure, a brain too large to
     finish in one session) is a finding.
   - *Tests.* Run `python <SKILL_DIR>/scripts/audit_tests.py <repo-root>` (read-only; it runs and times no test) and
     put its output in the report. A repo with other test conventions lists them in `<home>/test-audit.json`
     (the script's header says how). Output saying that no test file was found is not a clean result: ask which
     conventions the repo uses. The suite's wall time is not measured: ask the operator for it if it is not known.
     Each area with files over the limit is one finding (split them by area or concern); fixtures over 1 MB are
     one finding (slim them, or keep a named one that needs its size).
   - *Owner board route* (`audit: owner board route (references/upgrade.md step 4s)`). A repo that already has
     `<home>/board/` and no `board-route.json` is asked 4s's question now: own board (nothing changes) or a hub. A repo
     with no board gets 4s's whole step anyway.
3. **One card, never silence.** Turn the findings into proposed work-orders (a title, the evidence with its counts,
   what the order would do) and put them on ONE owner-board card, group `decision`:
   `python <home>/board/board.py add-decision "<N> orders proposed by the v<target> audits" "<one numbered line per
   proposed order>" open_all="Open all as orders" park_all="Park them all" pick="Open some (say which in the note)"
   decline_all="Decline all" --group decision`. A decision card has one set of options, so the choice per order goes
   in the note. Nothing is created before the answer. Record the answer in the ledger before acting (the opened ones
   are written as orders by `orchestrator/authoring.md`; the parked ones as parked orders with their trigger), then
   close the card with the outcome. No finding: no card, and the report says what each audit looked at and found.
   An audit that could not run is reported as that (discipline (i)), never as "nothing found".

**4q. The one offer round.**
Run `python <SKILL_DIR>/scripts/offer.py <repo-root>` **last in step 4**, after the data migrations, the home
tools and the audits of 4v, so every question is computed against the repo as upgraded. It asks each subsystem's own check which
opt-in is still unanswered (model optimization has no recorded preference; lenses have no `lenses.json` and a lens
exists; System One has no repo choice in `<home>/system-one.json` and a machine config exists or
`system_one.py setup --detect` prints a line; federation has something to offer;
a legacy register is unanswered; the harness audit holds removal candidates) and prints **one question batch**,
or **nothing** when nothing is unanswered. **If it prints nothing, this step is over: say nothing.** It writes
nothing itself. A line `offer: X not read (reason)` on stderr means that check could not run and its question was
not asked: report it, never treat it as an empty offer.

When it prints, pass `questions` to `AskUserQuestion` as-is, in the groups `calls` names (a call takes at most four
questions; the groups are still one round, so nothing runs between them). **Never render the choices as a prose
list and wait for a typed reply** (`--text` is for a harness with no question UI). Then, per answered question, run
exactly the commands its entry's `apply` names for the chosen label; a question left unanswered runs the entry's
`if_unanswered` (model optimization: `skip`, recorded as off) and nothing else. Read `follow_up` for what a chosen
option leads to (the lens pick, federation's group pick and exposure flags, the drain after a register import).

**An answered question is never asked again**, because a question exists only while its store lacks the answer:
`model-optimization.json`, `lenses.json`, `system-one.json`, the `<!-- legacy: ... -->` line in the list header.
Declining federation stores nothing, by its own rule, so it is computed fresh each round; the harness popup is
computed from the audit. The answers are the operator's alone: a repo that came back federated, or with System One
on, because somebody asked for a directive refresh would have spent a consent nobody gave.

**4r. Consolidate the backlog (once, on the upgrade to v58).**
List every open order, parked order and loose end, group them by scope of work (the same subsystem, the same
files), and propose to the operator a smaller set: follow-up and "part 2" orders folded as slices into the order
that owns that scope (or one order per scope); items already fixed closed with the commit named; everything left
given an explicit finish order. Report `N open before -> M after`. Nothing changes without the operator's word.

**4p. The brain: front matter, written descriptions, the generated index, no log (v61).**
Skip when the repo has no `<home>/brain/`. The brain's front matter is the source of truth and `wiki/index.md` is
generated from it (`references/brain-schema.md` §3-4). Run the home copy of `brain_lint.py` on `<home>/brain`: a page
without `type`, `description`, `status` and a dated `updated` is reported under `schema`. For each such page add the
front matter with `type` from its directory, `status: active`, `updated` kept from the page's own date (a decision page
is a record: keep its `decided` date as `updated`; a hand-written `maps_to` becomes `rests_on`), and a `description`
that **you write by reading the page**: one line of at most 140 characters naming the situation in which to read it
("Read this when changing X: it keeps why Y was rejected"). A description is never derived by a script, and never the
page's title, its first line or a shortened first sentence: an index of those lines does not say when to read anything.
The lint reports `placeholder-description` for an empty description, one that ends in `:`, one with an unbalanced
bracket or quote (a cut line), one that opens `Read this when you need <title>:`, and one equal to the page's title or
first line; rewrite each one it names from the page. A repo that already took this step with placeholder lines gets
the same rewrite from 4v, which runs 4p and 4u for a repo stamped v61 whose canary reports `brain-schema` items or
`brain-upgrade-diary`. Then run `brain_lint.py <home>/brain --write-index` to generate the index (it replaces the
hand-kept one; over 200 lines / 8 KB is an error that names the longest descriptions) and delete `wiki/log.md` (git
keeps it: `git log -- <home>/brain`). Do not commit yet: step 4u audits the pages, then commits once.

**4u. The brain audit against the write test (v62's `audit: brain`, run by 4v; part of the upgrade, not the operator's chore).**
Skip when there is no brain. An old brain is mostly pages that restate an order, the code or the git log; the write
test (`brain-schema.md` §1) is applied to every page now, while the upgrade is open. List the pages and `wiki/` size
first. A brain of about fifteen pages is read by you; a larger one is split by directory (about ten to fifteen pages a
helper, the judgement a mid-tier model, never the cheapest) under one written brief that carries the rules below, and
each helper returns one line per page: its verdict and the reason. Per page the verdict is **keep** (passes as
written), **cut** (rewrite to only the content that passes; keep a decision's `updated` as its decision date),
**delete** (nothing passes) or **unsure** (kept as is and listed for the operator, never deleted on a guess). What
passes: the reason a design won over what was rejected and why each option lost, a trap a later change would walk into,
a convention no single file shows, a standing rule of the operator. What fails: what was built (the code says), the
history of events (git says), an order's own adjudication, a catalog of files or tools, a restatement of a reference doc.
A page named `engine-upgrade-v<N>` narrates one upgrade, which git and the CHANGELOG hold: delete it unless it holds a
why, a rejected option or a trap that git and an order do not, and then cut it to that and rename it for that content.

Two rules before a deletion:
1. **Grep the order or orders a page cites for its why, its rejected options and its traps before deleting it.** Take
   the page's key terms (each rejected option, each trap) and `grep` them in the cited order file. Where the order
   lacks them the page is **cut** to that content, not deleted: an earlier audit that trusted "the order covers it"
   deleted rejected options no order held and had to restore them.
2. **A decision the operator made in conversation and recorded nowhere else** (a standing rule, a product direction,
   a strategy model) passes the test by definition, because git and the orders do not hold it. Cut its narration and
   keep the decision and its reasons.

Then run `brain_lint.py <home>/brain --write-index` again (the index is generated from what is left) and
`brain_lint.py <home>/brain --check`; the lint must report no `placeholder-description` and no `upgrade-diary` page
except one the audit kept as unsure, which is named in the report. Commit the brain in the repo's own commit, together
with 4p. Report the pages kept, cut, deleted and unsure (the unsure ones by name, with the reason), and the size of
`wiki/` before and after in bytes. Nothing is asked of the operator beyond the unsure list.

**5. Stamp the new version.**
Write the skill's `ENGINE_VERSION` back as the repo's `engine_version`:
`<home>/brain/.brainmeta.json` (`engine_version` field) for a repo with a brain, else
`<home>/HANDOFF.md`. Then run `python <SKILL_DIR>/scripts/ledger_index.py <home>` (the board header names the stamp).

**6. Record a decision only if there is a why.**
The from→to versions, the adopted directives and the re-pointed pointers are in the stamp and in git, so they are not
a brain page. Add a decision page (with its front matter) only when the upgrade carried a choice that passes the
write test (`brain-schema.md` §1): a rejected option, a trap, an operator decision. No log line: the brain has no log.

**7. Report.**
Show the `git diff` of what changed (the re-pointed pointers, the stamp, any decision page, any
`<home>/tools/` copy that was newly copied **or refreshed** — name each refreshed tool and
say the prior bytes are in git), and the `ledger_migrate.py` result (the `not-now:` moves and anything `LEFT`,
converted orders, skipped orders with their reason, `work-orders/history/` removed) — confirm each explicitly in the
report.

## What it never does

- It never relocates or renames the home (`.pipeline/` and `outputs/debug/` stay where
  they are).
- It never edits a downstream product's domain profile or project state — a wrapper
  (the product's own engine-sync bridge, e.g. a `BRIDGE.md`) owns that and calls this
  procedure for the engine part.
- It is the only copy of the upgrade logic. Wrappers reference it; they do not duplicate
  these steps.
