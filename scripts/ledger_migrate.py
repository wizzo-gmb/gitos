#!/usr/bin/env python3
"""ledger_migrate.py - bring a home's ledger to the current form: folder orders, one not-now list, the generated board.

    python ledger_migrate.py HOME [--write]

HOME is the gitos home dir (`<repo>/.gitos`). Dry run by default: it prints what it would do and writes nothing.
It is idempotent: run again after a crash, or after `--write`, it finds what is left (nothing, the second time).

**One not-now list (WO-115).** Every item that is not yet an order becomes a row of `loose-ends.md`:

  * a pending drain proposal (`drain/pending/<id>.md`) stays as the attachment; each item it holds gets its row back
    (own id, Added, Source, text) as `proposed: <kind>`, or a `new` row it holds becomes `proposed: <kind>`;
  * a `parked: <trigger>` row (retired by WO-116) becomes a parked work-order: a new order file with front matter
    `status: parked`, `trigger: <trigger>` and `origin: L<n>`, and the row leaves the list;
  * an open hand-kept INDEX Parked row (any id: `P<n>`, `214-P1`, `nt8-freeze`, `L63`, `004`; no `->` in it) becomes a
    parked work-order the same way (`origin:` is the id, verbatim); a closed one (`-> WO-NNN`, `-> dropped ...`) is
    routed and goes; the INDEX then becomes the generated board (below);
  * an open carried box (`- [ ] L<n> (slice: ..) ..`) of an open order goes back on the list as `new` (own id) and
    the box is ticked `-> L<n>`;
  * `drain/declined/`, `drain/accepted/` and `drain/routed.txt` are removed: a declined item is already a
    `declined:` row, an accepted or routed one is off the list (git keeps the files);
  * `<home>/system-one.json` is removed (v75 retired the local model; the file held its per-repo choice, nothing the
    drain reads; the machine config under `~/.claude/gitos-system-one/` is the operator's and is never touched);
  * the front-matter key `landed:` holding an engine version (`vN` or a bare integer: the version an order resolved in) is
    renamed `released:`; `landed: <commit sha>` (merged, awaiting accept) is the current meaning and is left alone.

**The board (WO-124).** An INDEX that is not yet the generated board (no `<!-- gitos:index board -->` line) is replaced by it
(`ledger_index.py` writes the whole file from the order files). Nothing is dropped silently:

  * a Resolved row whose order file is in `work-orders/resolved/` goes (the file is the record; `ls` is the list, `git log`
    the timeline), and when that file carries no `released:` and the row's "Fix landed in" cell names an engine version, the
    file is stamped `released: vN` first; a row with no order file is moved to RESUME.md;
  * an Open or Parked row that its order file regenerates goes; one with no file (or a Parked row the step above reported
    LEFT) is moved to RESUME.md;
  * every other section and any text above the first section (release shaping notes, Findings DISPROVED, next steps) is moved to
    RESUME.md, verbatim in a fenced block under a dated heading, for the operator to sort: live state stays, a durable decision goes to
    the brain, the rest is deleted (git keeps the old INDEX);
  * `footprints.md` is removed (a landing's footprint is `git show --name-only <sha>`), and so is every `work-orders/**/WO-NNN/log.md`
    (the slice files hold the state, `git log -- work-orders/WO-NNN` the history).

What cannot be moved with confidence (an item a pile file holds while its row is in another state, a routed id that
is still a row, a Parked row with no trigger, a box line that is not a box) is reported and left alone.
The Parked section is rewritten only when every row of the table is accounted for (converted, routed-closed, already
held, or reported LEFT).

An open order `work-orders/WO-NNN-slug.md` whose `## Slices` section holds two or more `### S<n>` sections
becomes the folder form (see slice.py): the file is `git mv`-ed to `WO-NNN/order.md` (history follows), each slice
section becomes `slices/S<n>-<name>.md`.

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
# the legacy key: `landed:` holding an engine version (`v12`, `12`); a commit sha (`0c907dd`) is the v74 meaning, not renamed
LANDED_VERSION_RE = re.compile(r"(?m)^landed:(?=[ 	]*[\"']?(?:v\d+|\d{1,5})(?![0-9A-Za-z]))")


def _landed_version(meta: dict) -> str:
    v = meta.get("landed")
    return v if isinstance(v, str) and re.fullmatch(r"[\"']?(?:v\d+|\d{1,5})[\"']?", v.strip()) else ""


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
            live.append({"n": sl.slice_label(m.group(1)), "title": m.group(2).strip() or f"slice {m.group(1)}",
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
        tn = re.match(rf"(?i)S({sl.SLICE_NO})\b\W*(.*)$", tok)
        target = by_n.get(sl.slice_label(tn.group(1))) if tn else None
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
            n = sl.slice_label(tn.group(1))
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
    live.sort(key=lambda x: sl.slice_key(x["n"]))
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
            refs = re.findall(rf"(?:WO-?\d{{3}}/)?S({sl.SLICE_NO})\b", rest)
            if refs:
                deps = [f"WO-{nnn}/S{sl.slice_label(r)}" for r in refs]
                bad = [r for r in refs if sl.slice_label(r) not in by_n or sl.slice_key(r) >= sl.slice_key(x["n"])]
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
    if hist_path and hist_path.is_file():
        if not (top and _git(top, "rm", "-q", "-f", "--", str(hist_path)) is not None):
            hist_path.unlink()
    if top:
        _git(top, "add", "--", str(folder))


def _rm(path: Path) -> None:
    """Remove a file, through git when it is tracked (history keeps it)."""
    top = (_git(path.parent, "rev-parse", "--show-toplevel") or "").strip()
    if not (top and _git(top, "rm", "-q", "-f", "--", str(path)) is not None):
        path.unlink()


def _shorten(text: str, n: int = 300) -> str:
    s = " ".join(text.split())
    return s if len(s) <= n else s[:n - 3].rstrip() + "..."


def _parked_order(nnn: str, item: str, trigger: str, origin: str, evidence: str) -> tuple:
    """(file name, text) of a parked work-order made from a retired parked item (WO-116)."""
    item = " ".join(item.split())
    title = _shorten(item, 90).replace("[", "(").replace("]", ")")
    slug = "-".join(re.findall(r"[a-z0-9]+", title.lower())[:6]) or "parked"
    text = (f"---\nstatus: parked\ntrigger: {' '.join(trigger.split())}\nseverity: low\ntitle: {title}\n"
            f"evidence: {evidence}\norigin: {origin}\n---\n# WO-{nnn} — {title}\n\n## Severity\n\n"
            f"low — parked until its trigger fires.\n\n## Objective\n\n{item}\n\n## Proposed fix scope\n\n"
            "Written when the trigger fires and the order is opened (remove `status: parked`).\n\n"
            "## Implementer notes\n")
    return f"WO-{nnn}-{slug}.md", text


def migrate_not_now(home: Path, write: bool, out=print, report: "dict | None" = None) -> int:
    """The WO-115 moves (see the module docstring). -> how many moves were found. `report["parked_left"]` receives
    the ids of the hand-kept Parked rows it left alone (`"?"`: rows nobody accounted for)."""
    le, cn, s1 = _load("loose_ends"), _load("canary"), _load("system_one")
    moves = 0

    def say(text: str) -> None:
        nonlocal moves
        moves += 1
        out(f"not-now: {text}")
    rows = {r["id"]: r for r in le.rows_of(home)}
    state = {k: (le.parse_state(r["state"]) or ("?", ""))[0] for k, r in rows.items()}
    routed_file = home / "drain" / "routed.txt"
    routed = set(re.findall(r"(?m)^(L\d+) -> ", _read(routed_file))) if routed_file.is_file() else set()
    # 1. the pile: the row is the authority, the file an attachment
    pend = home / "drain" / "pending"
    back, marks = [], {}
    for f in sorted(pend.glob("*.md")) if pend.is_dir() else []:
        m = s1._read_proposal(f) if s1._DRAIN_ID.fullmatch(f.stem) else None
        if not m:
            continue
        lines = {r[0]: r for r in s1._proposal_rows(m)}
        for lid in m["item_list"]:
            want = f"proposed: {m['kind']}"
            if lid in routed:
                say(f"{lid} is in pile {f.name} and in drain/routed.txt: routed, so it leaves the pile")
                if write:
                    s1.release_items(home, [lid])
            elif lid not in rows and lid in lines:
                say(f"{lid} (pile {f.name}) -> back on the list as `{want}`")
                back.append((lid, lines[lid][1], lines[lid][2], lines[lid][3], want))
            elif lid not in rows:
                out(f"not-now: LEFT {lid}: pile {f.name} names it but carries no item line; settle it by hand")
            elif state[lid] == "new":
                say(f"{lid} `new` (pile {f.name}) -> `{want}`")
                marks[lid] = want
            elif state[lid] != "proposed":
                out(f"not-now: LEFT {lid}: pile {f.name} holds it while its row is `{rows[lid]['state']}`; "
                    "withdraw or decline the proposal by hand")
    # 2. the INDEX Parked rows
    idx = home / "INDEX.md"
    idx_text = _read(idx) if idx.is_file() else ""
    imported = {r["source"][len("import:"):] for r in rows.values() if r["source"].startswith("import:P")}
    origins = {}
    for nnn, meta in cn.parked_orders(home):
        og = " ".join(meta.get("origin", "").split())
        for o in [og] + re.findall(r"\b[LP]\d+\b", og):
            if o:
                origins.setdefault(o, nnn)
    parked_new, parked_left, parked_gone, from_index = [], [], [], set()
    # 2a. the retired `parked:` rows (WO-116)
    for lid, r in rows.items():
        if state[lid] != "parked":
            continue
        if lid in origins:
            say(f"{lid} `parked:` is already held by the parked order WO-{origins[lid]}: the row goes")
        else:
            parked_new.append((lid, r["item"], le.parse_state(r["state"])[1],
                               f"loose end {lid} ({r['source']}), added {r['added']}"))
        parked_gone.append(lid)
    n_read = n_done = 0
    for row in cn.parked_table_rows(idx_text):      # the hand-kept rows, any id (one definition, canary.py)
        pid = cn.clean_cell(row[0]) if row else ""
        item = _shorten(row[1] if len(row) > 1 else "")
        n_read += 1
        if any("->" in c or "→" in c for c in row):
            say(f"Parked {pid} is closed (routed): it goes with the hand-kept table")
            n_done += 1
            continue
        trig = " ".join((row[2] if len(row) > 2 else "").split())
        if pid in imported or pid in origins:
            n_done += 1
            continue
        if not pid or cn.PLACEHOLDER_TRIGGER_RE.fullmatch(cn.clean_cell(trig)) or not item:
            parked_left.append(pid)
            n_done += 1
            out(f"not-now: LEFT Parked {pid or '(no id)'}: no id, no item or no restart trigger; name one, then run again")
            continue
        when = re.search(r"\d{4}-\d\d-\d\d", cn.clean_cell(row[4]) if len(row) > 4 else "")
        when = when.group(0) if when else ""
        parked_new.append((pid, item, trig, f"INDEX Parked {pid}" + (f", parked {when}" if when else "")))
        from_index.add(pid)
        n_done += 1
    if n_done < n_read:                             # safety net: a row nobody accounted for keeps the section
        parked_left.append("?")
        out(f"not-now: LEFT Parked: {n_read - n_done} row(s) of the table were not accounted for; the section stays")
    nums = [int(n) for d in (home / "work-orders", home / "work-orders" / "resolved") for n in cn._wo_files(d)[0]]
    made = []
    for k, (origin, item, trig, evidence) in enumerate(parked_new):
        name, text = _parked_order(f"{max(nums + [0]) + 1 + k:03d}", item, trig, origin, evidence)
        made.append((name, text))
        say(f"{'Parked ' if origin in from_index else ''}{origin} -> a parked order work-orders/{name} "
            f"(trigger: {trig[:60]}{'...' if len(trig) > 60 else ''})")
    if report is not None:
        report["parked_left"] = list(parked_left)
    # 3. carried boxes of open orders
    boxes = []
    wod = home / "work-orders"
    for f in sorted(wod.glob("*.md")) + sorted(wod.glob("*/order.md")) if wod.is_dir() else []:
        text = _read(f)
        info = cn.parse_carried(text, legacy=True)
        for b in info["boxes"]:
            if b["done"]:
                continue
            boxes.append((f, b))
            where = f.relative_to(home).as_posix()
            if b["id"] in rows:
                say(f"{b['id']} carried in {where} is also a row: the box is ticked `-> {b['id']}`")
            else:
                say(f"{b['id']} carried in {where} -> back on the list as `new`, the box ticked `-> {b['id']}`")
        for n, ln in info["bad"]:
            out(f"not-now: LEFT {f.relative_to(home).as_posix()}:{n}: not a box: {ln.strip()[:80]}")
    # 4. the retired drain stores
    retired = []
    for sub in ("declined", "accepted"):
        d = home / "drain" / sub
        files = sorted(d.glob("*.md")) if d.is_dir() else []
        if files:
            ids = sorted({x for f in files for x in (s1._read_proposal(f) or {}).get("item_list", [])},
                         key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
            on = [x for x in ids if x in rows]
            say(f"drain/{sub}/ ({len(files)} files) retired; their items: "
                + (", ".join(f"{x} {'is a row' if x in rows else 'off the list'}" for x in ids) or "none")
                + (" (the row is the authority)" if on else ""))
            retired += files
    if routed_file.is_file():
        both = sorted(routed & set(rows))
        say(f"drain/routed.txt retired ({len(routed)} id(s); not on the list means routed)")
        for lid in both:
            out(f"not-now: LEFT {lid}: drain/routed.txt says routed while it is still a row; drop it or keep it by hand")
        retired.append(routed_file)
    sysone = home / "system-one.json"
    if sysone.is_file():
        say("system-one.json retired (the local model was retired in v75; the drain runs on a helper)")
        retired.append(sysone)
    # 5. the version key of resolved orders
    keyed = []
    for f in sorted(wod.rglob("*.md")) if wod.is_dir() else []:
        raw = _read(f)
        m = re.match(r"---\r?\n(.*?\n)---\r?\n", raw, re.S)
        if m and LANDED_VERSION_RE.search(m.group(1)) and not re.search(r"(?m)^released:", m.group(1)):
            keyed.append(f)
            say(f"{f.relative_to(home).as_posix()}: front matter `landed:` -> `released:`")
    if not write or not moves:
        return moves
    # write: the list first (the authority), then the stores that copied it; a parked order before its row leaves
    if back or [b for _f, b in boxes if b["id"] not in rows]:
        le.insert_rows(home, back + [(b["id"], "", "WO-" + re.search(r"(\d{3})", f.parent.name if f.name == "order.md" else f.name).group(1),
                                      _shorten(b["text"]), "new") for f, b in boxes if b["id"] not in rows])
    for name, text in made:
        dest = wod / name
        dest.write_bytes(text.encode("utf-8"))
        top = (_git(wod, "rev-parse", "--show-toplevel") or "").strip()
        if top:
            _git(top, "add", "--", str(dest))
    if parked_gone:
        le.remove_rows(home, parked_gone)
    if marks:
        le.set_states(home, marks)
    for f in sorted({f for f, _b in boxes}):
        raw = f.read_bytes().decode("utf-8")
        for _f, b in [x for x in boxes if x[0] == f]:
            raw = re.sub(rf"(?m)^- \[ \] ({re.escape(b['id'])} \(slice: [^()\n]*\S\) [^\r\n]*?)[ \t]*(\r?)$",
                         lambda mm: f"- [x] {mm.group(1)} -> {b['id']}{mm.group(2)}", raw, count=1)
        f.write_bytes(raw.encode("utf-8"))
    for f in keyed:
        raw = f.read_bytes().decode("utf-8")
        head, sep, rest = raw.partition("\n---")
        f.write_bytes((LANDED_VERSION_RE.sub("released:", head, count=1) + sep + rest).encode("utf-8"))
    for f in retired:
        _rm(f)
    for sub in ("declined", "accepted"):
        try:
            (home / "drain" / sub).rmdir()
        except OSError:
            pass
    return moves


BOARD_STANDARD_RE = re.compile(r"^(?:Established|Home|Role briefs)\s*:")
PLACEHOLDER_LINE_RE = re.compile(r"^\*?\(?(?:no|none)\b[^|]*\)?\*?$|^\*No recommendations recorded yet\.\*$", re.I)


def _split_sections(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(lines above the first `## ` heading, [(heading line, body lines)]); a fenced `## ` is not a heading."""
    pre: list[str] = []
    secs: list[tuple[str, list[str]]] = []
    fence = False
    for ln in text.splitlines():
        if re.match(r"^\s*```", ln):
            fence = not fence
        if not fence and ln.startswith("## "):
            secs.append((ln, []))
        elif secs:
            secs[-1][1].append(ln)
        else:
            pre.append(ln)
    return pre, secs


def _strip_comments(body: list[str]) -> list[str]:
    """`body` without HTML comments (template guidance, one line or several); the `gitos:index` markers stay."""
    out: list[str] = []
    in_comment = False
    for ln in body:
        s = ln.strip()
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("<!--") and not s.startswith(("<!-- gitos:index", "<!-- /gitos:index")):
            in_comment = "-->" not in s
            continue
        out.append(ln)
    return out


def _is_filler(ln: str) -> bool:
    """A line a section carries by template or by the generated regions: blank, rule, marker, table head or separator."""
    s = ln.strip()
    if not s or set(s) <= set("-|: ") or s.startswith("<!-- gitos:index") or s == "<!-- /gitos:index -->":
        return True
    return bool(re.match(r"^\|\s*(NNN|ID)\s*\|", s))


def _row_id(ln: str, cn) -> str:
    """The identity of a table or prose row (`NNN`, `P1`, ...), else ""."""
    s = ln.strip()
    if s.startswith("|"):
        cells = [c.strip() for c in s.strip("|").split("|")]
        return cn.clean_cell(cells[0]) if cells else ""
    m = cn.PROSE_NNN.match(ln)
    return re.findall(r"\d{3}", m.group(0))[-1] if m else ""


def _body_extras(body: list[str], keep_row, cn) -> list[str]:
    """The lines of a table section that nothing regenerates: text, and rows `keep_row(id, line)` says to keep.
    HTML comments (template guidance) and the generated regions are not extras."""
    out: list[str] = []
    in_region = False
    for ln in body:
        s = ln.strip()
        if s.startswith("<!-- gitos:index"):
            in_region = True
            continue
        if s == "<!-- /gitos:index -->":
            in_region = False
            continue
        if in_region or _is_filler(ln) or PLACEHOLDER_LINE_RE.match(s):
            continue
        rid = _row_id(ln, cn)
        if rid and keep_row(rid, ln):
            out.append(ln)
        elif not rid and not s.startswith("|"):
            out.append(ln)
    return out


def _stamp_released(path: Path, ver: int) -> None:
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    m = re.match(r"(\ufeff?---\r?\n)(.*?)(^---[ \t]*\r?$)", raw, re.S | re.M)
    line = f"released: v{ver}{eol}"
    if m:
        body = m.group(2) if m.group(2).endswith("\n") else m.group(2) + eol
        raw = m.group(1) + body + line + raw[m.start(3):]
    else:
        raw = f"---{eol}{line}---{eol}" + raw
    path.write_bytes(raw.encode("utf-8"))


def migrate_board(home: Path, write: bool, out=print, report: "dict | None" = None) -> int:
    """The WO-124 moves (see the module docstring). -> how many moves were found."""
    cn, li = _load("canary"), _load("ledger_index")
    moves = 0

    def say(text: str) -> None:
        nonlocal moves
        moves += 1
        out(f"board: {text}")
    idx = home / "INDEX.md"
    wod = home / "work-orders"
    raw = _read(idx) if idx.is_file() else ""
    left = set((report or {}).get("parked_left", []))
    on_root = set(cn._wo_files(wod)[0])
    on_res = set(cn._wo_files(wod / "resolved")[0])
    moved: list[tuple[str, list[str]]] = []
    stamps: list[tuple[Path, int]] = []
    if idx.is_file() and li.BOARD_MARK not in raw:
        pre, secs = _split_sections(raw)
        eol = "\r\n" if "\r\n" in raw else "\n"
        above = [ln for ln in pre[1:] if ln.strip() and ln.strip() != "---" and not BOARD_STANDARD_RE.match(ln.strip())]
        if above:
            moved.append(("(text above the first section)", above))
        n_res = n_drop = 0
        for head, body in secs:
            body = _strip_comments(body)
            h = head[3:].strip().lower()
            if h.startswith("open"):
                extra = _body_extras(body, lambda rid, ln: rid not in on_root and rid not in {n for n, _m in cn.parked_orders(home)}, cn)
            elif h.startswith("parked"):
                hand = {cn.clean_cell(r[0]) if r else "" for r in cn.parked_table_rows(raw)}
                extra = _body_extras(body, lambda rid, ln: rid in hand and ("?" in left or rid in left), cn)
            elif h.startswith("resolved"):
                extra = []
                in_region = False
                for ln in body:
                    rid = _row_id(ln, cn) if not _is_filler(ln) else ""
                    if rid and (rid in on_res):
                        n_res += 1
                        f = wod / "resolved" / cn._wo_files(wod / "resolved")[0][rid][0]
                        cells = [c.strip() for c in ln.strip().strip("|").split("|")] if ln.strip().startswith("|") else []
                        vers = [int(v) for v in cn.VERSION_IN_CELL_RE.findall(cells[2])] if len(cells) > 2 else []
                        meta = cn.parse_frontmatter(_read(f) or "") or {}
                        if vers and max(vers) >= cn.LOOSE_ENDS_FROM_VERSION and not (meta.get("released") or _landed_version(meta)):
                            stamps.append((f, max(vers)))
                    elif rid:
                        extra.append(ln)
                    elif not _is_filler(ln) and not ln.strip().startswith("<!--") and ln.strip().strip("*") and not PLACEHOLDER_LINE_RE.match(ln.strip()):
                        extra.append(ln)
                extra = _body_extras(extra, lambda rid, ln: True, cn) if extra else []
            else:
                extra = list(body) if any(not _is_filler(ln) and not PLACEHOLDER_LINE_RE.match(ln.strip()) for ln in body) else []
                while extra and not extra[0].strip():
                    extra.pop(0)
                while extra and (not extra[-1].strip() or extra[-1].strip() == "---"):
                    extra.pop()
            if extra:
                moved.append((head, extra))
        n_drop = n_res
        say(f"INDEX.md ({len(raw.encode('utf-8')):,} bytes) -> the generated board: {n_drop} Resolved row(s) go "
            f"(their order files are the record), {len(stamps)} order file(s) stamped `released:` from the row "
            f"(only a version from v{cn.LOOSE_ENDS_FROM_VERSION} on is read, by the adjudication check)")
        for f, v in stamps:
            say(f"{f.relative_to(home).as_posix()}: `released: v{v}` stamped from its Resolved row")
        if moved:
            say("moved to RESUME.md under one dated heading: " + "; ".join(h.lstrip("# ") for h, _b in moved))
        title = li.BOARD_NAME_RE.search(raw)
        name = title.group(1) if title else home.parent.name
        if write:
            for f, v in stamps:
                _stamp_released(f, v)
            if moved:
                resume = home / "RESUME.md"
                block = [f"## Moved from INDEX.md ({date.today().isoformat()}): sort these", "",
                         "The board (`INDEX.md`) is generated now and holds no hand-written text. What stood in it is below, verbatim:",
                         "keep live state in this file, put a durable decision in the brain (`brain/wiki/decisions/`), delete the rest",
                         "(git keeps the old INDEX). Remove this section once sorted.", "", "````text"]
                for head, body in moved:
                    block += ([head] if head.startswith("## ") else [head]) + body + [""]
                block += ["````", ""]
                old = _read(resume) if resume.is_file() else f"# {name} — RESUME (live session state)\n"
                reol = "\r\n" if "\r\n" in old else "\n"
                resume.write_bytes((old.rstrip("\r\n") + reol + reol + "---" + reol + reol + reol.join(block)).encode("utf-8"))
            idx.write_bytes(f"# {name} — Work-order board{eol}{li.BOARD_MARK}{eol}".encode("utf-8"))
            new, _differing, _found = li.render(home)
            idx.write_bytes(new.encode("utf-8"))
    elif idx.is_file():
        new, differing, found = li.render(home)
        if found and differing:
            say(f"INDEX.md differs from its source ({', '.join(differing)}): regenerated")
            if write:
                idx.write_bytes(new.encode("utf-8"))
    fp = home / "footprints.md"
    if fp.is_file():
        say("footprints.md retired (a landing's footprint is `git show --name-only <sha>`)")
        if write:
            _rm(fp)
    logs = sorted(wod.rglob("WO-*/log.md")) if wod.is_dir() else []
    logs += [f for f in sorted(wod.rglob("*/log.md")) if f not in logs and (f.parent / "order.md").is_file()]
    if logs:
        say(f"{len(logs)} per-order log.md file(s) retired (the slice files hold the state, `git log` the history)")
        if write:
            for f in logs:
                _rm(f)
    return moves



def run(home: Path, write: bool, out=print) -> int:
    sl, cn = _load("slice"), _load("canary")
    wod = home / "work-orders"
    hdir = wod / "history"
    out(f"ledger_migrate: {home} ({'--write' if write else 'dry run; nothing is written, pass --write to apply'})")
    if not wod.is_dir():
        out("ledger_migrate: no work-orders/ folder; nothing to migrate")
        return 0
    state: dict = {}
    if not migrate_not_now(home, write, out, state):
        out("not-now: nothing to move (one list already)")
    if not migrate_board(home, write, out, state):
        out("board: nothing to move (the INDEX is the generated board already)")
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
        out("ledger_migrate: no order to convert to the folder form")
    for b in boxes:
        out(f"carried box left in order.md (the not-now step above moves it to the list): {b}")
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
