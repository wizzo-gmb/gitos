#!/usr/bin/env python3
"""loose_ends.py - the loose-ends list every repo has (WO-093). Standard library only.

`<home>/loose-ends.md` is a tracked table of small things that came up while other work was going
on: written down in the turn they come up, drained at the seams. It is never a work queue or a
notebook: an item is one or two sentences (at most MAX_ITEM characters); anything that needs
evidence, a cause, a fix or its own worker is a work order, and a session plan belongs in the
resume file. Work is never dispatched from the list (an item is first dropped `--to WO-NNN`).

    | ID | Added | Source | Item | State |

`ID` is `L<n>`, never reused (the next id lives in `<!-- next: L<n> -->` under the table).
`Source` is `WO-NNN`, `P<n>`, `chat`, `proposal:<id>` or `import:<old id>`. `State` is `new` or
`declined: <reason>` (a suggestion the orchestrator declined without routing it; the drain never suggests
it again and the orchestrator decides it by hand with `drop`). An item that is routed or closed is
REMOVED; git keeps the history.

The list is the inbox: only items not yet suggested. When the drain suggests an item it writes the pile file
(`<home>/drain/pending/<id>.md`) and removes the item from the list in the same run; from then on the pile is
its one home, until `accept`, `decline` or `withdraw` (`system_one.py drain ...`). An ask for the operator is a
pile state too: the orchestrator raises it from the pile.

    loose_ends.py add        [--root R] --source S --item TEXT
    loose_ends.py drop       [--root R] L<n> --to WO-NNN | P<n> | brain:<page> | closed:<reason>
    loose_ends.py list       [--root R] [--json]
    loose_ends.py status     [--brief] [ROOT]     (inbox, pile, and the boxes carried in open orders)
    loose_ends.py candidates [--root R] [--json]     (code only, no model)
    loose_ends.py import     [--root R] FILE
    loose_ends.py legacy     pending | decline FILE [--root R] [--json]

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
PICK_OPTIONS = 26                 # open orders offered to the title pick (the best by BM25)
PICK_TOP = 2                      # orders the pick adds to an item's candidates
JOIN_MIN_COVER = 0.0              # share of the item's words an order must hold when nothing is shared; none
DECLINED_RE = re.compile(r"declined:\s*(\S.*)")
DEST_RE = re.compile(r"(?:WO-(\d{3,})|P(\d+)|brain:(\S.*)|closed:(\S.*))")
DONE_CELL_RE = re.compile(r"^[\s*_`~>\-]*(?:done|fixed|closed|merged|superseded|resolved)\b", re.IGNORECASE)
UNESC_PIPE = re.compile(r"(?<!\\)\|")
TOO_LONG = ("this is a work order or a RESUME entry, not a loose end: author one, or shorten it "
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
    else changes. `new_rows` are (source, item[, added date]) tuples with the item already cleaned."""
    p = parse(text)
    if p["table"] is None:
        raise LooseEndsError(f"{NAME} has no `| ID | Added | Source | Item | State |` table: fix it first")
    lines, eol, nid = list(p["lines"]), _eol(text), _next_id(p)
    add = []
    for row in new_rows:
        src, item = row[0], row[1]
        added = row[2] if len(row) > 2 and row[2] else today().isoformat()
        add.append(f"| L{nid} | {added} | {src} | {_esc(item)} | {STATE_NEW} |{eol}")
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
def add(home, source: str, item: str) -> str:
    src, it = _source(source), _item(item)
    text = _text_or_template(home)
    p = parse(text)
    new_id = f"L{_next_id(p)}"
    _write(home, _append_rows(text, [(src, it)]))
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


def _parked_exists(home: Path, pid: str) -> bool:
    try:
        idx = (Path(home) / "INDEX.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    block = _canary().section_lines(idx, "## Parked") or []
    return any(re.match(rf"^\s*\|\s*{re.escape(pid)}\s*\|", ln) for ln in block)


def check_dest(home, dest: str) -> str:
    """The destination `drop` and a routed decline accept, normalised; a LooseEndsError when it is not one."""
    d = " ".join(str(dest).split())
    m = DEST_RE.fullmatch(d)
    if not m:
        raise LooseEndsError(f"--to {d!r} is not WO-NNN, P<n>, brain:<page> or closed:<reason>")
    wo, par, brain, closed = m.groups()
    if wo and not _wo_open(home, wo):
        raise LooseEndsError(f"WO-{wo} is not an open work order in {Path(home) / 'work-orders'}: "
                             "author it first, then drop the item to it")
    if par and not _parked_exists(home, f"P{par}"):
        raise LooseEndsError(f"P{par} is not a row of the INDEX Parked list: park it first")
    if closed and len(closed.split()) < 3:
        raise LooseEndsError("closed: needs a reason of at least a few words (what makes it done or moot)")
    if brain and not brain.strip():
        raise LooseEndsError("brain: needs a page name")
    return d


def drop(home, lid: str, dest: str) -> "str | None":
    d = check_dest(home, dest)
    if not list_path(home).is_file():
        return None                                    # no file is an empty list: nothing to drop
    p = parse(_text_or_template(home))
    r = _find(p, lid)
    lines = list(p["lines"])
    del lines[r["line"]]
    _write(home, "".join(lines))
    return f"{r['id']} -> {d}"


def remove_rows(home, ids) -> list:
    """Remove the rows with these ids in one atomic write (no destination: the items live on in the pile).
    -> the ids removed. No file, or none of them on the list, writes nothing."""
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


def restore_rows(home, rows: list, state: str = STATE_NEW) -> list:
    """Put rows back on the list with their own id, Added date, Source and text; State `state`. `rows` are
    (id, added, source, item); an empty Added is today, an id already on the list is left as it is.
    -> the ids put back. Ids are never reused, so the next-id comment only ever moves up."""
    text = _text_or_template(home)
    p = parse(text)
    if p["table"] is None:
        raise LooseEndsError(f"{NAME} has no `| ID | Added | Source | Item | State |` table: fix it first")
    have = {r["id"] for r in p["rows"]}
    todo = [r for r in rows if r[0] not in have]
    if not todo:
        return []
    lines, eol = list(p["lines"]), _eol(text)
    add = [f"| {lid} | {added or today().isoformat()} | {src} | {_esc(item)} | {_esc(state)} |{eol}"
           for lid, added, src, item in todo]
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


def pile_counts(home) -> tuple:
    """(suggestions pending in the pile, those that wait for the operator = pending `ask`)."""
    d = Path(home) / "drain" / "pending"
    n = k = 0
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = re.search(r"(?m)^- kind: (\S+)\s*$", text)
        if m:
            n += 1
            k += m.group(1) == "ask"
    return n, k


def _fmt(r: dict, now=None) -> str:
    age = age_days(r["added"], now)
    when = f"{age}d" if age is not None else "?d"
    state = "new" if r["state"] == STATE_NEW else r["state"]
    return f"{r['id']}  {when:>4}  [{r['source']}]  {r['item']}  ({state})"


def rows_of(home) -> list:
    p = load(home)
    return [] if p is None else p["rows"]


def carried_open(home) -> int:
    """Open boxes (`- [ ] L<n> (slice: ..) ..`) in the open work orders."""
    c = _canary()
    d = Path(home) / "work-orders"
    n = 0
    for names in c._wo_files(d)[0].values():
        if "/" in names[0]:
            continue          # a folder order carries no boxes
        try:
            n += len(c.open_boxes((d / names[0]).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return n


def brief(home, now=None) -> "str | None":
    """One line, or None when there is no list file, no pile and no carried box."""
    p = load(home)
    n, k = pile_counts(home)
    carried = carried_open(home)
    if p is None and not n and not carried:
        return None
    return f"loose ends: inbox {len(p['rows']) if p else 0} · pile {n} ({k} for you) · carried {carried} open"


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
        scope = c.section_lines(text, "## Proposed fix scope") or []
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


def join_candidates(home, items: list, sm=None, top: int = JOIN_TOP, cap: int = MAX_JOIN_PAIRS,
                    pick=None) -> dict:
    """The one reader of the open work orders for any item text, on the list or not.
    `items` is [(ref, text)]. Each item is offered its `top` best orders: a shared reference or path
    ranks first, then BM25 of the item's words over the order (its title counted twice, read up to its
    Implementer notes; its Proposed fix scope need not exist), so a long order gains nothing from its length.
    `pick(item_ref, item_text, [(order ref, title)]) -> [(order ref, probability)]` (best first), when given,
    is a model's title pick for what words cannot find: it sees the best PICK_OPTIONS orders by BM25 and its
    top PICK_TOP orders are added to the candidates (unique). No minimum: the model's `loose-end-join`
    question decides. At most `cap` pairs, taken best first across the items in turn, each pair once.
    Every open order is a candidate, dispatched or not: the drain only proposes, the orchestrator decides.
    An order is in progress ("dispatched") when a worktree exists for it or its Implementer notes have
    content; that is information on the order and on each pair, never a filter.
    -> {"join": [{item, wo, shared, score, picked, dispatched, wo_title, wo_text, item_text}], "orders":
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
                mine.append({"item": ref, "wo": o["ref"], "shared": shared, "score": round(sc, 3), "picked": None,
                             "dispatched": o["dispatched"], "wo_title": o["title"], "wo_text": o["text"],
                             "item_text": text})
        mine.sort(key=lambda x: (-len(x["shared"]), -x["score"], x["wo"]))
        chosen = mine[:top]
        if pick is not None and mine:
            offered = mine[:PICK_OPTIONS]
            got = pick(ref, text, [(x["wo"], x["wo_title"]) for x in offered])
            have = {x["wo"] for x in chosen}
            by_wo = {x["wo"]: x for x in offered}
            for wo, prob in got[:PICK_TOP]:
                if wo in by_wo and wo not in have:
                    chosen.append({**by_wo[wo], "picked": round(prob, 3)})
                    have.add(wo)
        per_item.append(chosen)
    pairs = []
    for rank in range(max((len(c) for c in per_item), default=0)):       # best of every item first
        for c in per_item:
            if rank < len(c) and len(pairs) < cap:
                pairs.append(c[rank])
    pairs.sort(key=lambda x: (-len(x["shared"]), -x["score"], x["item"], x["wo"]))
    return {"join": pairs, "orders": orders}


def candidates(home, sm=None, pick=None) -> dict:
    """For each `new` item: its best open work orders (`join_candidates`); and the pairs
    of `new` items that could be bundled, chosen by code with System One's signals: a shared reference or
    path (one shared by more than HUB_LIMIT texts is no signal) or word overlap (OVERLAP).
    -> {"items", "join", "bundle", "orders"}."""
    sm = sm or _system_one()
    home = Path(home)
    items = [r for r in rows_of(home) if r["state"].strip() == STATE_NEW and ID_RE.fullmatch(r["id"])]
    jc = join_candidates(home, [(r["id"], r["item"]) for r in items], sm, pick=pick)
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
    """Repo-relative paths of files under the home (top level, work-orders/, work-orders/resolved/) whose
    file name or `# ` title says loose ends or register, minus those already answered. Empty when none."""
    home = Path(home)
    done = legacy_recorded(home)
    out = []
    for d in (home, home / "work-orders", home / "work-orders" / "resolved"):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name == NAME:
                continue
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
        sp.add_argument("--root", default=None, help="the repo root or the gitos home (default: here)")
        return sp
    s = cmd("add", "append a new item; prints its id")
    s.add_argument("--source", required=True)
    s.add_argument("--item", required=True)
    s = cmd("drop", "remove an item that was routed or closed")
    s.add_argument("id")
    s.add_argument("--to", required=True, help="WO-NNN | P<n> | brain:<page> | closed:<reason>")
    s = cmd("list", "print the list")
    s.add_argument("--json", action="store_true")
    s = cmd("status", "one line: the inbox, the pile, and what waits for you")
    s.add_argument("--brief", action="store_true")
    s.add_argument("root_pos", nargs="?", default=None)
    s = cmd("candidates", "open work orders each new item could join, and items that could be bundled")
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
            print(add(home, a.source, a.item))
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
