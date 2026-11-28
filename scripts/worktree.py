"""worktree - one worktree per work-order, and nothing left behind once it lands.

stdlib-only, harness-neutral (plain git; no client feature is assumed).

  new NNN      Create `<parent>/<repo name>.worktrees/wo-NNN` (outside the repo tree, so editors and
               language servers do not index it; under the layout's `root` when `worktrees.json`
               sets one) on a new branch `wo-NNN` from the CURRENT `HEAD` (never a remote's default
               branch), for an open work-order. Prints the absolute path to dispatch the implementer
               into. A re-run prints the existing path and changes nothing. Worktrees already under
               `.claude/worktrees/` are still found, classified and reaped.
  new NNN --slice SN
               The same for slice SN of a folder order, in its own worktree `wo-NNN-sN` on branch `wo-NNN-sN`
               (one per slice, so parallel slices never share a checkout), with the slice marker the edit hook
               reads. `status`, `reap` and the canary treat it like `wo-NNN`.
  reap NNN     Remove that worktree (and every `wo-NNN-sN` slice worktree of the order) and delete its branch, only if the branch is merged (into the
               current branch, the default branch or a declared integration branch) and the
               worktree has no changed or untracked files. A removal git refuses over a long path
               ("Filename too long", or on Windows a path past 260 characters) is retried (see LONG PATHS).
               A slice worktree is taken by `reap NNN` only when it is reapable (see `status`): a slice with no commits
               yet is a worker about to start, and an order a live sprint claims is never reaped (see SPRINTS).
  reap NNN-sN  That one slice (`wo-NNN-sN`) only, named by the operator: it may have no commits yet, but a claimed order still refuses.
  reap --merged
               The same for every reapable one (see `status`), `wo-NNN`, `worktree-*` and declared
               worktrees alike.
  status       READ-ONLY. Every linked worktree and every `wo-NNN` / `worktree-*` local branch,
               classed in flight / reapable / abandoned / dirty. `--json` for scripts.
  lock acquire [--wait S] | release | status
               The merge lock of the home: one merge, gate and landing at a time across the home's sprints and the
               interactive orchestrator (see THE MERGE LOCK).
  land         Run in a named sprint's worktree: land the sprint branch on the main branch under the lock (see LAND).

Usage:
    python worktree.py new NNN [--slice SN] [ROOT] [--home DIR]
    python worktree.py reap NNN | NNN-sN | wo-NNN-sN | --merged [ROOT] [--home DIR]
    python worktree.py status [ROOT] [--home DIR] [--json]
    python worktree.py lock acquire [--wait S] [--pid N] | release [--pid N] | status [ROOT] [--home DIR]
    python worktree.py land [--wait S] [--pid N] [ROOT] [--home DIR]
Exit codes: 0 = done / nothing to do, 1 = refused (reason printed), 2 = usage or not a git repo.

SPRINTS (WO-150). A named sprint runs in its own worktree `<repo name>.worktrees/sprint-<id>` on branch `sprint-<id>` (the
driver makes it); its claims, state, signals and the merge lock live in the MAIN checkout's home (`GITOS_SPRINT_HOME`).
  * `reap` and the inventory never take a `sprint-<id>` worktree or branch, however a `worktrees.json` glob classes it: the
    driver removes it, and only when its branch is in the main branch and it is clean.
  * A work-order a live sprint claims (`<home>/sprint/claims/WO-NNN.json`, live = pid alive and the same start time) is in
    flight for everybody else: `status` shows it so, `reap` of any form refuses it. The sprint's own session is not "another".
  * `new` also runs inside a sprint worktree. Its worker worktrees go to `<sprint worktree path>.worktrees/` (a sibling of
    the sprint worktree, whatever `worktrees.json` says): no two sprints share a path, none lands inside another sprint's
    tree, and a path inside any other worktree of the repository is refused. The workers branch from the sprint branch.
  * `reap` also runs inside a sprint worktree, and then takes only the worktrees under that sprint's `.worktrees/` (HEAD,
    the sprint branch, is what they are merged into).

THE MERGE LOCK. `<main home>/sprint/merge.lock` is `{"holder", "pid", "start", "since"}`, and during a `land` also `"step"` (merge, index, canary, gate or fast-forward; `lock status` shows it). The main home is `GITOS_SPRINT_HOME`
(when it names a home of this repository), else the main checkout's own home. `holder` is `GITOS_SPRINT_ID`, else
`interactive`. `pid` is what keeps the lock alive: `GITOS_SPRINT_PID` (the sprint's driver), else `--pid N`, else the nearest ancestor
process of this command that is the Claude Code session (the shell that ran the command is gone before the merge is, so it is
never used: no session among the ancestors refuses, and the message says to pass `--pid` of a process that lives through the
merge). The session is matched by executable name (`claude`, `claude.exe`), or a `node` whose command line names `claude-code`
(where a command line can be read: not on Windows, where a `node` is not matched). The lock is created whole and exclusively (a hard link of a finished file), so a reader never sees half of it. Live =
the pid is running and has the recorded start time; a dead one (or a reused pid) is taken over under a short takeover guard
that re-reads it, and the takeover is said. `release` by anyone but the holder is refused (a dead lock excepted: it is
garbage). A holder that acquires again is refused: its own lock means an earlier `land` or acquire never released it.

LAND. Run in the sprint worktree, under the lock, in this order; the lock is released on every way out:
  1. merge the main branch into the sprint branch (the worktree must be clean). A conflict in a generated file (the board
     `INDEX.md`, the brain `wiki/index.md`) is kept as the sprint's and regenerated in step 2; a conflict anywhere else
     aborts the merge and exits 1 naming the files.
  2. regenerate `INDEX.md` (`ledger_index.py`) and, when the sprint changed the brain, `wiki/index.md`
     (`brain_lint.py --write-index`), and commit.
  3. the gate: the canary (`canary.py <home>`), then `<home>/sprint-gate.json` `{"command": [...], "timeout_s": N}` when
     there is one (the sprint's copy, else the main home's), run in the sprint worktree. A non-zero exit, a timeout or a
     command that cannot start refuses: nothing lands.
  4. fast-forward the main branch to the sprint branch in the main checkout, refused when that checkout is not on the
     main branch or has changed tracked files (the operator's own window is never merged over; an untracked file does not
     refuse, git itself refuses one that would be overwritten) or when the main branch moved since step 1.
  5. release the lock.
The main branch is `main`, else `master`, else the branch the main checkout is on (the sprint driver's rule).

WHAT IT RELIES ON. Only refusals git itself makes, checked against git 2.51 (`git help worktree`):
`git worktree remove` (no force) refuses a worktree with modified or untracked files and a locked
one, and says so; it does NOT check that the branch is merged, so `reap` checks that BEFORE it
removes anything; `git branch -d` refuses an unmerged branch and a branch still checked out in a
worktree (a worktree whose directory was deleted by hand stays registered until `git worktree
prune`, which `reap` runs). Ignored files (for example `__pycache__`) do not block a removal.

WHAT IT NEVER DOES. No `--force` except the long-path retry below, no `git worktree unlock`, and no deletion from a hook or the canary:
the canary and the `Stop` hook only READ the classification below. A refusal is printed with the reason
and what the operator can do, and the run exits 1. `reap` does use `git branch -D`, and only after its
own merged check passed: git's `-d` asks whether the branch is merged into the CURRENT branch alone,
which is too narrow once work lands on an integration branch.

LONG PATHS (WO-125). When `git worktree remove` fails and the failure names a long path (git says "Filename too long") or,
on Windows, a path inside the worktree is longer than 260 characters, `reap` retries in this order and prints each fallback
it takes: (1) a status check with `core.longpaths=true`, and a worktree that shows a changed or untracked file there is
refused, never forced; (2) `git -c core.longpaths=true worktree remove --force` on that one worktree; (3) whatever
directory is left is removed through the Windows extended-length prefix by a walk that unlinks a link and never follows one;
(4) `git worktree prune`. A locked worktree is never retried. Only the named worktree's own directory is touched.

THE DECLARED LAYOUT. An optional `<home>/worktrees.json`, every key optional:
  {"root": "<dir>", "roots": ["<glob>"], "branches": ["<glob>"], "integration": ["<glob>"],
   "archive": ["<relative dir>"]}
`root` is where `new` puts worktrees (relative = under the repo root). A linked worktree whose path
matches a `roots` glob, or whose branch matches a `branches` glob, is managed (kind `declared`), a
detached checkout included (it has no branch; reap removes the worktree only). MERGED means the tip is
an ancestor of the current HEAD, of the default branch (`main`, else `master`), or of a local branch
matching an `integration` glob; the status line names which. `archive` lists ignored directories copied
to `<home>/worktree-archive/<name>/<dir>` before a removal. A malformed file is a one-line refusal.

THE LINK GUARD. Before any removal, every symlink or Windows junction inside the worktree whose target
is outside it is unlinked (the link, never its target; links are never traversed); one that cannot be
unlinked refuses the removal. Ignored folders do not make git refuse, so without this a removal could
reach through a link into another checkout.

THE CLASSES, one per branch or worktree (`classify`):
  dirty      uncommitted or untracked files in the worktree.
  reapable   merged (see DECLARED LAYOUT) and clean, and not brand new (see FRESH).
  abandoned  unmerged work that nothing is going to finish: a `wo-NNN` whose work-order is resolved
             or missing, or a `worktree-*` branch with no worktree left.
  in flight  everything else: an open work-order, a locked worktree, a `worktree-*` worktree that is
             still on disk, any other linked worktree, a declared worktree that is not merged, and a
             merge target: a worktree or branch that IS the default branch or an `integration` branch
             (a target is where work lands, not work; never reapable, never abandoned, whatever its
             tip is merged into). Merged always means merged into a branch other than its own; a
             detached checkout holds no branch, so one at a target's tip is still reapable.
FRESH (`wo`, `builtin` and `declared` kinds). A branch that has never had a commit of its own is an ancestor of HEAD
from the moment it is created, so "merged" alone would call every new worktree reapable. Its reflog tells them apart: one
distinct hash is a branch nobody has committed to. A fresh branch is in flight while its work-order is
open (or, for `worktree-*`, while its worktree is on disk). A declared worktree on disk is fresh when its
own HEAD reflog holds one distinct hash (nothing committed there), a detached checkout included; for a
branch checkout whose worktree reflog cannot be read the branch reflog decides. An explicit `reap NNN` is the operator
naming it and is not held back by this; the passive surfaces (status, canary, Stop) are.
HONEST LIMIT: a reflog that was expired or never written makes a branch look not-fresh, so a brand-new
worktree could read as reapable; `reap` still refuses anything dirty.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

# The engine's detection order (model_optimization.HOMES).
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")
WORKTREES_REL = ".claude/worktrees"
IGNORE_LINE = ".claude/worktrees/"
IGNORE_COMMENT = "# Agent worktrees (gitos worktree.py): one per work-order, never tracked."
# `wo-NNN`, or `wo-NNN-sN` for slice N of a folder order (group 1 is the order either way)
WO_BRANCH_RE = re.compile(r"^wo-(\d{3})(?:-s\d+)?$")
BUILTIN_PREFIX = "worktree-"
# canary.WO_FILE_RE, restated (this file must not import the canary, which imports it); the selftest
# gate asserts the two agree on a list of names.
WO_FILE_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)[-_.][A-Za-z0-9][\w.-]*\.md$")
# the folder form of an order (two or more slices): `<prefix>NNN[-slug]/order.md`
WO_DIR_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)(?:[-_.][A-Za-z0-9][\w.-]*)?$")
SLICE_MARKER = "gitos-slice"
GIT_TIMEOUT = 30
LAYOUT_FILE = "worktrees.json"
ARCHIVE_DIR = "worktree-archive"
LAYOUT_LISTS = ("roots", "branches", "integration", "archive")
CLASSES = ("in flight", "reapable", "abandoned", "dirty")
SCRIPTS = Path(__file__).resolve().parent          # where ledger_index.py, brain_lint.py, canary.py and compact_restore.py are
SPRINT_BRANCH_RE = re.compile(r"^sprint-([a-z0-9-]{1,32})$")     # a named sprint's branch and worktree name (the driver's)
SPRINT_ID_RE = re.compile(r"^[a-z0-9-]{1,32}$")
LOCK_FILE = "merge.lock"
GUARD_STALE_S = 30            # a takeover guard older than this belongs to a process that died inside it
INTERACTIVE = "interactive"
SESSION_EXE_NAMES = ("claude", "claude.exe")                      # the Claude Code session, by executable name
SESSION_NODE_NAMES = ("node", "node.exe")                         # ... or one of these running Claude Code (command line)
SESSION_CMDLINE_MARKS = ("claude-code", "@anthropic-ai/claude-code")
SESSION_WALK_STEPS = 64       # the ancestor walk is bounded
NO_SESSION_MSG = ("no Claude Code session found among the parent processes of this command, so no process is known to live "
                  "through the merge -> pass `--pid N` of one that does (never the shell this command runs in)")
GATE_FILE = "sprint-gate.json"
GATE_DEFAULT_S = 600
CANARY_TIMEOUT_S = 300
MERGE_TIMEOUT = 600
KILL_WAIT_S = 5               # after a timeout kills a process tree: how long its output is waited for


# ------------------------------------------------------------------------------------- git
def _kill_tree(proc):
    """Kill `proc` and everything below it: `taskkill /T /F` on Windows (a grandchild that holds the output pipes would otherwise keep a
    wait for the output going), the process group elsewhere (`proc` was started as its own group)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=KILL_WAIT_S)
        else:
            os.killpg(proc.pid, 9)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _spawn(argv, cwd, timeout):
    """Run `argv` in `cwd` with a timeout that holds on every platform, grandchildren included. -> (returncode, stdout, stderr, why);
    `why` is "" or "timed out after Ns" / "cannot run ..." (returncode None). On a timeout the whole process tree is killed and the
    output is waited for a bounded time (the output of an orphan that holds the pipes is abandoned)."""
    kw = {} if sys.platform == "win32" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", **kw)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", "", f"cannot run {argv[0]!r}: {e}"
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return None, out or "", err or "", f"timed out after {timeout:g}s"
    except (OSError, subprocess.SubprocessError) as e:
        _kill_tree(proc)
        return None, "", "", f"cannot run {argv[0]!r}: {e}"
    return proc.returncode, out or "", err or "", ""


def git(root, *args, timeout=GIT_TIMEOUT):
    """-> (returncode, stdout, stderr); returncode None when git is absent or times out (its whole process tree is then killed)."""
    rc, out, err, _ = _spawn(["git", "-C", str(root), *args], os.getcwd(), timeout)
    return (rc, out, err) if rc is not None else (None, "", "")


def git_ok(root, *args):
    """-> stdout text, or None when git is absent or the command fails."""
    rc, out, _ = git(root, *args)
    return out if rc == 0 else None


def toplevel(path):
    """The working-tree root containing `path`, or None when it is not inside a git work tree."""
    out = git_ok(path, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out and out.strip() else None


def is_linked(root):
    """True when `root` is a linked worktree (its git dir differs from the common one)."""
    out = git_ok(root, "rev-parse", "--absolute-git-dir", "--git-common-dir")
    lines = out.splitlines() if out else []
    if len(lines) < 2:
        return False
    try:
        common = Path(lines[1])
        common = (common if common.is_absolute() else Path(root) / common).resolve()
        return Path(lines[0]).resolve() != common
    except OSError:
        return False


def find_home(root, home_arg=None):
    if home_arg:
        return Path(home_arg).resolve()
    for rel in HOMES:
        if (Path(root) / rel).is_dir():
            return Path(root) / rel
    return Path(root) / HOMES[0]


def root_for_home(home):
    """The repo root a gitos home sits in (the home may be `outputs/debug` or `docs/agents`)."""
    home = Path(home)
    if home.name == "debug" and home.parent.name == "outputs":
        return home.parent.parent
    if home.name == "agents" and home.parent.name == "docs":
        return home.parent.parent
    return home.parent


def posix(path):
    return Path(path).as_posix()


# ----------------------------------------------------------------------------- work-orders
def wo_states(home):
    """-> (open NNNs, resolved NNNs, known). `known` is False when there is no work-orders/ dir."""
    wo_dir = Path(home) / "work-orders"
    if not wo_dir.is_dir():
        return set(), set(), False
    found = []
    for d in (wo_dir, wo_dir / "resolved"):
        nnns = set()
        try:
            for f in d.glob("*.md"):
                m = WO_FILE_RE.match(f.name)
                if m:
                    nnns.add(m.group(1))
            for sub in d.iterdir():
                m = WO_DIR_RE.match(sub.name)
                if m and sub.is_dir() and (sub / "order.md").is_file():
                    nnns.add(m.group(1))
        except OSError:
            pass
        found.append(nnns)
    return found[0], found[1], True


# ---------------------------------------------------------------------------------- layout
class LayoutError(Exception):
    """`worktrees.json` is malformed. The message is the one line to print."""


def load_layout(home):
    """The declared layout under `home` (every key optional). Raises LayoutError when malformed."""
    lay = {"root": None, "roots": [], "branches": [], "integration": [], "archive": []}
    path = Path(home) / LAYOUT_FILE
    if not path.is_file():
        return lay
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise LayoutError(f"{LAYOUT_FILE}: whole file is not valid JSON ({str(e).splitlines()[0]})")
    if not isinstance(data, dict):
        raise LayoutError(f"{LAYOUT_FILE}: whole file must be a JSON object")
    for key, val in data.items():
        if key == "root":
            if not isinstance(val, str) or not val.strip():
                raise LayoutError(f"{LAYOUT_FILE}: key 'root' must be a non-empty string")
            lay["root"] = val
        elif key in LAYOUT_LISTS:
            if not isinstance(val, list) or not all(isinstance(v, str) and v.strip() for v in val):
                raise LayoutError(f"{LAYOUT_FILE}: key '{key}' must be a list of non-empty strings")
            if key == "archive" and any(os.path.isabs(v) or ".." in Path(v).parts for v in val):
                raise LayoutError(f"{LAYOUT_FILE}: key 'archive' holds paths relative to a worktree "
                                  f"(no absolute path, no '..')")
            lay[key] = list(val)
        else:
            raise LayoutError(f"{LAYOUT_FILE}: unknown key '{key}' (known: root, "
                              f"{', '.join(LAYOUT_LISTS)})")
    return lay


def layout_root(root, layout):
    """Where `new` puts worktrees: the layout's `root`, else a sibling `<repo name>.worktrees`."""
    root = Path(root)
    if layout["root"]:
        base = Path(layout["root"])
        return (base if base.is_absolute() else root / base)
    return root.parent / f"{root.name}.worktrees"


def _norm(text):
    text = text.replace("\\", "/")
    return text.lower() if os.name == "nt" else text


def _under(path, base):
    """`path` relative to `base` (posix), or None when it is not inside it."""
    try:
        return Path(os.path.realpath(path)).relative_to(os.path.realpath(base)).as_posix()
    except ValueError:
        return None


def _path_matches(path, root, layout):
    """True when a worktree path matches a `roots` glob: absolute, repo-relative or `root`-relative."""
    if not layout["roots"]:
        return False
    cands = [posix(path)]
    for base in (root, layout_root(root, layout)):
        rel = _under(path, base)
        if rel:
            cands.append(rel)
    pats = [_norm(g) for g in layout["roots"]]
    return any(fnmatch.fnmatchcase(_norm(c), g) for c in cands for g in pats)


def _declared(entry, root, layout):
    if entry["branch"] and any(fnmatch.fnmatchcase(entry["branch"], g) for g in layout["branches"]):
        return True
    return _path_matches(entry["path"], root, layout)


# ------------------------------------------------------------------------------- inventory
def _entries(root):
    """The `git worktree list --porcelain` entries, main worktree first. -> list of dicts or None."""
    out = git_ok(root, "worktree", "list", "--porcelain")
    if out is None:
        return None
    entries, cur = [], None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[9:], "branch": None, "locked": False, "lock_reason": "",
                   "prunable": False, "detached": False, "head": None}
            entries.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur["head"] = line[5:].strip()
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "", 1)
        elif line == "detached":
            cur["detached"] = True
        elif line.startswith("locked"):
            cur["locked"] = True
            cur["lock_reason"] = line[6:].strip()
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return entries


def _managed(branch):
    if WO_BRANCH_RE.match(branch):
        return "wo"
    if branch.startswith(BUILTIN_PREFIX):
        return "builtin"
    return None


def _merge_targets(root, current, layout):
    """-> [(label, ref)]: where work counts as merged. Order is the order the status line prefers:
    the current HEAD, the default branch (`main`, else `master`), then local branches matching an
    `integration` glob."""
    targets = [(current or "HEAD", "HEAD")]
    for default in ("main", "master"):
        if git_ok(root, "rev-parse", "--verify", "-q", f"refs/heads/{default}") is not None:
            targets.append((default, f"refs/heads/{default}"))
            break
    if layout["integration"]:
        refs = git_ok(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/") or ""
        for b in refs.splitlines():
            if b and all(b != t[0] for t in targets) and any(
                    fnmatch.fnmatchcase(b, g) for g in layout["integration"]):
                targets.append((b, f"refs/heads/{b}"))
    return targets


def _is_target(branch, targets, layout):
    """True when `branch` is itself a merge target: the default branch or an `integration` branch."""
    return bool(branch) and (branch in [t[0] for t in targets[1:]] or any(
        fnmatch.fnmatchcase(branch, g) for g in layout["integration"]))


def _merged_into(root, tip, targets, own=None):
    """The label of the first target that has `tip` as an ancestor, or None. `own` is the item's own
    branch: it is skipped, because a branch is always an ancestor of itself."""
    for label, ref in targets:
        if own and label == own:
            continue
        rc, _, _ = git(root, "merge-base", "--is-ancestor", tip, ref)
        if rc == 0:
            return label
    return None


def _ahead(root, tip):
    """Commits on `tip` that HEAD does not have, or None when git cannot say."""
    out = git_ok(root, "rev-list", "--count", f"HEAD..{tip}")
    try:
        return int(out.strip())
    except (AttributeError, ValueError):
        return None


def _fresh(root, branch):
    """True when the branch has never had a commit of its own (one distinct reflog hash)."""
    out = git_ok(root, "reflog", "show", "--format=%H", f"refs/heads/{branch}")
    hashes = {h for h in (out or "").split() if h}
    return len(hashes) == 1


def _fresh_worktree(path, root, branch):
    """True when a worktree on disk has had no commit since it was created: one distinct hash in its
    own HEAD reflog. Falls back to the branch reflog (a branch checkout) when that cannot be read;
    unreadable both ways is not fresh."""
    out = git_ok(path, "reflog", "show", "--format=%H", "HEAD")
    hashes = {h for h in (out or "").split() if h}
    if hashes:
        return len(hashes) == 1
    return _fresh(root, branch) if branch else False


def _dirty_count(path):
    """Changed or untracked files in a worktree. Unreadable counts as dirty (the safe answer). Read with
    `core.longpaths=true`: without it git cannot open a directory past the path limit and reports it as untracked."""
    out = git_ok(path, "-c", "core.longpaths=true", "status", "--porcelain")
    if out is None:
        return 1
    return len([ln for ln in out.splitlines() if ln.strip()])


# ------------------------------------------------------------------------------------- sprints
def _cr():
    """compact_restore (the liveness helpers the sprint driver also uses), imported on first use."""
    try:
        import compact_restore
    except ImportError:
        sys.path.insert(0, str(SCRIPTS))
        import compact_restore
    return compact_restore


def _live(rec):
    """True when the process a claim or lock record names is still that process: its pid is running and has the recorded start time."""
    return _cr().record_alive(rec)


def env_sprint_id():
    """The named sprint this process belongs to (GITOS_SPRINT_ID), "" for none or a value that is not a sprint id."""
    sid = os.environ.get("GITOS_SPRINT_ID", "")
    return sid if SPRINT_ID_RE.fullmatch(sid) and sid not in _cr().SPRINT_RESERVED_IDS else ""


def _same(a, b):
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def _common_dir(path):
    out = git_ok(path, "rev-parse", "--git-common-dir")
    if not out or not out.strip():
        return None
    p = Path(out.strip())
    return os.path.normcase(os.path.realpath(p if p.is_absolute() else Path(path) / p))


def main_checkout(root, entries=None):
    """The main working tree of the repository `root` belongs to (the first `git worktree list` entry), or None."""
    entries = entries if entries is not None else _entries(root)
    return Path(entries[0]["path"]) if entries else None


def main_home(root, home, entries=None):
    """The home that holds the sprints' meeting point (`sprint/`: claims, state, the merge lock): GITOS_SPRINT_HOME when it is a home
    of this repository, else the main checkout's copy of `home`, else `home` itself."""
    env = os.environ.get("GITOS_SPRINT_HOME", "")
    if env and Path(env).is_dir():
        eh = Path(env).resolve()
        mine = _common_dir(root)
        if mine is not None and _common_dir(root_for_home(eh)) == mine:
            return eh
    main = main_checkout(root, entries)
    if main is not None and not _same(main, root):
        rel = _under(home, root)
        if rel is not None:
            return main / rel
    return Path(home)


def sprint_of(root):
    """The sprint id when `root` is a named sprint's own worktree (a linked worktree on branch `sprint-<id>`), else ""."""
    if not is_linked(root):
        return ""
    m = SPRINT_BRANCH_RE.fullmatch((git_ok(root, "branch", "--show-current") or "").strip())
    return m.group(1) if m else ""


def worker_root(sprint_root):
    """Where the worker worktrees of the sprint worktree `sprint_root` go: `<sprint worktree path>.worktrees`, a sibling of the
    sprint worktree itself (never inside it, never inside another sprint's)."""
    sprint_root = Path(sprint_root)
    return sprint_root.parent / f"{sprint_root.name}.worktrees"


def _is_sprint_entry(e):
    """A worktree entry that is a named sprint's (its branch, or for a detached checkout its folder, is `sprint-<id>`)."""
    return bool(SPRINT_BRANCH_RE.fullmatch(e["branch"] or Path(e["path"]).name))


def live_claims(mhome, own=""):
    """{NNN: text} of the orders a live sprint other than `own` claims (`<home>/sprint/claims/WO-NNN.json`). A claim file that
    cannot be read counts as a claim: reaping around a file nobody can judge is the unsafe answer."""
    out = {}
    try:
        files = sorted((Path(mhome) / "sprint" / "claims").glob("WO-*.json"))
    except OSError:
        return out
    for f in files:
        m = re.fullmatch(r"WO-(\d{3})", f.stem)
        if not m:
            continue
        try:
            rec = _cr().load_json(f)               # the hooks reach this through the inventory: a claim being rewritten is read again
        except (OSError, ValueError):
            out[m.group(1)] = "a claim file that cannot be read"
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("sprint"), str) or isinstance(rec.get("pid"), bool) \
                or not isinstance(rec.get("pid"), int):
            out[m.group(1)] = "a claim file that is not a claim"
        elif (not own or rec["sprint"] != own) and _live(rec):
            out[m.group(1)] = f'sprint "{rec["sprint"]}" (pid {rec["pid"]})'
    return out


def classify(item):
    """-> (class, why) for an inventory item. The one definition the tool, canary and hooks share."""
    kind, merged = item["kind"], item["merged"]
    has_dir = item["path"] is not None
    if item.get("sprint"):
        return "in flight", "a sprint's worktree (its driver removes it)"
    if item["dirty"]:
        return "dirty", f"{item['dirty']} changed or untracked file(s)"
    if item.get("target"):
        return "in flight", "a merge target"
    if kind == "other":
        return "in flight", "linked worktree on a branch this tool does not manage"
    if item["locked"]:
        return "in flight", "locked (git will not remove it)"
    if merged:
        if item.get("claimed"):
            return "in flight", f"WO-{item['nnn']} is claimed by {item['claimed']}"
        if item["fresh"] and (item["wo"] == "open" if kind == "wo" else has_dir):
            return "in flight", "no commits of its own yet"
        into = item.get("merged_into")
        why = "merged and clean" if item.get("merged_head", True) else f"merged into {into} and clean"
        return "reapable", why
    if kind == "declared":
        n = "unmerged" if item["ahead"] is None else f"{item['ahead']} commit(s) not merged"
        return "in flight", n
    if kind == "wo":
        if item["wo"] == "open" or item["wo"] == "unknown":
            return "in flight", f"{item['ahead']} commit(s) not merged"
        return "abandoned", f"unmerged work and WO-{item['nnn']} is {item['wo']}"
    if has_dir:
        return "in flight", f"{item['ahead']} commit(s) not merged"
    return "abandoned", f"{item['ahead']} unmerged commit(s) and no worktree"


def inventory(root, home):
    """Every linked worktree and every `wo-NNN` / `worktree-*` local branch. READ-ONLY.

    -> dict with `head`, `branch`, `linked` and `items`, or None when git cannot be read (not a
    repo, no git, a failing command). Never raises.
    """
    try:
        root = Path(root)
        entries = _entries(root)
        refs = git_ok(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        head = git_ok(root, "rev-parse", "--short", "HEAD")
        if entries is None or refs is None or head is None:
            return None
        current = (git_ok(root, "branch", "--show-current") or "").strip()
        open_nnns, resolved_nnns, known = wo_states(home)
        layout = load_layout(home)
        targets = _merge_targets(root, current, layout)
        claims = live_claims(main_home(root, home, entries), env_sprint_id())
        main_branch = entries[0]["branch"] if entries else None
        by_branch = {e["branch"]: e for e in entries[1:] if e["branch"]}
        names = [b for b in refs.splitlines() if b and b != main_branch and _managed(b)]
        items = []

        def _merge_state(tip, own=None):
            """-> (ahead, merged_into). `ahead` is 0 when the tip is merged into ANY target (the
            reap check reads it), else the count of commits HEAD lacks."""
            into = _merged_into(root, tip, targets, own)
            return (0 if into else _ahead(root, tip)), into

        def build(name, kind, entry):
            nnn = WO_BRANCH_RE.match(name).group(1) if kind == "wo" else None
            path = None
            if entry is not None and not entry["prunable"] and Path(entry["path"]).is_dir():
                path = entry["path"]
            if kind == "wo":
                wo = ("open" if nnn in open_nnns else "resolved" if nnn in resolved_nnns
                      else "missing" if known else "unknown")
            else:
                wo = "none"
            ahead, into = _merge_state(f"refs/heads/{name}", name)
            it = {"name": name, "kind": kind, "nnn": nnn, "branch": name, "path": path,
                  "registered": entry is not None,
                  "locked": bool(entry and entry["locked"]),
                  "lock_reason": entry["lock_reason"] if entry else "",
                  "prunable": bool(entry and entry["prunable"]),
                  "wo": wo, "ahead": ahead, "merged": ahead == 0, "merged_into": into,
                  "claimed": claims.get(nnn, "") if nnn else "", "sprint": False,
                  "target": _is_target(name, targets, layout),
                  "detached": False, "merged_head": into == targets[0][0],
                  "fresh": _fresh(root, name) if name and ahead == 0 else False,
                  "dirty": _dirty_count(path) if path and not (entry and entry["locked"]) else 0}
            it["class"], it["why"] = classify(it)
            return it

        for name in names:
            items.append(build(name, _managed(name), by_branch.get(name)))
        for e in entries[1:]:
            if e["branch"] and _managed(e["branch"]):
                continue
            label = e["branch"] or "(detached)"
            sprint = _is_sprint_entry(e)
            decl = _declared(e, root, layout) and not sprint     # a sprint's worktree is never declared, whatever a glob says
            p = Path(e["path"])
            name = (e["branch"] or f"{p.parent.name}/{p.name}") if decl else p.name
            ahead, into = None, None
            if decl and (e["branch"] or e["head"]):
                ahead, into = _merge_state(f"refs/heads/{e['branch']}" if e["branch"] else e["head"],
                                           e["branch"])
            it = {"name": name, "kind": "declared" if decl else "other", "nnn": None, "branch": label,
                  "path": e["path"] if not e["prunable"] and Path(e["path"]).is_dir() else None,
                  "registered": True, "locked": e["locked"], "lock_reason": e["lock_reason"],
                  "claimed": "", "sprint": sprint,
                  "prunable": e["prunable"], "wo": "none", "ahead": ahead, "merged": ahead == 0,
                  "merged_into": into, "merged_head": into == targets[0][0],
                  "target": _is_target(e["branch"], targets, layout),
                  "detached": e["branch"] is None, "fresh": False, "dirty": 0}
            if decl and it["path"] and it["merged"]:
                it["fresh"] = _fresh_worktree(it["path"], root, e["branch"])
            if it["path"] and not e["locked"]:
                it["dirty"] = _dirty_count(it["path"])
            it["class"], it["why"] = classify(it)
            items.append(it)
        return {"root": posix(root), "head": head.strip(), "branch": current,
                "linked": is_linked(root), "items": items}
    except Exception:
        return None


def findings(inv):
    """The canary's view of an inventory: `worktree-reapable` and `worktree-abandoned` items.

    A dirty worktree is a finding only when its work-order is resolved or missing (it is somebody's
    leftover); dirty with an open order is live work and is not.
    """
    out = []
    for it in (inv or {}).get("items", []):
        what = it["name"] if it["path"] is None else f"{it['name']} ({posix(it['path'])})"
        target = f"WO-{it['nnn']}" if it["nnn"] else "a worktree-* branch"
        if it["class"] == "reapable":
            slice_branch = it["nnn"] and it["name"] != f"wo-{it['nnn']}"   # `reap NNN` would take the order's other slices too
            cmd = (f"worktree.py reap {it['name'] if slice_branch else it['nnn']}"
                   if it["nnn"] else "worktree.py reap --merged")
            out.append({"kind": "worktree-reapable", "name": it["name"], "wo": target if it["nnn"] else "",
                        "has_worktree": it["path"] is not None,
                        "finding": f"{what} is merged into "
                                   f"{it.get('merged_into') or inv['branch'] or 'HEAD'} and clean but "
                                   f"still present -> run `{cmd}`"})
        elif it["class"] == "abandoned" or (it["class"] == "dirty" and it["kind"] == "wo"
                                            and it["wo"] in ("resolved", "missing")):
            detail = it["why"] if it["class"] == "abandoned" else \
                f"{it['why']} and WO-{it['nnn']} is {it['wo']}"
            out.append({"kind": "worktree-abandoned", "name": it["name"], "wo": target if it["nnn"] else "",
                        "has_worktree": it["path"] is not None,
                        "finding": f"{what} holds work that is not merged ({detail}) -> the operator "
                                   f"decides: merge it, or remove it by hand ({target} has no one "
                                   f"to finish it)"})
    return out


# ----------------------------------------------------------------------------------- status
def render_status(inv):
    lines = [f"worktrees - root {inv['root']}, on {inv['branch'] or '(detached)'} @ {inv['head']}"]
    if not inv["items"]:
        lines.append("  none: no linked worktree and no wo-NNN / worktree-* branch")
    order = {c: i for i, c in enumerate(("reapable", "abandoned", "dirty", "in flight"))}
    for it in sorted(inv["items"], key=lambda i: (order[i["class"]], i["name"])):
        where = it["path"] if it["path"] else "(branch only)"
        wo = f", WO {it['wo']}" if it["kind"] == "wo" else ""
        lines.append(f"  {it['class']:<9}  {it['name']}  {where}  [{it['why']}{wo}]")
    return lines


def cmd_status(root, home, as_json):
    try:
        load_layout(home)
    except LayoutError as e:
        print(f"worktree: {e}", file=sys.stderr)
        return 1
    inv = inventory(root, home)
    if inv is None:
        print(f"worktree: git could not be read at {posix(root)} (not a repository, or git failed)",
              file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(inv, indent=2, ensure_ascii=False))
    else:
        print("\n".join(render_status(inv)))
    return 0


# --------------------------------------------------------------------------------------- new
def ensure_ignored(root, rel=WORKTREES_REL):
    """Make the repo-relative directory `rel` (default `.claude/worktrees/`) ignored.
    -> True when a line was appended."""
    rc, _, _ = git(root, "check-ignore", "-q", f"{rel}/x/")
    if rc == 0:
        return False
    path = Path(root) / ".gitignore"
    data = path.read_bytes() if path.exists() else b""
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    if data and not data.endswith(b"\n"):
        data += eol
    data += (IGNORE_COMMENT + "\n" + f"{rel}/" + "\n").encode("utf-8").replace(b"\n", eol)
    path.write_bytes(data)
    return True


def _slice_file(home, nnn, sid):
    """The slice file `S<n>-*.md` of folder order `nnn` under `home`, or None."""
    wo_dir = Path(home) / "work-orders"
    try:
        for sub in wo_dir.iterdir():
            m = WO_DIR_RE.match(sub.name)
            if m and m.group(1) == nnn and sub.is_dir():
                for f in sorted((sub / "slices").glob(f"{sid}-*.md")) + sorted((sub / "slices").glob(f"{sid}.md")):
                    return f
    except OSError:
        pass
    return None


def write_slice_marker(wt_path, nnn, sid):
    """Record which slice this worktree is for, in the worktree's own git dir (untracked, removed with the
    worktree). The edit hook (slice_guard.py) reads it. -> the marker path, or None when git gave no dir."""
    out = git_ok(wt_path, "rev-parse", "--absolute-git-dir")
    if not out or not out.strip():
        return None
    marker = Path(out.strip()) / SLICE_MARKER
    marker.write_text(f"WO-{nnn}/{sid}\n", encoding="utf-8")
    return marker


def _own_claim(mhome, nnn, sid):
    """True when `<home>/sprint/claims/WO-<nnn>.json` is a claim of sprint `sid`."""
    try:
        rec = _cr().load_json(Path(mhome) / "sprint" / "claims" / f"WO-{nnn}.json")
    except (OSError, ValueError):
        return False
    return isinstance(rec, dict) and rec.get("sprint") == sid


def _claim_refusal(mhome, nnn):
    """Why a worktree for order `nnn` may not be made by this caller (the claims are read from the main home), or "". A named sprint's
    session (GITOS_SPRINT_ID) makes worktrees only for the orders it claims; any other caller, the interactive window included, only
    for orders no other live sprint claims."""
    own = env_sprint_id()
    held = live_claims(mhome, own).get(nnn)
    if held:
        return f"WO-{nnn} is claimed by {held}: not made a worktree for here"
    if own and not _own_claim(mhome, nnn, own):
        return f'WO-{nnn} is not one of the orders sprint "{own}" claims: a sprint works only its own orders'
    return ""


def cmd_new(root, home, nnn, slice_id=None):
    if toplevel(root) is None:
        print(f"worktree: {posix(root)} is not a git repository -> run `git init` first",
              file=sys.stderr)
        return 2
    sprint = sprint_of(root)
    if is_linked(root) and not sprint:
        print(f"worktree: {posix(root)} is itself a linked worktree -> run this from the main "
              f"checkout; worktrees do not nest", file=sys.stderr)
        return 1
    try:
        layout = load_layout(home)
    except LayoutError as e:
        print(f"worktree: {e}", file=sys.stderr)
        return 1
    open_nnns, resolved_nnns, known = wo_states(home)
    if nnn not in open_nnns:
        why = ("is resolved" if nnn in resolved_nnns else
               "has no file" if known else "cannot be found (no work-orders/ under the home)")
        print(f"worktree: WO-{nnn} {why} -> a worktree is made only for an open work-order "
              f"(under {posix(home)}/work-orders/)", file=sys.stderr)
        return 1
    entries = _entries(root) or []
    why = _claim_refusal(main_home(root, home, entries), nnn)
    if why:
        print(f"worktree: {why}", file=sys.stderr)
        return 1
    if slice_id and _slice_file(home, nnn, slice_id) is None:
        print(f"worktree: WO-{nnn} has no slice {slice_id} (--slice names a slice of a folder order: "
              f"work-orders/WO-{nnn}/slices/{slice_id}-<name>.md)", file=sys.stderr)
        return 1
    if git_ok(root, "rev-parse", "--verify", "-q", "HEAD") is None:
        print("worktree: this repository has no commit yet -> commit once, then retry",
              file=sys.stderr)
        return 1
    branch = f"wo-{nnn}-{slice_id.lower()}" if slice_id else f"wo-{nnn}"
    path = (worker_root(root) if sprint else layout_root(root, layout)) / branch
    for e in entries[1:]:
        if e["branch"] == branch:
            if _under(e["path"], path.parent) is None:
                print(f"worktree: {branch} already has a worktree at {posix(Path(e['path']))}, outside {posix(path.parent)} (where this "
                      f"caller's worktrees go): it belongs to another sprint or window, so it is not reused -> leave it to its owner",
                      file=sys.stderr)
                return 1
            print(f"worktree: {branch} already exists, nothing changed"
                  + (" but the slice marker" if slice_id else ""))
            if slice_id:
                write_slice_marker(Path(e["path"]), nnn, slice_id)
            print(posix(Path(e["path"])))
            return 0
    if git_ok(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}") is not None:
        print(f"worktree: branch {branch} exists but has no worktree -> not recreating it over "
              f"existing work; check it with `git log {branch}` and decide", file=sys.stderr)
        return 1
    for e in entries:
        if not _same(e["path"], root) and _under(path, e["path"]) is not None:
            print(f"worktree: {posix(path)} would be inside the worktree {posix(e['path'])} -> a worktree is never made "
                  f"inside another one; change `root` in worktrees.json", file=sys.stderr)
            return 1
    if path.exists():
        print(f"worktree: {posix(path)} exists but is not a worktree of this repository -> "
              f"move or remove it, then retry", file=sys.stderr)
        return 1
    inside = _under(path.parent, root)
    if inside and inside != "." and ensure_ignored(root, inside):
        print(f"worktree: added `{inside}/` to .gitignore (it was not ignored); commit that "
              f"line with your next state edit")
    rc, _, err = git(root, "worktree", "add", "-b", branch, str(path), "HEAD")
    if rc != 0:
        print(f"worktree: git refused: {err.strip() or 'worktree add failed'}", file=sys.stderr)
        return 1
    print(f"worktree: created {branch} from HEAD @ {(git_ok(root, 'rev-parse', '--short', 'HEAD') or '').strip()}")
    if slice_id:
        marker = write_slice_marker(path, nnn, slice_id)
        print(f"worktree: slice marker WO-{nnn}/{slice_id} " + (f"written to {posix(marker)}" if marker else
              "NOT written (git gave no git dir); the edit hook will not bind this worktree"))
    print(posix(path.resolve()))
    print("worktree: dispatch the implementer with this path as its working root; keep the "
          "orchestrator's own cwd on the main checkout")
    return 0


# -------------------------------------------------------------------------------------- reap
def _inside(cwd, path):
    try:
        a, b = os.path.normcase(os.path.realpath(cwd)), os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


_REPARSE, _DIRECTORY = 0x400, 0x10
BS = chr(92)
EXT_PREFIX = BS * 2 + "?" + BS      # the Windows extended-length prefix: two backslashes, a question mark, a backslash
UNC_PREFIX = EXT_PREFIX + "UNC" + BS
LONG_PATH = 260


def _ext(path, always=False):
    """On Windows the extended-length form of `path` (no 260-character limit) when it is long (or `always`); a short path,
    and any path elsewhere, as given."""
    p = str(path)
    if os.name != "nt" or p.startswith(EXT_PREFIX):
        return p
    p = os.path.abspath(p)
    if not always and len(p) < LONG_PATH - 20:
        return str(path)
    return UNC_PREFIX + p[2:] if p.startswith(BS * 2) else EXT_PREFIX + p


def _plain(path):
    """The inverse of `_ext`."""
    p = str(path)
    if p.startswith(UNC_PREFIX):
        return BS * 2 + p[len(UNC_PREFIX):]
    return p[len(EXT_PREFIX):] if p.startswith(EXT_PREFIX) else p


def _link_kind(path):
    """'dir' / 'file' when `path` is a symlink or a Windows reparse point (junction), else None.
    Never follows the link."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    attrs = getattr(st, "st_file_attributes", 0)
    if os.path.islink(path) or attrs & _REPARSE:
        if attrs & _DIRECTORY:
            return "dir"
        return "dir" if (not attrs and os.path.isdir(path)) else "file"
    return None


class UnreadableDir(OSError):
    """A directory under a worktree could not be listed, so a link under it could not be checked."""

    def __init__(self, path, why):
        super().__init__(f"{path}: {why}")
        self.path = path


def _walk_links(top):
    """Every link under `top`, found without following any: -> [path]. A link is reported and not
    entered; only real directories are. A directory that cannot be listed raises UnreadableDir naming it:
    skipping it would leave a link under it unchecked."""
    top = str(top)
    found, stack = [], [top]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(_ext(cur)) as it:
                children = [(os.path.join(cur, e.name), e.name) for e in it]
        except OSError as e:
            raise UnreadableDir(cur, e.strerror or e) from e
        for full, name in children:
            if cur == top and name == ".git":
                continue
            if _link_kind(_ext(full)):
                found.append(full)
            elif os.path.isdir(_ext(full)):
                stack.append(full)
    return found


def _unlink(path):
    """Remove the link itself (never its target). True when it is gone."""
    path = _ext(path)
    kind = _link_kind(path)
    for fn in ((os.rmdir, os.unlink) if kind == "dir" else (os.unlink, os.rmdir)):
        try:
            fn(path)
            return not os.path.lexists(path)
        except OSError:
            continue
    return False


def link_guard(worktree):
    """Unlink every link inside `worktree` whose target resolves outside it.
    -> (unlinked paths, paths that could not be unlinked). Raises UnreadableDir, before anything is
    unlinked, when a directory in it cannot be listed."""
    base = os.path.normcase(os.path.realpath(worktree))
    done, failed = [], []
    for link in _walk_links(worktree):
        target = os.path.normcase(_plain(os.path.realpath(_ext(link))))
        try:
            outside = os.path.commonpath([base, target]) != base
        except ValueError:
            outside = True
        if not outside:
            continue
        (done if _unlink(link) else failed).append(link)
    return done, failed


def _archive(root, home, it, archive_home=None):
    """Copy each `archive` directory that exists in the worktree to
    `<archive_home or home>/worktree-archive/<name>/<dir>`. -> (copied rel dirs, error text or None). Links inside are
    skipped, never followed."""
    layout = load_layout(home)
    if not layout["archive"]:
        return [], None
    dest_base = Path(archive_home or home) / ARCHIVE_DIR / re.sub(r"[^\w.-]+", "-", it["name"])
    # an archive kept outside this worktree (land step 0) must not edit this worktree's .gitignore: land refuses a dirty tree
    ignore_rel = None if archive_home else _under(Path(home) / ARCHIVE_DIR, root)
    copied = []

    def skip_links(d, names):
        return [n for n in names if _link_kind(os.path.join(d, n))]

    for rel in layout["archive"]:
        src = Path(it["path"]) / rel
        if _link_kind(src) or not src.is_dir():
            continue
        try:
            if ignore_rel and ignore_rel != ".":
                ensure_ignored(root, ignore_rel)
            shutil.copytree(src, dest_base / rel, ignore=skip_links, dirs_exist_ok=True)
        except (OSError, shutil.Error) as e:
            return copied, f"archive of {rel} failed: {e}"
        copied.append(rel)
    return copied, None


def _longest_path(top):
    """The length of the longest path under `top` (the walk never follows a link), stopping once one is past
    LONG_PATH; 0 when nothing could be read."""
    best, stack = len(_plain(top)), [_ext(top, True)]
    while stack and best <= LONG_PATH:
        try:
            with os.scandir(stack.pop()) as entries:
                for e in entries:
                    best = max(best, len(_plain(e.path)))
                    if not _link_kind(e.path) and e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
        except OSError:
            continue
    return best


def _remove_tree(top):
    """Delete the directory `top` and everything in it through the extended-length form of every path. A link inside
    is unlinked and never followed. -> None when it is gone, else a one-line reason."""
    def walk(d):
        with os.scandir(d) as entries:
            for e in list(entries):
                if _link_kind(e.path):
                    if not _unlink(e.path):
                        raise OSError(f"cannot unlink {_plain(e.path)}")
                elif e.is_dir(follow_symlinks=False):
                    walk(e.path)
                else:
                    try:
                        os.unlink(e.path)
                    except PermissionError:
                        os.chmod(e.path, 0o666)
                        os.unlink(e.path)
        try:
            os.rmdir(d)
        except PermissionError:
            os.chmod(d, 0o777)
            os.rmdir(d)
    top = _ext(top, True)
    try:
        if _link_kind(top):
            return "it is a link, not a directory" if not _unlink(top) else None
        if os.path.lexists(top):
            walk(top)
    except OSError as e:
        return str(e)
    return None if not os.path.lexists(top) else "it is still there"


def _remove_worktree(root, it):
    """`git worktree remove` for one worktree, with the long-path fallbacks (see LONG PATHS in the module docstring).
    -> (ok, messages when it was removed (each fallback taken named), git's error text when it was not)."""
    path = it["path"]
    rc, _, err = git(root, "worktree", "remove", path)
    if rc == 0:
        return True, [f"removed worktree {path}"], ""
    long_named = "filename too long" in err.lower()
    if it["locked"] or it["dirty"] or not (long_named or (os.name == "nt" and _longest_path(path) > LONG_PATH)):
        return False, [], err
    why = "git said the filename is too long" if long_named else f"a path in it is over {LONG_PATH} characters"
    msgs = [f"{why}: retried with core.longpaths"]
    out = git_ok(path, "-c", "core.longpaths=true", "status", "--porcelain")
    if out is None or out.strip():
        return False, [], ("the worktree could not be read with core.longpaths=true" if out is None else
                           "with core.longpaths=true it shows changed or untracked files, so it is not forced")
    rc, _, ferr = git(root, "-c", "core.longpaths=true", "worktree", "remove", "--force", path)
    if rc == 0:
        msgs.append(f"removed worktree {path} with --force (clean, checked with core.longpaths=true)")
    if os.path.lexists(_ext(path)):
        if os.name != "nt" or _inside(root, path):
            return False, [], (ferr or err).strip()
        left = _remove_tree(path)
        if left:
            return False, [], f"the leftover directory could not be removed: {left}"
        msgs.append("removed the leftover directory through the extended-length prefix")
    git(root, "worktree", "prune")
    msgs.append("pruned worktree records")
    return True, msgs, ""


def _is_slice(it):
    return it["kind"] == "wo" and it["name"] != f"wo-{it['nnn']}"


def _reap_one(root, it, current, home=None, by_order=False, archive_home=None):
    """Reap one inventory item. -> (ok, [message lines]). Refuses on anything git or we object to. `by_order`: the operator named
    the order (`reap NNN`), not this worktree: a slice that has had no commit yet is then a worker about to start, not a leftover."""
    name = it["name"]
    if it.get("target"):
        return False, [f"worktree: {name} NOT reaped: it is a merge target (the default or an "
                       f"integration branch), where work lands"]
    if it.get("sprint"):
        return False, [f"worktree: {name} NOT reaped: it is a sprint's worktree; the sprint driver removes it, and only "
                       f"when its branch is in the main branch and it is clean"]
    if it.get("claimed"):
        return False, [f"worktree: {name} NOT reaped: WO-{it['nnn']} is claimed by {it['claimed']}; reap it once that "
                       f"sprint has finished (its claim goes with it)"]
    if it["ahead"] != 0:
        n = "an unknown number of" if it["ahead"] is None else str(it["ahead"])
        return False, [f"worktree: {name} NOT reaped: {n} commit(s) are not merged into "
                       f"{current or 'HEAD'}. Merge it, or if it is abandoned remove it by hand "
                       f"(`git worktree remove`, `git branch -D` are yours to run, not this tool's)"]
    if by_order and _is_slice(it) and it["fresh"] and it["wo"] == "open":
        return False, [f"worktree: {name} NOT reaped: it has no commits of its own yet and WO-{it['nnn']} is open (a worker "
                       f"may be about to start in it) -> `worktree.py reap {name}` names it and removes it anyway"]
    if it["path"] and _inside(Path.cwd(), it["path"]):
        return False, [f"worktree: {name} NOT reaped: this process's working directory is inside "
                       f"it. `cd` to {posix(root)} and run it again"]
    msgs = []
    if it["registered"] and it["path"]:
        if not it["dirty"] and not it["locked"]:
            # before the removal; a dirty or locked tree is left to git's own refusal, untouched
            if home is not None:
                copied, bad = _archive(root, home, it, archive_home)
                if bad:
                    return False, [f"worktree: {name} NOT reaped: {bad}"]
                if copied:
                    msgs.append(f"archived {', '.join(copied)} to {posix(Path(archive_home or home) / ARCHIVE_DIR)}")
            try:
                gone, stuck = link_guard(it["path"])
            except UnreadableDir as e:
                return False, [f"worktree: {name} NOT reaped: cannot read the directory {posix(e.path)}"
                               f" under it, so a link in it could not be checked -> make it readable "
                               f"(or remove it by hand), then retry"]
            if stuck:
                return False, [f"worktree: {name} NOT reaped: cannot unlink {posix(stuck[0])}, a link "
                               f"that points outside the worktree -> remove that link by hand, then retry"]
            if gone:
                msgs.append(f"unlinked {len(gone)} link(s) pointing outside it")
        ok, done, err = _remove_worktree(root, it)
        if not ok:
            hint = ("it is locked: whoever locked it decides (`git worktree unlock`, then retry)"
                    if it["locked"] else
                    "remove what is left of it by hand, then run `git worktree prune` and reap again"
                    if "leftover directory" in err else
                    "commit or discard what is in it, then retry")
            return False, [f"worktree: {name} NOT reaped: git refused: {err.strip()}",
                           f"          -> {hint}"]
        msgs.extend(done)
    git(root, "worktree", "prune")
    if it.get("detached") or not it["branch"] or it["branch"] == "(detached)":
        return True, [f"worktree: reaped {name} ({'; '.join(msgs) or 'nothing to remove'})"]
    # `-D`, not `-d`: the merged check above already passed (against HEAD, the default branch or an
    # integration branch). `-d` only looks at the current branch and would refuse work that landed
    # elsewhere.
    rc, out, err = git(root, "branch", "-D", it["branch"])
    if rc != 0:
        return False, msgs + [f"worktree: {name} branch NOT deleted: git refused: "
                              f"{(err or out).strip().splitlines()[0] if (err or out).strip() else ''}"]
    msgs.append(f"deleted branch {it['branch']}")
    return True, [f"worktree: reaped {name} ({'; '.join(msgs)})"]


def cmd_reap(root, home, target, merged_all):
    if toplevel(root) is None:
        print(f"worktree: {posix(root)} is not a git repository", file=sys.stderr)
        return 2
    sprint = sprint_of(root)
    if is_linked(root) and not sprint:
        print(f"worktree: {posix(root)} is a linked worktree -> reap from the main checkout, "
              f"whose HEAD is what the branch is merged into", file=sys.stderr)
        return 1
    if target and SPRINT_BRANCH_RE.fullmatch(target):
        print(f"worktree: {target} NOT reaped: it is a sprint's worktree and branch; the sprint driver removes them, and only "
              f"when the branch is in the main branch and the worktree is clean", file=sys.stderr)
        return 1
    try:
        load_layout(home)
    except LayoutError as e:
        print(f"worktree: {e}", file=sys.stderr)
        return 1
    inv = inventory(root, home)
    if inv is None:
        print("worktree: git could not be read", file=sys.stderr)
        return 2
    current = inv["branch"]
    scope = worker_root(root) if sprint else None      # a sprint's session reaps only its own workers
    if scope is not None:
        inv["items"] = [i for i in inv["items"] if i["path"] and _under(i["path"], scope) is not None]
    by_order = bool(target) and re.fullmatch(r"\d{3}", target) is not None
    if merged_all:
        todo = [i for i in inv["items"] if i["class"] == "reapable"]
        if not todo:
            print("worktree: nothing to reap")
            return 0
    else:
        wanted = f"wo-{target}" if by_order else target
        if by_order:      # an order number reaps the order's own worktree and every slice's
            todo = [i for i in inv["items"] if i["kind"] == "wo" and i["nnn"] == target]
        else:
            todo = [i for i in inv["items"] if wanted in (i["branch"], i["name"]) and i["kind"] != "other"]
        if not todo:
            print(f"worktree: no worktree or branch named {wanted} to reap" +
                  (f" under {posix(scope)}" if scope is not None else ""), file=sys.stderr)
            return 1
    status = 0
    for it in todo:
        ok, msgs = _reap_one(root, it, current, home, by_order)
        for m in msgs:
            print(m, file=None if ok else sys.stderr)
        status = status or (0 if ok else 1)
    return status


# ------------------------------------------------------------------------------- the merge lock
def lock_path(mhome):
    return Path(mhome) / "sprint" / LOCK_FILE


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exe_base(name):
    return os.path.basename(str(name or "").replace("\\", "/")).lower()


def is_session(name, cmdline=""):
    """Whether a process with this executable name (and command line, when it could be read) is the Claude Code session."""
    base = _exe_base(name)
    if base in SESSION_EXE_NAMES:
        return True
    cl = str(cmdline or "").replace("\\", "/").lower()
    return base in SESSION_NODE_NAMES and any(m in cl for m in SESSION_CMDLINE_MARKS)


def _win_process_table():
    """{pid: (parent pid, executable name)} of every process now (a Toolhelp32 snapshot)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)               # TH32CS_SNAPPROCESS
    if snap in (None, 0, ctypes.c_void_p(-1).value):
        return {}
    table = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return table


def _posix_parent_of(pid):
    """-> (parent pid, executable name) from `/proc/<pid>/stat` (the parent is field 4), else `ps`; (None, "") when unknown."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        head, _, tail = raw.rpartition(")")
        return int(tail.split()[1]), head.partition("(")[2]
    except (OSError, ValueError, IndexError):
        pass
    try:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout
        ppid, _, comm = out.strip().partition(" ")
        return int(ppid), comm.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, ""


def _posix_cmdline_of(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        pass
    try:
        return subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def default_parent_of():
    """-> `parent_of(pid) -> (parent pid or None, executable name)` for the processes of this machine now."""
    if sys.platform == "win32":
        table = _win_process_table()
        return lambda pid: table.get(pid, (None, ""))
    return _posix_parent_of


def find_session(parent_of=None, cmdline_of=None, start=None):
    """The pid of the nearest ancestor of process `start` (default: this one) that is the Claude Code session, else None. The walk is
    bounded and stops at pid 0 or 1, an unknown parent, or a cycle. `parent_of` and `cmdline_of` are the seams of a test; the
    command line is only read for a `node`, and not at all on Windows."""
    if parent_of is None:
        parent_of = default_parent_of()
        if cmdline_of is None and sys.platform != "win32":
            cmdline_of = _posix_cmdline_of
    cmdline_of = cmdline_of or (lambda pid: "")
    cur = os.getpid() if start is None else start
    seen = {cur}
    ppid = parent_of(cur)[0]
    for _ in range(SESSION_WALK_STEPS):
        if not isinstance(ppid, int) or isinstance(ppid, bool) or ppid <= 1 or ppid in seen:
            return None
        seen.add(ppid)
        nxt, name = parent_of(ppid)
        if is_session(name, cmdline_of(ppid) if _exe_base(name) in SESSION_NODE_NAMES else ""):
            return ppid
        ppid = nxt
    return None


def holder_identity(pid_arg=None, parent_of=None, cmdline_of=None):
    """-> (holder, pid, pid_known). `holder` is the sprint this process belongs to, else `interactive`. `pid` is the process whose
    life keeps the lock: the sprint's driver (GITOS_SPRINT_PID), else `--pid`, else the nearest ancestor that is the Claude Code
    session; None when there is none (the shell that ran this command is never used: it is gone before the merge is)."""
    sid = env_sprint_id()
    env_pid = os.environ.get("GITOS_SPRINT_PID", "")
    if sid and env_pid.isdigit() and int(env_pid) > 0 and pid_arg is None:
        return sid, int(env_pid), True
    if pid_arg is not None:
        return sid or INTERACTIVE, pid_arg, True
    return sid or INTERACTIVE, find_session(parent_of, cmdline_of), True


def _read_lock(path):
    """-> (record, state): state "free" (no file), "held" (a readable record) or "unreadable" (a file that stays unreadable)."""
    for _ in range(6):
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return None, "free"
        except OSError:                      # being removed or replaced right now
            time.sleep(0.05)
            continue
        try:
            rec = json.loads(text)
        except ValueError:
            time.sleep(0.05)
            continue
        if isinstance(rec, dict) and isinstance(rec.get("holder"), str) and isinstance(rec.get("pid"), int) \
                and not isinstance(rec.get("pid"), bool):
            return rec, "held"
        time.sleep(0.05)
    return None, "unreadable"


def _create_lock(path, rec):
    """Create the lock file whole, or not at all. -> True when this call created it, False when it is there already.
    A hard link of a finished file is atomic and exclusive; where links are not available the file is created exclusively
    and then written (a reader that meets it empty waits and reads again)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(rec) + "\n").encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_bytes(data)
    try:
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            return True
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _remove_lock(path):
    """Remove the lock file; a reader that has it open delays that on Windows, so a refusal is retried for a moment."""
    for i in range(40):
        try:
            Path(path).unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.05)
    return False


@contextlib.contextmanager
def _takeover_guard(path, wait=10.0):
    """Hold `<lock>.takeover` (created exclusively) while a dead lock is judged again and replaced, so two processes that both found it
    dead cannot both replace it. A guard older than GUARD_STALE_S belongs to a process that died inside it and is removed. Yields
    False when the guard could not be had within `wait` seconds."""
    g = Path(path).with_name(Path(path).name + ".takeover")
    deadline = time.monotonic() + wait
    got = False
    while not got:
        try:
            os.close(os.open(g, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            got = True
        except FileExistsError:
            try:
                if time.time() - g.stat().st_mtime > GUARD_STALE_S:
                    g.unlink()
                    continue
            except OSError:
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        except OSError:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
    try:
        yield got
    finally:
        if got:
            try:
                g.unlink()
            except OSError:
                pass


def _who(rec):
    step = f", at {rec['step']}" if rec.get("step") else ""
    return f'"{rec.get("holder")}" (pid {rec.get("pid")}, since {rec.get("since", "?")}{step})'


def _lock_step(mhome, holder, pid, step):
    """Name the `land` step that is running in the lock record this process holds (`status` and the refusals to others show it).
    The record is replaced whole; one that is not this holder's, or cannot be read, is left alone. A failure here never stops a land."""
    path = lock_path(mhome)
    cur, state = _read_lock(path)
    if state != "held" or cur.get("holder") != holder or cur.get("pid") != pid:
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.step")
    try:
        tmp.write_text(json.dumps({**cur, "step": step}) + "\n", encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(tmp, path)
                return
            except OSError:                  # a reader has the file open (Windows)
                time.sleep(0.05)
    except OSError:
        pass
    try:
        tmp.unlink()
    except OSError:
        pass


def lock_acquire(mhome, holder, pid, wait=0.0, say=None):
    """Take the merge lock of the home `mhome`. -> (ok, message, the record written or None). A lock held by a live process is waited on for `wait` seconds;
    a dead one (the process is gone, or its pid now belongs to another process) is taken over and the message says so."""
    path = lock_path(mhome)
    rec = {"holder": holder, "pid": pid, "start": _cr().process_start(pid), "since": _utc_now()}
    deadline = time.monotonic() + max(0.0, wait)
    announced = False
    while True:
        if _create_lock(path, rec):
            return True, f"acquired the merge lock as {holder} (pid {pid})", rec
        cur, state = _read_lock(path)
        if state == "free":
            continue
        if state == "unreadable":
            return False, (f"the merge lock {posix(path)} exists but cannot be read -> if no merge is running, remove it by "
                           f"hand, then retry"), None
        if cur.get("holder") == holder and cur.get("pid") == pid:
            return False, (f"you already hold the merge lock (since {cur.get('since', '?')}): an earlier land or acquire "
                           f"did not release it -> `worktree.py lock release`, then retry"), None
        if _live(cur):
            if time.monotonic() >= deadline:
                return False, f"the merge lock is held by {_who(cur)}: wait for it, or retry with `--wait S`", None
            if not announced and say:
                say(f"worktree: the merge lock is held by {_who(cur)}; waiting up to {wait:g}s")
                announced = True
            time.sleep(0.2)
            continue
        with _takeover_guard(path) as got:
            if not got:
                if time.monotonic() >= deadline:
                    return False, f"the merge lock is stale ({_who(cur)}) but its takeover guard stayed busy; retry", None
                continue
            again, state = _read_lock(path)
            if state != "held" or again != cur or _live(again):
                continue                      # it changed while the guard was being had: judge it again
            if not _remove_lock(path):
                return False, f"the stale merge lock {posix(path)} could not be removed -> remove it by hand", None
            if _create_lock(path, rec):
                return True, (f"took over a stale merge lock held by {_who(cur)}: that process is gone; "
                              f"acquired it as {holder} (pid {pid})"), rec


def lock_release(mhome, holder, pid, pid_known):
    """Release the merge lock. -> (ok, message). Only its holder releases it; a lock whose process is gone is garbage and anyone may
    remove it, under the takeover guard and judged again once the guard is had (a taker may have replaced it meanwhile, and a fresh lock
    must not be removed as the stale one). `pid_known`: compare the pid as well as the holder name."""
    path = lock_path(mhome)
    for _ in range(5):
        cur, state = _read_lock(path)
        if state == "free":
            return True, "no merge lock is held"
        if state == "unreadable":
            return False, f"the merge lock {posix(path)} cannot be read -> remove it by hand if no merge is running"
        mine = cur.get("holder") == holder and (not pid_known or cur.get("pid") == pid)
        if not mine and _live(cur):
            return False, f"the merge lock is held by {_who(cur)}, not by {holder}: only its holder releases it"
        if mine:
            if not _remove_lock(path):
                return False, f"the merge lock {posix(path)} could not be removed"
            return True, "released the merge lock"
        with _takeover_guard(path) as got:
            if not got:
                return False, f"the merge lock is stale ({_who(cur)}) but its takeover guard stayed busy; retry"
            again, state = _read_lock(path)
            if state == "free":
                return True, "no merge lock is held"
            if state != "held" or again != cur:
                continue                      # it changed while the guard was being had: judge it again
            if not _remove_lock(path):
                return False, f"the merge lock {posix(path)} could not be removed"
            return True, f"removed a stale merge lock held by {_who(cur)} (that process is gone)"
    return False, "the merge lock kept changing while it was being released; retry"


def cmd_lock(root, home, action, wait, pid_arg):
    set_home = os.environ.get("GITOS_SPRINT_HOME", "")
    if set_home and not _is_gitos_home(set_home):
        print(f"worktree: lock {action}: GITOS_SPRINT_HOME is {set_home}, which is not a gitos home (a directory with INDEX.md beside "
              f"work-orders/ or sprint/); nothing was done -> point it at the main checkout's home, or unset it", file=sys.stderr)
        return 1
    mhome = main_home(root, home)
    path = lock_path(mhome)
    if action == "status":
        cur, state = _read_lock(path)
        if state == "free":
            print(f"worktree: merge lock: free ({posix(path)})")
        elif state == "unreadable":
            print(f"worktree: merge lock: {posix(path)} exists but cannot be read", file=sys.stderr)
            return 1
        else:
            print(f"worktree: merge lock: held by {_who(cur)}" + ("" if _live(cur) else " [stale: that process is gone]"))
        return 0
    holder, pid, known = holder_identity(pid_arg)
    if pid is None:
        print(f"worktree: lock {action}: {NO_SESSION_MSG}", file=sys.stderr)
        return 1
    if action == "acquire":
        ok, msg, _ = lock_acquire(mhome, holder, pid, wait, say=print)
    else:
        ok, msg = lock_release(mhome, holder, pid, known)
    print(f"worktree: {msg}", file=None if ok else sys.stderr)
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------- land
def default_branch(root):
    """The main branch of the repository at `root`: `main`, else `master`, else the branch the checkout is on ("" when detached)."""
    for name in ("main", "master"):
        if git_ok(root, "rev-parse", "--verify", "-q", f"refs/heads/{name}") is not None:
            return name
    return (git_ok(root, "branch", "--show-current") or "").strip()


def _tracked_changes(path):
    """The changed tracked files of a working tree (`git status`, untracked files left out); None when git cannot say."""
    out = git_ok(path, "-c", "core.longpaths=true", "status", "--porcelain", "--untracked-files=no")
    return None if out is None else [ln for ln in out.splitlines() if ln.strip()]


def _run(argv, cwd, timeout):
    """Run a command, merging stderr into stdout. -> (returncode, output); returncode None when it cannot start or times out (the
    whole process tree is then killed, on Windows too)."""
    rc, out, err, why = _spawn(argv, cwd, timeout)
    return (rc, out + err) if rc is not None else (None, why)


def _tail(text, n=25):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join("    " + ln for ln in lines[-n:])


def read_gate(main_root, mbranch, home_rel):
    """The declared gate command `<home>/sprint-gate.json` `{"command": [...], "timeout_s": N}` as the main branch has it (`git show`:
    never the sprint's own copy, which the sprint could have rewritten to pass). -> (command or None, timeout, problem). No file on the
    main branch is no gate; a file that is not that shape, or one git cannot read, is a problem, never a skipped gate."""
    rel = GATE_FILE if home_rel in ("", ".") else f"{home_rel}/{GATE_FILE}"
    label = f"{mbranch}:{rel}"
    rc, listed, err = git(main_root, "ls-tree", "--name-only", mbranch, "--", rel)
    if rc != 0:
        return None, 0, f"{label} could not be looked up ({(err or 'git gave no reason').strip().splitlines()[0]})"
    if not listed.strip():
        return None, 0, ""
    rc, text, err = git(main_root, "show", label)
    if rc != 0:
        return None, 0, f"{label} could not be read ({(err or 'git gave no reason').strip().splitlines()[0]})"
    try:
        data = json.loads(text.lstrip(chr(0xFEFF)))
    except ValueError as e:
        return None, 0, f"{label} is not valid JSON ({str(e).splitlines()[0] if str(e) else 'unreadable'})"
    cmd, t = (data.get("command"), data.get("timeout_s", GATE_DEFAULT_S)) if isinstance(data, dict) else (None, None)
    if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) and c for c in cmd)):
        return None, 0, f'{label} needs "command": a non-empty list of strings'
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
        return None, 0, f'{label}: "timeout_s" must be a positive number'
    return cmd, float(t), ""


def _gate(root, home, main_root, mbranch, step=lambda name: None):
    """Step 3: the canary, then the declared gate command (from the main branch), in the sprint worktree. -> "" or why nothing may land."""
    step("canary")
    rc, out = _run([sys.executable, str(SCRIPTS / "canary.py"), str(home)], root, CANARY_TIMEOUT_S)
    if rc != 0:
        return f"the canary is not clean ({'exit ' + str(rc) if rc is not None else out}):\n{_tail(out)}"
    cmd, timeout, problem = read_gate(main_root, mbranch, _under(home, root) or ".")
    if problem:
        return problem
    if cmd:
        step("gate")
        rc, out = _run(cmd, root, timeout)
        if rc != 0:
            return f"the gate command {cmd} failed ({'exit ' + str(rc) if rc is not None else out}):\n{_tail(out)}"
    return ""


def _abort_merge(root):
    if git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0:
        git(root, "merge", "--abort")


def _main_blocker(main_root, mbranch):
    """Why the main checkout cannot take a fast-forward right now (it is not on the main branch, or has changed tracked files), or ""."""
    cur = (git_ok(main_root, "branch", "--show-current") or "").strip()
    if cur != mbranch:
        return (f"the main checkout {posix(main_root)} is on {cur or '(detached)'}, not on {mbranch}; nothing landed -> "
                f"put it back on {mbranch}, then run land again")
    changes = _tracked_changes(main_root)
    if changes is None or changes:
        return (f"the main checkout {posix(main_root)} has uncommitted changes to tracked files; nothing landed (that window is "
                f"never merged over) -> commit or stash them, then run land again:\n{_tail(chr(10).join(changes or []))}")
    return ""


def _is_gitos_home(path):
    """A gitos home: a directory with `INDEX.md` beside `work-orders/` or `sprint/`."""
    p = Path(path)
    return p.is_dir() and (p / "INDEX.md").is_file() and ((p / "work-orders").is_dir() or (p / "sprint").is_dir())


def _reap_own_workers(root, home, archive_home=None):
    """Land step 0: reap the sprint's own merged, clean worker worktrees under `<sprint worktree>.worktrees/` (the reapable test and
    `_reap_one`'s refusals are `reap --merged`'s; nothing outside that folder is looked at). A worker's `archive` folders are copied
    to `archive_home` (the main home: the sprint worktree's own folder goes with that worktree). -> (lines reaped, lines skipped)."""
    try:
        load_layout(home)
    except LayoutError as e:
        return [], [f"worktrees were not looked at: {e}"]
    inv = inventory(root, home)
    if inv is None:
        return [], ["worktrees were not looked at: git could not be read"]
    scope = worker_root(root)
    done, skipped = [], []
    for it in inv["items"]:
        if not it["path"] or _under(it["path"], scope) is None or it["class"] != "reapable":
            continue
        ok, msgs = _reap_one(root, it, inv["branch"], home, archive_home=archive_home)
        (done if ok else skipped).extend(msgs)
    return done, skipped


def _land_locked(root, home, sid, main_root, mbranch, mhome):
    """Steps 1-4 of `land`, with the lock held; the lock record names the step that runs (merge, index, canary, gate, fast-forward).
    -> exit code."""
    step = lambda name: _lock_step(mhome, sid, os.getpid(), name)        # noqa: E731
    br = f"sprint-{sid}"
    err = lambda m: print(f"worktree: land: {m}", file=sys.stderr)       # noqa: E731
    # 0. the sprint's own finished worker worktrees go first, so the canary does not meet them
    done, skipped = _reap_own_workers(root, home, mhome)
    for m in skipped:
        print(f"worktree: land 0/4: {m}", file=sys.stderr)
    if done:
        print(f"worktree: land 0/4: reaped {len(done)} worker worktree(s) of {br}:")
        for m in done:
            print(f"    {m}")
    else:
        print("worktree: land 0/4: reaped nothing (no merged, clean worker worktree of this sprint)")
    dirty = git_ok(root, "status", "--porcelain")
    if dirty is None:
        err("git could not read the sprint worktree")
        return 1
    if dirty.strip():
        err(f"the sprint worktree has uncommitted or untracked files -> commit or remove them, then run land again:\n"
            f"{_tail(dirty)}")
        return 1
    # 1. the main branch into the sprint branch
    step("merge")
    rel = _under(home, root) or "."
    generated = {f"{rel}/INDEX.md".removeprefix("./"), f"{rel}/brain/wiki/index.md".removeprefix("./")}
    rc, out, e = git(root, "merge", "--no-edit", mbranch, timeout=MERGE_TIMEOUT)
    if rc != 0:
        unmerged = [ln.strip() for ln in (git_ok(root, "diff", "--name-only", "--diff-filter=U") or "").splitlines() if ln.strip()]
        merging = git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
        other = [f for f in unmerged if f not in generated]
        if not merging or other or not unmerged:
            _abort_merge(root)
            err("merging " + mbranch + " into " + br + " failed and was aborted: " +
                (f"conflicts in {', '.join(other)} (not generated files: resolve them by hand)" if other else
                 (e or out).strip().splitlines()[0] if (e or out).strip() else "git gave no reason"))
            return 1
        for f in unmerged:                    # a generated file: keep the sprint's, step 2 regenerates it
            if git(root, "checkout", "--ours", "--", f)[0] != 0 or git(root, "add", "--", f)[0] != 0:
                _abort_merge(root)
                err(f"could not set aside the generated conflict in {f}; the merge was aborted")
                return 1
    merging = git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    print(f"worktree: land 1/4: merged {mbranch} into {br}" + (" (a conflict in a generated file is regenerated next)" if merging else ""))
    # 2. regenerate the indexes
    step("index")
    paths = []
    if (home / "INDEX.md").is_file():
        rc, out = _run([sys.executable, str(SCRIPTS / "ledger_index.py"), str(home)], root, 120)
        if rc != 0:
            _abort_merge(root)
            err(f"ledger_index.py failed ({'exit ' + str(rc) if rc is not None else out}); nothing was landed:\n{_tail(out)}")
            return 1
        paths.append(f"{rel}/INDEX.md".removeprefix("./"))
    brain = Path(home) / "brain"
    brel = f"{rel}/brain/wiki".removeprefix("./")
    changed = git_ok(root, "diff", "--name-only", mbranch, "--", brel) or ""
    if (brain / "wiki").is_dir() and [c for c in changed.splitlines() if c.strip() and c.strip() != f"{brel}/index.md"]:
        rc, out = _run([sys.executable, str(SCRIPTS / "brain_lint.py"), str(brain), "--write-index"], root, 120)
        if rc != 0:
            _abort_merge(root)
            err(f"brain_lint.py --write-index failed ({'exit ' + str(rc) if rc is not None else out}); nothing was landed:\n"
                f"{_tail(out)}")
            return 1
        paths.append(f"{brel}/index.md")
    if paths and git(root, "add", "--", *paths)[0] != 0:
        _abort_merge(root)
        err("could not stage the regenerated indexes; nothing was landed")
        return 1
    if merging:
        rc, out, e = git(root, "commit", "--no-edit", timeout=MERGE_TIMEOUT)
    elif git(root, "diff", "--cached", "--quiet")[0] == 1:
        rc, out, e = git(root, "commit", "-m", f"land: regenerate the indexes before {br} lands", timeout=MERGE_TIMEOUT)
    else:
        rc, out, e = 0, "", ""
    if rc != 0:
        _abort_merge(root)
        err(f"the commit failed: {(e or out).strip()[:300]}")
        return 1
    print("worktree: land 2/4: indexes regenerated" + (" and committed" if paths else ""))
    if git(root, "merge-base", "--is-ancestor", br, mbranch)[0] == 0:
        print(f"worktree: land: nothing to land: {mbranch} already has everything on {br}")
        return 0
    # 3. the gate
    why = _gate(root, home, main_root, mbranch, step)
    if why:
        err(f"the gate refused; nothing landed on {mbranch}: {why}")
        return 1
    print("worktree: land 3/4: the canary and the gate command passed")
    # 4. the fast-forward, in the main checkout (checked again: it can change while the gate runs)
    step("fast-forward")
    why = _main_blocker(main_root, mbranch)
    if why:
        err(why)
        return 1
    before = (git_ok(main_root, "rev-parse", "--short", "HEAD") or "").strip()
    rc, out, e = git(main_root, "merge", "--ff-only", br, timeout=MERGE_TIMEOUT)
    if rc != 0:
        err(f"the fast-forward of {mbranch} to {br} was refused ({(e or out).strip().splitlines()[0] if (e or out).strip() else 'no reason'}); "
            f"{mbranch} may have moved since step 1 -> run land again")
        return 1
    after = (git_ok(main_root, "rev-parse", "--short", "HEAD") or "").strip()
    print(f"worktree: land 4/4: {mbranch} fast-forwarded {before} -> {after} ({br})")
    return 0


def cmd_land(root, home, wait, pid_arg):
    sid = sprint_of(root)
    if not sid:
        print("worktree: land runs in a named sprint's worktree (a linked worktree on branch sprint-<id>); in the main "
              "checkout take the merge lock with `worktree.py lock acquire`, merge and run the gate yourself, then "
              "`lock release`", file=sys.stderr)
        return 1
    if env_sprint_id() and env_sprint_id() != sid:
        print(f'worktree: land: this session is sprint "{env_sprint_id()}" but this worktree is sprint "{sid}"; it is not '
              f"landed from here", file=sys.stderr)
        return 1
    entries = _entries(root)
    main_root = main_checkout(root, entries)
    mbranch = default_branch(main_root) if main_root else ""
    if not mbranch:
        print("worktree: land: the main branch cannot be told (the main checkout is detached and has no main or master)",
              file=sys.stderr)
        return 1
    env_home = os.environ.get("GITOS_SPRINT_HOME", "")
    if env_home and not _is_gitos_home(env_home):
        print(f"worktree: land: GITOS_SPRINT_HOME is {env_home}, which is not a gitos home (a directory with INDEX.md beside "
              f"work-orders/ or sprint/); nothing was run -> point it at the main checkout's home, or unset it", file=sys.stderr)
        return 1
    why = _main_blocker(main_root, mbranch)
    if why:
        print(f"worktree: land: {why}", file=sys.stderr)
        return 1
    mhome = main_home(root, home, entries)
    holder, pid = sid, os.getpid()      # land holds the lock for its whole life: the lock lives and dies with this process, not the driver's
    ok, msg, rec = lock_acquire(mhome, holder, pid, wait, say=print)
    print(f"worktree: land: {msg}", file=None if ok else sys.stderr)
    if not ok:
        return 1
    try:
        return _land_locked(root, home, sid, main_root, mbranch, mhome)
    finally:
        lock_release(mhome, holder, pid, True)


# --------------------------------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description="One worktree per work-order; nothing left behind.")
    ap.add_argument("cmd", choices=("new", "reap", "status", "lock", "land"))
    ap.add_argument("args", nargs="*", help="new: NNN [ROOT]; reap: NNN [ROOT]; status: [ROOT]; "
                                            "lock: acquire|release|status [ROOT]; land: [ROOT]")
    ap.add_argument("--home", default=None, help="the home directory (default: auto-detected under ROOT)")
    ap.add_argument("--slice", default=None, metavar="SN",
                    help="new: bind the worktree to slice SN of a folder order (the edit hook reads the marker)")
    ap.add_argument("--merged", action="store_true", help="reap: every reapable worktree/branch")
    ap.add_argument("--json", action="store_true", help="status: machine-readable")
    ap.add_argument("--wait", type=float, default=0.0, metavar="S",
                    help="lock acquire, land: wait up to S seconds for a lock another process holds")
    ap.add_argument("--pid", type=int, default=None, metavar="N",
                    help="lock: the process whose life keeps the lock (default: the sprint driver, else the Claude Code session "
                         "this command runs under; none found refuses); land holds the lock under its own pid and ignores it")
    a = ap.parse_intermixed_args(argv)  # so `reap --merged ROOT` reads ROOT as the argument, as `reap ROOT --merged`
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    pos = list(a.args)
    target = None
    action = None
    if a.cmd == "lock":
        if not pos or pos[0] not in ("acquire", "release", "status"):
            ap.error("lock needs acquire, release or status")
        action = pos.pop(0)
    if a.wait < 0 or (a.pid is not None and a.pid <= 0):
        ap.error("--wait must be 0 or more and --pid a process id")
    if a.cmd in ("new", "reap") and not (a.cmd == "reap" and a.merged):
        if not pos:
            ap.error(f"{a.cmd} needs a work-order number (NNN)")
        target = pos.pop(0)
        if a.cmd == "new" and not re.fullmatch(r"\d{3}", target):
            ap.error("new needs a three-digit work-order number")
        if a.slice and (a.cmd != "new" or not re.fullmatch(r"S\d+", a.slice)):
            ap.error("--slice SN (e.g. S2) belongs to `new`")
        if a.cmd == "reap" and target.startswith("-"):
            ap.error("reap needs NNN, a branch or worktree name, or --merged")
        if a.cmd == "reap" and re.fullmatch(r"wo-\d{3}", target):
            target = target[3:]
        if a.cmd == "reap" and re.fullmatch(r"\d{3}-[sS]\d+", target):      # a slice named by order and number
            target = f"wo-{target.lower()}"
    if len(pos) > 1:
        ap.error("too many arguments")
    start = Path(pos[0] if pos else ".").resolve()
    if not start.is_dir():
        print(f"worktree: not a directory: {start}", file=sys.stderr)
        return 2
    root = toplevel(start) or start
    root = root.resolve()
    home = find_home(root, a.home)
    if a.cmd == "status":
        return cmd_status(root, home, a.json)
    if a.cmd == "new":
        return cmd_new(root, home, target, a.slice)
    if a.cmd == "lock":
        return cmd_lock(root, home, action, a.wait, a.pid)
    if a.cmd == "land":
        return cmd_land(root, home, a.wait, a.pid)
    return cmd_reap(root, home, target, a.merged)


if __name__ == "__main__":
    raise SystemExit(main())
