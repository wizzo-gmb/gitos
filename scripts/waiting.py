#!/usr/bin/env python3
"""waiting.py - the one "waiting on you" view (WO-115). Standard library only, read-only, no network.

`loose_ends.py status` calls `show()`; `waiting.py [ROOT]` runs it alone. It lists everything that waits on
the operator, one line each, from the stores that already hold it:

    ask      a drain proposal of kind `ask` in <home>/drain/pending/ (and a loose-ends row `proposed: ask`)
    row      a loose-ends row whose state starts `waiting:` (needs the operator)
    intake   proposals other repos filed into <home>/intake/ (a count; `federation.py intake` lists them)
    parked   a parked work-order (`status: parked`; or a hand-kept INDEX Parked row) whose `trigger:` may have
             fired: a work-order it names is resolved, or a date it names has passed. A trigger in words is the orchestrator's to judge.
    board    the owner board's cards on disk (<home>/board/data, WO-122): each card that needs the owner (an
             answer voided by a later edit counts), each answered card not yet acted on, and the answers and notes
             the agent has not read yet. Read by running the home's board.py `summary` in a separate process
             (`python -I`, a timeout): a crash, a hang or forged output stays out of this view. It is not a sandbox;
             that board.py runs with the user's rights.

A view, never a store: nothing is written and nothing is remembered. A source that is missing is skipped; one that
cannot be read is reported as itself ("not read (reason)") and the others still print. Nothing waiting prints nothing.

    waiting.py [ROOT] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from datetime import date
from importlib import util as importlib_util
from pathlib import Path

HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")
MAX_TEXT = 110                      # characters of a question or trigger shown on a line
WO_REF = re.compile(r"WO-0*(\d{1,})", re.IGNORECASE)
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
CLOSED_ROW = re.compile(r"->\s*(?:WO-\d|dropped|closed)", re.IGNORECASE)


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


def resolve_home(root) -> Path:
    root = Path(root)
    for rel in HOMES:
        if (root / rel).is_dir():
            return root / rel
    return root


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 3].rstrip() + "..."


def _source(name: str, items=None, status: str = "ok", note: str = "") -> dict:
    return {"source": name, "status": status, "note": note, "items": items or []}


# ------------------------------------------------------------------ the sources
def pile_asks(home: Path) -> list:
    """[{ref, text, items}] for each pending drain proposal of kind `ask` (the question when it carries one)."""
    d = home / "drain" / "pending"
    out = []
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        kind = re.search(r"(?m)^- kind: (\S+)\s*$", text)
        if not kind or kind.group(1) != "ask":
            continue
        pid = re.search(r"(?m)^- id: (\S+)\s*$", text)
        items = re.search(r"(?m)^- items: (.*)$", text)
        q = re.search(r"(?ms)^## Question for the operator\s*\n\s*- (.+?)\s*$", text)
        out.append({"ref": pid.group(1) if pid else f.stem,
                    "text": _short(q.group(1)) if q else "an ask: read the proposal",
                    "items": [x.strip() for x in items.group(1).split(",") if x.strip()] if items else []})
    return out


def list_rows(home: Path) -> list:
    """The loose-ends rows ([] when there is no list file)."""
    return _sibling("_gitos_loose_ends_w", "loose_ends.py").rows_of(home)


def _state_is(row: dict, word: str) -> bool:
    return str(row.get("state", "")).strip().lower().startswith(word)


def src_asks(home: Path, rows: list) -> dict:
    asks = pile_asks(home)
    seen = {i for a in asks for i in a["items"]}
    items = [{"ref": a["ref"], "text": a["text"]} for a in asks]
    for r in rows:                                   # a row `proposed: ask` whose pile file is not (or no longer) there
        if _state_is(r, "proposed:") and re.match(r"proposed:\s*ask\b", r["state"].strip(), re.IGNORECASE) \
                and r["id"] not in seen:
            items.append({"ref": r["id"], "text": _short(r["item"])})
    return _source("ask", items)


def src_rows(rows: list) -> dict:
    items = []
    for r in rows:
        if _state_is(r, "waiting:"):
            q = re.sub(r"^waiting:\s*(?:user\s*[-—:]\s*)?", "", r["state"].strip(), flags=re.IGNORECASE)
            items.append({"ref": r["id"], "text": _short(q or r["item"])})
    return _source("row", items)


def src_intake(home: Path) -> dict:
    d = home / "intake"
    if not d.is_dir():
        return _source("intake", status="absent")
    n = len(list(d.glob("*.md")))
    items = [{"ref": "intake", "text": f"{n} proposal(s) filed by other repos; `federation.py intake` lists them "
                                       f"(metadata only)"}] if n else []
    return _source("intake", items)


def _resolved_orders(home: Path) -> set:
    r = home / "work-orders" / "resolved"
    out = set()
    for p in r.iterdir() if r.is_dir() else []:
        m = re.match(r"WO-0*(\d+)", p.name, re.IGNORECASE)
        if m:
            out.add(m.group(1))
    return out


def trigger_check(trigger: str, resolved: set, now: "date | None" = None) -> "str | None":
    """Why a restart trigger may have fired, or None. A resolved work-order it names, or a date it names that has
    passed. A trigger in words ("the operator asks") is not decidable here and gives None."""
    now = now or date.today()
    named = [m.group(1) for m in WO_REF.finditer(trigger)]
    done = [n for n in named if n in resolved]
    if done:
        return "WO-" + done[0].zfill(3) + " is resolved"
    for m in ISO_DATE.finditer(trigger):
        try:
            if date.fromisoformat(m.group(1)) <= now:
                return f"{m.group(1)} has passed"
        except ValueError:
            continue
    return None


def _parked_index(home: Path) -> list:
    """[(id, trigger)] of the open rows of INDEX's `## Parked` table."""
    p = home / "INDEX.md"
    if not p.is_file():
        return []
    c = _sibling("_gitos_canary_w", "canary.py")
    out = []
    for row in c.parked_table_rows(p.read_text(encoding="utf-8")):
        if len(row) > 2 and c.clean_cell(row[0]) and not any(CLOSED_ROW.search(cell) for cell in row):
            out.append((c.clean_cell(row[0]), c.clean_cell(row[2])))
    return out


def src_parked(home: Path, now: "date | None" = None) -> dict:
    resolved = _resolved_orders(home)
    cand = _parked_index(home) + [(f"WO-{nnn}", meta.get("trigger", ""))
                                  for nnn, meta in _sibling("_gitos_canary_w", "canary.py").parked_orders(home)]
    items = []
    for ref, trig in cand:
        why = trigger_check(trig, resolved, now)
        if why:
            items.append({"ref": ref, "text": f"trigger may have fired ({why}): {_short(trig)}"})
    return _source("parked", items)


BOARD_TIMEOUT = 20                   # seconds the board's own `summary` may take


def _clean(text) -> str:
    """One printable line from another program's text: control and format characters dropped, whitespace collapsed."""
    s = "".join(ch if unicodedata.category(ch) not in ("Cc", "Cf") else " " for ch in str(text))
    return _short(s)


def src_board(home: Path) -> dict:
    """The owner board, read by the home's own board.py (`summary`, JSON) in a separate `python -I` process with a
    timeout, so its crash, hang or forged output cannot break this view (not a sandbox: it runs with the user's
    rights). No <home>/board/board.py: absent. A summary that fails, times out or is not JSON is said as `not read`."""
    board_py = home / "board" / "board.py"
    if not board_py.is_file():
        return _source("board", status="absent")
    cp = subprocess.run([sys.executable, "-I", "-B", str(board_py), "summary"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=BOARD_TIMEOUT, cwd=str(board_py.parent),
                        stdin=subprocess.DEVNULL)
    if cp.returncode != 0:
        raise RuntimeError(f"board.py summary exited {cp.returncode}: {(cp.stderr or cp.stdout).strip()[-200:]}")
    c = json.loads(cp.stdout)
    items = []
    for card in c["needs"]:
        changed = " (the card changed after the answer; asked again)" if card.get("voided") else ""
        items.append({"ref": _clean(card["id"]), "text": _clean(str(card["title"]) + changed)})
    for card in c["acted"]:
        items.append({"ref": _clean(card["id"]), "text": _clean("answered, not acted on: " + str(card["title"]))})
    if c["new_answers"]:
        items.append({"ref": "answers", "text": f"{int(c['new_answers'])} new answer(s) not read yet: "
                                                f"`board.py list --open`"})
    if c["new_notes"]:
        items.append({"ref": "notes", "text": f"{int(c['new_notes'])} new note(s) not read yet: `board.py notes`"})
    if c["problems"]:
        items.append({"ref": "problems", "text": _clean(f"{len(c['problems'])} problem(s) in the board's files: "
                                                        + "; ".join(map(str, c["problems"])))})
    return _source("board", items)


def collect(home, rows=None, now: "date | None" = None) -> list:
    """Every source, each as {source, status, note, items}. A source that raises is reported as `not read`; the
    rest are unaffected. `rows` = the loose-ends rows when the caller already has them."""
    home = Path(home)
    out = []
    state = {"rows": rows}

    def need_rows():
        if state["rows"] is None:
            state["rows"] = list_rows(home)
        return state["rows"]

    for name, fn in (("ask", lambda: src_asks(home, need_rows())),
                     ("row", lambda: src_rows(need_rows())),
                     ("intake", lambda: src_intake(home)),
                     ("parked", lambda: src_parked(home, now)),
                     ("board", lambda: src_board(home))):
        try:
            out.append(fn())
        except Exception as e:                       # a source that cannot be read is said, never skipped silently
            out.append(_source(name, status="not read", note=f"{type(e).__name__}: {_short(e)}"))
    return out


def render(sources: list) -> list:
    n = sum(len(s["items"]) for s in sources)
    bad = [s for s in sources if s["status"] == "not read"]
    if not n and not bad:
        return []
    head = f"waiting on you: {n}" + (f" ({len(bad)} source(s) not read)" if bad else "")
    lines = [head]
    for s in sources:
        for it in s["items"]:
            lines.append(f"  {s['source']:<7} {it['ref']}  {it['text']}")
        if s["status"] == "not read":
            lines.append(f"  {s['source']:<7} not read ({s['note']})")
    return lines


def show(home, brief: bool = False) -> None:
    """What `loose_ends.py status` prints after its one line. `--brief` stays one line, so it prints nothing here."""
    if brief:
        return
    for ln in render(collect(home)):
        print(ln)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(prog="waiting.py", description="Everything that waits on the operator.")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    home = resolve_home(a.root)
    src = collect(home)
    if a.json:
        print(json.dumps(src, indent=2, ensure_ascii=False))
    else:
        for ln in render(src):
            print(ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
