#!/usr/bin/env python3
"""ledger_index.py - generate a gitos home's INDEX.md: the work-order board.

    python ledger_index.py [--check] <home>

INDEX.md is the board and nothing else: a header (the engine version stamp, the counts, pointers to RESUME.md, the
brain index and `work-orders/resolved/`), the Open table and the Parked table. The whole file is generated from the order
files, so its size is a function of the open and parked work only. History is not copied into it: an order's file in
`work-orders/resolved/` is its record, `ls work-orders/resolved` is the list and `git log` is the timeline.

An INDEX carries the line `<!-- gitos:index board -->` once the repo has the board form (`ledger_migrate.py` lays it;
`scaffold.py` seeds it). With it, `ledger_index.py` rewrites the whole file; the project name is read from the first
heading and the line endings are kept. An INDEX with `gitos:index` region markers but no board line is the older
hand-kept form: it is never rewritten (hand-written sections would be lost); the tool says so and `--check` reports
the part `form`. An INDEX with no marker is not touched: the tool prints one line saying so.

  * An order is a file `WO-NNN-slug.md` or, with two or more slices, a folder `WO-NNN/` whose `order.md` is
    read as the file would be.
  * Open rows come from the order files in `work-orders/` that are not parked: `| NNN | Severity | Title | evidence |`.
    Severity, title and evidence read from front matter (`severity`, `title`, `evidence`); with none, from
    the H1 (`# WO-NNN - Title`) and the first word of `## Severity`; evidence then reads an em dash. The evidence
    cell is cut at EVIDENCE_MAX characters (the order file holds it whole). Sorted by severity (critical, high,
    medium, low, unconfirmed), then number.
  * Parked rows come from the parked orders (WO-116): an order file in `work-orders/` whose front matter says
    `status: parked` and `trigger: <restart trigger>`, as `| NNN | Title | trigger | evidence |`, by number.
    Nobody types a row here.
  * A resolved order is stamped `released: <engine version>` in its front matter (the older key `landed` still reads)
    and moved to `work-orders/resolved/`; nothing else is written for it.
  * `--check` writes nothing and exits 1 with one line per differing part, 0 when in sync.

Front matter is a flat block between `---` lines at the very top of a file: `key: value`, a value is a bare
string or `[a, b]`. Nothing else; the engine is stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BOARD_MARK = "<!-- gitos:index board -->"
INDEX_MARK = "<!-- gitos:index "
OPEN_MARK = "<!-- gitos:index open -->"
PARKED_MARK = "<!-- gitos:index parked -->"
RELEASED_KEYS = ("released", "landed")      # the version key of a resolved order; `landed` is its older name
END_MARK = "<!-- /gitos:index -->"
SEVERITY_ORDER = ("critical", "high", "medium", "low", "unconfirmed")
WO_FILE_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)[-_.][A-Za-z0-9][\w.-]*\.md$")
DIR_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)(?:[-_.][A-Za-z0-9][\w.-]*)?$")
H1_RE = re.compile(r"^#\s+(?:[A-Za-z]+[-_.]?)?\d{3}(?!\d)\s*[—–-]+\s*(.+?)\s*$")
EM_DASH = "—"
EVIDENCE_MAX = 100          # characters of the evidence cell on the board; the order file holds it whole
BOARD_NAME_RE = re.compile(r"^#\s+(.+?)\s+[—–-]+\s+Work-order\b", re.MULTILINE)
# Per-file limits of a folder order (lines), and the slice count past which splitting the order is advised.
ORDER_MAX_LINES = 200
SLICE_MAX_LINES = 150
SPLIT_ADVICE_SLICES = 8
SLICE_STALE_DAYS = 7


def parse_front_matter(text: str) -> tuple[dict, str]:
    """-> ({key: str | list[str]}, body). No front matter (or an unclosed block) -> ({}, text)."""
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict = {}
    for i in range(1, len(lines)):
        s = lines[i].strip()
        if s == "---":
            return meta, "".join(lines[i + 1:])
        if not s or s.startswith("#") or ":" not in s:
            continue
        key, _, val = s.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key.strip()] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = val
    return {}, text


def _info(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_front_matter(text)
    lines = body.splitlines()
    h1 = next((m.group(1) for m in (H1_RE.match(ln) for ln in lines) if m), "")
    sev_word = ""
    for i, ln in enumerate(lines):
        if ln.strip().startswith("## Severity"):
            for nxt in lines[i + 1:]:
                m = re.search(r"[A-Za-z]+", nxt)
                if m:
                    sev_word = m.group(0).lower()
                    break
            break
    return {"meta": meta,
            "title": meta.get("title") or h1 or path.stem,
            "severity": (meta.get("severity") or sev_word or "unconfirmed").lower(),
            "evidence": meta.get("evidence") or EM_DASH}


def _orders(d: Path) -> list[tuple[str, Path]]:
    out = []
    if d.is_dir():
        for f in sorted(d.glob("*.md")):
            m = WO_FILE_RE.match(f.name)
            if m:
                out.append((m.group(1), f))
        # the folder form (an order with two or more slices): `WO-NNN/order.md` is the order
        for sub in sorted(x for x in d.iterdir() if x.is_dir()):
            m = DIR_RE.match(sub.name)
            if m and (sub / "order.md").is_file():
                out.append((m.group(1), sub / "order.md"))
    return out


def is_parked(meta: dict) -> bool:
    return str(meta.get("status", "")).strip().lower() == "parked"


def parked_orders(home: Path) -> list[tuple[str, Path, dict]]:
    """[(NNN, file, info)] of the parked orders: open order files whose front matter says `status: parked`."""
    return [(nnn, f, i) for nnn, f in _orders(home / "work-orders") for i in [_info(f)] if is_parked(i["meta"])]


def open_rows(home: Path) -> list[str]:
    rows = []
    for nnn, f in _orders(home / "work-orders"):
        i = _info(f)
        if is_parked(i["meta"]):
            continue
        sev = i["severity"]
        rank = SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else len(SEVERITY_ORDER)
        rows.append((rank, nnn, f"| {nnn} | {sev} | {i['title']} | {_short(i['evidence'])} |"))
    return [r[2] for r in sorted(rows, key=lambda r: (r[0], r[1]))]


def released(meta: dict) -> str:
    """The engine version a resolved order records (`released:`, else the older `landed:`); "" when neither."""
    return next((meta[k] for k in RELEASED_KEYS if isinstance(meta.get(k), str) and meta.get(k)), "")


def parked_rows(home: Path) -> list[str]:
    """The parked orders, as INDEX rows."""
    return [f"| {nnn} | {i['title']} | {i['meta'].get('trigger') or EM_DASH} | {_short(i['evidence'])} |"
            for nnn, _f, i in parked_orders(home)]


def _find(lines: list[str], mark: str) -> tuple[int, int] | None:
    """(start line, end line) of the first `mark` region, or None when it is absent or unclosed."""
    for i, ln in enumerate(lines):
        if ln.strip() == mark:
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == END_MARK:
                    return i, j
            return None
    return None


def _short(text: str, n: int = EVIDENCE_MAX) -> str:
    """`text` cut at `n` characters on a word boundary, never inside an open link or code span."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,;:-")
    while cut.count("[") > cut.count("]") or cut.count("(") > cut.count(")"):
        k = max(cut.rfind("["), cut.rfind("("))
        cut = cut[:k].rstrip(" ,;:-")
    if cut.count("`") % 2:
        cut += "`"
    return cut + "..."


def _engine_version(home: Path) -> str:
    """The brain's engine-version stamp as `vN`; "" when the home has none."""
    try:
        v = json.loads((home / "brain" / ".brainmeta.json").read_text(encoding="utf-8")).get("engine_version")
    except (OSError, ValueError, AttributeError):
        return ""
    return f"v{v}" if isinstance(v, (int, str)) and str(v).strip() else ""


def board_name(raw: str, home: Path) -> str:
    """The project name on the board's first line: kept from the existing heading, else the repo folder."""
    m = BOARD_NAME_RE.search(raw)
    return m.group(1) if m else home.parent.name


def board_text(home: Path, name: str, eol: str = "\n") -> str:
    """The whole INDEX.md of `home`: header, Open table, Parked table."""
    open_r, parked_r = open_rows(home), parked_rows(home)
    n_res = len(_orders(home / "work-orders" / "resolved"))
    ver = _engine_version(home)
    lines = [
        f"# {name} — Work-order board",
        BOARD_MARK,
        "",
        "Generated by `ledger_index.py` from the order files; an edit here is overwritten. "
        + (f"home stamped at engine {ver}. " if ver else "") + f"{len(open_r)} open, {len(parked_r)} parked, {n_res} resolved.",
        "",
        "Live state and next steps: `RESUME.md`. Brain index: `brain/wiki/index.md`. History: `work-orders/resolved/` "
        "(`ls` is the list, `git log` the timeline). Paths are relative to this file.",
        "",
        "## Open work-orders (by severity)",
        "",
        "| NNN | Severity | Title | Primary evidence file:line |",
        "|-----|----------|-------|---------------------------|",
        OPEN_MARK, *open_r, END_MARK,
        "",
        "## Parked (deferred, with restart trigger)",
        "",
        "| NNN | Title | Restart trigger | Evidence |",
        "|-----|-------|-----------------|----------|",
        PARKED_MARK, *parked_r, END_MARK,
    ]
    return eol.join(lines) + eol


def _region(lines: list[str], mark: str) -> "list[str] | None":
    span = _find(lines, mark)
    return None if span is None else lines[span[0] + 1:span[1]]


def render(home: Path) -> tuple[str, list[str], bool]:
    """-> (new INDEX text, names of the parts that differ, markers-found).

    A board INDEX is rebuilt whole; an older hand-kept INDEX with region markers is returned as it is with
    `["form"]` (nothing is generated into it); an INDEX with no markers is `found=False`."""
    raw = (home / "INDEX.md").read_bytes().decode("utf-8")
    if INDEX_MARK not in raw:
        return raw, [], False
    if BOARD_MARK not in raw:
        return raw, ["form"], True
    eol = "\r\n" if "\r\n" in raw else "\n"
    new = board_text(home, board_name(raw, home), eol)
    if new == raw:
        return new, [], True
    old_l, new_l = raw.splitlines(keepends=True), new.splitlines(keepends=True)
    differing = [name for name, mark in (("open", OPEN_MARK), ("parked", PARKED_MARK))
                 if _region(old_l, mark) != _region(new_l, mark)]
    return new, differing or ["header"], True


def drift(home: Path) -> list[str] | None:
    """The parts whose generated content differs from the file; None when the INDEX has no markers."""
    if not (home / "INDEX.md").is_file():
        return None
    _, differing, found = render(home)
    return differing if found else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the INDEX.md work-order board.")
    ap.add_argument("home", help="the home directory, e.g. <repo>/.gitos")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when the board differs")
    args = ap.parse_args()
    home = Path(args.home).resolve()
    if not (home / "INDEX.md").is_file():
        print(f"ledger_index: no INDEX.md in {home}", file=sys.stderr)
        return 2
    text, differing, found = render(home)
    if not found:
        print("ledger_index: no index markers in INDEX.md; nothing generated")
        return 0
    if differing == ["form"]:
        print("ledger_index: INDEX.md is the hand-kept form (no board line); nothing is generated into it "
              f"-> run ledger_migrate.py {home} --write to lay the board")
        return 1 if args.check else 0
    if args.check:
        for name in differing:
            print(f"ledger_index: the {name} part of INDEX.md differs from its source "
                  f"-> run ledger_index.py {home}")
        return 1 if differing else 0
    if differing:
        (home / "INDEX.md").write_bytes(text.encode("utf-8"))
        print("ledger_index: regenerated " + ", ".join(differing))
    else:
        print("ledger_index: in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
