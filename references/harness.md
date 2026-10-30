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

## Commands

- `audit` (read-only): per-repo usage from this repo's own session logs; listing-budget headroom
  with the declared-only projection; the skills whose descriptions drop first; the tool-definition
  lower bound against the 30-50 band; tool-search state (`ENABLE_TOOL_SEARCH`, forced-off
  conditions); hooks by scope and which reach every repo; subagent definitions; proposed edits;
  the limits below.
- `drift` (read-only; findings gate, notices do not): `undeclared-skill`, `declared-skill-missing`,
  `skill-pin-moved`, `undeclared-plugin`, `plugin-outside-baseline`, `declared-plugin-missing`,
  `pin-moved`, `undeclared-mcp`, `undeclared-connector`, `sync-not-off`, `connectors-not-off`,
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
