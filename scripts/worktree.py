"""worktree - one worktree per work order, and nothing left behind once it lands.

stdlib-only, harness-neutral (plain git; no client feature is assumed).

  new NNN      Create `<parent>/<repo name>.worktrees/wo-NNN` (outside the repo tree, so editors and
               language servers do not index it; under the layout's `root` when `worktrees.json`
               sets one) on a new branch `wo-NNN` from the CURRENT `HEAD` (never a remote's default
               branch), for an open work order. Prints the absolute path to dispatch the implementer
               into. A re-run prints the existing path and changes nothing. Worktrees already under
               `.claude/worktrees/` are still found, classified and reaped.
  reap NNN     Remove that worktree and delete its branch, only if the branch is merged (into the
               current branch, the default branch or a declared integration branch) and the
               worktree has no changed or untracked files.
  reap --merged
               The same for every reapable one (see `status`), `wo-NNN`, `worktree-*` and declared
               worktrees alike.
  status       READ-ONLY. Every linked worktree and every `wo-NNN` / `worktree-*` local branch,
               classed in flight / reapable / abandoned / dirty. `--json` for scripts.

Usage:
    python worktree.py new NNN [ROOT] [--home DIR]
    python worktree.py reap NNN | --merged [ROOT] [--home DIR]
    python worktree.py status [ROOT] [--home DIR] [--json]
Exit codes: 0 = done / nothing to do, 1 = refused (reason printed), 2 = usage or not a git repo.

WHAT IT RELIES ON. Only refusals git itself makes, checked against git 2.51 (`git help worktree`):
`git worktree remove` (no force) refuses a worktree with modified or untracked files and a locked
one, and says so; it does NOT check that the branch is merged, so `reap` checks that BEFORE it
removes anything; `git branch -d` refuses an unmerged branch and a branch still checked out in a
worktree (a worktree whose directory was deleted by hand stays registered until `git worktree
prune`, which `reap` runs). Ignored files (for example `__pycache__`) do not block a removal.

WHAT IT NEVER DOES. No `--force`, no `git worktree unlock`, and no deletion from a hook or the canary:
the canary and the `Stop` hook only READ the classification below. A refusal is printed with the reason
and what the operator can do, and the run exits 1. `reap` does use `git branch -D`, and only after its
own merged check passed: git's `-d` asks whether the branch is merged into the CURRENT branch alone,
which is too narrow once work lands on an integration branch.

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
  abandoned  unmerged work that nothing is going to finish: a `wo-NNN` whose work order is resolved
             or missing, or a `worktree-*` branch with no worktree left.
  in flight  everything else: an open work order, a locked worktree, a `worktree-*` worktree that is
             still on disk, any other linked worktree, a declared worktree that is not merged, and a
             merge target: a worktree or branch that IS the default branch or an `integration` branch
             (a target is where work lands, not work; never reapable, never abandoned, whatever its
             tip is merged into). Merged always means merged into a branch other than its own; a
             detached checkout holds no branch, so one at a target's tip is still reapable.
FRESH (`wo`, `builtin` and `declared` kinds). A branch that has never had a commit of its own is an ancestor of HEAD
from the moment it is created, so "merged" alone would call every new worktree reapable. Its reflog tells them apart: one
distinct hash is a branch nobody has committed to. A fresh branch is in flight while its work order is
open (or, for `worktree-*`, while its worktree is on disk). A declared worktree on disk is fresh when its
own HEAD reflog holds one distinct hash (nothing committed there), a detached checkout included; for a
branch checkout whose worktree reflog cannot be read the branch reflog decides. An explicit `reap NNN` is the operator
naming it and is not held back by this; the passive surfaces (status, canary, Stop) are.
HONEST LIMIT: a reflog that was expired or never written makes a branch look not-fresh, so a brand-new
worktree could read as reapable; `reap` still refuses anything dirty.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# The engine's detection order (model_optimization.HOMES).
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")
WORKTREES_REL = ".claude/worktrees"
IGNORE_LINE = ".claude/worktrees/"
IGNORE_COMMENT = "# Agent worktrees (gitos worktree.py): one per work order, never tracked."
WO_BRANCH_RE = re.compile(r"^wo-(\d{3})$")
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


# ------------------------------------------------------------------------------------- git
def git(root, *args):
    """-> (returncode, stdout, stderr); returncode None when git is absent or times out."""
    try:
        cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None, "", ""
    return cp.returncode, cp.stdout, cp.stderr


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


# ----------------------------------------------------------------------------- work orders
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
    """Changed or untracked files in a worktree. Unreadable counts as dirty (the safe answer)."""
    out = git_ok(path, "status", "--porcelain")
    if out is None:
        return 1
    return len([ln for ln in out.splitlines() if ln.strip()])


def classify(item):
    """-> (class, why) for an inventory item. The one definition the tool, canary and hooks share."""
    kind, merged = item["kind"], item["merged"]
    has_dir = item["path"] is not None
    if item["dirty"]:
        return "dirty", f"{item['dirty']} changed or untracked file(s)"
    if item.get("target"):
        return "in flight", "a merge target"
    if kind == "other":
        return "in flight", "linked worktree on a branch this tool does not manage"
    if item["locked"]:
        return "in flight", "locked (git will not remove it)"
    if merged:
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
            decl = _declared(e, root, layout)
            p = Path(e["path"])
            name = (e["branch"] or f"{p.parent.name}/{p.name}") if decl else p.name
            ahead, into = None, None
            if decl and (e["branch"] or e["head"]):
                ahead, into = _merge_state(f"refs/heads/{e['branch']}" if e["branch"] else e["head"],
                                           e["branch"])
            it = {"name": name, "kind": "declared" if decl else "other", "nnn": None, "branch": label,
                  "path": e["path"] if not e["prunable"] and Path(e["path"]).is_dir() else None,
                  "registered": True, "locked": e["locked"], "lock_reason": e["lock_reason"],
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

    A dirty worktree is a finding only when its work order is resolved or missing (it is somebody's
    leftover); dirty with an open order is live work and is not.
    """
    out = []
    for it in (inv or {}).get("items", []):
        what = it["name"] if it["path"] is None else f"{it['name']} ({posix(it['path'])})"
        target = f"WO-{it['nnn']}" if it["nnn"] else "a worktree-* branch"
        if it["class"] == "reapable":
            cmd = f"worktree.py reap {it['nnn']}" if it["nnn"] else "worktree.py reap --merged"
            out.append({"kind": "worktree-reapable", "name": it["name"], "nnn": it["nnn"],
                        "has_worktree": it["path"] is not None,
                        "finding": f"{what} is merged into "
                                   f"{it.get('merged_into') or inv['branch'] or 'HEAD'} and clean but "
                                   f"still present -> run `{cmd}`"})
        elif it["class"] == "abandoned" or (it["class"] == "dirty" and it["kind"] == "wo"
                                            and it["wo"] in ("resolved", "missing")):
            detail = it["why"] if it["class"] == "abandoned" else \
                f"{it['why']} and WO-{it['nnn']} is {it['wo']}"
            out.append({"kind": "worktree-abandoned", "name": it["name"], "nnn": it["nnn"],
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


def cmd_new(root, home, nnn, slice_id=None):
    if toplevel(root) is None:
        print(f"worktree: {posix(root)} is not a git repository -> run `git init` first",
              file=sys.stderr)
        return 2
    if is_linked(root):
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
        print(f"worktree: WO-{nnn} {why} -> a worktree is made only for an open work order "
              f"(under {posix(home)}/work-orders/)", file=sys.stderr)
        return 1
    if slice_id and _slice_file(home, nnn, slice_id) is None:
        print(f"worktree: WO-{nnn} has no slice {slice_id} (--slice names a slice of a folder order: "
              f"work-orders/WO-{nnn}/slices/{slice_id}-<name>.md)", file=sys.stderr)
        return 1
    if git_ok(root, "rev-parse", "--verify", "-q", "HEAD") is None:
        print("worktree: this repository has no commit yet -> commit once, then retry",
              file=sys.stderr)
        return 1
    branch = f"wo-{nnn}"
    path = layout_root(root, layout) / branch
    entries = _entries(root) or []
    for e in entries[1:]:
        if e["branch"] == branch:
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


def _walk_links(top):
    """Every link under `top`, found without following any: -> [path]. A link is reported and not
    entered; only real directories are."""
    found, stack = [], [str(top)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                children = [(e.path, e.name) for e in it]
        except OSError:
            continue
        for full, name in children:
            if cur == str(top) and name == ".git":
                continue
            if _link_kind(full):
                found.append(full)
            elif os.path.isdir(full):
                stack.append(full)
    return found


def _unlink(path):
    """Remove the link itself (never its target). True when it is gone."""
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
    -> (unlinked paths, paths that could not be unlinked)."""
    base = os.path.normcase(os.path.realpath(worktree))
    done, failed = [], []
    for link in _walk_links(worktree):
        target = os.path.normcase(os.path.realpath(link))
        try:
            outside = os.path.commonpath([base, target]) != base
        except ValueError:
            outside = True
        if not outside:
            continue
        (done if _unlink(link) else failed).append(link)
    return done, failed


def _archive(root, home, it):
    """Copy each `archive` directory that exists in the worktree to
    `<home>/worktree-archive/<name>/<dir>`. -> (copied rel dirs, error text or None). Links inside are
    skipped, never followed."""
    layout = load_layout(home)
    if not layout["archive"]:
        return [], None
    dest_base = Path(home) / ARCHIVE_DIR / re.sub(r"[^\w.-]+", "-", it["name"])
    ignore_rel = _under(Path(home) / ARCHIVE_DIR, root)
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


def _reap_one(root, it, current, home=None):
    """Reap one inventory item. -> (ok, [message lines]). Refuses on anything git or we object to."""
    name = it["name"]
    if it.get("target"):
        return False, [f"worktree: {name} NOT reaped: it is a merge target (the default or an "
                       f"integration branch), where work lands"]
    if it["ahead"] != 0:
        n = "an unknown number of" if it["ahead"] is None else str(it["ahead"])
        return False, [f"worktree: {name} NOT reaped: {n} commit(s) are not merged into "
                       f"{current or 'HEAD'}. Merge it, or if it is abandoned remove it by hand "
                       f"(`git worktree remove`, `git branch -D` are yours to run, not this tool's)"]
    if it["path"] and _inside(Path.cwd(), it["path"]):
        return False, [f"worktree: {name} NOT reaped: this process's working directory is inside "
                       f"it. `cd` to {posix(root)} and run it again"]
    msgs = []
    if it["registered"] and it["path"]:
        if not it["dirty"] and not it["locked"]:
            # before the removal; a dirty or locked tree is left to git's own refusal, untouched
            if home is not None:
                copied, bad = _archive(root, home, it)
                if bad:
                    return False, [f"worktree: {name} NOT reaped: {bad}"]
                if copied:
                    msgs.append(f"archived {', '.join(copied)} to {posix(Path(home) / ARCHIVE_DIR)}")
            gone, stuck = link_guard(it["path"])
            if stuck:
                return False, [f"worktree: {name} NOT reaped: cannot unlink {posix(stuck[0])}, a link "
                               f"that points outside the worktree -> remove that link by hand, then retry"]
            if gone:
                msgs.append(f"unlinked {len(gone)} link(s) pointing outside it")
        rc, _, err = git(root, "worktree", "remove", it["path"])
        if rc != 0:
            hint = ("it is locked: whoever locked it decides (`git worktree unlock`, then retry)"
                    if it["locked"] else
                    "commit or discard what is in it, then retry")
            return False, [f"worktree: {name} NOT reaped: git refused: {err.strip()}",
                           f"          -> {hint}"]
        msgs.append(f"removed worktree {it['path']}")
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
    if is_linked(root):
        print(f"worktree: {posix(root)} is a linked worktree -> reap from the main checkout, "
              f"whose HEAD is what the branch is merged into", file=sys.stderr)
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
    if merged_all:
        todo = [i for i in inv["items"] if i["class"] == "reapable"]
        if not todo:
            print("worktree: nothing to reap")
            return 0
    else:
        wanted = f"wo-{target}" if re.fullmatch(r"\d{3}", target) else target
        todo = [i for i in inv["items"] if wanted in (i["branch"], i["name"]) and i["kind"] != "other"]
        if not todo:
            print(f"worktree: no worktree or branch named {wanted} to reap", file=sys.stderr)
            return 1
    status = 0
    for it in todo:
        ok, msgs = _reap_one(root, it, current, home)
        for m in msgs:
            print(m, file=None if ok else sys.stderr)
        status = status or (0 if ok else 1)
    return status


# --------------------------------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description="One worktree per work order; nothing left behind.")
    ap.add_argument("cmd", choices=("new", "reap", "status"))
    ap.add_argument("args", nargs="*", help="new: NNN [ROOT]; reap: NNN [ROOT]; status: [ROOT]")
    ap.add_argument("--home", default=None, help="the gitos home (default: auto-detected under ROOT)")
    ap.add_argument("--slice", default=None, metavar="SN",
                    help="new: bind the worktree to slice SN of a folder order (the edit hook reads the marker)")
    ap.add_argument("--merged", action="store_true", help="reap: every reapable worktree/branch")
    ap.add_argument("--json", action="store_true", help="status: machine-readable")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    pos = list(a.args)
    target = None
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
        if a.cmd == "reap" and WO_BRANCH_RE.match(target):
            target = target[3:]
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
    return cmd_reap(root, home, target, a.merged)


if __name__ == "__main__":
    raise SystemExit(main())
