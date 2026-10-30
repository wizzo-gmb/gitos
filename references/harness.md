# The harness profile — each repo declares what it loads

A repo's Claude Code harness (skills, plugins, MCP servers, connectors, hooks, subagent
definitions) is **declared** in `<home>/harness.json`, **measured** by `harness.py audit`,
**checked** by `harness.py drift` (canary category `harness`) and **materialised** by
`harness.py sync`. Mechanism: `scripts/harness.py` (copy at `<home>/tools/harness.py`).
Disabled by default: no `harness.json` means the repo behaves as before, apart from one offer line at
bootstrap (`harness.py offer`).

## Why — accuracy, not context rent

The measured harm of a crowded harness is wrong tool and skill selection. Same model, same tasks,
only the number of tool definitions loaded varied: Opus 4 went 49% to 74% and Opus 4.5 went 79.5% to
88.1% with tool search enabled (Anthropic Engineering, *Advanced tool use*); the docs put the
degradation point at 30-50 tool definitions. Token cost is secondary: tool search is on by default
(names only at start), and skill bodies load only on invocation.

The skill-side mechanism is **crowding**. The skill listing is budgeted at 1% of the context window.
When it overflows, descriptions drop **least-invoked-first**, which removes the keywords the repo's
own skills need to trigger. Unused skills do not mainly cost tokens; they evict the descriptions of
the skills this repo uses. `audit` reports the headroom and names the skills at risk.

### What `audit` may propose to switch off (WO-062)

The audit exists to find useless skills that bloat the listing, and a wrong "switch it off" is the
one output that does damage. Three rules, enforced in `harness.py` (`PROTECTED_SKILLS`,
`vouch_usage`, `removal_plan`); preserve them:

1. **`gitos` is never a removal candidate**, whatever its count reads. The audit runs inside gitos,
   and this holds even if a future log format defeats the parser. Narrow on purpose: one name, not a
   list of "important" skills.
2. **Evidence protects everything else.** Any observed use (operator slash command or `Skill` tool
   call) exempts a skill. A zero counts only if the audit can vouch for it: logs present, every file
   readable, every relevant line parsed. The audit states the span (sessions, first..last day). When
   it cannot vouch it says *usage not established* and proposes nothing.
3. **Rank by purpose.** Candidates are ordered by listing cost (largest first), and the audit says
   plainly when removing every one still leaves the listing over budget: then the lever is
   plugin-level, because `skillOverrides` cannot split a plugin.

Usage counts both forms: a `Skill` tool call, and the operator-typed `<command-name>/x</command-name>`
user record. A slash command followed by a `Skill` call for the same skill and args (before the next
human turn) is one action and counts once.

### Removals are confirmed, never assumed (WO-063)

The audit proposes; only the operator's confirmation disposes. `harness.py popup` renders the
`removal` block as `AskUserQuestion` questions (a plugin is one option with its skill count;
ranked by budget; what does not fit is stated). `sync --confirm NAME` applies exactly the confirmed
names, to `settings.local.json` only: `skillOverrides: off` for a skill (synced claude.ai skills
included, sync left on) or `enabledPlugins: false` for a whole plugin. An empty confirmation applies
nothing; `gitos` is refused by any route; a name the audit did not propose is refused until checked.
The operator's confirmation is its own consent and needs neither a `harness.json` nor `adopted: true`; every declaration-driven write stays gated on adoption. No default-on selection, no apply on timeout. The claude.ai skill-sync switch is all-or-none and is
asked as its own question. `sync` writes `syncClaudeAiSkills`/`syncClaudeAiPlugins` only with
`--accept-sync-skills`/`--accept-sync-plugins`; unasked counts as declined.
Unverified: whether `skillOverrides` matches a synced skill by short name or only as
`anthropic-skills:<name>`. The popup itself is Claude-only; other harnesses get a numbered text list.

### The claude.ai sync questions (WO-072)

`popup` always carries one single-select question per sync switch (`Skill sync`, `Plugin sync`),
whether or not there are removal candidates. Each shows the current state (on, off in this checkout,
or off at user scope) and offers **Keep as is**, **Turn off** and **Turn back on**. Nothing is
pre-selected, and no answer writes nothing. The question states the documented consequences: the
switch is all-or-none; a `false` in `settings.local.json` applies to this checkout only and stops
every synced item loading and updating there; a user- or managed-scope `false` also moves the
copies to `~/.claude/{skills,plugins}/.trash/` at the next launch. It also says the switch is the
last resort: hide single synced skills with `skillOverrides: off`, and single synced plugins with
`"<name>@synced": false` in `enabledPlugins`, both through the removal questions.

The answer reaches `sync` as a flag (`popup` returns the map as `sync_flags`): **Turn off** is
`--accept-sync-skills` / `--accept-sync-plugins` and writes exactly `false` locally; **Turn back on**
is `--restore-sync-skills` / `--restore-sync-plugins` and removes the local `false`. It never writes
`true`, because only `false` is honoured. A user-scope `false` is proposed for removal, never
removed. Both flags for one switch are refused. Like a confirmed removal, the answer is its own
consent and needs neither a `harness.json` nor `adopted: true`. Turning sync back on while the
declaration says off makes drift report `sync-not-off` until the declaration changes.

Synced plugins are read from `<claude-home>/plugins/synced/` and load as `<name>@synced`. One with
no observed use is an ordinary plugin candidate. Declaration-driven `sync` and drift leave synced
plugins alone; only a confirmed removal hides one.

## `harness.json`

| key | meaning |
|---|---|
| `adopted` | `false` = starter; nothing is checked or written (canary shows a visible skip). Absent or `true` = enforced. |
| `library` | folder outside Claude's load path holding pinned skill copies (`<library>/<skill>/`). |
| `claude_ai` | `sync_skills`, `sync_plugins` (`false` = off) and `connectors` (`[]` = none). |
| `baseline` | what user scope may carry for every repo: `skills`, `plugins`, `hooks` (`{event, match}`). |
| `skills[]` | `{name, source: library\|user\|project, sha256, update, why}`. |
| `plugins[]` | `{name: plugin@marketplace, version, update, why}`. Whole-plugin granularity only. |
| `mcp[]` | `{name, tools, why}`; `tools` is the count you know, feeding the tool-definition total. |
| `agents[]` | `{name, sha256, why}` — see *Subagent definitions*. |
| `hooks[]` | `{event, match, scope, why}`; `match` is a substring of the hook command. |
| `permissions.allow` | allow-list additions `sync` appends to `settings.local.json`. |
| `last_checked` | UTC stamp of the last `update` pass. |

Update channels per entry: `auto` (source updates itself; a moved version is a **notice**, recorded by
`update --apply`), `review` (default; the operator approves before a pin moves: `update --approve
NAME`), `pinned` (never moves; a moved version is a finding). Synced claude.ai skills stop updating
once sync is off; no public upstream was verified here, so `update` reports "no update source"
rather than guessing, and sync is never re-enabled silently.

**Plugin channels act only through documented levers (WO-072).** Claude Code auto-updates per
**marketplace**, never per plugin. The first source that is set wins: `autoUpdate` on the
marketplace's `extraKnownMarketplaces` entry in a settings file (a repo entry counts only once the
workspace is trusted), then `known_marketplaces.json`, then the default. The default is on for
Anthropic's official marketplaces except `knowledge-work-plugins` and `first-party-plugins`, on for
marketplaces added from claude.ai, and off for every other.

- `auto`: `sync` proposes `autoUpdate: true` for the plugin's marketplace. That is a user-scope
  change, so it is a proposal and is never written. When the marketplace already auto-updates,
  `sync` says so instead.
- `review` (the default): unchanged; drift reports version moves.
- `pinned`: no write, because no per-plugin pin is documented. When the plugin's marketplace
  auto-updates, drift reports `pinned-but-auto-updates`, with the consequence: turning that
  marketplace's `autoUpdate` off freezes **every** plugin from it. The operator decides; the engine
  never picks a side.
- `known_marketplaces.json` is the client's own record. `harness.py` reads it and never writes it.

`DISABLE_UPDATES`, `DISABLE_AUTOUPDATER` or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` turns the
whole auto-update pass off unless `FORCE_AUTOUPDATE_PLUGINS` is set. `audit` reports that
(`plugin_auto_update`), and a pin held only by that override is a notice, not a conflict.

## Commands

- `audit` (read-only): per-repo usage from this repo's own session logs; listing-budget headroom
  with the declared-only projection; the skills whose descriptions drop first; the tool-definition
  lower bound against the 30-50 band; tool-search state (`ENABLE_TOOL_SEARCH`, forced-off
  conditions); hooks by scope and which reach every repo; subagent definitions; proposed edits;
  the limits below.
- `drift` (read-only; findings gate, notices do not): `undeclared-skill`, `declared-skill-missing`,
  `skill-pin-moved`, `undeclared-plugin`, `plugin-outside-baseline`, `declared-plugin-missing`,
  `pin-moved`, `pinned-but-auto-updates`, `undeclared-mcp`, `undeclared-connector`, `sync-not-off`,
  `connectors-not-off`,
  `undeclared-hook`, `undeclared-agent`, `declared-agent-missing`, `agent-changed`,
  `declaration-unreadable`.
- `update` (report-only unless `--apply`; writes `harness.json` only).
- `sync` (dry run unless `--apply`). Backs up first to `<claude-home>/backups/harness-<stamp>/`.
  Writes only: library skill copies into `<repo>/.claude/skills/`; in
  `<repo>/.claude/settings.local.json` the keys `enabledPlugins`, `skillOverrides`,
  `permissions.allow`, `syncClaudeAiSkills`, `syncClaudeAiPlugins`, `disableClaudeAiConnectors`; and
  `projects[<repo>].disabledMcpServers` in `~/.claude.json` (the `/mcp` field — no settings key for
  it exists). Idempotent. A declared name wins: an `off`/`false` for a now-declared entry is released.
  The `~/.claude.json` write refuses if the file changes while syncing. **There is no code path that
  writes the user-scope `settings.json`**: baseline changes are proposals for the operator.

Removal is an override, never a deletion: list keys merge across scopes, so a project file cannot
subtract a user-scope entry.

## Subagent definitions and hooks

`.claude/agents/` definitions carry `model`, `effort`, `tools`, `skills`, `mcpServers` and `hooks`, so
an undeclared or drifted one changes routing silently. **WO-055 writes the definitions; this order
declares and audits them** (`agents[].sha256` pins the file; `agent-changed` fires on any edit).
`harness.py` never writes under `.claude/agents/`.

Hooks at user or plugin scope **broadcast**: one edit to the user `settings.json` woke four live
sessions in four repos at once. `audit` lists them as reaching every repo; `drift` flags any hook
neither declared under `hooks` nor in `baseline.hooks`.

## Limits (printed by `audit`, never worked around)

No per-project claude.ai sync switch in the shared project file (only user/local/`--settings`
`false` counts). `skillOverrides` does not reach plugin skills and no single plugin skill can be
turned off. No per-MCP-tool disablement. Connectors are all-or-none. Synced claude.ai skills are not
enumerable from disk. Managed settings are not read. The tool-definition count is a lower bound
(observed in logs plus declared); the listing budget assumes a context window (`--context-window`,
default 200000). Session-log parsing is best effort over a non-contract format.

## Skills: copies, not junctions (measured)

Library skills are **copied** into `<repo>/.claude/skills/` and pinned by content hash. On Windows,
a junction there is followed by git (the files commit as an ordinary tree, so the "link" is a stale
copy in history); an uncommitted junction is simply absent from every sibling worktree; and
Python 3.10's `shutil.rmtree` refuses a junction (safe, but tooling that does not refuse risks the
target). Copies commit, travel into worktrees and hash cleanly for drift.

## Upgrade

`references/upgrade.md` carries the harness step: it runs `update`, shows `review` diffs for
approval, then `sync --apply`. One update command for the operator.
