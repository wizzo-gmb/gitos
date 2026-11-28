#!/usr/bin/env python3
"""loose_ends.py - the loose-ends list every repo has (WO-093). Standard library only.

`<home>/loose-ends.md` is a tracked table of small things that came up while other work was going
on. A loose end is the last resort (WO-116): a finding is fixed in the order that found it; only one clearly out of
that order's scope, or crossing into a new scope, is deferred, as a work-order, a parked work-order (`status:
parked`, `trigger:`) or, rarest, a row here that passes the five tests (concrete, a known small fix,
self-contained, not owned, a reason it cannot be done now). Nothing is dropped. `add` stores the fix and the
out-of-scope reason in the row (`<item> · fix: <fix> · not now: <why>`, at most MAX_ITEM characters). Work is never dispatched from the list (an item is first dropped `--to WO-NNN`).

    | ID | Added | Source | Item | State |

`ID` is `L<n>`, never reused (the next id lives in `<!-- next: L<n> -->` under the table).
`Source` is `WO-NNN`, `P<n>`, `chat`, `proposal:<id>` or `import:<old id>`. The list is the one place "not now"
lives (WO-115); a row's State is one of four:

    new                   written down, not looked at (the drain asks only these)
    proposed: <kind>      the drain proposed join | new-order | close | ask | park | read; the pile file
                          `<home>/drain/pending/<id>.md` is its attachment (what the helper saw), not its home
    waiting: <question>   needs the operator
    declined: <reason>    looked at and refused; never proposed again

`parked: <trigger>` is retired (WO-116): deferred work with a restart trigger is a parked work-order, and
`ledger_migrate.py` turns an old `parked:` row into one. A row whose State is none of these is reported, never
read as `new`. An item that is routed or closed is REMOVED
(git keeps it): not on the list means routed. One routing grammar, the adjudication arrows:
`WO-NNN | WO-NNN/SN | brain:<page> | closed:<reason>`.

    loose_ends.py add        [--root R] --source S --item TEXT --fix CHANGE --why-not-now REASON [--state STATE]
    loose_ends.py state      [--root R] L<n> STATE      (new, waiting: Q or declined: R)
    loose_ends.py drop       [--root R] L<n> --to WO-NNN | WO-NNN/SN | brain:<page> | closed:<reason>
    loose_ends.py list       [--root R] [--json]
    loose_ends.py status     [--brief] [ROOT]     (one line: the rows by state; then everything waiting on you: waiting.py)
    loose_ends.py candidates [--root R] [--json]     (code only, no model)
    loose_ends.py import     [--root R] FILE
    loose_ends.py legacy     pending | decline FILE [--root R] [--json]

`state` and `drop` on a row a pile file holds also release it: a proposal that holds only that item is removed, one
that holds others is rewritten without it.

Only the orchestrator writes the list. Every write is atomic and keeps every other row and line
byte for byte. No file means an empty list (nothing is written by drop, list, status, candidates);
`add` (and `import`, `legacy decline`) lays the file from the template on first use. A legacy register is
asked about once: the answer is a `<!-- legacy: <path> imported|declined -->` line in the list header.
"""
from __future__ import annotations

import argparse
import importlib.util as importlib_util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

NAME = "loose-ends.md"
MAX_ITEM = 300
HEADER_CELLS = ["id", "added", "source", "item", "state"]
TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "loose-ends.md.tmpl"
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")

ID_RE = re.compile(r"L\d+")
SOURCE_RE = re.compile(r"(?:WO-\d{3,}|P\d+|chat|proposal:\S+|import:.+)")
NEXT_RE = re.compile(r"<!--\s*next:\s*L(\d+)\s*-->")
STATE_NEW = "new"
JOIN_TOP = 3                      # open orders offered to an item as a join
MAX_JOIN_PAIRS = 60               # join pairs asked per run
ORDER_BODY_CHARS = 4000           # an order with no Implementer notes heading is read this far
BM25_K1, BM25_B = 1.2, 0.75       # the word part of the join score
JOIN_MIN_COVER = 0.0              # share of the item's words an order must hold when nothing is shared; none
DEST_RE = re.compile(r"(?:WO-(\d{3,})(?:/S(\d+[a-z]?))?|brain:\s*(\S.*)|closed:\s*(\S.*))")
SETTABLE = {"new": "", "waiting": "question", "declined": "reason"}   # `proposed:` is the drain's
DONE_CELL_RE = re.compile(r"^[\s*_`~>\-]*(?:done|fixed|closed|merged|superseded|resolved)\b", re.IGNORECASE)
UNESC_PIPE = re.compile(r"(?<!\\)\|")
TOO_LONG = ("this is a work-order or a RESUME entry, not a loose end: author one, or shorten it "
            f"(an item is at most {MAX_ITEM} characters)")


class LooseEndsError(Exception):
    """A refusal; the message is what the CLI prints."""


def today() -> date:
    return date.today()


# ------------------------------------------------------------------ siblings (loaded by path)
def _sibling(modname: str, filename: str):
    mod = sys.modules.get(modname)
    if mod is None:
        spec = importlib_util.spec_from_file_location(modname, Path(__file__).resolve().with_name(filename))
        mod = importlib_util.module_from_spec(spec)
        sys.modules[modname] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(modname, None)
            raise
    return mod


def _canary():
    return _sibling("_gitos_canary_le", "canary.py")


def _system_one():
    return _sibling("_gitos_system_one_le", "system_one.py")


# ------------------------------------------------------------------ home and file
def resolve_home(root) -> Path:
    root = Path(root)
    for rel in HOMES:
        if (root / rel).is_dir():
            return root / rel
    return root


def list_path(home) -> Path:
    return Path(home) / NAME


def _cells(line: str) -> list:
    """Raw cells of a table line (between the outer pipes), unescaped pipes only."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return UNESC_PIPE.split(s)


def _clean(cell: str) -> str:
    return cell.strip().replace("\\|", "|")


def _esc(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _row(raw_cells: list) -> dict:
    c = [_clean(x) for x in raw_cells] + [""] * 5
    return {"id": c[0], "added": c[1], "source": c[2], "item": c[3], "state": c[4],
            "ncells": len(raw_cells)}


def parse(text: str) -> dict:
    """{"header": (first, last) line index of the header+separator or None, "rows": [row + "line"],
    "end": index after the last table line, "next": int | None, "next_line": index | None,
    "lines": [...]}. Lenient: a malformed file still parses what it can (the canary judges it)."""
    lines = text.splitlines(keepends=True)
    out = {"lines": lines, "table": None, "rows": [], "end": None, "next": None, "next_line": None}
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("|") and [_clean(c).lower() for c in _cells(ln)] == HEADER_CELLS:
            out["table"] = i
            break
    if out["table"] is None:
        return out
    j = out["table"] + 1
    if j < len(lines) and lines[j].lstrip().startswith("|"):
        j += 1                                              # the separator
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        r = _row(_cells(lines[j]))
        r["line"] = j
        out["rows"].append(r)
        j += 1
    out["end"] = j
    for k in range(j, len(lines)):
        m = NEXT_RE.search(lines[k])
        if m:
            out["next"], out["next_line"] = int(m.group(1)), k
            break
    return out


def load(home) -> "dict | None":
    """The parsed list, or None when there is no file."""
    p = list_path(home)
    if not p.is_file():
        return None
    return parse(p.read_bytes().decode("utf-8"))


def age_days(added: str, now: "date | None" = None) -> "int | None":
    try:
        d = date.fromisoformat(added.strip())
    except ValueError:
        return None
    return max(0, ((now or today()) - d).days)


def _next_id(p: dict) -> int:
    used = [int(r["id"][1:]) for r in p["rows"] if ID_RE.fullmatch(r["id"])]
    return max([p["next"] or 1] + [u + 1 for u in used])


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _write(home, text: str) -> None:
    """Atomic: a temp file in the home, then replace. Bytes are written as given (no newline mapping)."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".loose-ends-", suffix=".tmp", dir=str(home))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        os.replace(tmp, list_path(home))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _source(text: str) -> str:
    s = " ".join(str(text).split())
    if not SOURCE_RE.fullmatch(s):
        raise LooseEndsError(f"--source {s!r} is not WO-NNN, P<n>, chat, proposal:<id> or import:<old id>")
    return s


def _item(text: str) -> str:
    s = " ".join(str(text).split())
    if not s:
        raise LooseEndsError("--item is empty")
    if len(s) > MAX_ITEM:
        raise LooseEndsError(f"{TOO_LONG}: {len(s)} characters")
    return s


def _text_or_template(home) -> str:
    p = list_path(home)
    if p.is_file():
        return p.read_bytes().decode("utf-8")
    try:
        return TEMPLATE.read_text(encoding="utf-8")
    except OSError as e:
        raise LooseEndsError(f"no {NAME} and the template cannot be read ({e})")


def _append_rows(text: str, new_rows: list) -> str:
    """`text` with the rows added at the end of the table and the next-id comment moved up. Nothing
    else changes. `new_rows` are (source, item[, added date[, state]]) tuples with the item already cleaned."""
    p = parse(text)
    if p["table"] is None:
        raise LooseEndsError(f"{NAME} has no `| ID | Added | Source | Item | State |` table: fix it first")
    lines, eol, nid = list(p["lines"]), _eol(text), _next_id(p)
    add = []
    for row in new_rows:
        src, item = row[0], row[1]
        added = row[2] if len(row) > 2 and row[2] else today().isoformat()
        state = row[3] if len(row) > 3 and row[3] else STATE_NEW
        add.append(f"| L{nid} | {added} | {src} | {_esc(item)} | {_esc(state)} |{eol}")
        nid += 1
    at = p["end"]
    if at > 0 and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += eol
    lines[at:at] = add
    comment = f"<!-- next: L{nid} -->"
    if p["next_line"] is not None:
        k = p["next_line"] + len(add)
        lines[k] = NEXT_RE.sub(comment, lines[k], count=1)
    else:
        k = at + len(add)
        lines[k:k] = [eol, comment + eol]
    return "".join(lines)


# ------------------------------------------------------------------ operations
PARKED_RETIRED = ("`parked:` is retired: deferred work with a restart trigger is a parked work-order (an order file "
                  "with front matter `status: parked` and `trigger: <restart trigger>`); author one, then "
                  "`drop L<n> --to WO-NNN`")


def specified(item: str, fix: str, why_not_now: str) -> str:
    """The Item cell of a loose end: the item, its known fix and why it cannot be done now. A LooseEndsError when
    the fix or the reason is missing or a word or two: a row that cannot say both is not a loose end."""
    for flag, text in (("--fix", fix), ("--why-not-now", why_not_now)):
        if len(" ".join(str(text or "").split()).split()) < 3:
            raise LooseEndsError(f"{flag} is required (a few words): a loose end is the last resort and names its "
                                 "known small fix and why it is out of the order's scope or crosses into a new "
                                 "scope; otherwise fix it in the order")
    return f"{' '.join(str(item).split())} · fix: {' '.join(fix.split())} · not now: {' '.join(why_not_now.split())}"


def add(home, source: str, item: str, state: "str | None" = None, fix: "str | None" = None,
        why_not_now: "str | None" = None) -> str:
    """Append a row. With `fix` or `why_not_now` both are required and stored in the Item cell (`specified`); the
    CLI always passes both. Without either it is the internal path (the import and tests write bare items)."""
    if fix is not None or why_not_now is not None:
        item = specified(item, fix, why_not_now)
    src, it = _source(source), _item(item)
    st = _state_text(state) if state else STATE_NEW
    text = _text_or_template(home)
    p = parse(text)
    new_id = f"L{_next_id(p)}"
    _write(home, _append_rows(text, [(src, it, "", st)]))
    return new_id


def _find(p: dict, lid: str) -> dict:
    lid = lid.strip()
    for r in p["rows"]:
        if r["id"] == lid:
            return r
    raise LooseEndsError(f"no loose end {lid}")


def _wo_open(home: Path, nnn: str) -> bool:
    by, _ = _canary()._wo_files(Path(home) / "work-orders")
    return bool(by.get(nnn))


def check_dest(home, dest: str) -> str:
    """The destination `drop` and a routed decline accept, normalised; a LooseEndsError when it is not one."""
    d = " ".join(str(dest).split())
    m = DEST_RE.fullmatch(d)
    if not m:
        raise LooseEndsError(f"--to {d!r} is not WO-NNN, WO-NNN/SN, brain:<page> or closed:<reason>")
    wo, sn, _brain, closed = m.groups()
    if wo and not _wo_open(home, wo):
        raise LooseEndsError(f"WO-{wo} is not an open work-order in {Path(home) / 'work-orders'}: "
                             "author it first, then drop the item to it")
    if sn and _sibling("_gitos_slice_le", "slice.py").find_slice(Path(home), f"WO-{wo}/S{sn}") is None:
        raise LooseEndsError(f"WO-{wo}/S{sn} is not a slice of WO-{wo}: add it first (`slice.py add`)")
    if closed and len(closed.split()) < 3:
        raise LooseEndsError("closed: needs a reason of at least a few words (what makes it done or moot)")
    return d


def parse_state(state: str) -> "tuple[str, str] | None":
    """(name, argument) of a State; None when it is not one of the five (see the module docstring)."""
    return _canary().parse_loose_state(state)


def _state_text(state: str) -> str:
    """A State `state` and `add --state` may write, normalised; a LooseEndsError otherwise."""
    s = " ".join(str(state).split())
    st = parse_state(s)
    if st is None or st[0] not in SETTABLE:
        if s.startswith("parked"):
            raise LooseEndsError(PARKED_RETIRED)
        raise LooseEndsError(f"State {s!r} is not one of: new, waiting: <question>, "
                             "declined: <reason> (`proposed:` is written by the drain)")
    return s


def _release(home, lid: str) -> list:
    """Take `lid` out of the pile files that hold it -> notes for the operator."""
    sm = _system_one()
    if not sm.pending_holding(home, lid):
        return []
    done = sm.release_items(home, [lid])
    return [f"withdrew proposal {x}" for x in done["withdrawn"]] + [
        f"proposal {old} is now {new} without it" for old, new in done["edited"]]


def drop(home, lid: str, dest: str) -> "str | None":
    """Route or close an item: its row leaves the list (not on the list means routed). Its pile files are released
    first, so a crash leaves the row (drop again), never a proposal for a routed item. No list file is an empty
    list: nothing to drop (None)."""
    d = check_dest(home, dest)
    lid = lid.strip()
    if not list_path(home).is_file():
        return None
    _find(parse(_text_or_template(home)), lid)
    note = _release(home, lid)
    remove_rows(home, [lid])
    return f"{lid} -> {d}" + ("; " + "; ".join(note) if note else "")


def set_states(home, states: dict) -> list:
    """Write each row's State (`{L<n>: state}`, checked by the caller) in one atomic write; every other byte stays.
    -> the ids changed. An id not on the list raises before anything is written."""
    text = _text_or_template(home)
    p = parse(text)
    lines = list(p["lines"])
    rows = {r["id"]: r for r in p["rows"]}
    for lid in states:
        if lid not in rows:
            raise LooseEndsError(f"no loose end {lid}")
    changed = []
    for lid, st in states.items():
        r = rows[lid]
        if r["state"] == st:
            continue
        ln = lines[r["line"]]
        body = ln.rstrip("\r\n")
        cells = _cells(body)
        cells[4] = f" {_esc(st)} "
        lines[r["line"]] = "|" + "|".join(cells) + "|" + ln[len(body):]
        changed.append(lid)
    if changed:
        _write(home, "".join(lines))
    return changed


def set_state(home, lid: str, state: str) -> str:
    """The `state` command: a row to `new`, `waiting: Q` or `declined: R`. The row is written first,
    then any pile file holding it is released, so a crash leaves a pile file beside a row that is not `proposed:`
    (the canary reports it; `state` run again clears it)."""
    s = _state_text(state)
    lid = lid.strip()
    if not list_path(home).is_file():
        raise LooseEndsError(f"no loose end {lid} (there is no {NAME})")
    _find(parse(_text_or_template(home)), lid)
    set_states(home, {lid: s})
    note = _release(home, lid)
    return f"{lid}: {s}" + ("; " + "; ".join(note) if note else "")


def remove_rows(home, ids) -> list:
    """Remove the rows with these ids in one atomic write. -> the ids removed. No file, or none of them on the list,
    writes nothing."""
    want = {i.strip() for i in ids}
    if not list_path(home).is_file() or not want:
        return []
    p = parse(_text_or_template(home))
    gone = [r for r in p["rows"] if r["id"] in want]
    if not gone:
        return []
    lines = [ln for k, ln in enumerate(p["lines"]) if k not in {r["line"] for r in gone}]
    _write(home, "".join(lines))
    return [r["id"] for r in gone]


def _fmt(r: dict, now=None) -> str:
    age = age_days(r["added"], now)
    when = f"{age}d" if age is not None else "?d"
    state = "new" if r["state"] == STATE_NEW else r["state"]
    return f"{r['id']}  {when:>4}  [{r['source']}]  {r['item']}  ({state})"


def rows_of(home) -> list:
    p = load(home)
    return [] if p is None else p["rows"]


def insert_rows(home, rows: list) -> list:
    """Put rows on the list with their own id: `rows` are (id, added, source, item, state), an empty Added is today.
    An id already on the list is left as it is. -> the ids added. Ids are never reused, so the next-id comment only
    ever moves up. Used by the migration (a pile item or a carried box back on the list)."""
    text = _text_or_template(home)
    p = parse(text)
    if p["table"] is None:
        raise LooseEndsError(f"{NAME} has no `| ID | Added | Source | Item | State |` table: fix it first")
    have = {r["id"] for r in p["rows"]}
    todo = [r for r in rows if r[0] not in have]
    if not todo:
        return []
    lines, eol = list(p["lines"]), _eol(text)
    add = [f"| {lid} | {added or today().isoformat()} | {_esc(src)} | {_esc(item)} | {_esc(state)} |{eol}"
           for lid, added, src, item, state in todo]
    at = p["end"]
    if at > 0 and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += eol
    lines[at:at] = add
    nid = max([_next_id(p)] + [int(r[0][1:]) + 1 for r in todo if ID_RE.fullmatch(r[0])])
    comment = f"<!-- next: L{nid} -->"
    if p["next_line"] is not None:
        k = p["next_line"] + len(add)
        lines[k] = NEXT_RE.sub(comment, lines[k], count=1)
    else:
        k = at + len(add)
        lines[k:k] = [eol, comment + eol]
    _write(home, "".join(lines))
    return [r[0] for r in todo]


def state_counts(home) -> "dict | None":
    """{new, proposed, parked, waiting, declined, unreadable: n}; None when there is no list file."""
    p = load(home)
    if p is None:
        return None
    out = {k: 0 for k in ("new", "proposed", "parked", "waiting", "declined", "unreadable")}
    for r in p["rows"]:
        out[(parse_state(r["state"]) or ("unreadable",))[0]] += 1
    return out


def brief(home, now=None) -> "str | None":
    """One line, or None when there is no list file."""
    n = state_counts(home)
    if n is None:
        return None
    line = (f"loose ends: {n['new']} new · {n['proposed']} proposed · "
            f"{n['waiting']} waiting · {n['declined']} declined")
    line += f" · {n['parked']} parked (retired: run ledger_migrate.py)" if n["parked"] else ""
    return line + (f" · {n['unreadable']} unreadable (fix the State)" if n["unreadable"] else "")


# ------------------------------------------------------------------ candidates (code only, no model)
_SENT_END = re.compile(r"[.!?][\"')\]]*\s+(?=[A-Z0-9\[*])")


def _severity_line(text: str, c) -> str:
    """The first sentence of the work-order's `## Severity` section ("" when absent)."""
    block = c.section_lines(text, "## Severity") or []
    body = " ".join(" ".join(ln.split()) for ln in block
                    if ln.strip() and not ln.strip().startswith(("#", ">", "<!--")))
    m = _SENT_END.search(body)
    return body[:m.start() + 1] if m else body


def _open_orders(home: Path) -> list:
    c = _canary()
    out = []
    by, _ = c._wo_files(home / "work-orders")
    for nnn, names in sorted(by.items()):
        path = home / "work-orders" / names[0]
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        title = next((" ".join(ln[2:].split()) for ln in text.splitlines() if ln.startswith("# ")), path.stem)
        scope = c.proposed_scope_lines(text) or []
        cut = re.search(r"(?m)^#{2,3}\s*Implementer notes", text)
        body = " ".join((text[:cut.start()] if cut else text[:ORDER_BODY_CHARS]).split())
        sev = _severity_line(text, c)
        notes = c.section_lines(text, c.NOTES_HEADING) or []
        has_notes = any(s and not c.NOTE_PLACEHOLDER_RE.match(s) and not s.startswith("<!--")
                        for s in (ln.strip() for ln in notes))
        lead = " ".join(scope) if any(x.strip() for x in scope) else body
        out.append({"nnn": nnn, "ref": f"WO-{nnn}", "file": names[0], "title": title, "body": body,
                    "text": " ".join((title + ". " + (sev + ". " if sev else "") + lead).split())[:1200],
                    "has_notes": has_notes})
    return out


def _worktree_nnns(home: Path) -> set:
    """NNNs that have a worktree directory, from `worktree.py status --json`. Empty when git cannot say."""
    root = home.parent
    tool = Path(__file__).resolve().with_name("worktree.py")
    try:
        r = subprocess.run([sys.executable, str(tool), "status", str(root), "--home", str(home), "--json"],
                           capture_output=True, text=True, timeout=60)
        inv = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        inv = None
    return {it["nnn"] for it in (inv or {}).get("items", []) if it.get("nnn") and it.get("path")}


def _signal_table(pool: list, sm) -> tuple:
    """({ref: (refs, paths, words)}, {reference or path: how many texts carry it})."""
    sig = {ref: sm._signals(t, ref) for ref, t in pool}
    count: dict = {}
    for refs, paths, _w in sig.values():
        for k in refs | paths:
            count[k] = count.get(k, 0) + 1
    return sig, count


def _shared(sig: dict, count: dict, a: str, b: str, sm) -> list:
    sa, sb = sig[a], sig[b]
    return sorted(k for k in (sa[0] | sa[1]) & (sb[0] | sb[1]) if count[k] <= sm.HUB_LIMIT)


def _tokens(text: str, sm) -> list:
    return [w for w in sm._WORD.findall(text.lower()) if w not in sm._STOP]


def _bm25(query: set, docs: list) -> list:
    """BM25 of the `query` words against each tokenised doc (k1 1.2, b 0.75; idf = ln(1 + (N - df + .5)/(df + .5)))
    -> [score]. A long document is normalised by its length, so length alone buys nothing."""
    n = len(docs)
    avg = sum(len(d) for d in docs) / n if n else 0.0
    df = {w: sum(1 for d in docs if w in d) for w in query}
    out = []
    for d in docs:
        tf: dict = {}
        for w in d:
            if w in query:
                tf[w] = tf.get(w, 0) + 1
        sc = 0.0
        for w, f in tf.items():
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            sc += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * len(d) / (avg or 1.0)))
        out.append(sc)
    return out


def join_candidates(home, items: list, sm=None, top: int = JOIN_TOP, cap: int = MAX_JOIN_PAIRS) -> dict:
    """The one reader of the open work-orders for any item text, on the list or not.
    `items` is [(ref, text)]. Each item is offered its `top` best orders: a shared reference or path
    ranks first, then BM25 of the item's words over the order (its title counted twice, read up to its
    Implementer notes; its Proposed fix scope need not exist), so a long order gains nothing from its length.
    No minimum: the helper's `loose-end-join` answer decides. At most `cap` pairs, taken best first across the items in turn, each pair once.
    Every open order is a candidate, dispatched or not: the drain only proposes, the orchestrator decides.
    An order is in progress ("dispatched") when a worktree exists for it or its Implementer notes have
    content; that is information on the order and on each pair, never a filter.
    -> {"join": [{item, wo, shared, score, dispatched, wo_title, wo_text, item_text}], "orders":
    [every open order, each with "dispatched": why | None}]}."""
    sm = sm or _system_one()
    home = Path(home)
    items = list(dict.fromkeys((ref, text) for ref, text in items))
    orders = _open_orders(home)
    wts = _worktree_nnns(home)
    for o in orders:
        o["dispatched"] = ("worktree" if o["nnn"] in wts else "notes started" if o["has_notes"] else None)
    live = orders
    pool = [(ref, text) for ref, text in items] + [(o["ref"], o["body"] or o["text"]) for o in live]
    sig, count = _signal_table(pool, sm)
    docs = [_tokens(o["title"], sm) + _tokens(o["body"] or o["text"], sm) for o in live]
    per_item = []
    for ref, text in items:
        words = sig[ref][2]
        scores = _bm25(words, docs)
        mine = []
        for o, sc, d in zip(live, scores, docs):
            shared = _shared(sig, count, ref, o["ref"], sm)
            cover = len(words & set(d)) / len(words) if words else 0.0
            if shared or cover >= JOIN_MIN_COVER:
                mine.append({"item": ref, "wo": o["ref"], "shared": shared, "score": round(sc, 3),
                             "dispatched": o["dispatched"], "wo_title": o["title"], "wo_text": o["text"],
                             "item_text": text})
        mine.sort(key=lambda x: (-len(x["shared"]), -x["score"], x["wo"]))
        chosen = mine[:top]
        per_item.append(chosen)
    pairs = []
    for rank in range(max((len(c) for c in per_item), default=0)):       # best of every item first
        for c in per_item:
            if rank < len(c) and len(pairs) < cap:
                pairs.append(c[rank])
    pairs.sort(key=lambda x: (-len(x["shared"]), -x["score"], x["item"], x["wo"]))
    return {"join": pairs, "orders": orders}


def candidates(home, sm=None) -> dict:
    """For each `new` item: its best open work-orders (`join_candidates`); and the pairs
    of `new` items that could be bundled, chosen by code with System One's signals: a shared reference or
    path (one shared by more than HUB_LIMIT texts is no signal) or word overlap (OVERLAP).
    -> {"items", "join", "bundle", "orders"}."""
    sm = sm or _system_one()
    home = Path(home)
    items = [r for r in rows_of(home) if r["state"].strip() == STATE_NEW and ID_RE.fullmatch(r["id"])]
    jc = join_candidates(home, [(r["id"], r["item"]) for r in items], sm)
    pool = [(r["id"], r["item"]) for r in items] + [(o["ref"], o["text"]) for o in jc["orders"]]
    sig, count = _signal_table(pool, sm)
    bundle = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            shared = _shared(sig, count, a["id"], b["id"], sm)
            wa, wb = sig[a["id"]][2], sig[b["id"]][2]
            jac = len(wa & wb) / len(wa | wb) if len(wa) >= 5 and len(wb) >= 5 else 0.0
            if shared or jac >= sm.OVERLAP:
                bundle.append({"a": a["id"], "b": b["id"], "shared": shared, "score": round(jac, 3),
                               "a_text": a["item"], "b_text": b["item"]})
    bundle.sort(key=lambda x: (-len(x["shared"]), -x["score"], x["a"], x["b"]))
    return {"items": [r["id"] for r in items], "join": jc["join"], "bundle": bundle[:sm.MAX_PAIRS],
            "orders": jc["orders"]}


# ------------------------------------------------------------------ fixed elsewhere (code only, no model)
FIX_MIN_SHARED = 3                # distinctive words an item and a fix must share
FIX_MIN_COVER = 0.5               # with no anchor: the share of the fix's own words the item holds, and at least 4
FIX_COMMITS = 2000                # commit subjects read at most
_FIX_TICKS = re.compile(r"`([^`\n]{4,60})`")
_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def _git(root: Path, *args) -> "str | None":
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _resolved_on(root: Path, path: Path) -> "str | None":
    """The date a resolved order file was last committed (the resolve commit), else its modified date."""
    out = _git(root, "log", "-1", "--format=%cs", "--", str(path))
    if out and re.fullmatch(r"\d{4}-\d\d-\d\d", out.strip()):
        return out.strip()
    try:
        return date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def _resolved_orders(home: Path) -> list:
    """[{nnn, ref, title, text, path}] for the files of `work-orders/resolved/`. `text` is what an item is
    matched against: the heading, the front matter's `title:` and `summary:`, never the whole order. The
    resolve date is read (git) only for an order that already matches: see `fixed_elsewhere`."""
    c = _canary()
    out = []
    d = home / "work-orders" / "resolved"
    for nnn, names in sorted(c._wo_files(d)[0].items()):
        path = d / names[0]
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = _FRONT.match(text)
        front = {}
        for ln in (m.group(1).splitlines() if m else []):
            k, _, v = ln.partition(":")
            front[k.strip().lower()] = v.strip()
        head = next((" ".join(ln[2:].split()) for ln in text.splitlines() if ln.startswith("# ")), "")
        out.append({"nnn": nnn, "ref": f"WO-{nnn}", "title": head or front.get("title", path.stem),
                    "text": " ".join(x for x in (head, front.get("title", ""), front.get("summary", "")) if x),
                    "path": path})
    return out


def _commit_subjects(home: Path, since: str) -> list:
    """[{sha, date, subject}] of the commits since `since` (YYYY-MM-DD), newest first; [] when git cannot say
    (no git, no repository, or `home` is not inside the repository's own top level)."""
    root = _repo_root(home)
    top = _git(root, "rev-parse", "--show-toplevel")
    try:
        if not top or Path(top.strip()).resolve() != root.resolve():
            return []
    except OSError:
        return []
    out = _git(root, "log", f"--since={since}", f"--max-count={FIX_COMMITS}", "--no-merges",
               "--format=%h%x09%cs%x09%s")
    rows = []
    for ln in (out or "").splitlines():
        parts = ln.split("\t", 2)
        if len(parts) == 3 and parts[1] >= since:
            rows.append({"sha": parts[0], "date": parts[1], "subject": " ".join(parts[2].split())})
    return rows


def _fix_score(item: str, target: str, sm) -> "tuple | None":
    """(shared words, anchored) when `target` reads as a fix of `item`, else None. Both sides are reduced to their
    distinctive words (System One's word list, no stop words). A match needs FIX_MIN_SHARED shared words and
    either an anchor (a backticked name, a path, or a word with an underscore, of the item, found in the target)
    or four shared words that make up half of the target's own words. Conservative on purpose: a miss costs the
    orchestrator the manual check made today; a false match costs a close proposal that is read and declined."""
    def words(t):
        return {w for w in sm._WORD.findall(t.lower()) if w not in sm._STOP}
    iw, tw = words(item), words(target)
    shared = iw & tw
    if len(shared) < FIX_MIN_SHARED or not tw:
        return None
    low = " ".join(target.lower().split())
    names = [" ".join(x.lower().split()) for x in _FIX_TICKS.findall(item)] + [x.lower() for x in sm._PATH.findall(item)]
    anchored = any(n and n in low for n in names) or any("_" in w for w in shared)
    if anchored or (len(shared) >= 4 and len(shared) / len(tw) >= FIX_MIN_COVER):
        return len(shared), anchored
    return None


def fixed_elsewhere(home, rows=None, sm=None) -> dict:
    """The new items that look already fixed, by code (no model). For each row ({id, added, source, item}; default
    the list's `new` rows) it looks at the orders resolved after the item (a higher WO number than the item's
    Source order, or resolved on or after its Added date; the Source order itself never) and at the commit
    subjects since its Added date, and keeps the best match (the most shared words; an order before a commit).
    -> {id: {"kind": "order" | "commit", "ref": "WO-NNN" | "<sha>", "title": ..., "date": ...}}. A match is
    only a lead: the drain turns it into a `close` proposal naming the fix, never into a close."""
    sm = sm or _system_one()
    home = Path(home)
    if rows is None:
        rows = [r for r in rows_of(home) if r["state"].strip() == STATE_NEW and ID_RE.fullmatch(r["id"])]
    if not rows:
        return {}
    orders = _resolved_orders(home)
    dated = [r["added"] for r in rows if re.fullmatch(r"\d{4}-\d\d-\d\d", r.get("added") or "")]
    commits = _commit_subjects(home, min(dated)) if dated else []
    out = {}
    resolved_on: dict = {}
    for r in rows:
        added = r.get("added") or ""
        src = re.fullmatch(r"WO-(\d{3,})", (r.get("source") or "").strip())
        best = None
        for o in orders:
            if src and int(o["nnn"]) == int(src.group(1)):
                continue
            sc = _fix_score(r["item"], o["text"], sm)
            if not sc or (best is not None and sc <= best[0]):
                continue
            later = bool(src) and int(o["nnn"]) > int(src.group(1))
            if o["nnn"] not in resolved_on:
                resolved_on[o["nnn"]] = _resolved_on(_repo_root(home), o["path"])
            if not later and not (added and resolved_on[o["nnn"]] and resolved_on[o["nnn"]] >= added):
                continue
            best = (sc, {"kind": "order", "ref": o["ref"], "title": o["title"],
                         "date": resolved_on.get(o["nnn"]) or ""})
        if best is None and re.fullmatch(r"\d{4}-\d\d-\d\d", added):
            for cm in commits:
                if cm["date"] < added:
                    continue
                sc = _fix_score(r["item"], cm["subject"], sm)
                if sc and (best is None or sc > best[0]):
                    best = (sc, {"kind": "commit", "ref": cm["sha"], "title": cm["subject"], "date": cm["date"]})
        if best:
            out[r["id"]] = best[1]
    return out


# ------------------------------------------------------------------ legacy registers (asked once per file)
LEGACY_RE = re.compile(r"<!--\s*legacy:\s*(.+?)\s+(imported|declined)\s*-->")
LEGACY_NAME_RE = re.compile(r"loose[-_ ]?ends?|register", re.IGNORECASE)


def _repo_root(home: Path) -> Path:
    home = Path(home)
    if home.name == "debug" and home.parent.name == "outputs":
        return home.parent.parent
    if home.name == "agents" and home.parent.name == "docs":
        return home.parent.parent
    return home.parent


def _relpath(home: Path, path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(_repo_root(home).resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def legacy_recorded(home) -> dict:
    """{repo-relative path: "imported" | "declined"} from the list header."""
    p = list_path(home)
    if not p.is_file():
        return {}
    return {m.group(1): m.group(2) for m in LEGACY_RE.finditer(p.read_bytes().decode("utf-8"))}


def _record_legacy(home, path, status: str) -> None:
    """One `<!-- legacy: <path> imported|declined -->` line in the header; creates the list file when the
    operator's answer has to live somewhere. A path already recorded is updated, never doubled."""
    rel = _relpath(home, path)
    text = _text_or_template(home)
    p = parse(text)
    if p["table"] is None:
        raise LooseEndsError(f"{NAME} has no table: fix it first")
    eol = _eol(text)
    line = f"<!-- legacy: {rel} {status} -->{eol}"
    lines = list(p["lines"])
    for i, ln in enumerate(lines[:p["table"]]):
        m = LEGACY_RE.search(ln)
        if m and m.group(1) == rel:
            lines[i] = line
            break
    else:
        lines.insert(p["table"], line)
    _write(home, "".join(lines))


def legacy_decline(home, path) -> None:
    _record_legacy(home, path, "declined")


def legacy_pending(home) -> list:
    """Repo-relative paths of `*.md` files in the home's top level and in work-orders/ whose file name or `# `
    title says loose ends or register, minus those already answered. Empty when none.

    Three limits, all deliberate. A work-order file (`WO-NNN-*.md`) in `work-orders/` is skipped: an order, open or
    resolved, is never a register, yet its title often mentions loose ends (only a plainly named list there is
    asked about). `work-orders/resolved/` is not scanned: a resolved order is history and never a
    register, yet its title often mentions loose ends. The rest of the home is not walked either: briefs, audit
    logs, archives and slice folders sit there and would match the name and title test far more often than a real
    register would; a register kept elsewhere is imported by naming it (`import FILE`)."""
    home = Path(home)
    done = legacy_recorded(home)
    out = []
    for d in (home, home / "work-orders"):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name == NAME or (d != home and _canary().wo_nnn(f.name)):
                continue                       # a work-order, open or resolved, is never a register
            try:
                head = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            title = next((ln[2:] for ln in head.splitlines() if ln.startswith("# ")), "")
            if LEGACY_NAME_RE.search(f.name) or LEGACY_NAME_RE.search(title):
                rel = _relpath(home, f)
                if rel not in done:
                    out.append(rel)
    return out


# ------------------------------------------------------------------ import of a legacy register
def import_register(home, path) -> dict:
    """Every table row of the register FILE as a `new` row with Source `import:<its first cell>`;
    FILE is only read; a row already imported (same source) is not added twice. Items over MAX_ITEM
    are shortened (the full text stays in FILE). -> {"added": [(id, old)], "skipped": [old],
    "probably_done": [old], "shortened": [old]}."""
    c = _canary()
    fp = Path(path)
    try:
        text = fp.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise LooseEndsError(f"cannot read register file {path}: {e}")
    # every table of the file; a header row (followed by a `|---|` row) and a row whose first cell is not
    # an item id (empty, `#`, `ID`) are skipped
    rows, cells_by_ref, lines = [], {}, text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.strip().startswith("|"):
            continue
        cs = [c.clean_cell(x) for x in ln.strip().strip("|").split("|")]
        if all(c.SEP_CELL.fullmatch(x) for x in cs):
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt.startswith("|") and all(c.SEP_CELL.fullmatch(x.strip()) for x in nxt.strip("|").split("|")):
            continue
        if not cs[0] or cs[0].lower() in ("#", "id", "no", "no."):
            continue
        rows.append({"ref": cs[0], "text": " | ".join(cs[1:]) if len(cs) > 1 else cs[0]})
        cells_by_ref.setdefault(cs[0], cs)
    existing = {r["source"] for r in rows_of(home)}
    res = {"added": [], "skipped": [], "probably_done": [], "shortened": []}
    new_rows, olds, seen = [], [], set()
    for it in rows:
        old = it["ref"]
        src = f"import:{old}"
        if src in existing or src in seen:
            res["skipped"].append(old)
            continue
        seen.add(src)
        body = " ".join(it["text"].split())
        if len(body) > MAX_ITEM:
            body = body[:MAX_ITEM - 3].rstrip() + "..."
            res["shortened"].append(old)
        if any(DONE_CELL_RE.match(c) for c in cells_by_ref.get(old, [])[1:]):
            res["probably_done"].append(old)
        second = cells_by_ref.get(old, [old, ""])[1] if len(cells_by_ref.get(old, [])) > 1 else ""
        try:
            added = date.fromisoformat(second).isoformat()
        except ValueError:
            added = ""
        new_rows.append((src, body, added))
        olds.append(old)
    if new_rows:
        text0 = _text_or_template(home)
        first = _next_id(parse(text0))
        _write(home, _append_rows(text0, new_rows))
        res["added"] = [(f"L{first + k}", o) for k, o in enumerate(olds)]
    _record_legacy(home, fp, "imported")
    return res


# ------------------------------------------------------------------ CLI
def _root(a) -> Path:
    return resolve_home(getattr(a, "root_pos", None) or a.root or ".")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(prog="loose_ends.py", description="The loose-ends list (<home>/loose-ends.md).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--root", default=None, help="the repo root or the home directory (default: here)")
        return sp
    s = cmd("add", "append a loose end (the last resort); prints its id")
    s.add_argument("--source", required=True)
    s.add_argument("--item", required=True)
    s.add_argument("--fix", default=None, help="the known small change (required)")
    s.add_argument("--why-not-now", default=None,
                   help="why it is out of the order's scope or crosses into a new scope, and why not an order (required)")
    s.add_argument("--state", default=None, help="new (default), waiting: Q or declined: R")
    s = cmd("state", "set an item's State: new, waiting: <question> or declined: <reason>")
    s.add_argument("id")
    s.add_argument("state")
    s = cmd("drop", "remove an item that was routed or closed")
    s.add_argument("id")
    s.add_argument("--to", required=True, help="WO-NNN | WO-NNN/SN | brain:<page> | closed:<reason>")
    s = cmd("list", "print the list")
    s.add_argument("--json", action="store_true")
    s = cmd("status", "one line: the rows by state")
    s.add_argument("--brief", action="store_true")
    s.add_argument("root_pos", nargs="?", default=None)
    s = cmd("candidates", "open work-orders each new item could join, and items that could be bundled")
    s.add_argument("--json", action="store_true")
    s = cmd("import", "add the rows of a legacy register file as new items (records the answer)")
    s.add_argument("file")
    s = cmd("legacy", "legacy registers: `pending` lists those not yet answered, `decline FILE` records a no")
    s.add_argument("action", choices=("pending", "decline"))
    s.add_argument("file", nargs="?", default=None)
    s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    home = _root(a)
    try:
        if a.cmd == "add":
            print(add(home, a.source, a.item, a.state, a.fix or "", a.why_not_now or ""))
        elif a.cmd == "state":
            print(set_state(home, a.id, a.state))
        elif a.cmd == "drop":
            print(drop(home, a.id, a.to) or "loose ends: empty (no list file), nothing to do")
        elif a.cmd == "list":
            rows = rows_of(home)
            if a.json:
                print(json.dumps([{**{k: v for k, v in r.items() if k not in ("line", "ncells")},
                                   "age_days": age_days(r["added"])}
                                  for r in rows], indent=2, ensure_ascii=False))
            else:
                print("\n".join(_fmt(r) for r in rows) if rows else "loose ends: empty")
        elif a.cmd == "status":
            line = brief(home)
            if line:
                print(line)
            _sibling("_gitos_waiting_le", "waiting.py").show(home, a.brief)     # the one "waiting on you" view
        elif a.cmd == "candidates":
            d = candidates(home)
            if a.json:
                print(json.dumps({k: v for k, v in d.items() if k != "orders"}, indent=2, ensure_ascii=False))
            else:
                for j in d["join"]:
                    why = ("shared " + ", ".join(j["shared"])) if j["shared"] else f"word overlap {j['score']}"
                    print(f"join    {j['item']} -> {j['wo']} ({why})"
                          + (f" [in progress: {j['dispatched']}]" if j["dispatched"] else ""))
                for b in d["bundle"]:
                    why = ("shared " + ", ".join(b["shared"])) if b["shared"] else f"word overlap {b['score']}"
                    print(f"bundle  {b['a']} + {b['b']} ({why})")
                if not (d["join"] or d["bundle"]):
                    print("no candidates")
        elif a.cmd == "legacy":
            if a.action == "decline":
                if not a.file:
                    raise LooseEndsError("legacy decline needs the FILE the operator declined")
                legacy_decline(home, a.file)
                print(f"recorded: {_relpath(home, a.file)} declined")
            else:
                found = legacy_pending(home)
                if a.json:
                    print(json.dumps(found))
                elif found:
                    print("\n".join(found))
        elif a.cmd == "import":
            r = import_register(home, a.file)
            for lid, old in r["added"]:
                print(f"{lid} <- {old}")
            print(f"imported {len(r['added'])}, already imported {len(r['skipped'])}")
            if r["probably_done"]:
                print("probably done (imported; the drain decides): " + ", ".join(r["probably_done"]))
            if r["shortened"]:
                print("shortened to 300 characters (the full text stays in the file): "
                      + ", ".join(r["shortened"]))
    except LooseEndsError as e:
        print(f"loose_ends: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
