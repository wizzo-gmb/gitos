#!/usr/bin/env python3
"""ledger_migrate.py - convert open single-file orders with two or more slice sections into the folder form.

    python ledger_migrate.py HOME [--write]

HOME is the gitos home dir (`<repo>/.gitos`). Dry run by default: it prints what it would do and writes nothing.

An open order `work-orders/WO-NNN-slug.md` whose `## Slices` section holds two or more `### S<n>` sections
becomes the folder form (see slice.py): the file is `git mv`-ed to `WO-NNN/order.md` (history follows), each slice
section becomes `slices/S<n>-<name>.md`, and `log.md` records the migration.

  * A slice is landed when its section holds an adjudication naming a commit, or the order's `## History`
    section has a pointer line `- <slice> landed <sha>: history/WO-NNN.md#<anchor>` for it; it gets
    `status: landed` and that commit. Every other slice is `ready`. `depends_on` runs in order (each slice on the
    one before) unless the slice's own text carries a `Depends on: ...` line.
  * `history/WO-NNN.md` content becomes the landed slice's Implementer notes; a slice that exists only in the
    history file (trimmed from the live order) is created from it. The history file is removed once consumed;
    an empty `work-orders/history/` folder is removed.
  * Open carried boxes (`- [ ] L<n> ...`) are never converted. They stay in order.md and are LISTED for the
    orchestrator to settle: a proposed slice (`slice add`, or `drain accept --new-slice`), a new order, or dropped.
  * Single-slice orders and resolved orders are left alone. When an order cannot be split with confidence the
    report names it and the reason, and `--write` skips it; nothing is guessed.

Nothing is committed; the changes are staged. Stdlib only.
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

HERE = Path(__file__).resolve().parent
SHA_RE = re.compile(r"(?<![0-9A-Za-z])([0-9a-f]{7,40})(?![0-9A-Za-z])")
ADJ_RE = re.compile(r"(?i)^\s*(?:#{1,6}\s*|\*\*|[-*]\s+\*\*)\s*adjudicat")
DEPS_RE = re.compile(r"(?im)^\W*depends[ _-]on\b\W*(.*)$")
NO_DEPS_RE = re.compile(r"(?i)^\W*(?:none|nothing|no\b.*|independent.*|n/a)\W*$")
POINTER_RE = re.compile(r"^\s*[-*]\s+(?P<tok>.+?)\s+landed\s+(?P<sha>[0-9a-f]{7,40})\b"
                        r"(?:\s*:\s*history/WO-(?P<h>\d{3})\.md(?:#(?P<anc>[\w-]+))?)?")


class Skip(Exception):
    """An order that cannot be split with confidence; the message is the reason."""


def _load(name: str):
    path = HERE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_gitos_migrate_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    try:
        cp = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _slug_anchor(h: str) -> str:
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", h.strip().lower()))


def _sha_of(lines: list) -> "str | None":
    """The commit an adjudication names: the one after ' as ' (the merge), else the first."""
    text = "\n".join(lines)
    cands = [m for m in SHA_RE.finditer(text) if re.search(r"\d", m.group(1)) and re.search(r"[a-f]", m.group(1))]
    if not cands:
        return None
    for m in cands:
        if re.search(r"\bas\s+`?$", text[max(0, m.start() - 8):m.start()]):
            return m.group(1)
    return cands[0].group(1)


def _section_end(lines: list, i: int, heads: tuple) -> int:
    return next((j for j in range(i + 1, len(lines)) if lines[j].startswith(heads)), len(lines))


def _history_sections(text: str) -> list:
    """[(heading text, anchor, body lines)] of a history file's `## ` sections."""
    lines = text.split("\n")
    out = []
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        head = lines[i][3:].strip()
        out.append((head, _slug_anchor(head), lines[i + 1:end]))
    return out


def plan_order(sl, cn, home: Path, nnn: str, path: Path, hist_path: "Path | None") -> dict:
    """The migration of one order: {slices, boxes, order_text, history_used}. Raises Skip with the reason."""
    text = _read(path)
    lines = text.split("\n")
    s = next((i for i, ln in enumerate(lines) if ln.strip() == "## Slices"), None)
    live: list = []
    if s is not None:
        e = _section_end(lines, s, ("## ",))
        heads = [i for i in range(s + 1, e) if sl.SLICE_HEAD_RE.match(lines[i])]
        for k, i in enumerate(heads):
            m = sl.SLICE_HEAD_RE.match(lines[i])
            end = heads[k + 1] if k + 1 < len(heads) else e
            live.append({"n": int(m.group(1)), "title": m.group(2).strip() or f"slice {m.group(1)}",
                         "head": i, "end": end, "body": lines[i + 1:end]})
    h = next((i for i, ln in enumerate(lines) if ln.strip() == "## History"), None)
    pointers: list = []
    h_end = None
    if h is not None:
        h_end = _section_end(lines, h, ("## ",))
        for ln in lines[h + 1:h_end]:
            m = POINTER_RE.match(re.sub(r"`", "", ln))
            if m:
                pointers.append(m)
    nums = [x["n"] for x in live]
    if len(set(nums)) != len(nums):
        raise Skip("two slice sections carry the same number")
    sections = _history_sections(_read(hist_path)) if hist_path and hist_path.is_file() else []
    used_sections: set = set()
    by_n = {x["n"]: x for x in live}
    for x in live:
        x.update(commit="", hist=None, only_history=False)
    for m in pointers:
        tok = m.group("tok").strip()
        tn = re.match(r"(?i)S(\d+)\b\W*(.*)$", tok)
        target = by_n.get(int(tn.group(1))) if tn else None
        if target is None and not tn:
            slug = sl._slug(tok)
            hits = [x for x in live if slug in (sl._slug(x["title"]), x["title"].lower())]
            target = hits[0] if len(hits) == 1 else None
            if target is None:
                raise Skip(f"the History pointer '{tok}' names no slice section and carries no S<n>")
        sec = None
        anc = m.group("anc")
        if anc:
            hits = [k for k, sc in enumerate(sections) if sc[1] == anc]
            if not hits:
                raise Skip(f"the History pointer '{tok}' -> #{anc}: no such heading in history/WO-{nnn}.md")
            sec = hits[0]
        elif sections:
            hits = [k for k, sc in enumerate(sections) if m.group("sha")[:7] in sc[0]]
            sec = hits[0] if len(hits) == 1 else None
        if sec is not None:
            if sec in used_sections:
                raise Skip(f"two History pointers name the history section '{sections[sec][0]}'")
            used_sections.add(sec)
        if target is None:                                # trimmed from the live order: created from the history
            title = (tn.group(2).strip() if tn and tn.group(2).strip() else
                     (re.sub(r"\s*\([0-9a-f]{7,40}\)\s*$", "", sections[sec][0]) if sec is not None else ""))
            if not title:
                raise Skip(f"the History pointer '{tok}' has no live section and no history heading to name it")
            n = int(tn.group(1))
            target = {"n": n, "title": title, "head": None, "end": None, "body": [], "commit": "", "hist": None,
                      "only_history": True}
            by_n[n] = target
            live.append(target)
        if target["commit"]:
            raise Skip(f"slice S{target['n']} is named by two History pointers")
        target["commit"] = m.group("sha")
        if sec is not None:
            target["hist"] = "\n".join(sections[sec][2]).strip("\n")
    if len(live) < 2:
        return {}
    live.sort(key=lambda x: x["n"])
    for x in live:
        if not x["commit"] and not x["only_history"]:
            a = next((i for i, ln in enumerate(x["body"]) if ADJ_RE.match(ln)), None)
            if a is not None:
                sha = _sha_of(x["body"][a:])
                if not sha:
                    raise Skip(f"slice S{x['n']} has an adjudication that names no commit")
                x["commit"] = sha
    if len(used_sections) != len(sections):
        left = [sections[k][0] for k in range(len(sections)) if k not in used_sections]
        raise Skip("history section(s) match no slice: " + "; ".join(left))
    for i, x in enumerate(live):
        deps = None
        m = DEPS_RE.search("\n".join(x["body"]))
        if m:
            rest = m.group(1).strip()
            refs = re.findall(r"(?:WO-?\d{3}/)?S(\d+)\b", rest)
            if refs:
                deps = [f"WO-{nnn}/S{r}" for r in refs]
                bad = [r for r in refs if int(r) not in by_n or int(r) >= x["n"]]
                if bad:
                    raise Skip(f"slice S{x['n']} depends on S{bad[0]}, which is no earlier slice of this order")
            elif NO_DEPS_RE.match(rest):
                deps = []
            else:
                raise Skip(f"slice S{x['n']} has a 'Depends on' line that names no slice: '{rest[:60]}'")
        elif re.search(r"(?im)^\W*independent\b", "\n".join(x["body"])):
            deps = []
        x["deps"] = deps if deps is not None else ([f"WO-{nnn}/S{live[i - 1]['n']}"] if i else [])
        x["name"] = sl._slug(x["title"])
        x["status"] = "landed" if x["commit"] else "ready"
    names = [x["name"] for x in live]
    if len(set(names)) != len(names):
        raise Skip("two slices have the same name once slugged")
    # the rewritten order.md: slice bodies move out, the History pointers go
    out = list(lines)
    cut = [(x["head"] + 1, x["end"], x) for x in live if x["head"] is not None]
    for a, b, x in sorted(cut, key=lambda t: -t[0]):
        out[a:b] = ["", f"(moved to slices/S{x['n']}-{x['name']}.md)", ""]
    if h is not None and pointers:
        hh = next(i for i, ln in enumerate(out) if ln.strip() == "## History")
        he = _section_end(out, hh, ("## ",))
        del out[hh:he]
    boxes = [b for b in cn.parse_carried(text, legacy=True)["boxes"] if not b["done"]]
    bad = cn.parse_carried(text, legacy=True)["bad"]
    return {"slices": live, "boxes": boxes, "bad": bad, "order_text": "\n".join(out),
            "history_used": bool(sections), "pointers": bool(pointers)}


def _slice_file(x: dict, nnn: str) -> str:
    body = "\n".join(x["body"]).strip("\n") or "(the scope text was trimmed into the history; see Implementer notes)"
    notes = x["hist"] if x.get("hist") else "\n\n".join(f"### {lab}\n" for lab in _load("slice").NOTE_LABELS)
    dep = "[" + ", ".join(x["deps"]) + "]"
    return (f"---\nstatus: {x['status']}\ndepends_on: {dep}\ncommit:{' ' + x['commit'] if x['commit'] else ''}\norigin:\n---\n"
            f"# S{x['n']} - {x['title']}\n\n## Scope\n\n{body}\n\n## Verification\n\n"
            f"## Implementer notes\n\n{notes}\n\n## Adjudication\n")


def apply(home: Path, nnn: str, path: Path, hist_path: "Path | None", plan: dict) -> None:
    folder = path.parent / f"WO-{nnn}"
    if folder.exists():
        raise Skip(f"{folder.name} already exists beside the single-file order")
    folder.mkdir(parents=True)
    dest = folder / "order.md"
    top = (_git(path.parent, "rev-parse", "--show-toplevel") or "").strip()
    if not (top and _git(top, "mv", str(path), str(dest)) is not None):
        os.replace(path, dest)
    _write(dest, plan["order_text"])
    for x in plan["slices"]:
        _write(folder / "slices" / f"S{x['n']}-{x['name']}.md", _slice_file(x, nnn))
    today = date.today().isoformat()
    log = [f"# WO-{nnn} log", "", f"- {today} migrated to the folder form by ledger_migrate: "
           + ", ".join(f"S{x['n']} {x['status']}" + (f" {x['commit']}" if x["commit"] else "") for x in plan["slices"])]
    for b in plan["boxes"]:
        log.append(f"- {today} open carried box {b['id']} (slice: {b['slice']}) left in order.md to be settled")
    _write(folder / "log.md", "\n".join(log) + "\n")
    if hist_path and hist_path.is_file():
        if not (top and _git(top, "rm", "-q", "-f", "--", str(hist_path)) is not None):
            hist_path.unlink()
    if top:
        _git(top, "add", "--", str(folder))


def run(home: Path, write: bool, out=print) -> int:
    sl, cn = _load("slice"), _load("canary")
    wod = home / "work-orders"
    hdir = wod / "history"
    out(f"ledger_migrate: {home} ({'--write' if write else 'dry run; nothing is written, pass --write to apply'})")
    if not wod.is_dir():
        out("ledger_migrate: no work-orders/ folder; nothing to migrate")
        return 0
    migrated, skipped, boxes, consumed = 0, 0, [], set()
    for f in sorted(x for x in wod.iterdir() if x.is_file()):
        m = sl.FILE_RE.match(f.name)
        if not m:
            continue
        nnn = m.group(1)
        hp = hdir / f"WO-{nnn}.md"
        try:
            plan = plan_order(sl, cn, home, nnn, f, hp if hp.is_file() else None)
        except Skip as e:
            out(f"WO-{nnn} SKIP {f.name}: {e}")
            skipped += 1
            continue
        if not plan:
            continue
        desc = ", ".join(f"S{x['n']} {x['status']}" + (f" {x['commit']}" if x["commit"] else "") for x in plan["slices"])
        out(f"WO-{nnn} {'migrated' if write else 'would migrate'} {f.name} -> WO-{nnn}/order.md: {desc}"
            + (f"; history/WO-{nnn}.md folded in" if plan["history_used"] else ""))
        for b in plan["boxes"]:
            boxes.append(f"WO-{nnn} {b['id']} (slice: {b['slice']}) {b['text']}")
        for ln, text in plan["bad"]:
            boxes.append(f"WO-{nnn} order.md line {ln}: {text.strip()}")
        if write:
            try:
                apply(home, nnn, f, hp if hp.is_file() else None, plan)
            except Skip as e:
                out(f"WO-{nnn} SKIP {f.name}: {e}")
                skipped += 1
                continue
        if hp.is_file():
            consumed.add(hp.name)
        migrated += 1
    if not migrated and not skipped:
        out("ledger_migrate: nothing to migrate")
    if boxes:
        out("carried boxes left in order.md, not converted; settle each (a proposed slice via `slice add` or "
            "`drain accept --new-slice`, a new order, or dropped):")
        for b in boxes:
            out(f"  {b}")
    if hdir.is_dir():
        left = sorted(p.name for p in hdir.iterdir() if p.name != ".gitkeep" and p.name not in consumed)
        for name in left:
            out(f"history/{name} stays: its order is single-slice, resolved or skipped; read it by hand")
        if not left:
            out(f"work-orders/history/ {'removed' if write else 'would be removed'} (retired)")
            if write:
                top = (_git(wod, "rev-parse", "--show-toplevel") or "").strip()
                for p in hdir.iterdir():
                    if p.is_file() and p.name == ".gitkeep":
                        if not (top and _git(top, "rm", "-q", "-f", "--", str(p)) is not None):
                            p.unlink()
                try:
                    hdir.rmdir()
                except OSError:
                    pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert open multi-slice single-file orders into the folder form.")
    ap.add_argument("home", help="the home directory, e.g. <repo>/.gitos")
    ap.add_argument("--write", action="store_true", help="apply the migration (default: dry run)")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    return run(Path(a.home).resolve(), a.write)


if __name__ == "__main__":
    raise SystemExit(main())
