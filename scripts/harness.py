"""harness - a repo's declared, minimal, checked Claude Code harness (WO-052).

stdlib-only. Policy and rationale live in references/harness.md; this file is the mechanism.

  audit   READ-ONLY. Measures this repo's harness: listing-budget headroom, which skills risk
          having their descriptions dropped, the tool-definition count against the 30-50 band,
          tool-search state, hooks (and their scope), subagent definitions, plugins, MCP.
  drift   READ-ONLY. Compares what is visible in this repo to `<home>/harness.json`.
          Findings gate (canary category `harness`); notices never do.
  offer   READ-ONLY. The single bootstrap line (silent when nothing is worth saying).
  update  The `auto`/`review` pass. Report-only unless --apply (which writes harness.json only).
  sync    Materialises the declaration. DRY-RUN unless --apply. See `plan_sync` for the exact
          write surface; it has NO code path that writes the user-scope settings.json.

Everything is rooted at three overridable locations so selftests never touch the real machine:
`--root` (the repo), `--claude-home` (default $CLAUDE_CONFIG_DIR or ~/.claude) and `--claude-json`
(default <claude-home>/.claude.json when CLAUDE_CONFIG_DIR is set, else ~/.claude.json).

Usage:
    python harness.py audit|drift|offer [--measure]|update|sync [--home <repo>/.gitos] [--json] [--apply]
Exit codes: 0 = ok / clean, 1 = drift findings (drift only), 2 = usage or unreadable declaration.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_FILENAME = "harness.json"
SCHEMA_VERSION = 1
TOOL_BAND = (30, 50)                 # documented degradation band for loaded tool definitions
DEFAULT_CONTEXT_WINDOW = 200_000     # ASSUMPTION - the model's real window is not on disk
DEFAULT_BUDGET_FRACTION = 0.01       # documented skill-listing budget: 1% of the context window
DEFAULT_MAX_DESC = 1536              # documented skillListingMaxDescChars default
UPDATE_CHANNELS = ("auto", "review", "pinned")
STALE_CHECK_DAYS = 7

# What this tool cannot do, stated rather than implied. Printed by `audit`, listed in --json.
LIMITS = (
    "No per-project switch for claude.ai skill/plugin sync: `false` is honoured from user, local "
    "or --settings scope only (a `false` in the shared project file is ignored). Sync writes it "
    "to settings.local.json; it cannot make a project file carry it.",
    "skillOverrides does not reach plugin skills, and no single skill inside a plugin can be "
    "switched off: the only lever is the whole plugin (enabledPlugins false).",
    "No per-MCP-tool disablement exists client-side: whole server (via ~/.claude.json "
    "disabledMcpServers, written by `/mcp`) or permissions.deny only.",
    "List keys MERGE across scopes, so a project file can never subtract a user-scope entry. "
    "Removal is an override (skillOverrides off, enabledPlugins false), never a deletion.",
    "disableClaudeAiConnectors is all-or-none: declaring a subset of connectors cannot be "
    "expressed; claude.ai connectors are only enumerable if ~/.claude.json lists them.",
    "claude.ai-synced skills are on disk in <claude-home>/skills/synced/ (Claude Code v2.1.273+) "
    "and are enumerated as scope `synced`; they are hidden per repo by skillOverrides off with sync "
    "left on. UNVERIFIED: whether skillOverrides matches a synced skill by its short name or only "
    "as `anthropic-skills:<name>`, and whether a repo-local syncClaudeAiSkills false trashes the "
    "synced skills machine-wide; the second is why that switch is all-or-none and asked separately.",
    "Managed (enterprise) settings are not read; a managed value can override anything reported.",
    "The tool-definition count is a LOWER BOUND (MCP tools observed in this repo's session logs "
    "plus counts you declare). Built-in and not-yet-invoked MCP tool counts are not on disk.",
    "The listing budget assumes a context window (default 200000, --context-window) and counts "
    "characters as the docs state the budget; the exact per-line overhead is estimated.",
    "User-scope changes (the baseline) are PROPOSED only. `sync` has no code path that writes "
    "<claude-home>/settings.json.",
)


# --------------------------------------------------------------------------- small helpers
def _read_text(p: Path) -> "str | None":
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _load_json(p: Path) -> "tuple[object | None, str | None]":
    """-> (obj, error). A missing file is (None, None); an unparseable one is (None, reason)."""
    raw = _read_text(p)
    if raw is None:
        return None, None
    try:
        return json.loads(raw), None
    except ValueError as e:
        return None, f"{p.name} is not valid JSON ({e})"


def _dict(x: object) -> dict:
    return x if isinstance(x, dict) else {}


def _norm_bytes(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def file_sha(p: Path) -> "str | None":
    try:
        return hashlib.sha256(_norm_bytes(p.read_bytes())).hexdigest()
    except OSError:
        return None


def dir_sha(d: Path) -> "str | None":
    """Content hash of a skill directory: sorted relative paths + CRLF-normalized bytes."""
    if not d.is_dir():
        return None
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(f.relative_to(d).as_posix().encode() + b"\0")
        try:
            h.update(_norm_bytes(f.read_bytes()) + b"\0")
        except OSError:
            return None
    return h.hexdigest()


def parse_fm(raw: str) -> dict:
    """Top-level frontmatter keys only. Folded/literal blocks (> | >- |-) and indented
    continuations are joined into the value; nested maps (hooks:) come back as the raw text."""
    if not raw.startswith("---"):
        return {}
    end = raw.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    key = None
    for line in raw[3:end].splitlines():
        if not line.strip():
            continue
        if line[0] not in " \t" and ":" in line:
            key, v = line.split(":", 1)
            key, v = key.strip(), v.strip()
            out[key] = "" if v in (">", "|", ">-", "|-", ">+", "|+") else v.strip("\"'")
        elif key is not None:
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def _slug(root: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(root))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def claude_paths(claude_home: "str | None", claude_json: "str | None") -> "tuple[Path, Path]":
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if claude_home:
        ch = Path(claude_home)
    elif env:
        ch = Path(env)
    else:
        ch = Path.home() / ".claude"
    if claude_json:
        cj = Path(claude_json)
    elif claude_home:
        cj = ch.parent / ".claude.json"
    elif env:
        cj = ch / ".claude.json"
    else:
        cj = Path.home() / ".claude.json"
    return ch, cj


# --------------------------------------------------------------------------- declaration
def load_declaration(home: Path) -> "tuple[dict | None, str | None]":
    """-> (declaration, error). (None, None) = no harness.json (the disabled-by-default state)."""
    obj, err = _load_json(home / HARNESS_FILENAME)
    if err:
        return None, err
    if obj is None:
        return None, None
    if not isinstance(obj, dict):
        return None, "harness.json top level is not an object"
    return obj, None


def _names(decl: dict, key: str) -> set:
    out = set()
    for e in decl.get(key) or []:
        out.add(e.get("name") if isinstance(e, dict) else e)
    return out - {None}


def declared(decl: dict) -> dict:
    base = _dict(decl.get("baseline"))
    return {
        "skills": _names(decl, "skills"), "plugins": _names(decl, "plugins"),
        "mcp": _names(decl, "mcp"), "agents": _names(decl, "agents"),
        "base_skills": set(base.get("skills") or []),
        "base_plugins": set(base.get("plugins") or []),
        "base_hooks": list(base.get("hooks") or []),
        "hooks": [h for h in (decl.get("hooks") or []) if isinstance(h, dict)],
    }


def is_adopted(decl: dict) -> bool:
    return decl.get("adopted", True) is not False


def starter_declaration() -> dict:
    """The inception seed: a minimal, NOT-yet-adopted declaration (see scaffold.py)."""
    return {
        "version": SCHEMA_VERSION,
        "adopted": False,
        "_note": ("Starter harness declaration. Run `python .gitos/tools/harness.py audit`, "
                  "review the proposals, fill the lists, then set adopted to true. "
                  "While adopted is false nothing is checked and nothing is written."),
        "library": None,
        "claude_ai": {"sync_skills": False, "sync_plugins": False, "connectors": []},
        "baseline": {"skills": [], "plugins": [], "hooks": []},
        "skills": [], "plugins": [], "mcp": [], "agents": [], "hooks": [],
        "permissions": {"allow": []},
        "last_checked": None,
    }


# --------------------------------------------------------------------------- machine scan
def _skill_entry(skill_md: Path, scope: str, prefix: str = "") -> dict:
    raw = _read_text(skill_md) or ""
    fm = parse_fm(raw)
    name = fm.get("name") or skill_md.parent.name
    return {"name": prefix + name, "dir": skill_md.parent.name, "scope": scope,
            "description": fm.get("description", ""), "path": str(skill_md.parent),
            "dmi": fm.get("disable-model-invocation", "").lower() == "true",
            "user_invocable": fm.get("user-invocable", "true").lower() != "false"}


def _skills_in(d: Path, scope: str, prefix: str = "") -> list:
    if not d.is_dir():
        return []
    return [_skill_entry(p / "SKILL.md", scope, prefix)
            for p in sorted(d.iterdir()) if (p / "SKILL.md").is_file()]


def _agent_entry(f: Path, scope: str) -> dict:
    raw = _read_text(f) or ""
    fm = parse_fm(raw)
    keys = ("model", "effort", "tools", "skills", "mcpServers", "hooks")
    return {"name": fm.get("name") or f.stem, "scope": scope, "path": str(f),
            "sha256": file_sha(f), **{k: fm[k] for k in keys if k in fm}}


def _agents_in(d: Path, scope: str) -> list:
    return [_agent_entry(f, scope) for f in sorted(d.glob("*.md"))] if d.is_dir() else []


def _hooks_from(settings: dict, scope: str) -> list:
    out = []
    for event, groups in _dict(settings.get("hooks")).items():
        for g in groups if isinstance(groups, list) else []:
            g = _dict(g)
            for h in g.get("hooks") or []:
                h = _dict(h)
                out.append({"event": event, "matcher": g.get("matcher", ""),
                            "command": str(h.get("command") or h.get("url") or h.get("prompt")
                                           or h.get("type") or ""), "scope": scope})
    return out


def _project_key(cj: dict, root: Path) -> "str | None":
    projects = _dict(cj.get("projects"))
    for cand in (root.as_posix(), str(root), root.resolve().as_posix(), str(root.resolve())):
        if cand in projects:
            return cand
    return None


def scan_machine(root: Path, ch: Path, cj_path: Path) -> dict:
    """Everything visible to a session in `root`, read from disk. Missing inputs are recorded
    in `gaps` (named, never silently zero)."""
    gaps: list[str] = []
    errors: list[str] = []
    settings = {}
    for scope, p in (("user", ch / "settings.json"),
                     ("project", root / ".claude" / "settings.json"),
                     ("local", root / ".claude" / "settings.local.json")):
        obj, err = _load_json(p)
        if err:
            errors.append(err)
        settings[scope] = _dict(obj)
        if obj is None and err is None and scope == "user":
            gaps.append(f"no {p} (user settings unreadable or absent)")

    def merged(key: str) -> dict:
        out: dict = {}
        for scope in ("user", "project", "local"):
            out.update(_dict(settings[scope].get(key)))
        return out

    enabled = merged("enabledPlugins")
    overrides = merged("skillOverrides")
    env = {**merged("env"), **{k: v for k, v in os.environ.items()
                               if k in ("ENABLE_TOOL_SEARCH", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS")}}

    def scoped_false(key: str, scopes=("user", "local")) -> bool:
        return any(settings[s].get(key) is False for s in scopes)

    flags = {
        "sync_skills_off": scoped_false("syncClaudeAiSkills"),
        "sync_plugins_off": scoped_false("syncClaudeAiPlugins"),
        "connectors_off": any(settings[s].get("disableClaudeAiConnectors") is True
                              for s in ("user", "project", "local")),
    }
    deny = [d for s in settings.values() for d in _dict(s.get("permissions")).get("deny") or []]
    allow = [d for s in settings.values() for d in _dict(s.get("permissions")).get("allow") or []]

    # plugins
    inst_obj, inst_err = _load_json(ch / "plugins" / "installed_plugins.json")
    if inst_err:
        errors.append(inst_err)
    plugins: dict[str, dict] = {}
    raw_plugins = _dict(_dict(inst_obj).get("plugins", inst_obj))
    for pname, val in raw_plugins.items():
        ent = val[0] if isinstance(val, list) and val else val
        ent = _dict(ent)
        plugins[pname] = {"name": pname, "version": ent.get("version"),
                          "install": ent.get("installPath"), "enabled": enabled.get(pname) is True}
    for pname, on in enabled.items():
        if pname not in plugins:
            plugins[pname] = {"name": pname, "version": None, "install": None,
                              "enabled": on is True}
            if on is True:
                gaps.append(f"plugin {pname} is enabled but not in installed_plugins.json "
                            "(its skills/hooks/MCP cannot be enumerated)")

    # skills / agents / hooks
    skills = (_skills_in(ch / "skills", "user") + _skills_in(ch / "skills" / "synced", "synced")
              + _skills_in(root / ".claude" / "skills", "project"))
    agents = _agents_in(root / ".claude" / "agents", "project") + _agents_in(ch / "agents", "user")
    hooks = []
    for scope in ("user", "project", "local"):
        hooks += _hooks_from(settings[scope], scope)
    mcp: dict[str, dict] = {}
    cj_obj, cj_err = _load_json(cj_path)
    if cj_err:
        errors.append(cj_err)
    cj = _dict(cj_obj)
    if cj_obj is None and cj_err is None:
        gaps.append(f"no {cj_path} (user/project MCP servers and /mcp disablement unreadable)")
    pkey = _project_key(cj, root)
    proj_cj = _dict(_dict(cj.get("projects")).get(pkey)) if pkey else {}
    for n in _dict(cj.get("mcpServers")):
        mcp[n] = {"name": n, "scope": "user"}
    for n in _dict(proj_cj.get("mcpServers")):
        mcp[n] = {"name": n, "scope": "project(~/.claude.json)"}
    mj, mj_err = _load_json(root / ".mcp.json")
    if mj_err:
        errors.append(mj_err)
    for n in _dict(_dict(mj).get("mcpServers")):
        mcp[n] = {"name": n, "scope": "project(.mcp.json)"}
    for pname, pl in plugins.items():
        if not pl["enabled"]:
            continue
        inst = Path(pl["install"]) if pl["install"] else None
        if inst is None or not inst.is_dir():
            continue
        short = pname.split("@")[0]
        skills += _skills_in(inst / "skills", f"plugin:{pname}", prefix=short + ":")
        agents += _agents_in(inst / "agents", f"plugin:{pname}")
        hj, _e = _load_json(inst / "hooks" / "hooks.json")
        hooks += _hooks_from(_dict(hj), f"plugin:{pname}")
        pm, _e = _load_json(inst / ".mcp.json")
        for n in _dict(_dict(pm).get("mcpServers", pm)):
            mcp[n] = {"name": n, "scope": f"plugin:{pname}"}
    # disablement
    disabled = set(proj_cj.get("disabledMcpServers") or [])
    for s in settings.values():
        for d in s.get("deniedMcpServers") or []:
            disabled.add(d.get("serverName") if isinstance(d, dict) else d)
    for n in list(mcp):
        mcp[n]["disabled"] = n in disabled
    # claude.ai connectors
    connectors = None
    if not flags["connectors_off"]:
        ever = cj.get("claudeAiMcpEverConnected")
        if isinstance(ever, list):
            connectors = [c for c in ever if c not in disabled]
    return {"settings": settings, "enabled_plugins": enabled, "overrides": overrides,
            "env": env, "flags": flags, "deny": deny, "allow": allow, "plugins": plugins,
            "skills": skills, "agents": agents, "hooks": hooks, "mcp": mcp,
            "connectors": connectors, "disabled_mcp": sorted(d for d in disabled if d),
            "claude_json": cj, "claude_json_path": cj_path, "project_key": pkey,
            "gaps": gaps, "errors": errors,
            "listing_fraction": next((settings[s]["skillListingBudgetFraction"]
                                      for s in ("local", "project", "user")
                                      if isinstance(settings[s].get("skillListingBudgetFraction"),
                                                    (int, float))), DEFAULT_BUDGET_FRACTION),
            "listing_max_desc": next((settings[s]["skillListingMaxDescChars"]
                                      for s in ("local", "project", "user")
                                      if isinstance(settings[s].get("skillListingMaxDescChars"),
                                                    int)), DEFAULT_MAX_DESC)}


def skill_mode(m: dict, sk: dict) -> str:
    """Effective listing mode of a skill: on | name-only | user-invocable-only | off."""
    if sk["scope"].startswith("plugin:"):
        return "off" if sk["dmi"] else "on"          # skillOverrides does not reach plugin skills
    mode = m["overrides"].get(sk["name"], m["overrides"].get(sk["dir"], "on"))
    if mode == "off":
        return "off"
    if sk["dmi"]:
        return "user-invocable-only"
    return mode if mode in ("name-only", "user-invocable-only") else "on"


# --------------------------------------------------------------------------- session logs
_CWD = re.compile(r'"cwd"\s*:\s*("(?:[^"\\]|\\.)*")')
_ADDED = re.compile(r"additionalDirectories|added director|/add-dir", re.I)


def _norm_path(p: str) -> str:
    return p.replace("\\", "/").rstrip("/").lower()


def _cwd_in_repo(line: str, rootn: str) -> bool:
    m = _CWD.search(line)
    if not m:
        return False
    try:
        c = _norm_path(json.loads(m.group(1)))
    except ValueError:
        return False
    return c == rootn or c.startswith(rootn + "/")


def _session_state(f: Path, root: Path) -> "tuple[bool, bool]":
    """-> (cwd_entered_repo, names_repo_as_added_dir). Real records carry `cwd`; a session started in
    a parent folder and moved with /cd shows the repo path in `cwd` on its later records."""
    rootn, entered, added = _norm_path(str(root)), False, False
    needle = rootn.split("/")[-1]
    try:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if not entered and '"cwd"' in ln and _cwd_in_repo(ln, rootn):
                    entered = True
                if not added and _ADDED.search(ln) and needle in ln.lower() and rootn in _norm_path(ln.replace("\\\\", "\\")):
                    added = True
                if entered and added:
                    break
    except OSError:
        pass
    return entered, added


def usage_dirs(root: Path, ch: Path) -> "tuple[Path, list]":
    """The repo's own log dir plus ancestor-start and descendant-start dirs, matched case-insensitively
    (the drive letter's case varies: D-- vs d--). Sessions started elsewhere and /cd'd in are NOT
    reachable without reading every project dir: that gap is stated, not hidden."""
    pr = ch / "projects"
    own = pr / _slug(root)
    if not pr.is_dir():
        return own, []
    want = {_slug(root).lower()} | {_slug(a).lower() for a in root.parents if str(a) != a.anchor}
    pre = _slug(root).lower() + "-"
    out = [d for d in sorted(pr.iterdir()) if d.is_dir() and (d.name.lower() in want
                                                              or d.name.lower().startswith(pre))]
    return own, out


def read_usage(root: Path, ch: Path) -> dict:
    """Per-REPO usage from this repo's session logs - never machine-wide. Besides the repo's own log
    dir, sessions started in a parent folder (or below) count when a record's `cwd` is the repo root or
    under it. A session that merely names the repo as an added directory cannot be attributed from the
    log shape: it is counted in `unattributed` and withholds the vouch. Best effort over a format that
    is not a contract: unreadable lines are counted, not guessed."""
    d, dirs = usage_dirs(root, ch)
    use = {"dir": str(d), "sessions": 0, "skills": {}, "agents": {}, "mcp_tools": set(),
           "hooks": {}, "bad_lines": 0, "found": bool(dirs), "unreadable": 0,
           "skills_tool": {}, "skills_slash": {}, "slash_deduped": 0,
           "first_day": "", "last_day": "", "_pending": {},
           "scanned_dirs": [str(x) for x in dirs], "from_other_dirs": 0, "unattributed": 0}
    files = []
    for x in dirs:
        for f in sorted(x.glob("*.jsonl")):
            if x.name.lower() == d.name.lower():
                files.append(f)
                continue
            entered, added = _session_state(f, root)
            if entered:
                files.append(f)
                use["from_other_dirs"] += 1
            elif added:
                use["unattributed"] += 1
    for f in files:
        use["sessions"] += 1
        use["_pending"] = {}
        try:
            fh = f.open(encoding="utf-8", errors="replace")
        except OSError:
            use["unreadable"] += 1
            continue
        with fh:
            for ln in fh:
                tm = _TS.search(ln)
                if tm:
                    day = tm.group(1)
                    use["first_day"] = min(use["first_day"] or day, day)
                    use["last_day"] = max(use["last_day"], day)
                st = ln.strip()
                if st and not (st[0] == "{" and st[-1] == "}"):
                    use["bad_lines"] += 1           # truncated/garbled, even if it names nothing
                    continue
                if ('"tool_use"' not in ln and "hook" not in ln.lower()
                        and "<command-name>" not in ln and not _HUMAN.search(ln)):
                    continue
                try:
                    obj = json.loads(ln)
                except ValueError:
                    use["bad_lines"] += 1
                    continue
                _slash_usage(obj, use)
                _walk_usage(obj, use)
    use.pop("_pending", None)
    return use


_TS = re.compile(r'"timestamp"\s*:\s*"(\d{4}-\d\d-\d\d)')
_HUMAN = re.compile(r'"kind"\s*:\s*"human"')
_SLASH = re.compile(r"\A\s*<command-message>[^<]*</command-message>\s*<command-name>/?([^<\s]+)</command-name>"
                    r"(?:\s*<command-args>(.*?)</command-args>)?", re.S)


def _slash_usage(o: dict, use: dict) -> None:
    """Operator-typed `/skill args` is logged as a TOP-LEVEL user record whose string content is
    `<command-message>x</command-message>\n<command-name>/x</command-name>\n<command-args>..`
    (no tool_use). Anchored to the record: the same text quoted inside a tool result, an attachment
    or an api-request blob is not a use. The model then often re-loads the skill with a Skill tool
    call carrying the same args - one action, so that call is absorbed (counted once). A pending
    slash is forgotten at the next human turn."""
    if not isinstance(o, dict) or o.get("type") != "user":
        return
    c = _dict(o.get("message")).get("content")
    mt = _SLASH.match(c) if isinstance(c, str) else None
    if mt:
        nm, args = mt.group(1), (mt.group(2) or "").strip()
        use["skills_slash"][nm] = use["skills_slash"].get(nm, 0) + 1
        use["skills"][nm] = use["skills"].get(nm, 0) + 1
        use["_pending"][nm] = args
    elif _dict(o.get("origin")).get("kind") == "human":
        use["_pending"].clear()


def _walk_usage(o: object, use: dict) -> None:
    if isinstance(o, dict):
        if o.get("type") == "tool_use":
            nm, inp = str(o.get("name", "")), _dict(o.get("input"))
            if nm == "Skill" and inp.get("skill"):
                sk = inp["skill"]
                pend = use.get("_pending", {})
                if sk in pend and str(inp.get("args") or "").strip() == pend[sk]:
                    del pend[sk]                    # the same action the slash line already counted
                    use["slash_deduped"] += 1
                else:
                    use["skills"][sk] = use["skills"].get(sk, 0) + 1
                use["skills_tool"][sk] = use["skills_tool"].get(sk, 0) + 1
            elif nm in ("Task", "Agent") and inp.get("subagent_type"):
                use["agents"][inp["subagent_type"]] = use["agents"].get(inp["subagent_type"], 0) + 1
            elif nm.startswith("mcp__"):
                use["mcp_tools"].add(nm)
        hn = o.get("hookName") or o.get("hook_name")
        if isinstance(hn, str):
            use["hooks"][hn] = use["hooks"].get(hn, 0) + 1
        for v in o.values():
            if isinstance(v, (dict, list)):
                _walk_usage(v, use)
    elif isinstance(o, list):
        for v in o:
            _walk_usage(v, use)


# --------------------------------------------------------------------------- audit
def listing_budget(m: dict, usage: dict, window: int, only: "set | None" = None,
                   listing_chars: "int | None" = None) -> dict:
    """Skill-listing headroom. Skills in `on` mode cost name + capped description; `name-only`
    costs the name. When over budget, descriptions drop least-invoked-first (ties: longest first,
    then name) - the documented eviction order. `only` restricts to a subset (projection)."""
    budget = int(window * m["listing_fraction"])
    cap = m["listing_max_desc"]
    rows = []
    for sk in m["skills"]:
        if only is not None and sk["name"] not in only:
            continue
        mode = skill_mode(m, sk)
        if mode in ("off", "user-invocable-only"):
            continue
        desc = "" if mode == "name-only" else sk["description"][:cap]
        cost = len(sk["name"]) + (len(desc) + 4 if desc else 0) + 3        # "- name: desc\n"
        uses = usage["skills"].get(sk["name"], 0) + (
            usage["skills"].get(sk["dir"], 0) if sk["dir"] != sk["name"] else 0)
        rows.append({"name": sk["name"], "scope": sk["scope"], "chars": cost, "uses": uses,
                     "name_only": mode == "name-only"})
    used = sum(r["chars"] for r in rows)
    if listing_chars is not None and only is None:
        used = int(listing_chars)               # the client's own figure (/context or /doctor)
    dropped = []
    if used > budget:
        left = used
        for r in sorted(rows, key=lambda r: (r["uses"], -r["chars"], r["name"])):
            if left <= budget:
                break
            if r["name_only"]:
                continue
            left -= max(0, r["chars"] - len(r["name"]) - 3)       # description gone, name stays
            dropped.append(r["name"])
    in_use = {r["name"] for r in rows if r["uses"] > 0}
    guarded = [n for n in dropped if n in in_use or n.split(":")[-1] in PROTECTED_SKILLS]
    return {"budget_chars": budget, "used_chars": used, "headroom": budget - used,
            "listed": len(rows), "over_budget": used > budget,
            "at_risk": [n for n in dropped if n not in guarded], "client_would_drop_in_use": guarded,
            "context_window": window, "fraction": m["listing_fraction"], "rows": rows,
            "used_source": ("client-reported" if listing_chars is not None and only is None
                            else "estimated"),
            "assumptions": (f"estimated budget = {m['listing_fraction']:.0%} x an assumed "
                            f"{window}-token context window (a guess, and it may mix tokens with "
                            "chars); the client's own limit is not read")}


PROTECTED_SKILLS = frozenset({"gitos"})   # the audit runs inside gitos: never a removal candidate


def vouch_usage(usage: dict) -> dict:
    """Can a ZERO be trusted? Only if logs exist, every log opened, every relevant line parsed.
    The span is stated so 'zero' reads as 'zero across N sessions over D..D2', not 'zero in the
    one log that loaded'. When it cannot vouch it says why; the audit then proposes no removal."""
    why = []
    if not usage["found"]:
        why.append("no session-log directory for this repo")
    elif usage["sessions"] == 0:
        why.append("no session logs")
    if usage["unreadable"]:
        why.append(f"{usage['unreadable']} log file(s) unreadable")
    if usage["bad_lines"]:
        why.append(f"{usage['bad_lines']} log line(s) unparseable")
    if usage.get("unattributed"):
        why.append(f"{usage['unattributed']} session(s) name this repo as an added directory but their "
                   "cwd never entered it, so their skill use cannot be attributed")
    span = (f"{usage['sessions']} session(s), {usage['first_day']}..{usage['last_day']}"
            if usage["first_day"] else f"{usage['sessions']} session(s), span unknown")
    nd = len(usage.get("scanned_dirs") or [])
    span += (f"; scanned {nd} log dir(s): " + ", ".join(Path(x).name for x in usage["scanned_dirs"])
             + f" ({usage.get('from_other_dirs', 0)} session(s) from parent/child-started dirs, kept by cwd)")
    if not why and not usage["first_day"]:
        why.append("logs carry no timestamps, so their span cannot be stated")
    return {"ok": not why, "why": why, "span": span}


def removal_plan(m: dict, usage: dict, lb: dict, vouch: dict) -> dict:
    """Removal candidates = vouched-unused x listing cost, biggest first. This dict IS the contract
    `audit --json` hands the operator-confirmation popup (WO-063): the popup may offer only what is
    listed here. A skill with ANY observed use, and `gitos`, never appear; with usage not
    established, nothing does. A standalone skill is switched off via skillOverrides; a plugin's
    skills cannot be split, so a plugin is a candidate only when ALL its listed skills are unused,
    and the mechanism is enabledPlugins for the whole plugin."""
    used = set(usage["skills"])
    plan = {"vouched": vouch["ok"], "span": vouch["span"], "why_not": vouch["why"],
            "candidates": [], "reclaim_chars": 0, "sufficient": None, "still_over_by": 0,
            "over_budget": lb["over_budget"], "protected": sorted(PROTECTED_SKILLS)}
    if not vouch["ok"]:
        return plan
    by_name = {r["name"]: r for r in lb["rows"]}
    uses0 = {"slash": 0, "tool": 0, "total": 0}

    def is_used(sk: dict) -> bool:
        return sk["name"] in used or sk["dir"] in used

    def is_protected(sk: dict) -> bool:
        return sk["name"].split(":")[-1] in PROTECTED_SKILLS or sk["dir"] in PROTECTED_SKILLS

    cands, plugins = [], {}
    for sk in m["skills"]:
        r = by_name.get(sk["name"])
        if r is None:
            continue
        if sk["scope"].startswith("plugin:"):
            plugins.setdefault(sk["scope"], []).append((sk, r))
        elif not is_used(sk) and not is_protected(sk):
            cands.append({"name": sk["name"], "scope": sk["scope"], "mechanism": "skillOverrides",
                          "desc_chars": r["chars"], "uses": dict(uses0), "span": vouch["span"],
                          "vouched": True,
                          "reason": f"Never invoked ({vouch['span']}) and its listing entry costs "
                                    f"{r['chars']} chars."})
    for scope, members in plugins.items():
        if any(is_used(sk) or is_protected(sk) for sk, _ in members):
            continue
        chars = sum(r["chars"] for _, r in members)
        cands.append({"name": scope[len("plugin:"):], "scope": scope, "mechanism": "enabledPlugins",
                      "desc_chars": chars, "skill_count": len(members), "uses": dict(uses0),
                      "span": vouch["span"], "vouched": True,
                      "reason": f"None of its {len(members)} skill(s) was invoked ({vouch['span']}); "
                                f"disabling the whole plugin reclaims {chars} listing chars."})
    cands.sort(key=lambda c: (-c["desc_chars"], c["name"]))
    plan["candidates"] = cands
    plan["reclaim_chars"] = sum(c["desc_chars"] for c in cands)
    if lb["over_budget"]:
        over = -lb["headroom"]
        plan["sufficient"] = plan["reclaim_chars"] >= over
        plan["still_over_by"] = max(0, over - plan["reclaim_chars"])
    return plan


def tool_search_state(m: dict) -> dict:
    v = str(m["env"].get("ENABLE_TOOL_SEARCH", "")).strip().lower()
    forced_off = []
    if str(m["env"].get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "")).strip() not in ("", "0", "false"):
        forced_off.append("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS")
    if "ToolSearch" in m["deny"]:
        forced_off.append("permissions.deny ToolSearch")
    if forced_off:
        mode, text = "off", "tool search forced off by " + ", ".join(forced_off) + ": definitions load upfront"
    elif v in ("", "true"):
        mode, text = "deferring", "tool search ON (default): only names load at start, definitions on demand"
    elif v == "false":
        mode, text = "upfront", "ENABLE_TOOL_SEARCH=false: ALL definitions load upfront"
    elif v.startswith("auto"):
        mode, text = "auto", (f"ENABLE_TOOL_SEARCH={v}: loads upfront while definitions stay under "
                              "the threshold (default 10% of window), defers past it")
    else:
        mode, text = "unknown", f"ENABLE_TOOL_SEARCH={v!r} is not a recognised value"
    return {"mode": mode, "value": v or "(unset)", "text": text + " (model gating not checkable here)"}


def audit(root: Path, home: Path, ch: Path, cj_path: Path, window: int = DEFAULT_CONTEXT_WINDOW,
          listing_chars: "int | None" = None) -> dict:
    decl, derr = load_declaration(home)
    m = scan_machine(root, ch, cj_path)
    usage = read_usage(root, ch)
    d = declared(decl) if decl else None
    lb = listing_budget(m, usage, window, listing_chars=listing_chars)
    proj = None
    if d:
        keep = d["skills"] | d["base_skills"]
        proj = listing_budget(m, usage, window,
                              {s["name"] for s in m["skills"] if s["name"] in keep
                               or s["scope"].startswith("plugin:")})
    # tool definitions: lower bound
    observed_by_server: dict[str, set] = {}
    for t in usage["mcp_tools"]:
        parts = t.split("__")
        observed_by_server.setdefault(parts[1] if len(parts) > 2 else t, set()).add(t)
    declared_counts = {e["name"]: e["tools"] for e in (decl or {}).get("mcp") or []
                       if isinstance(e, dict) and isinstance(e.get("tools"), int)}
    live = [n for n, s in m["mcp"].items() if not s["disabled"]]
    count = 0
    for n in live:
        count += max(declared_counts.get(n, 0), len(observed_by_server.get(n, ())))
    ts = tool_search_state(m)
    used_skills = set(usage["skills"])
    visible_names = {s["name"] for s in m["skills"]} | {s["dir"] for s in m["skills"]}
    vouch = vouch_usage(usage)
    plan = removal_plan(m, usage, lb, vouch)
    skills_unused = sorted(c["name"] for c in plan["candidates"] if c["mechanism"] == "skillOverrides")
    used_undeclared = sorted(s for s in used_skills if d and s not in d["skills"]
                             and s not in d["base_skills"] and ":" not in s
                             and (s in usage["skills_tool"] or s in visible_names))
    hooks_by_scope: dict[str, int] = {}
    for h in m["hooks"]:
        hooks_by_scope[h["scope"]] = hooks_by_scope.get(h["scope"], 0) + 1
    broadcast = [h for h in m["hooks"] if h["scope"] == "user" or h["scope"].startswith("plugin:")]
    proposals = []
    for s in used_undeclared:
        proposals.append(f"declare skill '{s}' (invoked {usage['skills'][s]}x in this repo's logs)")
    if d and vouch["ok"]:
        for s in sorted(d["skills"] - used_skills - PROTECTED_SKILLS):
            proposals.append(f"skill '{s}' is declared but never invoked here "
                             f"({vouch['span']}): keep, or drop it")
    if not vouch["ok"]:
        proposals.append("usage not established (" + "; ".join(vouch["why"]) + "): no skill is "
                         "proposed for removal, because an unmeasured zero is not a zero")
    for c in plan["candidates"][:20]:
        if c["mechanism"] == "enabledPlugins":
            proposals.append(f"plugin '{c['name']}' costs {c['desc_chars']} listing chars and none of its "
                             f"skills was invoked ({vouch['span']}): candidate for enabledPlugins false")
        else:
            proposals.append(f"skill '{c['name']}' costs {c['desc_chars']} listing chars and has 0 observed "
                             f"uses ({vouch['span']}): candidate for skillOverrides off")
    if plan["candidates"] and plan["sufficient"] is False:
        proposals.append(f"removing EVERY candidate above reclaims {plan['reclaim_chars']} chars and the "
                         f"listing is still over the estimated budget by {plan['still_over_by']}: skill-by-skill pruning "
                         "will not get there; the lever is plugin-level (disable whole plugins - "
                         "skillOverrides cannot split them)")
    elif lb["over_budget"] and not plan["candidates"] and vouch["ok"]:
        proposals.append("listing is over the estimated budget and no loose skill is a vouched candidate: the lever is "
                         "plugin-level (disable whole plugins - skillOverrides cannot split them)")
    rep = {
        "repo": str(root), "declaration": ("none" if decl is None else
                                           "adopted" if is_adopted(decl) else "present-not-adopted"),
        "declaration_error": derr,
        "usage": {"sessions": usage["sessions"], "log_dir": usage["dir"], "found": usage["found"],
                  "scanned_dirs": usage["scanned_dirs"], "from_other_dirs": usage["from_other_dirs"],
                  "unattributed": usage["unattributed"],
                  "skills": usage["skills"], "agents": usage["agents"], "hooks": usage["hooks"],
                  "bad_lines": usage["bad_lines"], "unreadable": usage["unreadable"],
                  "skills_by_tool": usage["skills_tool"], "skills_by_slash": usage["skills_slash"],
                  "slash_deduped": usage["slash_deduped"], "span": vouch["span"],
                  "vouched": vouch["ok"], "not_vouched_because": vouch["why"]},
        "removal": plan,
        "skills": {"visible": len(m["skills"]), "listed": lb["listed"], "unused_here": skills_unused,
                   "used_undeclared": used_undeclared},
        "listing_budget": {k: v for k, v in lb.items() if k != "rows"},
        "listing_budget_if_declared_only": ({k: v for k, v in proj.items() if k != "rows"}
                                            if proj else None),
        "tool_definitions": {"lower_bound": count, "band": list(TOOL_BAND),
                             "in_band": TOOL_BAND[0] <= count <= TOOL_BAND[1],
                             "over_band": count > TOOL_BAND[1],
                             "servers_live": sorted(live),
                             "servers_disabled": sorted(n for n, s in m["mcp"].items() if s["disabled"]),
                             "connectors": m["connectors"]},
        "tool_search": ts,
        "plugins_enabled": sorted(n for n, p in m["plugins"].items() if p["enabled"]),
        "claude_ai": m["flags"],
        "hooks": {"by_scope": hooks_by_scope,
                  "broadcast_to_every_repo": [f"{h['scope']}:{h['event']}:{h['command'][:60]}"
                                              for h in broadcast],
                  "fired_in_this_repo": usage["hooks"]},
        "agents": [{k: a.get(k) for k in ("name", "scope", "model", "effort", "tools", "skills",
                                          "mcpServers", "hooks") if a.get(k) is not None}
                   for a in m["agents"]],
        "agents_invoked": usage["agents"],
        "proposals": proposals, "gaps": m["gaps"], "errors": m["errors"], "limits": list(LIMITS),
    }
    return rep


def render_audit(r: dict) -> str:
    L = [f"harness audit - {r['repo']}", f"declaration: {r['declaration']}"]
    if r["declaration_error"]:
        L.append(f"  !! {r['declaration_error']}")
    u = r["usage"]
    L.append(f"usage (THIS repo only): {u['sessions']} session log(s); scanned: "
             + (", ".join(u["scanned_dirs"]) or u["log_dir"])
             + ("" if u["found"] else "  [no log dir: usage counts are zero, not measured]"))
    ts_, ss_ = sum(u["skills_by_tool"].values()), sum(u["skills_by_slash"].values())
    L.append(f"  skill uses counted: {ts_} by Skill tool call, {ss_} by operator slash command, "
             f"{u['slash_deduped']} tool call(s) absorbed as the same action as a slash command; "
             f"span {u['span']}")
    L.append("  zero-use evidence: " + ("vouched" if u["vouched"] else
             "NOT ESTABLISHED (" + "; ".join(u["not_vouched_because"]) + ") - no removal proposed"))
    b = r["listing_budget"]
    L.append(f"skill listing: {b['used_chars']} chars "
             f"({'client-reported' if b['used_source'] == 'client-reported' else 'estimated'}) vs an "
             f"ESTIMATED budget of {b['budget_chars']} chars; {b['listed']} of {r['skills']['visible']} "
             f"visible skills listed; estimated headroom {b['headroom']}"
             + ("  (estimated: over)" if b["over_budget"] else ""))
    L.append(f"  assumptions: {b['assumptions']}")
    if b["at_risk"]:
        L.append("  the client may drop these descriptions first (its least-invoked-first order, "
                 "estimated; not advice and not a removal candidate): " + ", ".join(b["at_risk"]))
    if b["client_would_drop_in_use"]:
        L.append("  the client's order would also reach in-use/protected skill(s) "
                 + ", ".join(b["client_would_drop_in_use"]) + ": that is the client's behaviour, "
                 "not a candidate")
    p = r["listing_budget_if_declared_only"]
    if p:
        L.append(f"  if only declared+baseline skills were visible (estimated): {p['used_chars']} chars, "
                 f"headroom {p['headroom']}, client may drop: {', '.join(p['at_risk']) or 'none'}")
    t = r["tool_definitions"]
    band = "OVER the 30-50 band" if t["over_band"] else ("inside the band" if t["in_band"]
                                                         else "below the 30-50 band")
    L.append(f"tool definitions (lower bound): {t['lower_bound']} from MCP servers "
             f"{t['servers_live'] or 'none'} - {band}; disabled: {t['servers_disabled'] or 'none'}")
    L.append(f"tool search: {r['tool_search']['text']}")
    L.append(f"claude.ai sync: skills {'OFF' if r['claude_ai']['sync_skills_off'] else 'on/unset'}, "
             f"plugins {'OFF' if r['claude_ai']['sync_plugins_off'] else 'on/unset'}, connectors "
             f"{'OFF' if r['claude_ai']['connectors_off'] else 'on/unset'}")
    L.append(f"plugins enabled: {len(r['plugins_enabled'])} {r['plugins_enabled']}")
    h = r["hooks"]
    L.append(f"hooks by scope: {h['by_scope'] or 'none'}; reaching EVERY repo (user/plugin scope): "
             f"{len(h['broadcast_to_every_repo'])}")
    for x in h["broadcast_to_every_repo"]:
        L.append(f"    - {x}")
    L.append(f"subagent definitions visible: {len(r['agents'])}")
    for a in r["agents"]:
        L.append("    - " + json.dumps(a, ensure_ascii=False))
    if r["proposals"]:
        L.append("proposed harness.json edits:")
        L += [f"  - {x}" for x in r["proposals"]]
    for k in ("gaps", "errors"):
        for x in r[k]:
            L.append(f"{k[:-1]}: {x}")
    L.append("limits (reported, not worked around):")
    L += [f"  - {x}" for x in r["limits"]]
    return "\n".join(L)


# --------------------------------------------------------------------------- drift
def drift(root: Path, home: Path, ch: Path, cj_path: Path) -> dict:
    """-> {applicable, adopted, findings[], notices[], error}. Findings gate; notices do not."""
    decl, derr = load_declaration(home)
    out = {"applicable": decl is not None or derr is not None, "adopted": False,
           "findings": [], "notices": [], "error": derr}
    if derr:
        out["findings"].append({"kind": "declaration-unreadable",
                                "finding": f"{HARNESS_FILENAME}: {derr} -> repair or remove the file"})
        return out
    if decl is None:
        return out
    out["adopted"] = is_adopted(decl)
    if not out["adopted"]:
        return out
    m = scan_machine(root, ch, cj_path)
    d = declared(decl)
    F = out["findings"]

    def add(kind: str, what: str, fix: str) -> None:
        F.append({"kind": kind, "item": what, "finding": f"{what} -> {fix}"})

    # skills (user + project scope; plugin skills are judged at plugin level)
    for sk in m["skills"]:
        if sk["scope"].startswith("plugin:") or skill_mode(m, sk) == "off":
            continue
        if sk["name"] not in d["skills"] and sk["name"] not in d["base_skills"]:
            add("undeclared-skill", f"{sk['scope']} skill '{sk['name']}' is visible but undeclared",
                "declare it in harness.json, or run `harness sync` to override it off")
    vis = {s["name"] for s in m["skills"]} | {s["dir"] for s in m["skills"]}
    lib = Path(decl["library"]) if decl.get("library") else None
    for e in decl.get("skills") or []:
        e = e if isinstance(e, dict) else {"name": e}
        n = e.get("name")
        sk = next((s for s in m["skills"] if s["name"] == n or s["dir"] == n), None)
        if sk is None or skill_mode(m, sk) == "off":
            add("declared-skill-missing", f"declared skill '{n}' is not visible in this repo",
                "run `harness sync` (library copy) or fix the declaration")
            continue
        if e.get("sha256") and sk["scope"] == "project":
            cur = dir_sha(Path(sk["path"]))
            if cur != e["sha256"]:
                add("skill-pin-moved", f"skill '{n}' content differs from its pinned sha256",
                    "review the change, then re-pin (`harness update --approve`) or `harness sync`")
        if lib and e.get("source") == "library" and e.get("sha256"):
            ls = dir_sha(lib / n)
            if ls and ls != e["sha256"]:
                out["notices"].append(f"library skill '{n}' changed upstream of its pin "
                                      f"(update channel: {e.get('update', 'review')})")
    # plugins
    for pname, pl in sorted(m["plugins"].items()):
        if not pl["enabled"] or pname in d["plugins"] or pname in d["base_plugins"]:
            continue
        user_on = m["settings"]["user"].get("enabledPlugins", {}).get(pname) is True \
            if isinstance(m["settings"]["user"].get("enabledPlugins"), dict) else False
        proj_on = any(_dict(m["settings"][s].get("enabledPlugins")).get(pname) is True
                      for s in ("project", "local"))
        if proj_on:
            add("undeclared-plugin", f"plugin '{pname}' is enabled by this repo but undeclared",
                "declare it or disable it")
        else:
            add("plugin-outside-baseline",
                f"user-scope plugin '{pname}' is enabled outside the baseline and undeclared"
                + ("" if user_on else " (via managed/other scope)"),
                "add it to the baseline, declare it here, or run `harness sync` to set it false locally")
    for e in decl.get("plugins") or []:
        e = e if isinstance(e, dict) else {"name": e}
        pl = m["plugins"].get(e.get("name"))
        if pl is None or not pl["enabled"]:
            add("declared-plugin-missing", f"declared plugin '{e.get('name')}' is not installed/enabled",
                "install/enable it, or run `harness sync`, or fix the declaration")
            continue
        if e.get("version") and pl["version"] and e["version"] != pl["version"]:
            chan = e.get("update", "review")
            msg = f"plugin '{e['name']}' version {e['version']} -> {pl['version']}"
            if chan == "auto":
                out["notices"].append(msg + " (update: auto; recorded by `harness update --apply`)")
            elif chan == "pinned":
                add("pin-moved", msg + " but the entry is pinned", "restore the pinned version or change the declaration")
            else:
                add("pin-moved", msg + " (update: review)", "review it, then `harness update --approve`")
    # MCP + connectors
    for n, s in sorted(m["mcp"].items()):
        if not s["disabled"] and n not in d["mcp"]:
            add("undeclared-mcp", f"MCP server '{n}' ({s['scope']}) is live but undeclared",
                "declare it, or run `harness sync` to disable it for this project")
    for n in m["connectors"] or []:
        if n not in d["mcp"]:
            add("undeclared-connector", f"claude.ai connector '{n}' is live but undeclared",
                "declare it, or set disableClaudeAiConnectors via `harness sync`")
    ca = _dict(decl.get("claude_ai"))
    for flag, key, label in (("sync_skills_off", "sync_skills", "syncClaudeAiSkills"),
                             ("sync_plugins_off", "sync_plugins", "syncClaudeAiPlugins")):
        if ca.get(key) is False and not m["flags"][flag]:
            add("sync-not-off", f"{label} is on/unset for this repo but the declaration says off",
                f"run `harness sync` (writes {label}: false to settings.local.json)")
    if ca.get("connectors") == [] and not m["flags"]["connectors_off"]:
        add("connectors-not-off", "claude.ai connectors are on but the declaration allows none",
            "run `harness sync` (writes disableClaudeAiConnectors: true to settings.local.json)")
    # hooks
    allowed = [h for h in d["hooks"] + [x if isinstance(x, dict) else {"match": x}
                                         for x in d["base_hooks"]]]
    for h in m["hooks"]:
        if not any(a.get("match", "") and a["match"] in h["command"]
                   and a.get("event", h["event"]) == h["event"] for a in allowed):
            bc = " (user/plugin scope: fires in EVERY repo on this machine)" \
                if h["scope"] == "user" or h["scope"].startswith("plugin:") else ""
            add("undeclared-hook", f"{h['scope']} hook {h['event']} '{h['command'][:70]}' is undeclared{bc}",
                "declare it under hooks (event + a substring `match` of its command)")
    # agents
    for a in m["agents"]:
        if a["scope"] == "project" and a["name"] not in d["agents"]:
            add("undeclared-agent", f"project subagent '{a['name']}' is not declared",
                "declare it under agents (WO-055 writes definitions; this file only declares them)")
    for e in decl.get("agents") or []:
        e = e if isinstance(e, dict) else {"name": e}
        a = next((x for x in m["agents"] if x["name"] == e.get("name")), None)
        if a is None:
            add("declared-agent-missing", f"declared subagent '{e.get('name')}' has no definition",
                "restore the definition or fix the declaration")
        elif e.get("sha256") and a["sha256"] != e["sha256"]:
            add("agent-changed", f"subagent '{e['name']}' definition differs from its pinned sha256",
                "review the change, then re-pin sha256 in harness.json")
    for g in m["gaps"]:
        out["notices"].append("gap: " + g)
    return out


# --------------------------------------------------------------------------- offer
def offer(home: Path) -> "str | None":
    decl, derr = load_declaration(home)
    if derr:
        return f"harness: {HARNESS_FILENAME} is unreadable ({derr}); repair it or remove it."
    if decl is None:
        return ("harness: this repo declares no harness. `python <skill>/scripts/harness.py audit` "
                "measures skill-listing crowding and tool-definition load (read-only, writes nothing).")
    lc = decl.get("last_checked")
    try:
        age = (now_utc() - datetime.fromisoformat(str(lc).replace("Z", "+00:00"))).days if lc else None
    except ValueError:
        age = None
    if is_adopted(decl) and (age is None or age >= STALE_CHECK_DAYS):
        return ("harness: pinned skills/plugins not checked in "
                f"{'ever' if age is None else str(age) + ' days'}; `/gitos upgrade` runs the harness step.")
    return None


def measure_summary(root: Path, home: Path, ch: Path, cj_path: Path,
                    window: int = DEFAULT_CONTEXT_WINDOW, listing_chars: "int | None" = None) -> str:
    """The upgrade's few-line budget finding. Read-only, and it can never fail the caller.

    Asks whether the DECLARED-OR-UNDECLARED load is too much, which drift cannot: a repo with no
    drift at all can still sit multiples over the listing budget. Any trouble becomes a one-line
    `not measured (reason)`; nothing here raises.
    """
    try:
        if not ch.is_dir():
            return f"harness budget: not measured (no Claude home at {ch})"
        r = audit(root, home, ch, cj_path, window, listing_chars)
        b, t, u = r["listing_budget"], r["tool_definitions"], r["usage"]
        lines = [f"harness budget: skill listing {b['used_chars']} chars "
                 f"({'client-reported' if b['used_source'] == 'client-reported' else 'estimated'}) vs "
                 f"an ESTIMATED budget of {b['budget_chars']} chars, estimated headroom {b['headroom']}"
                 + ("  (estimated: over)" if b["over_budget"] else "")
                 + f"; tool definitions >= {t['lower_bound']} (lower bound)"]
        if b["at_risk"]:
            lines.append("  the client may drop these descriptions first (estimated, not advice): "
                         + ", ".join(b["at_risk"][:5]) + (", ..." if len(b["at_risk"]) > 5 else ""))
        if b["client_would_drop_in_use"]:
            lines.append("  the client's order would also reach in-use/protected skill(s) "
                         + ", ".join(b["client_would_drop_in_use"][:5]) + ": client behaviour, not a candidate")
        lines.append(f"  estimated: {b['assumptions']}; pass --listing-chars N from /context or /doctor to "
                     "replace the estimate. The tool count misses what no log shows"
                     + ("" if u["found"] else "; no session logs found, so the drop order is "
                        "not usage-ranked"))
        if r["declaration_error"]:
            lines.append(f"  declaration unreadable: {r['declaration_error']}")
        return chr(10).join(lines)
    except Exception as e:  # a measurement must never abort an upgrade
        return f"harness budget: not measured ({type(e).__name__}: {e})"


# --------------------------------------------------------------------------- update (auto/review)
def update(root: Path, home: Path, ch: Path, cj_path: Path, apply: bool, approve: "list | None") -> dict:
    """The auto/review pass. Report-only; with --apply it records `auto` plugin versions and
    `last_checked` in harness.json (the repo's own file). `--approve NAME` moves a `review`
    library skill's pin to the library's current content. Nothing here touches settings."""
    decl, derr = load_declaration(home)
    rep = {"notices": [], "diffs": {}, "changes": [], "error": derr}
    if decl is None:
        return rep
    m = scan_machine(root, ch, cj_path)
    lib = Path(decl["library"]) if decl.get("library") else None
    for e in decl.get("plugins") or []:
        if not isinstance(e, dict):
            continue
        pl = m["plugins"].get(e.get("name"))
        if pl and pl["version"] and e.get("version") != pl["version"]:
            chan = e.get("update", "review")
            rep["notices"].append(f"plugin {e['name']}: {e.get('version')} -> {pl['version']} ({chan})")
            if chan == "auto":
                rep["changes"].append(("plugin-version", e["name"], pl["version"]))
                e["version"] = pl["version"]
    for e in decl.get("skills") or []:
        if not isinstance(e, dict) or e.get("source") != "library":
            continue
        if not lib:
            rep["notices"].append(f"skill {e['name']}: no library path declared - no update source")
            continue
        src = lib / e["name"]
        new = dir_sha(src)
        if new is None:
            rep["notices"].append(f"skill {e['name']}: not found in library - no update source")
            continue
        if e.get("sha256") and new != e["sha256"]:
            chan = e.get("update", "review")
            local = root / ".claude" / "skills" / e["name"]
            rep["diffs"][e["name"]] = _tree_diff(local, src)
            rep["notices"].append(f"skill {e['name']}: library content moved ({chan})")
            if chan == "pinned":
                continue
            if approve and e["name"] in approve:
                rep["changes"].append(("skill-pin", e["name"], new))
                e["sha256"] = new
    if apply:
        decl["last_checked"] = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_json(home / HARNESS_FILENAME, decl)
    return rep


def _tree_diff(a: Path, b: Path, limit: int = 80) -> list:
    out: list[str] = []
    names = sorted({p.relative_to(t).as_posix() for t in (a, b) if t.is_dir()
                    for p in t.rglob("*") if p.is_file()})
    for n in names:
        x = (_read_text(a / n) or "").splitlines()
        y = (_read_text(b / n) or "").splitlines()
        out += list(difflib.unified_diff(x, y, f"pinned/{n}", f"library/{n}", lineterm=""))
    return out[:limit]


# --------------------------------------------------------------------------- sync (WRITES)
def _write_json(p: Path, obj: object) -> None:
    """Atomic, LF-only write. Never a text-mode round trip (that converts newlines on Windows)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".harness-tmp")
    tmp.write_bytes((json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    os.replace(tmp, p)


def plan_sync(root: Path, home: Path, ch: Path, cj_path: Path, confirmed: "dict | None" = None,
              accept: "frozenset | set" = frozenset()) -> dict:
    """The exact write surface, computed without writing. Owns ONLY:
      - <root>/.claude/skills/<declared library skill>/            (copy, pin-gated)
      - <root>/.claude/settings.local.json: enabledPlugins, skillOverrides, permissions.allow,
        syncClaudeAiSkills, syncClaudeAiPlugins, disableClaudeAiConnectors
      - <claude-json> projects[<root>].disabledMcpServers          (the `/mcp` field)
    Any other key is never read-modified-written differently from how it was found.
    `confirmed` (from resolve_confirmation) adds ONLY the operator-confirmed removals. `accept`
    names the claude.ai sync switches the operator ACCEPTED in the popup (e.g. "syncClaudeAiSkills").
    A switch not accepted is never written, even when the declaration says off: unasked is declined."""
    decl, derr = load_declaration(home)
    plan = {"error": derr, "refused": None, "copies": [], "local": {}, "disable_mcp": [],
            "enable_mcp": [], "proposals": [], "pins": []}
    if derr:
        plan["refused"] = derr
        return plan
    if decl is None:
        # No harness.json (the default state): ONLY operator-confirmed removals, nothing declared.
        if not confirmed or not (confirmed.get("skills") or confirmed.get("plugins")):
            plan["refused"] = "no harness.json"
            return plan
        m = scan_machine(root, ch, cj_path)
        if m["errors"]:
            plan["refused"] = "unreadable settings input: " + "; ".join(m["errors"])
            return plan
        lo = m["settings"]["local"]
        ov, ep = _dict(lo.get("skillOverrides")), _dict(lo.get("enabledPlugins"))
        so = {n: "off" for n in confirmed.get("skills", [])
              if ov.get(n) != "off" and m["overrides"].get(n) != "off"}
        pe = {n: False for n in confirmed.get("plugins", [])
              if n in m["plugins"] and m["plugins"][n]["enabled"] and ep.get(n) is not False}
        plan["local"] = {"skillOverrides_set": so, "skillOverrides_drop": [], "enabledPlugins_set": pe,
                         "permissions_allow_add": [], "scalars": {}}
        return plan
    if not is_adopted(decl):
        plan["refused"] = "harness.json is not adopted (adopted: false); nothing will be written"
        return plan
    m = scan_machine(root, ch, cj_path)
    if m["errors"]:
        plan["refused"] = "unreadable settings input: " + "; ".join(m["errors"])
        return plan
    d = declared(decl)
    keep_skills = d["skills"] | d["base_skills"]
    lib = Path(decl["library"]) if decl.get("library") else None
    local_obj = dict(m["settings"]["local"])
    want_plugins, want_over = {}, {}
    # library copies (pin-gated)
    for e in decl.get("skills") or []:
        if not isinstance(e, dict) or e.get("source") != "library":
            continue
        n = e["name"]
        if not lib or not (lib / n).is_dir():
            plan["proposals"].append(f"skill '{n}': library copy not found - cannot materialise")
            continue
        src_sha, dest = dir_sha(lib / n), root / ".claude" / "skills" / n
        if e.get("sha256") and src_sha != e["sha256"]:
            plan["proposals"].append(f"skill '{n}': library moved past its pin; "
                                     "run `harness update --approve` first")
            continue
        if dir_sha(dest) != src_sha:
            plan["copies"].append({"name": n, "src": str(lib / n), "dest": str(dest)})
        if not e.get("sha256"):
            plan["pins"].append((n, src_sha))
    # skillOverrides: user-scope undeclared -> off; declared but we left it off -> on (remove)
    ov = dict(_dict(local_obj.get("skillOverrides")))
    for sk in m["skills"]:
        if sk["scope"] == "user" and sk["name"] not in keep_skills and ov.get(sk["name"]) != "off" \
                and m["overrides"].get(sk["name"]) != "off":
            want_over[sk["name"]] = "off"
    for n in (confirmed or {}).get("skills", []):
        if ov.get(n) != "off" and m["overrides"].get(n) != "off":
            want_over[n] = "off"
    drop_over = [n for n in ov if n in d["skills"] and ov[n] == "off"]
    # enabledPlugins
    ep = dict(_dict(local_obj.get("enabledPlugins")))
    for pname, pl in m["plugins"].items():
        if pl["enabled"] and pname not in d["plugins"] and pname not in d["base_plugins"]:
            want_plugins[pname] = False
    for pname in d["plugins"]:
        pl = m["plugins"].get(pname)
        if pl and not pl["enabled"]:
            want_plugins[pname] = True
    for pname in (confirmed or {}).get("plugins", []):
        if pname in m["plugins"] and m["plugins"][pname]["enabled"]:
            want_plugins[pname] = False
    # permissions
    add_allow = [a for a in _dict(decl.get("permissions")).get("allow") or []
                 if a not in m["allow"]]
    ca = _dict(decl.get("claude_ai"))
    scalar = {}
    if ca.get("sync_skills") is False and local_obj.get("syncClaudeAiSkills") is not False \
            and "syncClaudeAiSkills" in accept:
        scalar["syncClaudeAiSkills"] = False
    if ca.get("sync_plugins") is False and local_obj.get("syncClaudeAiPlugins") is not False \
            and "syncClaudeAiPlugins" in accept:
        scalar["syncClaudeAiPlugins"] = False
    if ca.get("connectors") == [] and local_obj.get("disableClaudeAiConnectors") is not True:
        scalar["disableClaudeAiConnectors"] = True
    if ca.get("connectors"):
        plan["proposals"].append("claude_ai.connectors lists names, but disableClaudeAiConnectors is "
                                 "all-or-none: connectors stay as they are (limit reported by audit)")
    # MCP (via ~/.claude.json, not settings)
    for n, s in m["mcp"].items():
        if not s["disabled"] and n not in d["mcp"]:
            plan["disable_mcp"].append(n)
    plan["enable_mcp"] = [n for n in d["mcp"] if m["mcp"].get(n, {}).get("disabled")
                          and n in m["disabled_mcp"] and not any(
                              n in _dict(s).get("deniedMcpServers", []) for s in m["settings"].values())]
    plan["local"] = {"skillOverrides_set": want_over, "skillOverrides_drop": drop_over,
                     "enabledPlugins_set": {k: v for k, v in want_plugins.items() if ep.get(k) != v
                                            and not (v is False and m["enabled_plugins"].get(k) is False)},
                     "permissions_allow_add": add_allow, "scalars": scalar}
    # user-scope proposals (NEVER applied)
    user_ep = _dict(m["settings"]["user"].get("enabledPlugins"))
    for pname, pl in m["plugins"].items():
        if pl["enabled"] and user_ep.get(pname) is True and pname not in d["plugins"] \
                and pname not in d["base_plugins"]:
            plan["proposals"].append(f"USER SCOPE (proposal only): plugin '{pname}' is on at user "
                                     "scope outside the baseline; set it false there with the "
                                     "operator's approval")
    return plan


POPUP_MAX_Q, POPUP_MAX_OPT = 4, 4     # AskUserQuestion: 1-4 questions, 2-4 options each
KEEP_ALL = "Keep everything (no change)"


def _opt(label: str, description: str, name: "str | None" = None) -> dict:
    """A popup option holding ONLY schema keys; names map back through `label_to_name`."""
    return {"label": label, "description": description}


def _cand_label(c: dict) -> str:
    if c["mechanism"] == "enabledPlugins":
        return f"{c['name']} (plugin, {c.get('skill_count', '?')} skills, {c['desc_chars']} chars)"
    return f"{c['name']} ({c['desc_chars']} chars)"


def popup_questions(removal: dict, sync_question: bool = False) -> dict:
    """AskUserQuestion payload from `audit --json`'s `removal` block (WO-063). A plugin is ONE option
    carrying its skill count and reclaimed chars; options are filled in budget order; what does not
    fit is STATED (count + chars), never dropped. Nothing is pre-selected. The claude.ai sync switch,
    when asked, is its own single-select question."""
    cands = list(removal.get("candidates") or [])
    room = POPUP_MAX_Q - (1 if sync_question else 0)
    shown, rest = cands[:room * POPUP_MAX_OPT], cands[room * POPUP_MAX_OPT:]
    qs = []
    if shown:
        nq = -(-len(shown) // POPUP_MAX_OPT)
        base, extra = divmod(len(shown), nq)
        i = 0
        for q in range(nq):
            size = base + (1 if q < extra else 0)
            opts = []
            for c in shown[i:i + size]:
                label = _cand_label(c)
                opts.append(_opt(label, c["reason"], c["name"]))
            i += size
            if len(opts) < 2:
                opts.append(_opt(KEEP_ALL, "Select nothing here.", None))
            qs.append({"question": f"Batch {q + 1} of {nq}: switch these off in THIS repo? "
                                   "Ticked = confirmed; unticked = kept.",
                       "header": f"Remove {q + 1}/{nq}", "multiSelect": True, "options": opts})
    if sync_question:
        qs.append({"question": "Also turn off claude.ai skill sync? All-or-none: synced skills stop "
                               "updating, and whether it affects other repos is unverified.",
                   "header": "Sync", "multiSelect": False, "options": [
                       _opt("Leave sync on", "Writes nothing.", None),
                       _opt("Turn sync off", "Writes syncClaudeAiSkills false here.",
                            "syncClaudeAiSkills")]})
    remainder = {"count": len(rest), "chars": sum(c["desc_chars"] for c in rest)}
    remainder["text"] = (f"{remainder['count']} more candidate(s) holding {remainder['chars']} chars are "
                         "not shown; a second popup can be offered." if rest else "")
    return {"questions": qs, "remainder": remainder, "claude_only": True,
            "label_to_name": {_cand_label(c): c["name"] for c in shown},
            "note": "AskUserQuestion is a Claude Code tool; elsewhere present these options as a "
                    "numbered text list and take the answer in text."}


def resolve_confirmation(removal: dict, confirmed_names, headroom: "int | None" = None) -> dict:
    """The operator's answer -> what may be applied. Only names that are audit candidates pass; an
    unknown name (an 'Other' entry) is held for an evidence check, and `gitos` never passes by any
    route. Empty answer -> nothing. Silence is never consent."""
    by = {c["name"]: c for c in removal.get("candidates") or []}
    by_label = {_cand_label(c): c["name"] for c in removal.get("candidates") or []}
    out = {"skills": [], "plugins": [], "refused": []}
    reclaimed = 0
    for raw in confirmed_names or []:
        n = str(raw).strip()
        n = by_label.get(n, n)             # the popup answers with labels; map them back to names
        if not n or n == KEEP_ALL:
            continue
        short = n.split("@")[0].split(":")[-1].lower()
        if short in PROTECTED_SKILLS:
            out["refused"].append((n, "protected: never removable"))
        elif n not in by:
            out["refused"].append((n, "not an audit candidate: check against the same evidence "
                                      "and confirm back before anything is applied"))
        elif by[n]["mechanism"] == "enabledPlugins":
            out["plugins"].append(n)
            reclaimed += by[n]["desc_chars"]
        else:
            out["skills"].append(n)
            reclaimed += by[n]["desc_chars"]
    out["reclaimed"] = reclaimed
    if headroom is None or headroom >= 0:
        out["verdict"] = ("listing is within the estimated budget" if headroom is not None
                          else "budget unknown")
    elif reclaimed >= -headroom:
        out["verdict"] = f"confirmed set reclaims {reclaimed} chars: listing gets within the estimated budget"
    else:
        out["verdict"] = (f"confirmed set reclaims {reclaimed} chars: still over the estimated budget by "
                          f"{-headroom - reclaimed}; the lever is a whole plugin")
    return out


def plan_empty(plan: dict) -> bool:
    loc = plan["local"]
    return not (plan["copies"] or plan["disable_mcp"] or plan["enable_mcp"] or plan["pins"]
                or any(loc.get(k) for k in loc))


def apply_sync(root: Path, home: Path, ch: Path, cj_path: Path, plan: dict) -> dict:
    """Backs up first, then performs `plan`. Returns {backup, wrote[]}."""
    res = {"backup": None, "wrote": []}
    if plan["refused"] or plan_empty(plan):
        return res
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    bdir = ch / "backups" / f"harness-{stamp}"
    bdir.mkdir(parents=True, exist_ok=True)
    res["backup"] = str(bdir)
    # 1. library copies (previous project copy is backed up whole)
    for c in plan["copies"]:
        dest = Path(c["dest"])
        if dest.is_dir():
            shutil.copytree(dest, bdir / "skills" / dest.name)
            shutil.rmtree(dest)
        shutil.copytree(c["src"], dest)
        res["wrote"].append(str(dest))
    # 2. settings.local.json
    loc, lp = plan["local"], root / ".claude" / "settings.local.json"
    if any(loc.get(k) for k in loc):
        obj, _e = _load_json(lp)
        obj = _dict(obj)
        if lp.is_file():
            shutil.copy2(lp, bdir / "settings.local.json")
        if loc["skillOverrides_set"] or loc["skillOverrides_drop"]:
            so = _dict(obj.get("skillOverrides"))
            so.update(loc["skillOverrides_set"])
            for n in loc["skillOverrides_drop"]:
                so.pop(n, None)
            obj["skillOverrides"] = so
        if loc["enabledPlugins_set"]:
            ep = _dict(obj.get("enabledPlugins"))
            ep.update(loc["enabledPlugins_set"])
            obj["enabledPlugins"] = ep
        if loc["permissions_allow_add"]:
            perms = _dict(obj.get("permissions"))
            perms["allow"] = list(perms.get("allow") or []) + loc["permissions_allow_add"]
            obj["permissions"] = perms
        obj.update(loc["scalars"])
        _write_json(lp, obj)
        res["wrote"].append(str(lp))
    # 3. ~/.claude.json  projects[<root>].disabledMcpServers  (optimistic concurrency)
    if plan["disable_mcp"] or plan["enable_mcp"]:
        before = cj_path.stat() if cj_path.is_file() else None
        obj, err = _load_json(cj_path)
        if err or obj is None:
            raise RuntimeError(f"refusing to write {cj_path}: {err or 'file absent'}")
        projects = obj.setdefault("projects", {})
        key = _project_key(obj, root) or root.as_posix()
        proj = projects.setdefault(key, {})
        cur = list(proj.get("disabledMcpServers") or [])
        cur = [n for n in cur if n not in plan["enable_mcp"]]
        cur += [n for n in plan["disable_mcp"] if n not in cur]
        proj["disabledMcpServers"] = cur
        shutil.copy2(cj_path, bdir / ".claude.json")
        after = cj_path.stat()
        if before is not None and (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size):
            raise RuntimeError(f"{cj_path} changed while syncing (Claude Code is writing it); "
                               "nothing was written to it - re-run")
        _write_json(cj_path, obj)
        res["wrote"].append(str(cj_path))
    # 4. record first-time pins in harness.json (the repo's own file)
    if plan["pins"]:
        decl, _e = load_declaration(home)
        for e in decl.get("skills") or []:
            for n, sha in plan["pins"]:
                if isinstance(e, dict) and e.get("name") == n and not e.get("sha256"):
                    e["sha256"] = sha
        _write_json(home / HARNESS_FILENAME, decl)
        res["wrote"].append(str(home / HARNESS_FILENAME))
    return res


def render_plan(plan: dict) -> str:
    if plan["refused"]:
        return f"harness sync: refused - {plan['refused']}"
    L = ["harness sync plan:"]
    for c in plan["copies"]:
        L.append(f"  copy skill {c['name']}: {c['src']} -> {c['dest']}")
    loc = plan["local"]
    for k, v in loc.items():
        if v:
            L.append(f"  settings.local.json {k}: {json.dumps(v, ensure_ascii=False)}")
    if plan["disable_mcp"]:
        L.append(f"  ~/.claude.json projects[repo].disabledMcpServers += {plan['disable_mcp']}")
    if plan["enable_mcp"]:
        L.append(f"  ~/.claude.json projects[repo].disabledMcpServers -= {plan['enable_mcp']}")
    for n, sha in plan["pins"]:
        L.append(f"  harness.json: pin skill {n} sha256 {sha[:12]}")
    for x in plan["proposals"]:
        L.append(f"  note: {x}")
    if plan_empty(plan):
        L.append("  (nothing to do - already in sync)")
    return "\n".join(L)


# --------------------------------------------------------------------------- canary entry
def canary_check(home: Path) -> "tuple[list, str | None, bool]":
    """-> (findings, skip_reason | None, applicable). Called by canary.py; reads the REAL machine
    state resolved from the environment (HOME / CLAUDE_CONFIG_DIR), which selftests override."""
    root = home.parent
    ch, cj = claude_paths(None, None)
    r = drift(root, home, ch, cj)
    if not r["applicable"]:
        return [], None, False
    if r["error"]:
        return r["findings"], None, True
    if not r["adopted"]:
        return [], "harness.json is not adopted (adopted: false)", True
    return r["findings"], None, True


# --------------------------------------------------------------------------- CLI
def main(argv: "list | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Per-project harness profile (audit/drift/sync).")
    ap.add_argument("cmd", choices=("audit", "drift", "offer", "update", "sync", "popup"))
    ap.add_argument("--home", default=".gitos", help="the gitos home (default ./.gitos)")
    ap.add_argument("--root", default=None, help="repo root (default: parent of --home)")
    ap.add_argument("--claude-home", default=None)
    ap.add_argument("--claude-json", default=None)
    ap.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    ap.add_argument("--listing-chars", type=int, default=None,
                    help="the client's own skill-listing size in chars (/context Skills row or /doctor); "
                         "replaces gitos's estimate of used chars")
    ap.add_argument("--apply", action="store_true", help="sync/update: actually write")
    ap.add_argument("--approve", action="append", default=None, help="update: move this review pin")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--confirm", action="append", default=[],
                    help="sync: a candidate the operator confirmed (repeatable); only these are removed")
    ap.add_argument("--accept-sync-skills", action="store_true",
                    help="sync: the operator ACCEPTED turning claude.ai skill sync off; without it nothing is written")
    ap.add_argument("--accept-sync-plugins", action="store_true",
                    help="sync: the operator ACCEPTED turning claude.ai plugin sync off; without it nothing is written")
    ap.add_argument("--measure", action="store_true",
                    help="offer: first print the read-only budget summary (the upgrade uses this)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    home = Path(a.home).resolve()
    root = Path(a.root).resolve() if a.root else home.parent
    ch, cj = claude_paths(a.claude_home, a.claude_json)

    def emit(obj: object, text: str) -> None:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=list) if a.json else text)

    if a.cmd == "offer":
        if a.measure:
            print(measure_summary(root, home, ch, cj, a.context_window, a.listing_chars))
        try:
            line = offer(home)
        except Exception as e:  # --measure runs inside an upgrade: never fail it
            if not a.measure:
                raise
            line = f"harness: offer not available ({type(e).__name__}: {e})"
        if line:
            print(line)
        return 0
    if a.cmd == "audit":
        r = audit(root, home, ch, cj, a.context_window, a.listing_chars)
        emit(r, render_audit(r))
        return 2 if r["declaration_error"] else 0
    if a.cmd == "drift":
        r = drift(root, home, ch, cj)
        if r["applicable"] and not r["adopted"] and not r["error"]:
            text = "harness drift: harness.json is not adopted - nothing checked"
        else:
            text = "\n".join([f"harness drift: {len(r['findings'])} finding(s), {len(r['notices'])} notice(s)"]
                             + [f"  !! {f['kind']}: {f['finding']}" for f in r["findings"]]
                             + [f"  .. {n}" for n in r["notices"]]) if r["applicable"] \
                else "harness drift: no harness.json (not applicable)"
        emit(r, text)
        return 1 if r["findings"] else 0
    if a.cmd == "update":
        r = update(root, home, ch, cj, a.apply, a.approve)
        emit(r, "\n".join(["harness update" + (" (applied)" if a.apply else " (report only)")]
                          + [f"  {n}" for n in r["notices"]]
                          + [f"  {k}: {len(v)} diff line(s)" for k, v in r["diffs"].items()]))
        return 0
    if a.cmd == "popup":
        r = audit(root, home, ch, cj, a.context_window, a.listing_chars)
        decl, _e = load_declaration(home)
        sq = bool(decl) and not r["claude_ai"]["sync_skills_off"] \
            and _dict(decl.get("claude_ai")).get("sync_skills") is False
        print(json.dumps(popup_questions(r["removal"], sq), indent=2, ensure_ascii=False))
        return 0
    confirmed = None
    if a.confirm:
        r = audit(root, home, ch, cj, a.context_window, a.listing_chars)
        confirmed = resolve_confirmation(r["removal"], a.confirm, r["listing_budget"]["headroom"])
        for n, why in confirmed["refused"]:
            print(f"harness sync: NOT applied - {n}: {why}", file=sys.stderr)
        print(f"harness sync: {confirmed['verdict']}")
    plan = plan_sync(root, home, ch, cj, confirmed,
                     ({"syncClaudeAiSkills"} if a.accept_sync_skills else set())
                     | ({"syncClaudeAiPlugins"} if a.accept_sync_plugins else set()))
    if plan["refused"] and plan["error"]:
        emit(plan, render_plan(plan))
        return 2
    if not a.apply:
        emit(plan, render_plan(plan) + "\n(dry run - pass --apply to write; backup first)")
        return 0
    try:
        res = apply_sync(root, home, ch, cj, plan)
    except RuntimeError as e:
        print(f"harness sync: {e}", file=sys.stderr)
        return 2
    emit({"plan": plan, **res}, render_plan(plan) + f"\napplied: backup={res['backup']} wrote={res['wrote']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
