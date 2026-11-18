#!/usr/bin/env python3
"""board.py - the owner board of one gitos home. Standard library only.

A small web page on 127.0.0.1 where the owner answers what the agent asks: every owner approval is a card here.
It lives at <home>/board/: this file and board.json (port, board_id) are tracked; data/ is git-ignored.

Agent side. No command here records an answer: only the board page does, through POST /api/answer.
  ensure                       start this home's board when it is not answering, then print one line:
                               board: http://127.0.0.1:<port>/ · N open · A new answers · M new notes
  serve                        run the board in the foreground (`ensure` starts this detached)
  url                          print the board's address
  add-decision TITLE BODY value=Label... [--details FILE] [--tech FILE] [--tab T] [--replaces ID] [CARD]
  add-plan PLAN_FILE TITLE [--table ROWS.json] [--tech FILE] [--item NAME] [CARD]
  add-send DRAFT_FILE TITLE --to ADDR [--cc ADDR] [--subject TEXT] [--tech FILE] [--item NAME] [CARD]
                               CARD: [--ref WO-NNN] [--where TEXT] [--group close|decision|action|parked];
                               `value=Label*` marks the recommended option
  list [--open]                the cards with their latest answer (locks each answer it shows, so it is no longer new)
  answer-for ID                the card's latest answer as JSON with `valid` and `locked` (exit 1 when none);
                               locks the answer
  close ID OUTCOME             move a card to Closed with what happened
  notes                        the owner's notes (marks them read)
  summary                      open, unread and not-acted-on counts as JSON (read-only; the waiting view runs it)

add-plan and add-send store a copy of the file at data/plans/<sha256>.<ext> or data/drafts/<sha256>.<ext>, bind the
card to the full SHA-256 of those exact bytes and print the stored path: dry-run and apply THAT file. A newer card for
the same item (--item, default the file's name) closes the older open one as "replaced by <id>".

Tools load this file BY PATH (importlib.util.spec_from_file_location), never through sys.path, and call:
  approved(kind, key, value, go=None)   the newest card of `kind` whose field `key` equals `value`, when it is not
                                        closed and its latest answer chose the go option (plan: apply, send: send)
                                        against the card's current content and is locked; otherwise None
  consume(card_id, outcome)             close the card BEFORE acting on it, so it never approves twice
  claim(kind, key, value, go, outcome)  approved() and consume() in one step under the board's lock: the card, or
                                        None. Two tools claiming the same approval: exactly one gets it. Use this.
  verify_bytes(card, data)              True only when `data` has exactly the SHA-256 the card bound

The owner answers by pressing an option (saved at once, with the note) or with Save note alone (a note-only answer:
answered, never a go), and may change it until the agent reads it. Reading an answer (`list`, `answer-for`,
`approved()`) LOCKS it: one line in data/read.jsonl, after which the page refuses a new answer to that card. Counting
(`ensure`, the waiting view) never locks.

Every write goes through one cross-process lock (data/.lock): an append, a lock, a close, and the page's check-then-
append of an answer, so an answer and a read, or two closes, never interleave.

Data (data/): cards/<id>.json written by the agent; answers.jsonl and notes.jsonl appended only by the board page;
read.jsonl (the locks) by the reads above; closed.jsonl by close and consume; plans/ and drafts/ the bound bytes;
read-mark.json, server.json and serve.log are bookkeeping. A card's hash is recomputed from its content on every read, so a card edited after its answer voids that
answer and goes back under Needs you. Files and lines that fail validation are listed on the board, never skipped
silently.

Tabs come from "tabs": [...] in board.json; the default is `decisions` alone, which is always present.

The honest limit: on a single-user machine the agent runs as the owner, so it could forge a browser request or write
these files itself. The board guards against accidents and against other local pages and programs, not against a
deliberately hostile agent.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BOARD_VERSION = 2
HOST = "127.0.0.1"
PORT_LO, PORT_HI = 8800, 8999
BASE_TABS = ("decisions",)
GROUPS = ("close", "decision", "action", "parked")
KINDS = ("decision", "plan", "send")
GO = {"plan": "apply", "send": "send"}
MAX_BODY = 64 * 1024
MAX_NOTE = 4000
ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}-[0-9a-f]{4}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VALUE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
TAB_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")

_LOCK = threading.RLock()
_HELD = threading.local()
LOCK_WAIT = 10.0


class BoardError(Exception):
    """A refused request from the agent side: the CLI prints it and exits 2."""


def set_dir(board_dir) -> None:
    """Point this module at one board directory (default: the one this file sits in)."""
    global HERE, DATA, CARDS, CONFIG
    HERE = Path(board_dir).resolve()
    DATA = HERE / "data"
    CARDS = DATA / "cards"
    CONFIG = HERE / "board.json"


set_dir(Path(__file__).resolve().parent)


def _os_lock(fd: int, deadline: float) -> None:
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.time() > deadline:
                raise BoardError("the board's files are busy (data/.lock held); try again")
            time.sleep(0.02)


def _os_unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(wait: float = LOCK_WAIT):
    """The board's one cross-process lock (data/.lock): msvcrt on Windows, flock on POSIX. Re-entrant in a thread, so
    a locked step may call another (claim -> approved -> lock -> append)."""
    with _LOCK:
        if getattr(_HELD, "depth", 0):
            _HELD.depth += 1
            try:
                yield
            finally:
                _HELD.depth -= 1
            return
        DATA.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(DATA / ".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            _os_lock(fd, time.time() + wait)
            _HELD.depth = 1
            try:
                yield
            finally:
                _HELD.depth = 0
                _os_unlock(fd)
        finally:
            os.close(fd)


def hidden(ch: str) -> bool:
    """A character the owner cannot see: any format character (Cf: bidi marks, zero-width, tag characters) and any
    control character (Cc) but tab, newline and carriage return. clean() and the card warning share this test."""
    cat = unicodedata.category(ch)
    return cat == "Cf" or (cat == "Cc" and ch not in "\t\n\r")


def clean(text) -> str:
    """One printable line: hidden characters (ESC, bidi, zero-width) and line breaks removed, whitespace collapsed."""
    s = "".join(" " if hidden(ch) or unicodedata.category(ch) == "Cc" else ch for ch in str(text))
    return " ".join(s.split())


def home_dir() -> Path:
    return HERE.parent


def now_dt() -> datetime:
    return datetime.now()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds")


# ------------------------------------------------------------------ config
def derive_port(home) -> int:
    """The port this home starts from: SHA-256 of its resolved path, folded into 8800-8999."""
    h = hashlib.sha256(str(Path(home).resolve()).encode("utf-8")).hexdigest()
    return PORT_LO + int(h, 16) % (PORT_HI - PORT_LO + 1)


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # a port in TIME_WAIT is free to a server
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def make_config(board_dir) -> dict:
    """Write <board_dir>/board.json once: the derived port, walked to the first free one, and a random board_id.
    An existing board.json is returned as it is and never rewritten."""
    board_dir = Path(board_dir)
    path = board_dir / "board.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    start = derive_port(board_dir.parent)
    span = PORT_HI - PORT_LO + 1
    for i in range(span):
        port = PORT_LO + (start - PORT_LO + i) % span
        if port_free(port):
            break
    else:
        raise BoardError(f"no free port in {PORT_LO}-{PORT_HI}")
    cfg = {"port": port, "board_id": secrets.token_hex(16)}
    board_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(cfg, indent=2) + "\n").encode("utf-8"))
    return cfg


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardError(f"{CONFIG} is missing or unreadable ({type(e).__name__}); scaffold or upgrade builds it")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("port"), int) or not 1024 <= cfg["port"] <= 65535 \
            or not isinstance(cfg.get("board_id"), str) or not cfg["board_id"]:
        raise BoardError(f"{CONFIG} needs an integer `port` (1024-65535) and a `board_id`")
    return cfg


def tabs(cfg: "dict | None" = None) -> tuple:
    try:
        cfg = cfg if cfg is not None else load_config()
    except BoardError:
        return BASE_TABS
    extra = cfg.get("tabs") if isinstance(cfg.get("tabs"), list) else []
    out = list(BASE_TABS)
    for t in extra:
        if isinstance(t, str) and TAB_RE.fullmatch(t) and t not in out:
            out.append(t)
    return tuple(out)


def url(cfg: "dict | None" = None) -> str:
    cfg = cfg or load_config()
    return f"http://{HOST}:{cfg['port']}/"


# ------------------------------------------------------------------ files
def valid_answer(e: dict) -> bool:
    """An answer line: an option value, or `option: null` with a non-empty note (a note-only answer)."""
    note = e.get("note", "")
    if not isinstance(note, str):
        return False
    return isinstance(e.get("option"), str) or (e.get("option") is None and "option" in e and bool(note.strip()))


def read_answers(problems: list) -> list:
    out = []
    for n, e in enumerate(read_jsonl("answers.jsonl", ("card", "card_hash"), problems), 1):
        if valid_answer(e):
            out.append(e)
        else:
            problems.append(f"answers.jsonl entry {n} has neither an option nor a note")
    return out


def read_jsonl(name: str, need: tuple, problems: list) -> list:
    """Entries of data/<name> that are objects with string fields `need` and a valid `at`. Each bad line is added to
    `problems` (per call: a threaded server never shares one list between requests)."""
    p = DATA / name
    if not p.is_file():
        return []
    out = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                e = None
            if not isinstance(e, dict) or any(not isinstance(e.get(k), str) for k in need + ("at",)) \
                    or not ISO_RE.fullmatch(e["at"]) or ("card" in e and not ID_RE.fullmatch(str(e["card"]))) \
                    or ("card_hash" in e and not SHA_RE.fullmatch(str(e["card_hash"]))):
                problems.append(f"{name} line {n} is malformed")
                continue
            out.append(e)
    return out


def append_jsonl(name: str, entry: dict) -> None:
    """One append of one ASCII line under data/, under the board's lock. A file whose last line was torn (no final
    newline) gets one first, so the new line never merges into it."""
    data = (json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
    with file_lock():
        path = DATA / name
        if path.is_file() and path.stat().st_size:
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    data = b"\n" + data
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes((json.dumps(obj, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    os.replace(tmp, path)


def content_hash(card: dict) -> str:
    """Full SHA-256 of the card's content (everything but card_hash itself)."""
    body = {k: v for k, v in card.items() if k != "card_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
                          .encode("ascii")).hexdigest()


def card_problem(c, fn: str, tab_set: tuple) -> "str | None":
    """Why card file `fn` is not a valid card, or None."""
    if not isinstance(c, dict):
        return "not a JSON object"
    if not isinstance(c.get("id"), str) or not ID_RE.fullmatch(c["id"]) or fn != c["id"] + ".json":
        return "its id is malformed or is not its file name"
    if c.get("tab") not in tab_set:
        return f"tab {c.get('tab')!r} is not one of {list(tab_set)}"
    if c.get("kind") not in KINDS:
        return f"kind {c.get('kind')!r} is not one of {list(KINDS)}"
    for k in ("title", "body"):
        if not isinstance(c.get(k), str) or not c[k].strip():
            return f"`{k}` is missing"
    for k in ("details", "tech", "item", "to", "cc", "subject", "file", "ref", "where", "warning"):
        if k in c and not isinstance(c[k], str):
            return f"`{k}` is not text"
    if not isinstance(c.get("created"), str) or not ISO_RE.fullmatch(c["created"]):
        return "`created` is not an ISO time with microseconds"
    try:
        datetime.fromisoformat(c["created"])
    except ValueError:
        return "`created` is not a real time"
    opts = c.get("options")
    if not isinstance(opts, list) or not opts or not all(
            isinstance(o, dict) and isinstance(o.get("value"), str) and VALUE_RE.fullmatch(o["value"])
            and isinstance(o.get("label"), str) and o["label"].strip() for o in opts):
        return "`options` must be a non-empty list of {value, label}"
    if len({o["value"] for o in opts}) != len(opts):
        return "two options share a value"
    if any("rec" in o and not isinstance(o["rec"], bool) for o in opts):
        return "an option's `rec` is not true or false"
    if "group" in c and c["group"] not in GROUPS:
        return f"group {c.get('group')!r} is not one of {list(GROUPS)}"
    if c["kind"] in GO and (not isinstance(c.get("sha256"), str) or not SHA_RE.fullmatch(c["sha256"])):
        return "a plan or send card needs the full `sha256` of its file"
    if "table" in c and not (isinstance(c["table"], list) and all(
            isinstance(r, list) and len(r) == 3 and all(isinstance(x, (str, int)) for x in r) for r in c["table"])):
        return "`table` must be rows of [label, count, what goes there]"
    return None


def load_cards(problems: list, tab_set: "tuple | None" = None) -> list:
    """Valid cards, oldest first by their microsecond `created`, each with card_hash recomputed from its content."""
    tab_set = tab_set or tabs()
    cards, seen = [], set()
    if CARDS.is_dir():
        for p in sorted(CARDS.iterdir()):
            if not p.name.endswith(".json"):
                continue
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError, UnicodeDecodeError):
                problems.append(f"card file {p.name} is not readable JSON; ignored")
                continue
            why = card_problem(c, p.name, tab_set)
            if why is None and c["id"] in seen:
                why = "a duplicate id"
            if why:
                problems.append(f"card file {p.name}: {why}; ignored")
                continue
            seen.add(c["id"])
            c["card_hash"] = content_hash(c)
            cards.append(c)
    return sorted(cards, key=lambda c: (c["created"], c["id"]))


def copy_text(cards: list) -> str:
    """What Copy my answers puts on the clipboard: one `id -> option | note` line per open card with a valid answer.
    Never a title, never a closed card, never an answer the card no longer matches."""
    lines = []
    for c in cards:
        a = c.get("answer")
        if c.get("status") == "closed" or not a:
            continue
        note = " / ".join(x.strip() for x in str(a.get("note") or "").splitlines() if x.strip())
        lines.append(f"{c['id']} -> {a['option'] if a['option'] is not None else '(note only)'}"
                     + (f" | {note}" if note else ""))
    return "\n".join(lines)


def state() -> dict:
    """Everything the board shows. Status: closed, answered (a valid latest answer) or needs (no answer, or an answer
    given to an earlier version of the card: `voided`)."""
    problems: list = []
    tab_set = tabs()
    cards = load_cards(problems, tab_set)
    ids = {c["id"] for c in cards}
    answers, closed, locks = {}, {}, {}
    for a in read_answers(problems):
        answers[a["card"]] = a
    for c in read_jsonl("closed.jsonl", ("card", "outcome"), problems):
        closed.setdefault(c["card"], c)
    for r in read_jsonl("read.jsonl", ("card", "card_hash", "read_at"), problems):
        locks.setdefault((r["card"], r["at"], r["card_hash"]), r["read_at"])
    out = []
    for c in cards:
        c = dict(c)
        a = answers.get(c["id"])
        c["closed"] = closed.get(c["id"])
        c["answer"] = a if a and hmac.compare_digest(a["card_hash"], c["card_hash"]) else None
        c["voided"] = a if a and c["answer"] is None else None
        c["locked"] = locks.get((c["id"], a["at"], a["card_hash"])) if c["answer"] else None
        c["status"] = "closed" if c["closed"] else ("answered" if c["answer"] else "needs")
        out.append(c)
    for cid in sorted(set(answers) - ids):
        problems.append(f"answers.jsonl names card {cid}, which has no valid card file")
    notes = read_jsonl("notes.jsonl", ("note",), problems)
    try:
        port = load_config()["port"]
    except BoardError:
        port = ""
    return {"cards": out, "notes": notes[-20:], "tabs": list(tab_set), "problems": problems,
            "copy": copy_text(out), "name": home_dir().parent.name, "where": f"{home_dir().name}/{HERE.name}",
            "port": port, "now": iso(now_dt())}


def read_mark() -> dict:
    """How many notes the agent has read (`notes`). Answers need no mark: reading one locks it."""
    try:
        m = json.loads((DATA / "read-mark.json").read_text(encoding="utf-8"))
        return {"notes": int(m.get("notes", 0))}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"notes": 0}


def counts() -> dict:
    """Open cards, and answers and notes the agent has not read yet. Read-only. A new answer is the current answer of a
    card that is not closed and that no read has locked: `answer-for`, `list` or a close each clear it."""
    problems: list = []
    s = state()
    n_notes = len(read_jsonl("notes.jsonl", ("note",), problems))
    mark = read_mark()
    return {"open": sum(1 for c in s["cards"] if c["status"] != "closed"),
            "needs": [c for c in s["cards"] if c["status"] == "needs"],
            "acted": [c for c in s["cards"] if c["status"] == "answered"],
            "new_answers": sum(1 for c in s["cards"] if c["status"] == "answered" and not c["locked"]),
            "new_notes": max(0, n_notes - mark["notes"]),
            "problems": s["problems"]}


def summary() -> dict:
    """counts() as plain JSON-ready data, every title cleaned: what the waiting view reads (in a subprocess)."""
    c = counts()
    return {"open": c["open"], "new_answers": c["new_answers"], "new_notes": c["new_notes"],
            "needs": [{"id": x["id"], "title": clean(x["title"]), "voided": bool(x["voided"])} for x in c["needs"]],
            "acted": [{"id": x["id"], "title": clean(x["title"]), "locked": bool(x["locked"])} for x in c["acted"]],
            "problems": [clean(p) for p in c["problems"]]}


def set_mark() -> None:
    """Mark every note read (`notes`)."""
    write_json(DATA / "read-mark.json", {"notes": len(read_jsonl("notes.jsonl", ("note",), []))})


# ------------------------------------------------------------------ agent side
def new_card(tab: str, kind: str, title: str, body: str, options: list, details: str = "",
             extra: "dict | None" = None, tech: str = "") -> dict:
    """Write one card. Its `created` is a microsecond time strictly after every existing card's, so the newest card
    for an item is always the last one written."""
    tab_set = tabs()
    if tab not in tab_set:
        raise BoardError(f"tab must be one of {list(tab_set)}")
    if not options:
        raise BoardError("a card needs at least one option")
    problems: list = []
    newest = max((datetime.fromisoformat(c["created"]) for c in load_cards(problems, tab_set)), default=None)
    dt = now_dt()
    if newest is not None and dt <= newest:
        dt = newest + timedelta(microseconds=1)
    cid = dt.strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(2)
    card = {"id": cid, "tab": tab, "kind": kind, "title": title, "body": body, "details": details,
            "options": options, "created": iso(dt)}
    if tech:
        card["tech"] = tech
    card.update(extra or {})
    why = card_problem(card, cid + ".json", tab_set)
    if why:
        raise BoardError(f"card refused: {why}")
    card["card_hash"] = content_hash(card)
    write_json(CARDS / (cid + ".json"), card)
    return card


def parse_options(args: list) -> list:
    opts = []
    for a in args:
        if "=" not in a:
            raise BoardError(f"option {a!r} must be value=Label")
        v, label = a.split("=", 1)
        rec = label.endswith("*")
        label = label[:-1] if rec else label
        if not VALUE_RE.fullmatch(v) or not label.strip():
            raise BoardError(f"option {a!r}: the value is 1-32 of a-z 0-9 _ - and the label is not empty")
        opts.append(dict({"value": v, "label": label}, **({"rec": True} if rec else {})))
    return opts


def store_bytes(sub: str, src: str) -> tuple:
    """Copy file `src` to data/<sub>/<sha256>.<ext>. -> (sha256, stored path, the bytes). The bytes must be UTF-8 text,
    so what the card shows is what is bound."""
    data = Path(src).read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise BoardError(f"{src} is not UTF-8 text; the card could not show exactly the bytes it binds")
    sha = hashlib.sha256(data).hexdigest()
    ext = Path(src).suffix.lstrip(".")
    ext = ext if re.fullmatch(r"[A-Za-z0-9]{1,10}", ext) else "bin"
    dest = DATA / sub / f"{sha}.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or dest.read_bytes() != data:
        dest.write_bytes(data)
    return sha, dest, data


def invisible_warning(text: str) -> dict:
    """{"warning": ...} when the text holds bidi or zero-width characters the owner cannot see, else {}."""
    return {"warning": "this file contains invisible characters (bidi or zero-width)"} if any(map(hidden, text)) else {}


def card_by_id(cid: str, s: "dict | None" = None) -> "dict | None":
    s = s or state()
    return next((c for c in s["cards"] if c["id"] == cid), None)


def consume(cid: str, outcome: str) -> None:
    """Close a card with what happened. A used approval is closed at once, so it never approves a second time."""
    if not isinstance(cid, str) or not ID_RE.fullmatch(cid) or not (CARDS / (cid + ".json")).is_file():
        raise BoardError(f"no card {cid}")
    if not isinstance(outcome, str) or not outcome.strip():
        raise BoardError("close needs an outcome line")
    with file_lock():
        c = card_by_id(cid)
        if c is not None and c["status"] == "closed":
            raise BoardError(f"card {cid} is already closed")
        append_jsonl("closed.jsonl", {"card": cid, "outcome": clean(outcome)[:500], "at": iso(now_dt())})


def replace_older(card: dict) -> list:
    """Close the older open cards of the same kind for the same item as `card`: "replaced by <id>"."""
    done = []
    for c in state()["cards"]:
        if c["id"] != card["id"] and c["kind"] == card["kind"] and c.get("item") == card.get("item") \
                and card.get("item") and c["status"] != "closed" and c["created"] < card["created"]:
            consume(c["id"], f"replaced by {card['id']}")
            done.append(c["id"])
    return done


def lock(card: dict) -> "str | None":
    """The agent has read this card's answer: append one line to data/read.jsonl (card, the answer's `at`, its
    card_hash), after which the page refuses a new answer to the card. A voided or missing answer is not locked.
    -> the lock time, or None."""
    a = card.get("answer")
    if not a:
        return None
    with file_lock():
        cur = card_by_id(card["id"])
        ca = cur and cur["answer"]
        if not ca or ca["at"] != a["at"] or ca["card_hash"] != a["card_hash"]:
            return None                                    # a newer answer arrived: it is pending, not this one
        if cur["locked"]:
            return cur["locked"]
        at = max(iso(now_dt()), a["at"])              # a clock stepped back never makes a read older than the answer
        append_jsonl("read.jsonl", {"card": card["id"], "at": a["at"], "card_hash": a["card_hash"], "read_at": at})
        return at


def answer_for(cid: str) -> "dict | None":
    """`answer-for`: read (and so lock) a card's answer, then report the answer as it is NOW, never a superseded one.
    `valid` is true only when that answer is locked and its hash matches the card. -> the answer dict, or None."""
    c = card_by_id(cid)
    if not c or not (c["answer"] or c["voided"]):
        return None
    if c["answer"] and c["status"] != "closed":
        lock(c)                                    # None when a newer answer arrived: that one is pending
    c = card_by_id(cid) or c
    a = c["answer"] or c["voided"]
    valid = bool(c["answer"] and c["locked"] and c["status"] != "closed"
                 and hmac.compare_digest(a["card_hash"], c["card_hash"]))
    return dict(a, note=clean(a.get("note", "")), valid=valid, status=c["status"], locked=c["locked"])


def _newest(cards: list, kind: str, key: str, value) -> "dict | None":
    return next((c for c in reversed(cards) if c["kind"] == kind and c.get(key) == value), None)


def approved(kind: str, key: str, value, go: "str | None" = None) -> "dict | None":
    """The newest card of `kind` whose `key` field equals `value`, when it is not closed and its latest answer chose
    the go option against the card's current content AND that answer is locked. Otherwise None. Reading locks the
    answer it sees, then the card is read again: an answer that arrived in between is pending, and a pending answer
    never authorizes. A note-only answer is never a go; a newer card for the same item always blocks an older one."""
    go = go or GO.get(kind)
    if not go:
        raise BoardError(f"approved() needs go= for kind {kind!r}")
    c = _newest(state()["cards"], kind, key, value)
    if c is None or c["status"] != "answered":
        return None
    lock(c)
    c = _newest(state()["cards"], kind, key, value)
    if c is None or c["status"] != "answered" or not c["locked"]:
        return None
    a = c["answer"]
    if a["at"] > c["locked"]:
        return None                                        # a lock older than the answer it names is not a read of it
    if a["option"] == go and hmac.compare_digest(a["card_hash"], c["card_hash"]):
        return c
    return None


def claim(kind: str, key: str, value, go: "str | None", outcome: str) -> "dict | None":
    """approved() and consume() as one step under the board's lock: the approved card, now closed with `outcome`, or
    None. Of two tools claiming the same approval, exactly one gets it. Act only after claim() returns the card."""
    with file_lock():
        c = approved(kind, key, value, go)
        if c is None:
            return None
        consume(c["id"], outcome)
        return c


def verify_bytes(card: dict, data: bytes) -> bool:
    """True only when `data` hashes to exactly the full SHA-256 the card bound."""
    want = card.get("sha256") if isinstance(card, dict) else None
    if not isinstance(want, str) or not SHA_RE.fullmatch(want) or not isinstance(data, (bytes, bytearray)):
        return False
    return hmac.compare_digest(hashlib.sha256(bytes(data)).hexdigest(), want)


def read_table(path: str) -> list:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    if not isinstance(rows, list):
        raise BoardError("--table is a JSON list of rows")
    for r in rows:
        if isinstance(r, dict):
            r = [r.get("label"), r.get("count"), r.get("what", "")]
        if not (isinstance(r, list) and len(r) == 3 and isinstance(r[0], str) and isinstance(r[1], (int, str))
                and isinstance(r[2], str)):
            raise BoardError("each --table row is {label, count, what} or [label, count, what]")
        out.append(r)
    return out


def text_of(path: str) -> str:
    return Path(path).read_bytes().decode("utf-8", errors="replace")


# ------------------------------------------------------------------ the page
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>
:root{--bg:#f4f6f6;--panel:#ffffff;--line:#dbe2e1;--edge:#7d8a87;--text:#16201f;--muted:#53605d;--accent:#c2410c;--onaccent:#ffffff;--tint:#fdeee6;--warn:#8a5a00;--warnbg:#fdf5e1;--code:#f4f6f6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#101514;--panel:#161c1b;--line:#2a3432;--edge:#5f6d6a;--text:#e3ebe9;--muted:#9aa8a5;--accent:#fdba74;--onaccent:#2a1408;--tint:#3a2418;--warn:#e3b24f;--warnbg:#2a2312;--code:#0c1110}}
:root[data-theme="dark"]{--bg:#101514;--panel:#161c1b;--line:#2a3432;--edge:#5f6d6a;--text:#e3ebe9;--muted:#9aa8a5;--accent:#fdba74;--onaccent:#2a1408;--tint:#3a2418;--warn:#e3b24f;--warnbg:#2a2312;--code:#0c1110}
*{box-sizing:border-box}button:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:900px;margin:0 auto;padding:24px 16px 110px}
.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}
h1{font-size:21px;margin:0}.sub{color:var(--muted);margin:2px 0 0;font-size:14px}
.repo{font:12px ui-monospace,monospace;color:var(--muted)}
.seg{display:flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;flex-wrap:wrap}
.seg button,.pills button{background:none;border:0;color:var(--muted);padding:8px 16px;font:inherit;cursor:pointer}
.seg button.on{background:var(--panel);color:var(--text);font-weight:600}
.n{display:inline-block;min-width:22px;padding:0 6px;margin-left:6px;border-radius:10px;background:var(--bg);border:1px solid var(--line);color:var(--text);font:12px ui-monospace,monospace;text-align:center}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 0}.chips button{border:1px solid var(--line);background:none;color:var(--muted);border-radius:14px;padding:3px 12px;font:inherit;font-size:13px;cursor:pointer}.chips button.on{background:var(--text);color:var(--bg);border-color:var(--text)}
.bar{display:flex;justify-content:space-between;align-items:center;margin:20px 0 12px;border-bottom:1px solid var(--line);padding-bottom:10px;flex-wrap:wrap;gap:8px}
.pills{display:flex;gap:6px;flex-wrap:wrap}.pills button{border:1px solid var(--line);border-radius:6px;padding:4px 11px}
.pills button.on{color:var(--text);border-color:var(--muted)}
.stamp{color:var(--muted);font:12px ui-monospace,monospace}
.problems{border:1px solid var(--warn);background:var(--warnbg);color:var(--warn);border-radius:6px;padding:10px 14px;margin:10px 0;font-size:14px}
.empty{border:1px dashed var(--line);border-radius:6px;padding:18px;color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 16px 16px 20px;margin:16px 0;box-shadow:0 1px 2px rgb(0 0 0/.04)}
.card.void{border-color:var(--warn);box-shadow:inset 3px 0 0 var(--warn)}
.head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.tag{font:11px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:1px 6px;color:var(--muted)}
.ref{font:12px ui-monospace,monospace;color:var(--muted);font-weight:600}
.card h2{font-size:16px;margin:0}.card p{margin:8px 0}
.where{font:12px ui-monospace,monospace;color:var(--muted);margin:4px 0}.reply{border-left:2px solid var(--line);padding:2px 0 2px 10px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:10px;overflow:auto;max-height:300px;white-space:pre-wrap;word-break:break-word;font:13px/1.45 ui-monospace,Consolas,monospace;margin:8px 0}
details summary{color:var(--muted);font-size:13px;cursor:pointer}
.opts{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 8px}
.opt{background:none;color:var(--text);border:1px solid var(--edge);border-radius:6px;padding:4px 12px;font:inherit;font-size:14px;line-height:20px;cursor:pointer}
.opt:hover{border-color:var(--accent)}.opt.sel{background:var(--accent);border-color:var(--accent);color:var(--onaccent);font-weight:600}
.opt:disabled{cursor:default;opacity:.55}.opt.sel:disabled{opacity:1}
.opt.recd{border-color:var(--accent)}.rec{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;background:var(--tint);color:var(--accent);border-radius:4px;padding:0 6px;margin-left:8px;vertical-align:1px}.opt.sel .rec{background:var(--onaccent);color:var(--accent)}
textarea{width:100%;min-height:70px;height:70px;resize:none;overflow-y:hidden;font:inherit;font-size:14px;background:var(--code);color:var(--text);border:1px solid var(--edge);border-radius:6px;padding:7px 8px}
.row{display:flex;gap:8px;align-items:center}.row textarea{flex:1}
.btn{background:none;border:1px solid var(--edge);border-radius:6px;padding:4px 10px;font:inherit;font-size:13px;line-height:20px;cursor:pointer;white-space:nowrap;color:var(--muted)}.btn:hover{color:var(--text)}
.ans,.lock,.closed{color:var(--muted);font-size:14px;margin:6px 0 0}.voidmsg{color:var(--warn);font-size:14px;margin:6px 0 0}
.fp{font:12px ui-monospace,monospace;color:var(--muted)}
.foot{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line)}
.foot div{max-width:900px;margin:0 auto;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.mono{font:13px ui-monospace,monospace;font-weight:700}.msg{color:var(--muted);font-size:13px}
</style></head><body><main>
<div class="top"><div><h1>Owner board</h1>
<p class="sub">Things Claude needs you to decide. Press a button to answer; it saves at once. To change it, open Answered and press another.<br>An answer locks when Claude reads it.</p>
<p class="repo" id="repo"></p></div>
<div class="seg" id="tabs"></div></div>
<div class="chips" id="chips"></div>
<div class="bar"><div class="pills" id="pills"></div><span class="stamp" id="stamp"></span></div>
<div id="list"></div>
<div class="card"><div class="head"><span class="tag">note</span><h2>Anything else for Claude</h2></div>
<p>A new instruction, a correction, or something the cards missed.</p>
<div class="row"><textarea id="freenote" placeholder="Write it here"></textarea><button class="btn" id="savenote">Save note</button></div>
<p class="msg" id="notemsg"></p></div>
</main><div class="foot"><div><span><span class="mono" id="count"></span> <span class="msg" id="footmsg">Claude reads answers from disk; pasting is optional.</span></span>
<button class="btn" id="copy">Copy my answers</button></div></div>
<script>
const TOKEN = "__TOKEN__";
const GROUPS = [["close","Close or keep open"],["decision","Decisions"],["action","Your actions"],["parked","Parked work"]];
let S = {cards:[], tabs:["decisions"], problems:[], copy:"", name:"", where:"", port:""};
let tab = location.hash.slice(1) || "decisions", sub = "needs", grp = "all";
const $ = id => document.getElementById(id);
const ID = /^\d{8}-\d{6}-\d{6}-[0-9a-f]{4}$/;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const label = t => t.charAt(0).toUpperCase() + t.slice(1);
const when = s => { const d = new Date(s); return isNaN(d) ? String(s ?? "") : d.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"}); };
const groupOf = c => GROUPS.some(([g]) => g === c.group) ? c.group : "decision";
const optLabel = (c, v) => { const o = c.options.find(o => o.value === v); return o ? o.label : v; };
const said = (c, a) => a.option === null ? "with a note" : optLabel(c, a.option);
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json","X-Board-Token":TOKEN}, body:JSON.stringify(body)});
  if(!r.ok){ let m = r.status + ""; try{ m = (await r.json()).error || m; }catch(e){} const err = new Error(m); err.status = r.status; throw err; }
  return r.json();
}
async function load(force){
  let next;
  try{ const r = await fetch("/api/state"); next = await r.json(); }
  catch(e){ $("stamp").textContent = "Board not reachable"; return; }
  // a note being typed keeps the cards it is about: S changes only together with what is rendered
  if(!force && document.activeElement && document.activeElement.tagName === "TEXTAREA") return;
  const typed = {};                                  // notes typed but not sent survive a re-render
  for(const c of S.cards){ const el = document.getElementById("n-" + c.id); if(el && el.value) typed[c.id] = el.value; }
  S = next;
  if(!S.tabs.includes(tab)) tab = S.tabs[0];
  $("repo").textContent = `${S.name} · ${S.where} · 127.0.0.1:${S.port}`;
  render();
  for(const id in typed){ const el = document.getElementById("n-" + id); if(el){ el.value = typed[id]; grow(el); } }
  $("stamp").textContent = "Up to date " + new Date().toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});
}
function render(){
  const inTab = S.cards.filter(c => c.tab === tab), cnt = s => inTab.filter(c => c.status === s).length;
  const open = t => S.cards.filter(c => c.tab === t && c.status === "needs").length;
  $("tabs").innerHTML = S.tabs.map(t => `<button class="${t===tab?"on":""}" data-t="${esc(t)}">${esc(label(t))}<span class="n">${open(t)}</span></button>`).join("");
  $("pills").innerHTML = [["needs","Needs you"],["answered","Answered"],["closed","Closed"]].map(([k,l]) => `<button class="${k===sub?"on":""}" data-s="${k}">${l} <span class="n">${cnt(k)}</span></button>`).join("");
  const view = inTab.filter(c => c.status === sub), gcount = g => view.filter(c => groupOf(c) === g).length;
  const live = GROUPS.filter(([g]) => gcount(g) > 0);
  if(grp !== "all" && !live.some(([g]) => g === grp)) grp = "all";
  $("chips").innerHTML = live.length < 2 ? "" : [["all","All"], ...live].map(([g,l]) => `<button class="${g===grp?"on":""}" data-c="${g}">${esc(l)} <span class="n">${g==="all" ? view.length : gcount(g)}</span></button>`).join("");
  const shown = view.filter(c => grp === "all" || groupOf(c) === grp).reverse();
  if(sub === "needs") shown.sort((a, b) => (b.voided ? 1 : 0) - (a.voided ? 1 : 0));
  const warn = S.problems.length ? `<div class="problems">Problems in the board's files (tell Claude): ${S.problems.map(esc).join("; ")}</div>` : "";
  $("list").innerHTML = warn + (shown.length ? shown.map(card).join("") :
    `<div class="empty">${sub==="needs" ? "Nothing is waiting here. Claude adds a card when something needs you." : "Nothing here yet."}</div>`);
  const notClosed = S.cards.filter(c => c.status !== "closed");
  $("count").textContent = `${notClosed.filter(c => c.answer).length} answered · ${notClosed.filter(c => c.locked).length} locked`;
  document.querySelectorAll("textarea").forEach(grow);
}
function grow(el){ el.style.height = "auto"; el.style.height = Math.max(70, el.scrollHeight + 2) + "px"; }   // a note box fits its text: never a scrollbar
function table(rows){
  return `<table><tr><th>What</th><th class="num">Count</th><th>What goes there</th></tr>${rows.map(r => `<tr><td>${esc(r[0])}</td><td class="num">${esc(r[1])}</td><td>${esc(r[2])}</td></tr>`).join("")}</table>`;
}
function card(c){
  if(!ID.test(c.id)) return "";
  const a = c.answer, closed = c.status === "closed", locked = !!c.locked, dis = closed || locked ? "disabled" : "";
  const h = esc(c.card_hash);
  const opts = c.options.map(o => `<button class="opt${a && a.option === o.value ? " sel" : ""}${o.rec ? " recd" : ""}" data-id="${c.id}" data-v="${esc(o.value)}" data-h="${h}" ${dis}>${esc(o.label)}${o.rec ? ' <span class="rec">★ recommended</span>' : ""}</button>`).join("");
  let status = "";
  if(closed){
    status = (a ? `<p class="ans">You answered ${esc(said(c, a))} at ${esc(when(a.at))}</p>` : "")
      + `<p class="reply">Claude: ${esc(c.closed.outcome)}</p><p class="closed">Closed ${esc(when(c.closed.at))}</p>`;
  } else if(c.voided){
    status = `<p class="voidmsg">⚠ This card changed after your answer, so your answer no longer counts. Read it again and answer.</p>`;
  } else if(a && locked){
    status = `<p class="ans">Answered ${esc(said(c, a))} at ${esc(when(a.at))}</p><p class="lock">🔒 Locked: Claude read this at ${esc(when(c.locked))}. To change it, write in "Anything else for Claude".</p>`;
  } else if(a){
    status = `<p class="ans">Answered ${esc(said(c, a))} at ${esc(when(a.at))} · not read yet, you can still change it</p>`;
  }
  const note = dis ? "" : `<div class="row"><textarea id="n-${c.id}" placeholder="Note — press a choice to send it with that, or Save note to answer with the note alone">${esc(a ? a.note : "")}</textarea><button class="btn" data-note="${c.id}" data-h="${h}">Save note</button></div>`;
  return `<div class="card${c.voided && !closed ? " void" : ""}"><div class="head"><span class="tag">${esc(c.kind)}</span>${c.ref ? `<span class="ref">${esc(c.ref)}</span>` : ""}<h2>${esc(c.title)}</h2></div>
  <p class="why">${esc(c.body)}</p>${c.where ? `<p class="where">where: ${esc(c.where)}</p>` : ""}
  ${c.table && c.table.length ? table(c.table) : ""}${c.details ? `<pre>${esc(c.details)}</pre>` : ""}
  ${c.tech ? `<details><summary>Technical details</summary><pre>${esc(c.tech)}</pre></details>` : ""}
  ${c.warning ? `<p class="voidmsg">⚠ ${esc(c.warning)}</p>` : ""}
  ${c.sha256 ? `<p class="fp">${c.kind === "send" ? "Draft" : "Plan"} ${esc(c.sha256.slice(0,12))}… (full SHA-256 bound)</p>` : ""}
  <div class="opts">${opts}</div>${note}${status}</div>`;
}
async function answer(id, option, h){
  const box = $("n-" + id);
  try{ await post("/api/answer", {card:id, option:option, note:box ? box.value : "", card_hash:h}); $("footmsg").textContent = "Saved. Claude will read it."; load(true); }
  catch(err){ $("footmsg").textContent = "Not saved: " + err.message; if(err.status === 409) load(true); }
}
document.addEventListener("click", async e => {
  const t = e.target.closest("button"); if(!t || t.disabled) return;
  if(t.dataset.t){ tab = t.dataset.t; location.hash = tab; sub = "needs"; grp = "all"; render(); }
  else if(t.dataset.s){ sub = t.dataset.s; render(); }
  else if(t.dataset.c){ grp = t.dataset.c; render(); }
  else if(t.dataset.id && t.dataset.v !== undefined){ if(ID.test(t.dataset.id)) answer(t.dataset.id, t.dataset.v, t.dataset.h); }
  else if(t.dataset.note){
    const id = t.dataset.note; if(!ID.test(id)) return;
    if(!$("n-" + id).value.trim()){ $("footmsg").textContent = "Write a note first, or press a choice."; return; }
    answer(id, null, t.dataset.h);
  }
  else if(t.id === "savenote"){
    const v = $("freenote").value.trim(); if(!v) return;
    try{ await post("/api/note", {note:v}); $("freenote").value = ""; $("notemsg").textContent = "Saved for Claude."; }
    catch(err){ $("notemsg").textContent = "Not saved: " + err.message; }
  }
  else if(t.id === "copy"){
    try{ await navigator.clipboard.writeText(S.copy || "No answers yet."); $("footmsg").textContent = "Copied. Claude also reads your answers directly."; }
    catch(err){ $("footmsg").textContent = "Copy failed."; }
  }
});
document.addEventListener("input", e => { if(e.target.tagName === "TEXTAREA") grow(e.target); });
window.addEventListener("hashchange", () => { tab = location.hash.slice(1) || S.tabs[0]; render(); });
load(); setInterval(load, 15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    token = ""
    port = 0
    board_id = ""
    timeout = 10
    server_version = "gitos-board"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        return self.headers.get("Host") in (f"{HOST}:{self.port}", f"localhost:{self.port}")

    def _send(self, code: int, body, ctype: str = "application/json; charset=utf-8", nonce: str = "none"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, code: int, msg: str):
        return self._send(code, json.dumps({"error": msg}))

    def do_GET(self):
        if not self._host_ok():
            return self._err(421, "wrong host")
        path = self.path.split("?", 1)[0]
        if path == "/":
            nonce = secrets.token_urlsafe(16)
            title = html.escape("Owner board · " + home_dir().parent.name)
            page = PAGE.replace("__TITLE__", title).replace("__TOKEN__", self.token) \
                       .replace("<script>", f'<script nonce="{nonce}">')
            return self._send(200, page, "text/html; charset=utf-8", nonce=nonce)
        if path == "/api/state":
            return self._send(200, json.dumps(state(), ensure_ascii=False))
        if path == "/api/identity":
            return self._send(200, json.dumps({"board_id": self.board_id, "home": str(home_dir())}))
        return self._err(404, "not found")

    def do_POST(self):
        # Read a modest body before any refusal: a reply sent while the client is still writing makes Windows reset
        # the connection, and the client would see an abort instead of the refusal.
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        raw = b""
        if 0 < n <= 4 * MAX_BODY:
            try:
                raw = self.rfile.read(n)
            except OSError:
                return None
        else:
            self.close_connection = True
        if not self._host_ok():
            return self._err(421, "wrong host")
        if self.headers.get("Origin") not in (f"http://{HOST}:{self.port}", f"http://localhost:{self.port}"):
            return self._err(403, "cross-origin request refused")
        # a browser sends these on a same-origin fetch(); a script sends them only by forging them
        if self.headers.get("Sec-Fetch-Site") != "same-origin" or self.headers.get("Sec-Fetch-Mode") != "cors":
            return self._err(403, "answers are accepted only from the board page in a browser")
        if not hmac.compare_digest(self.headers.get("X-Board-Token", "").encode("utf-8", "surrogateescape"),
                                   self.token.encode("utf-8")):
            return self._err(403, "missing or stale page token; reload the board")
        if n <= 0 or n > MAX_BODY or len(raw) != n:
            return self._err(413, "body size")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._err(400, "bad json")
        if not isinstance(body, dict):
            return self._err(400, "the body must be a JSON object")
        client = {"ua": str(self.headers.get("User-Agent", ""))[:200],
                  "sec_fetch": "/".join(str(self.headers.get(h)) for h in
                                        ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest"))}
        path = self.path.split("?", 1)[0]
        if path == "/api/answer":
            try:
                with file_lock():                          # re-check and append as one step against lock() and close
                    return self._answer(body, client)
            except BoardError as e:
                return self._err(503, str(e))
        if path == "/api/note":
            note = body.get("note")
            if not isinstance(note, str) or not note.strip():
                return self._err(400, "empty note")
            try:
                append_jsonl("notes.jsonl", dict({"note": note.strip()[:MAX_NOTE], "at": iso(now_dt()), "via": "board"},
                                                 **client))
            except BoardError as e:
                return self._err(503, str(e))
            return self._send(200, '{"ok":true}')
        return self._err(404, "not found")

    def _answer(self, body: dict, client: dict):
        cid = body.get("card")
        if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
            return self._err(404, "no such card")
        c = card_by_id(cid)
        if c is None:
            return self._err(404, "no such card")
        if c["status"] == "closed":
            return self._err(409, "the card is closed")
        if c["locked"]:
            return self._err(409, f"locked: Claude read this at {c['locked']}")
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            return self._err(400, "the note must be text")
        option = body.get("option")
        if option is None:
            if not (note or "").strip():
                return self._err(400, "a note-only answer needs a note")
        elif not isinstance(option, str) or option not in [o["value"] for o in c["options"]]:
            return self._err(400, "not one of the card's options")
        h = body.get("card_hash")
        if not isinstance(h, str) or not SHA_RE.fullmatch(h) or not hmac.compare_digest(h, c["card_hash"]):
            return self._err(409, "the card changed; reload and answer again")
        append_jsonl("answers.jsonl", dict({"card": cid, "option": option, "note": (note or "")[:MAX_NOTE],
                                            "card_hash": c["card_hash"], "at": iso(now_dt()), "via": "board"},
                                           **client))
        return self._send(200, '{"ok":true}')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"     # on Windows SO_REUSEADDR would let a second server share the port

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)  # skip HTTPServer's getfqdn(), which can stall for seconds
        self.server_name, self.server_port = HOST, self.server_address[1]


def make_server(cfg: dict) -> Server:
    handler = type("BoardHandler", (Handler,), {"token": secrets.token_urlsafe(24), "port": cfg["port"],
                                                "board_id": cfg["board_id"]})
    return Server((HOST, cfg["port"]), handler)


def serve() -> int:
    cfg = load_config()
    srv = make_server(cfg)
    write_json(DATA / "server.json", {"pid": os.getpid(), "port": cfg["port"], "started": iso(now_dt())})
    print(f"owner board at {url(cfg)} (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


# ------------------------------------------------------------------ ensure
def identity(port: int, timeout: float = 1.5) -> "dict | None":
    req = urllib.request.Request(f"http://{HOST}:{port}/api/identity", headers={"Host": f"{HOST}:{port}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            got = json.loads(r.read().decode("utf-8"))
            return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def is_mine(ident, cfg: dict) -> bool:
    return isinstance(ident, dict) and ident.get("board_id") == cfg["board_id"] and ident.get("home") == str(home_dir())


def start_detached() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    kw: dict = {"stdin": subprocess.DEVNULL, "close_fds": True, "cwd": str(HERE)}
    if os.name == "nt":
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                               | getattr(subprocess, "CREATE_NO_WINDOW", 0x8000000))
    else:
        kw["start_new_session"] = True
    with open(DATA / "serve.log", "ab") as log:
        subprocess.Popen([sys.executable, str(HERE / "board.py"), "serve"], stdout=log, stderr=log, **kw)


def cmd_ensure() -> int:
    """Start this home's board when it is not answering; never stops anything. Prints one line."""
    cfg = load_config()
    ident = identity(cfg["port"])
    if ident is None and not port_free(cfg["port"]):
        time.sleep(0.5)                      # a board that is still starting answers in a moment
        ident = identity(cfg["port"])
    if ident is None:
        if not port_free(cfg["port"]):
            print(f"board: port {cfg['port']} is held by another program; the board was not started "
                  f"(free the port, or give this home a new port in {CONFIG})")
            return 1
        start_detached()
        deadline = time.time() + 15
        while time.time() < deadline and not is_mine(ident, cfg):
            time.sleep(0.2)
            ident = identity(cfg["port"])
        if not is_mine(ident, cfg):
            print(f"board: did not start on port {cfg['port']}; see {DATA / 'serve.log'}")
            return 1
    elif not is_mine(ident, cfg):
        print(f"board: port {cfg['port']} answers for another board (not this home's board_id); "
              f"this board was not started")
        return 1
    c = counts()
    line = (f"board: {url(cfg)} · {c['open']} open · {c['new_answers']} new answers · {c['new_notes']} new notes")
    if c["acted"]:
        line += f" · {len(c['acted'])} waiting to be acted on"
    if c["problems"]:
        line += f" · {len(c['problems'])} problem(s) in its files"
    print(line)
    return 0


# ------------------------------------------------------------------ CLI
def take(rest: list, flag: str) -> "str | None":
    if flag not in rest:
        return None
    i = rest.index(flag)
    if i + 1 >= len(rest):
        raise BoardError(f"{flag} needs a value")
    val = rest[i + 1]
    del rest[i:i + 2]
    return val


def no_flags(rest: list) -> None:
    bad = [a for a in rest if a.startswith("--")]
    if bad:
        raise BoardError(f"unknown option {bad[0]}")


def card_flags(rest: list) -> dict:
    """The shared card flags: --ref, --where, --group."""
    out = {}
    for flag, key in (("--ref", "ref"), ("--where", "where"), ("--group", "group")):
        val = take(rest, flag)
        if val is not None:
            out[key] = val
    if "group" in out and out["group"] not in GROUPS:
        raise BoardError(f"--group is one of {', '.join(GROUPS)}")
    return out


def print_card_line(c: dict) -> None:
    a, v = c["answer"], c["voided"]
    tail = ""
    if a:
        tail = f"-> {a['option'] if a['option'] is not None else '(note only)'}" \
               + (f" | note: {clean(a['note'])[:80]}" if a.get("note") else "")
    elif v:
        tail = f"(the card changed after the answer {clean(v['option']) if v['option'] is not None else '(note only)'}; " \
               f"asked again)"
    print(f"{c['id']}  {c['tab']:<9} {c['status']:<8} {clean(c['title'])[:50]:<50} {tail}".rstrip())


def main(argv: "list | None" = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    try:
        if cmd == "serve" and not rest:
            return serve()
        if cmd == "ensure" and not rest:
            return cmd_ensure()
        if cmd == "url" and not rest:
            print(url())
            return 0
        if cmd == "add-decision":
            details, tech = take(rest, "--details"), take(rest, "--tech")
            tab, old = take(rest, "--tab") or "decisions", take(rest, "--replaces")
            extra = card_flags(rest)
            no_flags(rest)
            if len(rest) < 3:
                raise BoardError("usage: add-decision TITLE BODY value=Label ...")
            if old:
                prev = card_by_id(old)
                if prev is None or prev["status"] == "closed":
                    raise BoardError(f"--replaces: {old} is not an open card; nothing was written")
            card = new_card(tab, "decision", rest[0], rest[1], parse_options(rest[2:]),
                            text_of(details) if details else "", extra=extra, tech=text_of(tech) if tech else "")
            if old:
                consume(old, f"replaced by {card['id']}")
            print(f"card {card['id']} added to {tab}: {card['title']}")
            return 0
        if cmd == "add-plan":
            table, tech, item = take(rest, "--table"), take(rest, "--tech"), take(rest, "--item")
            flags = card_flags(rest)
            no_flags(rest)
            if len(rest) != 2:
                raise BoardError("usage: add-plan PLAN_FILE TITLE [--table ROWS.json] [--tech FILE] [--item NAME]")
            sha, stored, data = store_bytes("plans", rest[0])
            extra = dict({"sha256": sha, "file": str(stored), "item": item or Path(rest[0]).name}, **flags,
                         **invisible_warning(data.decode("utf-8")))
            if table:
                extra["table"] = read_table(table)
            card = new_card("decisions", "plan", rest[1],
                            "Nothing changes until you pick Apply it, and then only exactly this plan.",
                            [{"value": "apply", "label": "Apply it"},
                             {"value": "change", "label": "Change it (say how in the note)"},
                             {"value": "skip", "label": "Skip"}],
                            details=data.decode("utf-8"), extra=extra,
                            tech=text_of(tech) if tech else "")
            replaced = replace_older(card)
            print(f"card {card['id']} added to decisions: {card['title']}")
            print(f"stored: {stored}\n  dry-run and apply THIS file (sha256 {sha})")
            if replaced:
                print(f"  replaced: {', '.join(replaced)}")
            return 0
        if cmd == "add-send":
            to, cc, subject = take(rest, "--to"), take(rest, "--cc"), take(rest, "--subject")
            tech, item = take(rest, "--tech"), take(rest, "--item")
            flags = card_flags(rest)
            no_flags(rest)
            if len(rest) != 2 or not to:
                raise BoardError("usage: add-send DRAFT_FILE TITLE --to ADDR [--cc ADDR] [--subject TEXT] "
                                 "[--tech FILE] [--item NAME]")
            sha, stored, data = store_bytes("drafts", rest[0])
            body = (f"To {to}" + (f" | Cc {cc}" if cc else "") + (f" | Subject: {subject}" if subject else "")
                    + ". Read the whole draft below. It is sent only if it is still exactly this text.")
            extra = dict({"sha256": sha, "file": str(stored), "item": item or Path(rest[0]).name, "to": to}, **flags,
                         **invisible_warning(data.decode("utf-8")))
            if cc:
                extra["cc"] = cc
            if subject:
                extra["subject"] = subject
            card = new_card("email" if "email" in tabs() else "decisions", "send", rest[1], body,
                            [{"value": "send", "label": "Send it"},
                             {"value": "change", "label": "Change it (say how in the note)"},
                             {"value": "dont", "label": "Don't send"}],
                            details=data.decode("utf-8"), extra=extra,
                            tech=text_of(tech) if tech else "")
            replaced = replace_older(card)
            print(f"card {card['id']} added to {card['tab']}: {card['title']}")
            print(f"stored: {stored}\n  send THIS file only (sha256 {sha})")
            if replaced:
                print(f"  replaced: {', '.join(replaced)}")
            return 0
        if cmd == "list" and rest in ([], ["--open"]):
            s = state()
            for c in s["cards"]:
                if rest and c["status"] == "closed":
                    continue
                print_card_line(c)
                if c["answer"] and c["status"] != "closed":
                    lock(c)
            for p in s["problems"]:
                print(f"problem: {clean(p)}")
            return 0
        if cmd == "answer-for" and len(rest) == 1:
            got = answer_for(rest[0])
            print(json.dumps(got, ensure_ascii=True) if got else "null")
            return 0 if got else 1
        if cmd == "summary" and not rest:
            print(json.dumps(summary(), ensure_ascii=True))
            return 0
        if cmd == "close" and len(rest) == 2:
            consume(rest[0], rest[1])
            print(f"closed {rest[0]}")
            return 0
        if cmd == "notes" and not rest:
            problems: list = []
            for n in read_jsonl("notes.jsonl", ("note",), problems):
                print(f"{n['at']}  {clean(n['note'])}")
            for p in problems:
                print(f"problem: {clean(p)}")
            set_mark()
            return 0
    except BoardError as e:
        print(f"board: {e}", file=sys.stderr)
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
