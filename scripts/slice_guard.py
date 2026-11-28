#!/usr/bin/env python3
"""slice_guard.py - PreToolUse hook: keep a slice implementer's file edits to its own slice file (Claude Code only).

An implementer for a slice of a folder order works in a worktree made by `worktree.py new NNN --slice SN`, which
writes an untracked marker `gitos-slice` (content `WO-NNN/SN`) into that worktree's own git dir. This hook
runs before Edit, Write, MultiEdit and NotebookEdit:

  * No marker for the file's worktree and none for the session's cwd: ALLOW (the orchestrator, or anyone not
    working a slice).
  * Marker present: REFUSE an edit to a folder order's `order.md`, to any slice file other than
    the implementer's own `slices/SN-*.md`, to `INDEX.md` of a gitos home, and a front-matter `status` change of
    the implementer's own slice to `landed` or `dropped`. Everything else is allowed: code, tests, docs, and the
    implementer's own slice notes and its status move in-progress -> implemented.

A NAMED SPRINT'S SESSION (WO-150: GITOS_SPRINT=1, a GITOS_SPRINT_ID that is a sprint id and GITOS_SPRINT_WORKTREE, all set by the
sprint driver) is bound first, marker or not, to its own place inside the repository: an edit is REFUSED, with the path named, when the file
lies in the main checkout, in any other worktree of the same repository (`git worktree list`, run in the sprint worktree), under
`<main checkout>.worktrees/`, or in the main home (`$GITOS_SPRINT_HOME`), unless it is in the session's own worktree, its workers' area
(`<worktree>.worktrees/`, where the slice rules above still apply) or `$GITOS_SPRINT_HOME/sprint/<id>/`. Files outside the repository
(temp and scratch files, `~/.claude`) are not this guard's business. If git cannot list the worktrees the main checkout and
`<main checkout>.worktrees/` are still refused, by the paths the environment gives (the home's parent, the worktree's parent); the git
list only adds to them. Paths are compared by realpath and, on Windows, case-folded, as whole path components. Outside a named sprint
nothing here applies.

The marker is looked up from the edited file's worktree and from the session's cwd, either one binds the
edit, so an implementer cannot step around it by an absolute path into another checkout, and a subagent whose
cwd is its parent's still binds when its files are in the worktree.

HONEST LIMITS. Bash edits are not covered (`sed -i`, a redirect, a script): an implementer that wants to write a
protected file through the shell is not stopped, and the orchestrator's review of the diff at merge is the
backstop. An implementer that edits a file in the main checkout by a path while its own cwd and the file's
worktree both lack the marker is also allowed. Hooks can be switched off by configuration, a Codex session
runs none, and any failure of the hook itself allows the edit (it never blocks by accident).
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

EVENT = "PreToolUse"
TOOLS = "Edit|Write|MultiEdit|NotebookEdit"
MARKER = "gitos-slice"
MARKER_RE = re.compile(r"^WO-(\d{3})/S(\d+[a-z]?)$")   # a slice id is S<number><optional lowercase letter> (slice.py owns the pattern)
FOLDER_PATH_RE = re.compile(r"(?:^|/)work-orders/(?:resolved/)?([^/]+)/(order\.md|slices/([^/]+\.md))$")
NNN_RE = re.compile(r"(\d{3})(?!\d)")
TERMINAL = ("landed", "dropped")
# A named sprint's session. The id rule and reserved ids are compact_restore.py's, copied here: this hook is loaded alone by path
# and must not depend on a sibling that could fail to import (it would then silently stop guarding); a selftest gate pins the copy.
SPRINT_ID_RE = re.compile(r"[a-z0-9-]{1,32}")
SPRINT_RESERVED_IDS = ("claims", "archive", "stop", "rotate", "busy", "exclusive")


def _git_dir(path: Path) -> "Path | None":
    d = path
    while not d.is_dir():
        if d.parent == d:
            return None
        d = d.parent
    try:
        cp = subprocess.run(["git", "-C", str(d), "rev-parse", "--absolute-git-dir"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(cp.stdout.strip()) if cp.returncode == 0 and cp.stdout.strip() else None


def marker_for(path: "str | Path") -> "tuple[str, str] | None":
    """(nnn, slice number) of the slice marker of `path`'s worktree, or None."""
    gd = _git_dir(Path(path))
    if gd is None:
        return None
    f = gd / MARKER
    try:
        m = MARKER_RE.match(f.read_text(encoding="utf-8").strip()) if f.is_file() else None
    except OSError:
        return None
    return (m.group(1), m.group(2)) if m else None


def _status(text: str) -> "str | None":
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for ln in lines[1:]:
        if ln.strip() == "---":
            return None
        key, _, val = ln.partition(":")
        if key.strip() == "status":
            return val.strip().strip("\"'")
    return None


def _after(text: str, tool: str, inp: dict) -> "str | None":
    """The file text after the edit, or None when it cannot be worked out."""
    if tool == "Write":
        c = inp.get("content")
        return c if isinstance(c, str) else None
    edits = inp.get("edits") if tool == "MultiEdit" else [inp]
    if not isinstance(edits, list):
        return None
    for e in edits:
        if not isinstance(e, dict) or not isinstance(e.get("old_string"), str) or not isinstance(e.get("new_string"), str):
            return None
        if e["old_string"] in text:
            text = text.replace(e["old_string"], e["new_string"]) if e.get("replace_all") \
                else text.replace(e["old_string"], e["new_string"], 1)
    return text


EXTENDED_PREFIXES = ("\\\\?\\", "//?/")      # the Windows extended-length prefix, in either slash form


def _plain(path: str) -> str:
    r"""`path` without the extended-length prefix: `\\?\C:\x` is `C:\x` and `\\?\UNC\host\share` is `\\host\share`."""
    for pre in EXTENDED_PREFIXES:
        if path.startswith(pre):
            rest = path[len(pre):]
            if rest[:4].upper() in ("UNC\\", "UNC/"):
                return "\\\\" + rest[4:]
            return rest
    return path


def _norm(path) -> str:
    return os.path.normcase(_plain(os.path.realpath(_plain(str(path)))))


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def named_sprint() -> "tuple[str, str, str, str] | None":
    """(sprint id, its worktree, its folder `<GITOS_SPRINT_HOME>/sprint/<id>`, the home) normalised, for a named sprint's session; the
    last two are "" when no home is named. None in any other session (no GITOS_SPRINT=1, no valid id, or no worktree to name: the guard
    then leaves the edit to the other rules)."""
    if os.environ.get("GITOS_SPRINT") != "1":
        return None
    sid = os.environ.get("GITOS_SPRINT_ID", "")
    wt = os.environ.get("GITOS_SPRINT_WORKTREE", "")
    if not SPRINT_ID_RE.fullmatch(sid) or sid in SPRINT_RESERVED_IDS or not wt:
        return None
    home = os.environ.get("GITOS_SPRINT_HOME", "")
    return (sid, _norm(wt), _norm(Path(home) / "sprint" / sid) if home else "", _norm(home) if home else "")


def _git_worktrees(wt: str) -> "list[str] | None":
    """The paths `git worktree list` gives, run in the sprint worktree (the first is the main checkout); None when git cannot say."""
    d = Path(wt)
    while not d.is_dir():
        if d.parent == d:
            return None
        d = d.parent
    for args in (["--porcelain", "-z"], ["--porcelain"]):
        try:
            cp = subprocess.run(["git", "-C", str(d), "worktree", "list", *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=10)
        except Exception:
            return None
        if cp.returncode == 0:
            paths = [ln[len("worktree "):] for ln in cp.stdout.replace("\0", "\n").splitlines() if ln.startswith("worktree ")]
            return paths or None
    return None


def _env_trees(wt: str, home: str) -> "list[str]":
    """What the environment alone says is inside the repository and not the session's: the main home, its parent when the home is a
    `.gitos` folder (the main checkout), the worktree's parent when that is a `<repo>.worktrees` folder, and that repo."""
    out: list = []
    if home:
        out.append(home)
        if os.path.basename(home) == os.path.normcase(".gitos"):
            out.append(os.path.dirname(home))
    area = os.path.dirname(wt)
    if os.path.basename(area).endswith(os.path.normcase(".worktrees")):
        out += [area, area[:-len(".worktrees")]]
    return out


def protected_trees(wt: str, home: str) -> "list[str]":
    """The trees of this repository a named session must not edit (before the exceptions): what the environment names, always, plus
    every worktree of the repository git lists. A git that cannot answer only takes the second part away."""
    out = _env_trees(wt, home)
    out += [_norm(p) for p in _git_worktrees(wt) or []]
    return [t for t in dict.fromkeys(out) if t]


def sprint_refused(path: str, sprint) -> bool:
    """True when `path` (normalised) is inside the repository and not the named session's own: see the module docstring."""
    _sid, wt, sdir, home = sprint
    if _within(path, wt) or _within(path, wt + ".worktrees") or (sdir and _within(path, sdir)):
        return False
    return any(_within(path, t) for t in protected_trees(wt, home))


def sprint_refusal(path: str, sid: str) -> dict:
    reason = (f"gitos slice_guard: sprint {sid} edits only inside its own worktree, its workers' area and its sprint/{sid}/ folder "
              f"when the file is in this repository, and {path} is in the main checkout, another worktree or the main home. Edit the "
              f"same file in your sprint worktree ($GITOS_SPRINT_WORKTREE); the main branch gets it through `worktree.py land`, never "
              f"by an edit in the main checkout.")
    return {"hookSpecificOutput": {"hookEventName": EVENT, "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def refusal(path: str, why: str, marker) -> dict:
    sid = f"WO-{marker[0]}/S{marker[1]}"
    reason = (f"gitos slice_guard: this worktree is bound to slice {sid}; {why} ({path}). An implementer edits only its own slice "
              f"file's notes and moves its status in-progress -> implemented; the orchestrator owns the rest. "
              f"Report what you need changed instead.")
    return {"hookSpecificOutput": {"hookEventName": EVENT, "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def decide(payload) -> "dict | None":
    """A deny decision, or None to allow."""
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool_name")
    inp = payload.get("tool_input")
    if tool not in ("Edit", "Write", "MultiEdit", "NotebookEdit") or not isinstance(inp, dict):
        return None
    raw = inp.get("file_path") or inp.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    p = Path(raw)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / raw
    sprint = named_sprint()
    if sprint is not None:
        if sprint_refused(_norm(p), sprint):
            return sprint_refusal(p.as_posix(), sprint[0])
    marker = marker_for(p) or (marker_for(cwd) if cwd else None)
    if marker is None:
        return None
    posix = p.as_posix().replace("\\", "/")
    if p.name == "INDEX.md" and (p.parent / "work-orders").is_dir():
        return refusal(posix, "INDEX.md is generated and kept by the orchestrator", marker)
    m = FOLDER_PATH_RE.search(posix)
    if not m:
        return None
    folder, leaf, slice_leaf = m.group(1), m.group(2), m.group(3)
    nm = NNN_RE.search(folder)
    own_order = bool(nm) and nm.group(1) == marker[0]
    if slice_leaf is None:
        return refusal(posix, f"{leaf} is the orchestrator's", marker)
    own = own_order and re.match(rf"^S{marker[1]}(?:-|\.md$)", slice_leaf) is not None
    if not own:
        return refusal(posix, "that is another slice's file", marker)
    if tool == "NotebookEdit":
        return None
    try:
        before = p.read_text(encoding="utf-8") if p.is_file() else ""
    except OSError:
        return None
    after = _after(before, tool, inp)
    if after is None:
        return None
    new = _status(after)
    if new in TERMINAL and new != _status(before):
        return refusal(posix, f"only the orchestrator sets a slice's status to {new}", marker)
    return None


def end_orphan_session() -> None:
    """In a sprint session (named or exclusive) whose driver is gone, end the session (`compact_restore.end_orphan_session`, loaded from beside this
    file; any other session never loads it). Anything that goes wrong leaves the guard to its own job."""
    if os.environ.get("GITOS_SPRINT") != "1" or not os.environ.get("GITOS_SPRINT_PID"):
        return
    try:
        spec = importlib.util.spec_from_file_location("_gitos_slice_guard_restore", Path(__file__).resolve().parent / "compact_restore.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.end_orphan_session()
    except Exception:
        pass


def hook_command(stream) -> int:
    """The client-event entry point. ALWAYS returns 0; stdout carries a refusal or nothing. Anything the hook
    cannot decide leaves the edit alone."""
    try:
        end_orphan_session()
        decision = decide(json.loads(stream.read() or "null"))
        if decision is not None:
            print(json.dumps(decision, ensure_ascii=False))
    except Exception as exc:
        print(f"gitos slice_guard: inert - {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


# Self-locating, like the other gitos hooks: the settings file is committed, so no absolute path may travel.
HOOK_BOOTSTRAP = (
    "import importlib.util, pathlib, sys\n"
    "try:\n"
    "    p = pathlib.Path.home() / '.claude/skills/gitos/scripts/slice_guard.py'\n"
    "    spec = importlib.util.spec_from_file_location('gitos_slice_guard', p)\n"
    "    mod = importlib.util.module_from_spec(spec)\n"
    "    spec.loader.exec_module(mod)\n"
    "    mod.hook_command(sys.stdin)\n"
    "except BaseException:\n"
    "    pass\n"
)
HOOK_MATCHERS = {EVENT: TOOLS}


def hook_entry() -> dict:
    """Neither `async` nor `onFailure` is set: an async hook's decision has no effect, and `onFailure: block`
    would make the hook's own breakage a refusal."""
    engine = _engine()                     # the one interpreter choice all four hook writers share (WO-166)
    command, args = engine.hook_python(["-c", HOOK_BOOTSTRAP]) if engine else (sys.executable or "python",
                                                                               ["-I", "-c", HOOK_BOOTSTRAP])
    return {"type": "command", "command": command, "args": args,
            "statusMessage": "gitos slice_guard: a slice implementer edits only its own slice file"}


def _engine():
    path = Path(__file__).resolve().parent / "model_optimization.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_gitos_slice_guard_model_optimization", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def ensure_hook(root, engine=None):
    """Register this hook in `<root>/.claude/settings.json`, beside whatever is there. -> (status, detail)."""
    engine = _engine() if engine is None else engine
    if engine is None:
        return "skipped", "model_optimization.py not found beside slice_guard.py"
    return engine.ensure_settings_hook(root, entry=copy.deepcopy(hook_entry()), matchers=HOOK_MATCHERS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PreToolUse hook keeping a slice implementer to its own slice file.")
    ap.add_argument("command", choices=("hook", "install"))
    ap.add_argument("root", nargs="?", default=".")
    a = ap.parse_args(argv)
    if a.command == "hook":
        return hook_command(sys.stdin)
    status, detail = ensure_hook(Path(a.root).resolve())
    print(f"gitos slice_guard: {status}{f' - {detail}' if detail else ''}")
    return 0 if status != "skipped" else 3


if __name__ == "__main__":
    raise SystemExit(main())
