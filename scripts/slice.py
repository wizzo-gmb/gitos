#!/usr/bin/env python3
"""slice.py - the slice commands of a folder order (an order with two or more slices).

    python slice.py add  WO-NNN NAME HOME [--depends-on WO-NNN/SN ...] [--origin TEXT]
    python slice.py next [WO-NNN] HOME
    python slice.py brief WO-NNN/SN HOME

HOME is the gitos home dir (`<repo>/.gitos`). An order is a single file `work-orders/WO-NNN-slug.md` while it
has one slice, and a folder once it has two:

    work-orders/WO-NNN/order.md              the spec, frozen at accept (amended only by appended, dated notes)
    work-orders/WO-NNN/slices/SN-<name>.md   front matter `status`, `depends_on`, `commit`, `origin`; the scope,
                                             verification, the five note labels and the adjudication in the body
    work-orders/WO-NNN/log.md                append-only

  * `add` is the orchestrator's. On a single-file order it first converts the order with `git mv` (blame
    survives on `order.md`): the scope section becomes `S1`, the rest stays `order.md`; then it writes the new
    slice as `proposed`. On a folder order it writes the next number. It refuses inside a worker's worktree
    (one made by `worktree.py new NNN --slice SN`).
  * `next` prints the first `ready` slice whose `depends_on` are all `landed` (across orders: by severity,
    then number); with none it says so and exits 1, naming what waits on what.
  * `brief` prints what a worker reads: `order.md`, the slice file, and the Durable facts of each *landed*
    dependency, each under its path. Nothing else is inlined; a worker opens other files by path.

Status values: proposed | ready | in-progress | implemented | landed | dropped. Stdlib only; the front-matter
parser is `ledger_index.parse_front_matter`.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

STATUSES = ("proposed", "ready", "in-progress", "implemented", "landed", "dropped")
SLICE_ID_RE = re.compile(r"^(?:WO-?)?(\d{3})/S(\d+)$", re.IGNORECASE)
DIR_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)(?:[-_.][A-Za-z0-9][\w.-]*)?$")
FILE_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)[-_.][A-Za-z0-9][\w.-]*\.md$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SLICE_FILE_RE = re.compile(r"^S(\d+)(?:-[^/]*)?\.md$")
SLICE_HEAD_RE = re.compile(r"^###\s+S(\d+)\b\s*[—–:-]*\s*(.*)$")
MARKER = "gitos-slice"
NOTE_LABELS = ("Deviations", "Surprises", "Durable facts", "Process notes", "Follow-ups")


class SliceError(Exception):
    """One line for the operator; nothing was changed."""


def _load_index():
    path = Path(__file__).resolve().with_name("ledger_index.py")
    spec = importlib.util.spec_from_file_location("_gitos_slice_ledger_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    try:
        cp = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def norm_wo(ref: str) -> str:
    m = re.search(r"(\d{3})(?!\d)", str(ref))
    if not m:
        raise SliceError(f"'{ref}' is not a work-order number (WO-NNN)")
    return m.group(1)


# ------------------------------------------------------------------------------------------ locating
def find_order(home: Path, nnn: str):
    """-> (path, resolved, is_folder) of the order's file or folder, or None."""
    for sub, resolved in (("work-orders", False), ("work-orders/resolved", True)):
        d = home / sub
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_dir():
                m = DIR_RE.match(f.name)
                if m and m.group(1) == nnn and (f / "order.md").is_file():
                    return f, resolved, True
            else:
                m = FILE_RE.match(f.name)
                if m and m.group(1) == nnn:
                    return f, resolved, False
    return None


def list_slices(folder: Path) -> list:
    """[(number, path, meta)] sorted by number."""
    out = []
    sd = folder / "slices"
    if sd.is_dir():
        li = _load_index()
        for f in sd.glob("*.md"):
            m = SLICE_FILE_RE.match(f.name)
            if m:
                out.append((int(m.group(1)), f, li.parse_front_matter(_read(f))[0]))
    return sorted(out, key=lambda t: t[0])


def find_slice(home: Path, sid: str):
    """-> (folder, number, path, meta) for `WO-NNN/SN`, or None."""
    m = SLICE_ID_RE.match(sid.strip())
    if not m:
        raise SliceError(f"'{sid}' is not a slice id (WO-NNN/SN)")
    found = find_order(home, m.group(1))
    if not found or not found[2]:
        return None
    for num, path, meta in list_slices(found[0]):
        if num == int(m.group(2)):
            return found[0], num, path, meta
    return None


def _worker_marker(home: Path):
    out = _git(home, "rev-parse", "--absolute-git-dir")
    if out and (Path(out.strip()) / MARKER).is_file():
        return (Path(out.strip()) / MARKER).read_text(encoding="utf-8").strip()
    return None


def _rel(home: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(home.resolve().parent).as_posix()
    except ValueError:
        return path.as_posix()


# ------------------------------------------------------------------------------------------ add
def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] or s[:limit]
    return s or "scope"


def _slice_text(num: int, title: str, status: str, scope: str, depends_on=(), origin: str = "") -> str:
    dep = "[" + ", ".join(depends_on) + "]"
    notes = "\n\n".join(f"### {lab}\n" for lab in NOTE_LABELS)
    return (f"---\nstatus: {status}\ndepends_on: {dep}\ncommit:\norigin: {origin}\n---\n"
            f"# S{num} - {title}\n\n## Scope\n\n{scope.strip() or '(to be written)'}\n\n## Verification\n\n"
            f"## Implementer notes\n\n{notes}\n\n## Adjudication\n")


def _section(lines: list, idx: int, level_prefix: str) -> int:
    """End index (exclusive) of the section whose heading is lines[idx]: the next heading at the same or a
    shallower level (`level_prefix` is '## ' or '### ')."""
    heads = ("## ",) if level_prefix == "## " else ("## ", "### ")
    for j in range(idx + 1, len(lines)):
        if lines[j].startswith(heads):
            return j
    return len(lines)


def convert(home: Path, path: Path, nnn: str):
    """Single-file order -> folder. -> (folder, slice file, note)."""
    text = _read(path).replace("\r\n", "\n")
    lines = text.split("\n")
    heads = [i for i, ln in enumerate(lines) if SLICE_HEAD_RE.match(ln)]
    in_slices = []
    cur = None
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            cur = ln.strip()
        if i in heads and cur and cur.startswith("## Slices"):
            in_slices.append(i)
    if len(in_slices) > 1:
        raise SliceError(f"{path.name} has {len(in_slices)} slice sections; split it by hand into the folder form "
                         f"(or run ledger_migrate.py); nothing was changed")
    if in_slices:
        i = in_slices[0]
        end = _section(lines, i, "### ")
        m = SLICE_HEAD_RE.match(lines[i])
        title = m.group(2).strip() or "scope"
        body = "\n".join(lines[i + 1:end])
        new_lines = lines[:i + 1] + ["", "(moved to slices/S1-@NAME@.md)", ""] + lines[end:]
    else:
        i = next((k for k, ln in enumerate(lines) if ln.startswith("## Proposed fix scope")), None)
        if i is None:
            raise SliceError(f"{path.name} has no slice section and no '## Proposed fix scope' to become S1; "
                             f"nothing was changed")
        end = _section(lines, i, "## ")
        title = re.sub(r"^WO-?\d{3}\s*[—–-]+\s*", "", next((ln[2:].strip() for ln in lines if ln.startswith("# ")),
                                                           "scope"))
        body = "\n".join(lines[i + 1:end])
        new_lines = lines[:i + 1] + ["", "(moved to slices/S1-@NAME@.md)", ""] + lines[end:]
    name = _slug(title)
    folder = path.parent / f"WO-{nnn}"
    if folder.exists():
        raise SliceError(f"{_rel(home, folder)} already exists beside the single-file order; nothing was changed")
    folder.mkdir(parents=True)
    dest = folder / "order.md"
    top = (_git(path.parent, "rev-parse", "--show-toplevel") or "").strip()
    moved = False
    if top:
        moved = _git(top, "mv", str(path), str(dest)) is not None
    if not moved:
        os.replace(path, dest)
    _write(dest, "\n".join(new_lines).replace("@NAME@", name))
    sl = folder / "slices" / f"S1-{name}.md"
    _write(sl, _slice_text(1, title, "ready", body))
    _write(folder / "log.md", f"# WO-{nnn} log\n\n- {date.today().isoformat()} converted to the folder form: "
                              f"the scope became S1 ({name}, ready)\n")
    note = ("converted " + path.name + " -> " + _rel(home, dest) + (" (git mv)" if moved else " (plain move: not tracked)")
            + f"; S1-{name} is `ready` (set it by hand if the work has started)")
    return folder, sl, note


def slice_add(home: Path, wo: str, name: str, depends_on=(), origin: str = ""):
    nnn = norm_wo(wo)
    if not NAME_RE.match(name):
        raise SliceError(f"slice name '{name}' must be lower-case letters, digits and hyphens")
    marker = _worker_marker(home)
    if marker:
        raise SliceError(f"this is a worker's worktree (slice {marker}): `slice add` is the orchestrator's; "
                         f"nothing was changed")
    found = find_order(home, nnn)
    if not found:
        raise SliceError(f"no work-order {nnn} under {home / 'work-orders'}; nothing was changed")
    path, resolved, is_folder = found
    if resolved:
        raise SliceError(f"WO-{nnn} is resolved: a slice is added to an open order; nothing was changed")
    for d in depends_on:
        if not SLICE_ID_RE.match(d):
            raise SliceError(f"depends-on '{d}' is not a slice id (WO-NNN/SN)")
    msgs = []
    if not is_folder:
        folder, _s1, note = convert(home, path, nnn)
        msgs.append(note)
    else:
        folder = path
        lines = len(_read(folder / "order.md").splitlines())
        limit = _load_index().ORDER_MAX_LINES
        if lines > limit:
            raise SliceError(f"WO-{nnn}'s order.md is {lines} lines, over the {limit}-line limit: trim it (move detail "
                             f"into the slices) or author a new order; nothing was added")
    existing = list_slices(folder)
    num = (existing[-1][0] if existing else 0) + 1
    if any(re.sub(r"^S\d+-", "", p.stem) == name for _n, p, _m in existing):
        raise SliceError(f"WO-{nnn} already has a slice named '{name}'; nothing was added")
    dest = folder / "slices" / f"S{num}-{name}.md"
    _write(dest, _slice_text(num, name.replace("-", " "), "proposed", "", tuple(depends_on), origin))
    log = folder / "log.md"
    stamp = f"- {date.today().isoformat()} slice S{num}-{name} added (proposed)\n"
    _write(log, (_read(log) if log.is_file() else f"# WO-{nnn} log\n\n") + stamp)
    top = (_git(folder, "rev-parse", "--show-toplevel") or "").strip()
    if top:
        _git(top, "add", "--", str(folder))
    msgs.append(f"added {_rel(home, dest)} (proposed)")
    if num >= _load_index().SPLIT_ADVICE_SLICES:
        msgs.append(f"WO-{nnn} now has {num} slices: consider splitting the rest into a new order")
    return msgs


# ------------------------------------------------------------------------------------------ next
def _folder_orders(home: Path):
    out = []
    d = home / "work-orders"
    if d.is_dir():
        for f in sorted(x for x in d.iterdir() if x.is_dir()):
            m = DIR_RE.match(f.name)
            if m and (f / "order.md").is_file():
                out.append((m.group(1), f))
    return out


def slice_next(home: Path, wo: "str | None" = None):
    """-> (id, path) of the first ready slice with every dependency landed, or None; and the waiting notes."""
    li = _load_index()
    orders = _folder_orders(home)
    if wo:
        nnn = norm_wo(wo)
        orders = [o for o in orders if o[0] == nnn]
        if not orders:
            raise SliceError(f"WO-{nnn} is not an open folder order under {home / 'work-orders'}")

    def rank(o):
        sev = li._info(o[1] / "order.md")["severity"]
        return (li.SEVERITY_ORDER.index(sev) if sev in li.SEVERITY_ORDER else len(li.SEVERITY_ORDER), o[0])
    waiting = []
    for nnn, folder in sorted(orders, key=rank):
        for num, path, meta in list_slices(folder):
            if str(meta.get("status", "")).strip() != "ready":
                continue
            deps = meta.get("depends_on") or []
            if isinstance(deps, str):
                deps = [deps] if deps.strip() else []
            blockers = []
            for dep in deps:
                try:
                    hit = find_slice(home, dep)
                except SliceError:
                    hit = None
                status = str(hit[3].get("status", "")).strip() if hit else "missing"
                if status != "landed":
                    blockers.append(f"{dep} ({status})")
            sid = f"WO-{nnn}/S{num}"
            if blockers:
                waiting.append(f"{sid} waits on " + ", ".join(blockers))
            else:
                return (sid, path), waiting
    return None, waiting


# ------------------------------------------------------------------------------------------ brief
def durable_facts(text: str) -> "str | None":
    """The Durable facts section of a slice file: a `Durable facts` heading's body, or the `- **Durable facts:**`
    bullet's lines. None when there is none."""
    lines = text.replace("\r\n", "\n").split("\n")
    for i, ln in enumerate(lines):
        h = re.match(r"^(#{1,6})\s*\**Durable facts\b", ln)
        if h:
            lvl = len(h.group(1))
            end = next((j for j in range(i + 1, len(lines)) if re.match(rf"^#{{1,{lvl}}}\s", lines[j])), len(lines))
            return "\n".join(lines[i + 1:end]).strip("\n")
        if re.match(r"^\s*[-*]\s+\*\*Durable facts:?\*\*", ln):
            end = next((j for j in range(i + 1, len(lines))
                        if re.match(r"^\s*[-*]\s+\*\*[^*]+:?\*\*", lines[j]) or lines[j].startswith("#")), len(lines))
            return "\n".join(lines[i:end]).strip("\n")
    return None


def slice_brief(home: Path, sid: str):
    hit = find_slice(home, sid)
    if not hit:
        raise SliceError(f"no slice {sid} under {home / 'work-orders'} (a folder order's slices/SN-<name>.md)")
    folder, num, path, meta = hit
    nnn = norm_wo(sid)
    out = [f"# Brief for WO-{nnn}/S{num}",
           "",
           "Read this, then work. Open any other file only by the path given here, and only when you need it.",
           f"Edit only your slice file ({_rel(home, path)}): its notes, and its status from in-progress to "
           "implemented. Never edit order.md, log.md, another slice file or INDEX.md, and never set a status "
           "to landed or dropped; the orchestrator does.",
           "", f"## order.md ({_rel(home, folder / 'order.md')})", "", _read(folder / "order.md").strip(), "",
           f"## Your slice ({_rel(home, path)})", "", _read(path).strip(), ""]
    deps = meta.get("depends_on") or []
    if isinstance(deps, str):
        deps = [deps] if deps.strip() else []
    notes = []
    for dep in deps:
        d = find_slice(home, dep)
        status = str(d[3].get("status", "")).strip() if d else "missing"
        if not d or status != "landed":
            notes.append(f"slice_brief: dependency {dep} is {status}, not landed: its Durable facts are not included")
            continue
        facts = durable_facts(_read(d[2]))
        out += [f"## Durable facts of {dep} ({_rel(home, d[2])})", "", facts if facts else "(none recorded)", ""]
    return "\n".join(out).rstrip("\n") + "\n", notes


# ------------------------------------------------------------------------------------------ cli
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Slice commands of a folder order.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_add = sub.add_parser("add", help="add a slice (converts a single-file order to the folder form first)")
    a_add.add_argument("wo")
    a_add.add_argument("name")
    a_add.add_argument("home")
    a_add.add_argument("--depends-on", nargs="*", default=[], metavar="WO-NNN/SN")
    a_add.add_argument("--origin", default="")
    a_next = sub.add_parser("next", help="the first ready slice whose dependencies are all landed")
    a_next.add_argument("args", nargs="+", metavar="[WO-NNN] HOME")
    a_brief = sub.add_parser("brief", help="print a worker's brief for WO-NNN/SN")
    a_brief.add_argument("slice")
    a_brief.add_argument("home")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        if a.cmd == "add":
            home = Path(a.home).resolve()
            for m in slice_add(home, a.wo, a.name, a.depends_on, a.origin):
                print(f"slice: {m}")
            return 0
        if a.cmd == "next":
            if len(a.args) > 2:
                ap.error("next takes [WO-NNN] HOME")
            home = Path(a.args[-1]).resolve()
            hit, waiting = slice_next(home, a.args[0] if len(a.args) == 2 else None)
            if hit:
                print(f"{hit[0]} {_rel(home, hit[1])}")
                return 0
            print("slice: no ready slice with every dependency landed")
            for w in waiting:
                print(f"slice: {w}", file=sys.stderr)
            return 1
        home = Path(a.home).resolve()
        text, notes = slice_brief(home, a.slice)
        sys.stdout.write(text)
        for n in notes:
            print(n, file=sys.stderr)
        return 0
    except SliceError as e:
        print(f"slice: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
