# Orchestrator step: confirming skill removals (the harness popup)

Read this at the upgrade offer round (`references/upgrade.md` step 4q) or when the operator asks about removing skills or plugins.

The audit proposes; the operator disposes. At upgrade the removal batches are asked in the one offer round
(`references/upgrade.md` step 4q), only when the audit holds removal candidates; on demand, run `harness.py popup` and
pass its `questions` to `AskUserQuestion` as-is. It always ends with the two claude.ai sync
questions. Removal batches come first, and only when `audit --json` has vouched
`removal.candidates`: a plugin is one option with its skill count, and options are ranked by budget
reclaimed. The 1-4 question / 2-4 option limit, less the two sync questions, means at most 8 are
shown. Read out `remainder.text` so the operator knows what was not shown. A second popup is
offered, never forced. Rules:

- The answer is authoritative both ways: unticked is kept. Nothing is pre-selected and no answer
  (or a timeout) is not consent. Never apply on silence.
- An "Other" answer naming something the audit did not propose is checked against the same evidence
  and confirmed back first; `sync --confirm` refuses it, and refuses `gitos` by any route.
- Apply through `harness.py sync --confirm NAME ...` (repeat per ticked candidate): dry run, show
  it, then `--apply`. Pass `--accept-sync-skills` (or `--accept-sync-plugins`) ONLY when the operator
  accepted that sync question; without it nothing is written, so no answer means declined. Say whether the confirmed set gets the
  listing within budget (`sync` prints the verdict) and, if not, name the lever, usually a whole
  plugin.
- Synced claude.ai skills are ordinary candidates (`skillOverrides: off`, sync stays on). Synced
  plugins are candidates as `<name>@synced` (`enabledPlugins` `false`, sync stays on).
- **Sync questions (WO-072).** Each sync question shows the current state and offers Keep as is /
  Turn off / Turn back on, with nothing pre-selected. Map the answer through `sync_flags`: Turn off
  is `--accept-sync-skills`/`--accept-sync-plugins` (writes exactly `false` to
  `settings.local.json`), and Turn back on is `--restore-sync-skills`/`--restore-sync-plugins`
  (removes that `false` and never writes `true`). Keep as is, Other, or no answer passes no flag and
  writes nothing. The switch is the last resort: say so, and point to hiding single synced items
  first.
- **Plugin update channels.** `update: auto` gives a user-scope proposal (`autoUpdate: true` on the
  marketplace) that you relay and never apply. `update: pinned` on an auto-updating marketplace is a
  drift conflict: put both sides to the operator (turning the marketplace's auto-update off
  freezes every plugin from it, or change the entry's channel) and never pick one. Never write
  `known_marketplaces.json`.
- **Claude-only.** `AskUserQuestion` exists in Claude Code, not on every harness (for example
  `codex`). There, list the same candidates as a numbered text list and take the answer in text,
  under the same rules. Do not describe the popup as universal.

- **A large round: the decisions page (WO-080).** The popup stays the default. Only when a round has
  more than 4 items (more than one popup holds) and the harness has a tool that publishes a private
  page (in Claude Code, the Artifact tool) may you put the round on one page; otherwise use several
  popups, or the numbered text list where there is no popup. Fill `assets/decisions-page.html.tmpl`
  from an item list (id, title, why, where, optional now/proposed, options, recommendation, reason;
  the fill format is documented at the top of the template). Each item shows what and why, where,
  the options with the recommendation marked and its reason, and a "Decide later" choice; the bottom
  bar shows "N of M decided" and "Copy my decisions" (one `<id>: <choice>` line per item).
  - **The pasted reply is the answer.** The page's own state is never read as consent, and an item
    left undecided (or "later") is not approved. Record each answer in the ledger (the work-order, a
    loose-end row or a decision page) before acting on it.
  - Re-read every item on the page before you publish it. The page is private to the operator, holds
    no secrets and no foreign text (a federation proposal body is never rendered on it).
  - You publish it with the harness's own tool; the engine has no code that does.
  - An approval is never asked on it: an approval is a board card (*Ask on the board* in `references/roles/orchestrator.md`).
