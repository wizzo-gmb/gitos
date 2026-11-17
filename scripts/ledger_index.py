#!/usr/bin/env python3
"""ledger_index.py - generate the Open and Resolved tables of a gitos home's INDEX.md from the order files.

    python ledger_index.py [--check] <home>

Regenerates only what lies between `<!-- gitos:index open -->` ... `<!-- /gitos:index -->` and
`<!-- gitos:index resolved -->` ... `<!-- /gitos:index -->` in `<home>/INDEX.md`. Everything else in the
file is left byte for byte, line endings included. An INDEX with no markers is not touched: the tool prints
one line saying so (a repo opts in by laying the markers).

  * An order is a file `WO-NNN-slug.md` or, with two or more slices, a folder `WO-NNN/` whose `order.md` is
    read as the file would be.
  * Open rows come from the order files in `work-orders/`: `| NNN | Severity | Title | evidence |`.
    Severity, title and evidence read from front matter (`severity`, `title`, `evidence`); with none, from
    the H1 (`# WO-NNN - Title`) and the first word of `## Severity`; evidence then reads an em dash.
    Sorted by severity (critical, high, medium, low, unconfirmed), then number.
  * Resolved rows come from `work-orders/resolved/` files whose front matter carries `summary`, `landed`
    and `result`. Newest number first. A resolved order without them is skipped: its hand-kept row stays.
  * `--check` writes nothing and exits 1 with one line per differing region, 0 when in sync.

Front matter is a flat block between `---` lines at the very top of a file: `key: value`, a value is a bare
string or `[a, b]`. Nothing else; the engine is stdlib-only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

OPEN_MARK = "<!-- gitos:index open -->"
RESOLVED_MARK = "<!-- gitos:index resolved -->"
END_MARK = "<!-- /gitos:index -->"
SEVERITY_ORDER = ("critical", "high", "medium", "low", "unconfirmed")
WO_FILE_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)[-_.][A-Za-z0-9][\w.-]*\.md$")
DIR_RE = re.compile(r"^(?:[A-Za-z]+[-_.]?)?(\d{3})(?!\d)(?:[-_.][A-Za-z0-9][\w.-]*)?$")
H1_RE = re.compile(r"^#\s+(?:[A-Za-z]+[-_.]?)?\d{3}(?!\d)\s*[—–-]+\s*(.+?)\s*$")
EM_DASH = "—"
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


def open_rows(home: Path) -> list[str]:
    rows = []
    for nnn, f in _orders(home / "work-orders"):
        i = _info(f)
        sev = i["severity"]
        rank = SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else len(SEVERITY_ORDER)
        rows.append((rank, nnn, f"| {nnn} | {sev} | {i['title']} | {i['evidence']} |"))
    return [r[2] for r in sorted(rows, key=lambda r: (r[0], r[1]))]


def resolved_rows(home: Path) -> list[str]:
    rows = []
    for nnn, f in _orders(home / "work-orders" / "resolved"):
        i = _info(f)
        m = i["meta"]
        if not all(isinstance(m.get(k), str) and m.get(k) for k in ("summary", "landed", "result")):
            continue
        title = i["title"].rstrip(".")
        rel = f.relative_to(home / "work-orders" / "resolved").as_posix()
        rows.append((nnn, f"| {nnn} | **{title}.** {m['summary']} ([WO-{nnn}](work-orders/resolved/{rel})) "
                          f"| {m['landed']} | {m['result']} |"))
    return [r[1] for r in sorted(rows, key=lambda r: r[0], reverse=True)]


def _find(lines: list[str], mark: str) -> tuple[int, int] | None:
    """(start line, end line) of the first `mark` region, or None when it is absent or unclosed."""
    for i, ln in enumerate(lines):
        if ln.strip() == mark:
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == END_MARK:
                    return i, j
            return None
    return None


def render(home: Path) -> tuple[str, list[str], bool]:
    """-> (new INDEX text, names of the regions that differ, markers-found)."""
    raw = (home / "INDEX.md").read_bytes().decode("utf-8")
    lines = raw.splitlines(keepends=True)
    differing: list[str] = []
    found = False
    for name, mark, rows in (("open", OPEN_MARK, open_rows(home)),
                             ("resolved", RESOLVED_MARK, resolved_rows(home))):
        span = _find(lines, mark)
        if span is None:
            continue
        found = True
        s, e = span
        eol = "\r\n" if lines[s].endswith("\r\n") else "\n"
        new = [r + eol for r in rows]
        if lines[s + 1:e] != new:
            differing.append(name)
            lines[s + 1:e] = new
    return "".join(lines), differing, found


def drift(home: Path) -> list[str] | None:
    """The regions whose generated content differs from the file; None when the INDEX has no markers."""
    if not (home / "INDEX.md").is_file():
        return None
    _, differing, found = render(home)
    return differing if found else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the INDEX.md Open and Resolved tables from the order files.")
    ap.add_argument("home", help="the home directory, e.g. <repo>/.gitos")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when a region differs")
    args = ap.parse_args()
    home = Path(args.home).resolve()
    if not (home / "INDEX.md").is_file():
        print(f"ledger_index: no INDEX.md in {home}", file=sys.stderr)
        return 2
    text, differing, found = render(home)
    if not found:
        print("ledger_index: no index markers in INDEX.md; nothing generated")
        return 0
    if args.check:
        for name in differing:
            print(f"ledger_index: the {name} region of INDEX.md differs from the order files "
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
