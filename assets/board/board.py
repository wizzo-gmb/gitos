#!/usr/bin/env python3
"""board.py - the owner board of one gitos home. Standard library only.

A small web page on a loopback address (127.0.0.1 unless board.json says `host`) where the owner answers what the agent
asks: a plan, a send, a `claim()` approval and anything asked while the operator is away is a card here; a single
in-window question is asked in chat. It lives at <home>/board/: this file and board.json (port, board_id, optional host,
tabs, routes) are tracked; data/, inbox/ and outbox/ are git-ignored.

Agent side. No command here records an answer: only the board page does, through POST /api/answer.
  ensure [--tab T]             start this home's board when it is not answering, then print one line:
                               board: http://127.0.0.1:<port>/ · N open · A new answers · M new notes
                               (a warning goes to stderr when Docker is present and `host` is 127.0.0.1)
  serve                        run the board in the foreground (`ensure` starts this detached)
  url                          print the board's address
  add-decision TITLE BODY value=Label... [--details FILE] [--tech FILE] [--tab T] [--replaces ID] [CARD]
  add-plan PLAN_FILE TITLE [--table ROWS.json] [--tech FILE] [--item NAME] [--tab T] [CARD]
  add-send DRAFT_FILE TITLE --to ADDR [--cc ADDR] [--subject TEXT] [--tech FILE] [--item NAME] [--tab T] [CARD]
                               CARD: [--ref WO-NNN] [--where TEXT] [--group close|decision|action|parked];
                               `value=Label*` marks the recommended option
  list [--open] [--tab T]      the cards with their latest answer (locks each answer it shows, so it is no longer new)
  answer-for ID [--tab T]      the card's latest answer as JSON with `valid` and `locked` (exit 1 when none);
                               locks the answer
  close ID OUTCOME [--tab T]   move a card to Closed with what happened
  notes [--tab T]              the owner's notes (marks them read)
  summary [--tab T]            open, unread and not-acted-on counts as JSON (read-only; the waiting view runs it)
  actions [--json] [--tab T]   the owner's open actions from the page (WO-153/S5), marking each read; on a hub --tab T is one repo's
  action-done ID [--rejected REASON] [--tab T]   close one action: applied to the ledger, or rejected with the reason the page shows
  register-tab TAB --repo PATH on a hub: add TAB, routed to the repo at PATH (board.json), and make inbox/ and outbox/TAB/
With --tab T a command sees only that tab's cards and notes; on a hub every repo works in its own tab.

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

Data (data/): cards/<id>.json written by the agent; answers.jsonl, notes.jsonl and actions.jsonl appended only by the board page;
actions-read.jsonl and actions-done.jsonl by `actions` and `action-done`;
read.jsonl (the locks) by the reads above; closed.jsonl by close and consume; plans/ and drafts/ the bound bytes;
read-mark.json, server.json and serve.log are bookkeeping. A card's hash is recomputed from its content on every read, so a card edited after its answer voids that
answer and goes back under Needs you. Files and lines that fail validation are listed on the board, never skipped
silently.

Tabs come from "tabs": [...] in board.json; the default is `decisions` alone, which is always present.

A hub (one board for several repos, each in its own tab; board.json `host` 127.0.0.2, `routes` from register-tab):
seats propose cards by dropping <board dir>/inbox/<name>.json, written under another name and renamed when complete:
{"tab", "title", "body", "options": [{"value", "label"}], "ref"?, "group"?}. The server (and `list`) turns a valid
request into a decision card marked `source: inbox` and moves an invalid one to inbox/rejected/ with a reason (shown as
a problem); a request never answers anything. The owner answers on the page only. The server writes an answer to
outbox/<tab>/<card id>.json once it is a minute old, and that write is the read that locks it; a changed or voided card
loses its file. Nothing in inbox/ or outbox/ is ever a consent.

A repo's own views, data and look (WO-153/S6), three opt-in parts under <board dir>, committed with the repo and never touched by
an upgrade or scaffold: views/<name>.js (name `a-z 0-9 -`, 1-32) is an ES module that exports `meta` and registers the custom
element gb-repo-<name>; the state lists each as `views` ({name, v}) and GET /views/<name>.js serves it from 'self' (no inline or
remote script), so the page puts it in the sidebar and mounts it like an engine view. providers/<name>.py (same names) is run by
the board in its own `python -I -B` process (argument 1 the home, working directory the home; 10 s; one JSON value on stdout, at
most 256 KB), again when the watcher sees a change and at most every 5 s; its output is `state.ext.<name>`, and a crash, a hang
or bad output is an `errors` entry (the last good output stays). views/theme.css is loaded after the engine's styles
(`state.theme` says when it changed). A repo view is repo code in the board's page, trusted like its providers; the contract
(references/owner-board.md) is that it asks for an owner action only through the kit's requestAction. There is no /local/ any more.

Owner actions (WO-153/S5): the owner asks for a change to an order on the page (reprioritize, park with a trigger, unpark, hold,
release, approve for dispatch, add a note); POST /api/action has the checks an answer has and appends one line to
data/actions.jsonl naming the order and the state the owner saw (its version and the order's hash). The board never writes a
work-order file: the orchestrator reads the actions (`summary` counts the new ones, `actions` lists them and marks them read) and
applies each to the ledger, then closes it with `action-done` (data/actions-done.jsonl; nothing is inferred from the ledger). The
page shows an action as pending until it is closed, and says applied or the rejection reason.

A hub's repos (WO-153/S7): a hub's `routes` name each repo's folder. GET /api/state?tab=T and GET /api/events?tab=T are that repo's
state and stream, built from the repo's own home only (never the board's own, never another repo's); T must be a tab `routes`
lists, else 404. The hub's own state (no `tab`) holds `repos`, one counts-only row per routed repo for the page's `all` view, and
a row whose home cannot be read says why. The stream cap counts every stream of every tab. A repo tab holds none of the hub's
own views, providers, theme or canary. An owner action on a repo's order is asked with its `tab`, checked against that repo's
state and appended to this board's data/actions.jsonl with the tab: `actions --tab T` and `action-done --tab T` are that repo's
orchestrator's. The board writes nothing into a repo.

Live data (WO-153): GET /api/state is the board's own state (cards, notes, tabs, problems) plus the ledger half, built through the
engine's readers (ledger_index, slice, sprint_log, loose_ends): orders with their slices and `depends_on`, resolved orders, sprints,
loose ends, the brain's decision records as metadata, and `errors` (a reader that raised, said and never thrown), with a `version`.
A sprint's Stop card (sprint tab, a `stop` option) is a control: the page's state holds it in `controls`, not in `cards`, and counts and
lists of the owner's cards leave it out; the CLI and the driver still see it as a card.
GET /api/events is a text/event-stream of that state (event `state`, the version as its id, honouring Last-Event-ID), a comment
every 15 s, at most 16 open and a seventeenth gets 503. One watcher thread notices changes in the files the state is built from.
The readers are found beside this file's repo (the engine's own checkout) or in the installed skill; with none, `errors` says so.
`canary` is {total, at}: the engine's canary run in its own process every 5 minutes (the first a few seconds after the start), a
failed run an `errors` entry.

The page (WO-153/S3): <board dir>/ui/ is the app, an engine file set that scaffold copies beside this file and an upgrade replaces
whole: index.html, app.js and the ES modules and style sheets it imports, views/<name>.js. GET / fills index.html (title, page
token, script nonce); GET /ui/<name>.js|css and /ui/views/<name>.js are served from 'self' by the raw path (no decoding, no `..`).
The page's CSP allows scripts and styles from this origin only (no inline), a fetch to this origin, a frame of this origin.

A named sprint's session (GITOS_SPRINT=1, GITOS_SPRINT_ID, GITOS_SPRINT_HOME) runs in its own worktree: every command there uses the
board of GITOS_SPRINT_HOME (that home's hub, when its board-route.json names one), never the worktree's own copy and data/. When that home is missing, has no board or has a route that cannot be read, board.py refuses (a line naming the home and the fix, exit 2) instead of using the local board.

The honest limit: on a single-user machine the agent runs as the owner, so it could forge a browser request or write
these files itself. The board guards against accidents and against other local pages and programs, not against a
deliberately hostile agent.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import html
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BOARD_VERSION = 9
DEFAULT_HOST = "127.0.0.1"
PORT_LO, PORT_HI = 8800, 8999
BASE_TABS = ("decisions",)
CONTROL_TAB = "sprint"     # the tab a sprint driver posts its Stop card to
GROUPS = ("close", "decision", "action", "parked")
KINDS = ("decision", "plan", "send")
GO = {"plan": "apply", "send": "send"}
MAX_BODY = 64 * 1024
MAX_NOTE = 4000
ACTION_KINDS = ("severity", "park", "unpark", "hold", "release", "approve", "note")
ACTION_SEVERITY = ("critical", "high", "medium", "low")
MAX_OPEN_ACTIONS = 200                               # open owner actions; the next is refused until the orchestrator closes some
ACTIONS_DONE_SHOWN = 20                              # the newest closed actions the state lists (for the toast and the drawer)
ORDER_ID_RE = re.compile(r"^\d{3}$")
HASH16_RE = re.compile(r"^[0-9a-f]{16}$")
VERSION_RE = re.compile(r"^[0-9a-f]{6}\.\d{1,9}$")
INBOX_KEYS = ("tab", "title", "body", "options", "ref", "group")
INBOX_BATCH = 20                                     # request files taken per pass
INBOX_EVERY, MIRROR_EVERY, MIRROR_AFTER = 5, 60, 60  # seconds: look at inbox/, mirror, an answer's age before its mirror
ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}-[0-9a-f]{4}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VALUE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
TAB_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
NAME_RE = re.compile(r"^[a-z0-9-]{1,32}$")            # a repo view's or provider's name
VIEWS_MAX = 32                                       # repo views and providers listed; more are ignored

_LOCK = threading.RLock()
_HELD = threading.local()
LOCK_WAIT = 10.0


class BoardError(Exception):
    """A refused request from the agent side: the CLI prints it and exits 2."""


def set_dir(board_dir) -> None:
    """Point this module at one board directory (default: the one this file sits in, or a named sprint's board: follow_sprint())."""
    global HERE, DATA, CARDS, CONFIG
    HERE = Path(board_dir).resolve()
    DATA = HERE / "data"
    CARDS = DATA / "cards"
    CONFIG = HERE / "board.json"


set_dir(Path(__file__).resolve().parent)

# A named sprint's session (WO-150) runs in its own worktree, whose copy of this board has its own data/. The driver gives the
# main checkout's home as GITOS_SPRINT_HOME: the sprint's cards and page belong to that home's board. The id rule and the
# reserved ids are scripts/compact_restore.py's (this file is copied into every home alone, so it cannot import them).
SPRINT_ID_RE = re.compile(r"[a-z0-9-]{1,32}")
SPRINT_RESERVED_IDS = ("claims", "archive", "stop", "rotate", "busy", "exclusive")


def sprint_board_dir() -> "Path | None":
    """The board directory a named sprint's session must use, or None (no such session, or no home named): GITOS_SPRINT=1, a
    GITOS_SPRINT_ID that is a sprint id and a GITOS_SPRINT_HOME. That home's own routing applies: a hub route in its
    board-route.json leads to the hub's board directory, else it is `<home>/board`. A home that is missing, has no board or has a
    route that cannot be read raises BoardError: a sprint's card never lands on another board (WO-152/S3)."""
    if os.environ.get("GITOS_SPRINT") != "1":
        return None
    sid = os.environ.get("GITOS_SPRINT_ID", "")
    home = os.environ.get("GITOS_SPRINT_HOME", "")
    if not SPRINT_ID_RE.fullmatch(sid) or sid in SPRINT_RESERVED_IDS or not home:
        return None
    fix = "set GITOS_SPRINT_HOME to the main checkout's .gitos home that holds a board (or unset it outside a sprint)"
    if not Path(home).is_dir():
        raise BoardError(f"GITOS_SPRINT_HOME {home} is not a folder; {fix}")
    try:
        r = route(home)
    except BoardError as e:
        raise BoardError(f"GITOS_SPRINT_HOME {home} has an unusable board route ({e}); {fix}")
    target = Path(r["board"]) if r else Path(home) / "board"
    if not (target / "board.json").is_file():
        raise BoardError(f"GITOS_SPRINT_HOME {home} has no board (no {target / 'board.json'}); {fix}")
    return target


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


def valid_host(host) -> bool:
    """127.0.0.1 - 127.0.0.254: the loopback addresses a board may bind. A hub leaves 127.0.0.1, which Docker Desktop's
    host gateway forwards a container to, for another one."""
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return isinstance(host, str) and str(ip) == host and ip in ipaddress.ip_network("127.0.0.0/24") \
        and host not in ("127.0.0.0", "127.0.0.255")


def host_of(cfg: dict) -> str:
    return cfg.get("host", DEFAULT_HOST)


def docker_present() -> bool:
    """A `docker` CLI on PATH, or a Docker Desktop install (it forwards a container's host gateway to 127.0.0.1)."""
    desktop = (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe",
               Path("/Applications/Docker.app"))
    return shutil.which("docker") is not None or any(p.exists() for p in desktop)


def docker_warning(cfg: dict) -> "str | None":
    """The `ensure` warning: this board listens on 127.0.0.1 and Docker is here, so a container can read the page (token
    included) and answer. None when `host` is another loopback address or there is no Docker."""
    if host_of(cfg) == DEFAULT_HOST and docker_present():
        return ("board: warning: Docker is present and this board listens on 127.0.0.1, which a container reaches through "
                f'its host gateway; set "host": "127.0.0.2" in {CONFIG} and restart the board')
    return None


def port_free(port: int, host: str = DEFAULT_HOST) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # a port in TIME_WAIT is free to a server
        s.bind((host, port))
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
    if not valid_host(host_of(cfg)):
        raise BoardError(f"{CONFIG}: `host` must be an address from 127.0.0.1 to 127.0.0.254")
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


def route(home) -> "dict | None":
    """`<home>/board-route.json` (the one shared reader of it): None when this home keeps its own board (no file, or
    mode `local`); for a hub `{"mode": "hub", "board": <the hub's board dir, absolute>, "tab": <this repo's tab>}`. A file
    that does not parse or lacks what its mode needs raises BoardError."""
    path = Path(home) / "board-route.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        r = json.loads(raw)
    except ValueError:
        raise BoardError(f"{path} is not JSON")
    if not isinstance(r, dict) or r.get("mode") not in ("local", "hub"):
        raise BoardError(f"{path}: `mode` is `local` or `hub`")
    if r["mode"] == "local":
        return None
    if not isinstance(r.get("board"), str) or not Path(r["board"]).is_absolute() \
            or not isinstance(r.get("tab"), str) or not TAB_RE.fullmatch(r["tab"]):
        raise BoardError(f"{path}: a hub route needs `board` (an absolute path) and `tab` (a-z 0-9 -, 1-24)")
    return r


HOME_DIRS = (".gitos", "outputs/debug", ".pipeline", "docs/agents")   # where a repo's home may be (scaffold.py detect_home, same order)


def routes(cfg: "dict | None" = None) -> dict:
    """A hub's routes as {tab: the repo's root folder}: each `routes` entry of board.json whose tab is one of the board's tabs and
    whose value is an absolute path. {} for a board that routes nothing (not a hub). The only place a tab becomes a folder."""
    try:
        cfg = cfg if cfg is not None else load_config()
    except BoardError:
        return {}
    raw, known = cfg.get("routes"), tabs(cfg)
    if not isinstance(raw, dict):
        return {}
    return {t: Path(p) for t, p in raw.items() if isinstance(t, str) and TAB_RE.fullmatch(t) and t in known
            and isinstance(p, str) and Path(p).is_absolute()}


def repo_home(root: Path) -> "Path | None":
    """The gitos home of a routed repo (its `.gitos/`, else the older homes), or None when the folder has none."""
    for rel in HOME_DIRS:
        if (Path(root) / rel).is_dir():
            return Path(root) / rel
    return None


def _plain_files(folder: Path, suffix: str) -> list:
    """[(name, stat)] of the plain files `<name><suffix>` of `folder` whose name matches NAME_RE, sorted, at most VIEWS_MAX. A
    symbolic link, a directory and any other name are ignored; a missing folder is empty."""
    out = []
    try:
        for p in sorted(folder.iterdir()):
            if p.suffix == suffix and NAME_RE.fullmatch(p.stem) and p.is_file() and not p.is_symlink():
                out.append((p.stem, p.stat()))
    except OSError:
        return out
    return out[:VIEWS_MAX]


def repo_views() -> list:
    """The repo's views: [{name, v}] for each `<board dir>/views/<name>.js` (`v` changes when the file does)."""
    return [{"name": n, "v": f"{st.st_mtime_ns}-{st.st_size}"} for n, st in _plain_files(HERE / "views", ".js")]


def theme_version() -> "str | None":
    """`views/theme.css` as a version string, or None when the repo has none."""
    p = HERE / "views" / "theme.css"
    try:
        st = p.stat()
        return f"{st.st_mtime_ns}-{st.st_size}" if p.is_file() and not p.is_symlink() else None
    except OSError:
        return None


def url(cfg: "dict | None" = None, tab: "str | None" = None) -> str:
    cfg = cfg or load_config()
    return f"http://{host_of(cfg)}:{cfg['port']}/" + (f"#{tab}" if tab else "")


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
    if "source" in c and c["source"] != "inbox":
        return "`source` is only ever `inbox`"
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


def is_control(c: dict) -> bool:
    """A sprint's Stop card: on the sprint tab, with a `stop` option. A stop is a control on the Sprints view, not a decision: it
    stays a card (the driver reads its answer through `answer-for`) but is not one of the owner's open cards."""
    return c.get("tab") == CONTROL_TAB and any(isinstance(o, dict) and o.get("value") == "stop" for o in c.get("options") or [])


def hide_controls(s: dict) -> dict:
    """The page's state: Stop cards move from `cards` to `controls` (the Sprints view answers them), so no count, tab or list of
    the owner's cards holds one; the sprint tab goes when nothing but Stop cards was on it. The CLI and the driver read `state()`."""
    cards = s["cards"]
    s["controls"] = [c for c in cards if is_control(c)]
    s["cards"] = [c for c in cards if not is_control(c)]
    s["copy"] = copy_text(s["cards"])
    if not any(c["tab"] == CONTROL_TAB for c in s["cards"]):
        s["tabs"] = [t for t in s["tabs"] if t != CONTROL_TAB]
    return s


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
        cfg = load_config()
    except BoardError:
        cfg = {}
    return {"cards": out, "notes": notes[-20:], "tabs": list(tab_set),
            "problems": problems + inbox_problems(), "copy": copy_text(out), "name": home_dir().parent.name,
            "where": f"{home_dir().name}/{HERE.name}", "host": host_of(cfg), "port": cfg.get("port", ""),
            "now": iso(now_dt())}


def note_tab(n: dict) -> str:
    """The tab a note was saved on; a note from before tabs belongs to the default tab."""
    return n["tab"] if isinstance(n.get("tab"), str) else BASE_TABS[0]


def note_counts() -> dict:
    out: dict = {}
    for n in read_jsonl("notes.jsonl", ("note",), []):
        out[note_tab(n)] = out.get(note_tab(n), 0) + 1
    return out


def read_mark() -> dict:
    """How many notes of each tab the agent has read (`notes`). Answers need no mark: reading one locks it."""
    try:
        return {t: int(n) for t, n in json.loads((DATA / "read-mark.json").read_text(encoding="utf-8"))["tabs"].items()}
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return {}


def counts(tab: "str | None" = None) -> dict:
    """Open cards, and answers and notes the agent has not read yet (one tab's, or all). Read-only. A new answer is the
    current answer of a card that is not closed and that no read has locked: `answer-for`, `list` or a close each clear
    it."""
    s = state()
    cards = [c for c in s["cards"] if tab in (None, c["tab"])]
    cards = [c for c in cards if not is_control(c)]
    mark = read_mark()
    ap: list = []
    live = [a for a in acts_in_tab(read_actions(ap), tab) if not a["closed"]]
    return {"open": sum(1 for c in cards if c["status"] != "closed"),
            "open_actions": len(live), "new_actions": sum(1 for a in live if not a["read"]),
            "needs": [c for c in cards if c["status"] == "needs"],
            "acted": [c for c in cards if c["status"] == "answered"],
            "new_answers": sum(1 for c in cards if c["status"] == "answered" and not c["locked"]),
            "new_notes": sum(max(0, n - mark.get(t, 0)) for t, n in note_counts().items() if tab in (None, t)),
            "problems": s["problems"] + ap}


def summary(tab: "str | None" = None) -> dict:
    """counts() as plain JSON-ready data, every title cleaned: what the waiting view reads (in a subprocess)."""
    c = counts(tab)
    return {"open": c["open"], "new_answers": c["new_answers"], "new_notes": c["new_notes"],
            "new_actions": c["new_actions"], "open_actions": c["open_actions"],
            "needs": [{"id": x["id"], "title": clean(x["title"]), "voided": bool(x["voided"])} for x in c["needs"]],
            "acted": [{"id": x["id"], "title": clean(x["title"]), "locked": bool(x["locked"])} for x in c["acted"]],
            "problems": [clean(p) for p in c["problems"]]}


def set_mark(tab: "str | None" = None) -> None:
    """Mark the notes read (`notes`): one tab's, or every tab's."""
    mark = read_mark()
    mark.update({t: n for t, n in note_counts().items() if tab in (None, t)})
    write_json(DATA / "read-mark.json", {"tabs": mark})


# ------------------------------------------------------------------ owner actions (WO-153/S5)
def read_actions(problems: list) -> list:
    """Every owner action in data/actions.jsonl, oldest first, as plain dicts: id, order, kind, value, at, version and hash (the
    state the owner saw), stale (the order had changed since), `read` (the orchestrator has listed or closed it) and `closed`
    (None, or {outcome, reason, at}). A line that is not an action is a problem, never skipped silently."""
    acts, ids = [], set()
    for n, e in enumerate(read_jsonl("actions.jsonl", ("id", "order", "kind"), problems), 1):
        v = e.get("value")
        if not (ID_RE.fullmatch(e["id"]) and ORDER_ID_RE.fullmatch(e["order"]) and e["kind"] in ACTION_KINDS
                and (v is None or isinstance(v, str)) and e["id"] not in ids):
            problems.append(f"actions.jsonl entry {n} is not an owner action")
            continue
        if e.get("tab") is not None and not (isinstance(e["tab"], str) and TAB_RE.fullmatch(e["tab"])):
            problems.append(f"actions.jsonl entry {n} names a tab that is not a tab")
            continue
        ids.add(e["id"])
        acts.append(e)
    done = {}
    for d in read_jsonl("actions-done.jsonl", ("action", "outcome"), problems):
        if d["outcome"] in ("applied", "rejected"):
            done.setdefault(d["action"], d)
    read = {r["action"] for r in read_jsonl("actions-read.jsonl", ("action",), problems)}
    out = []
    for a in acts:
        d = done.get(a["id"])
        out.append({"id": a["id"], "order": a["order"], "kind": a["kind"], "value": a.get("value"), "at": a["at"], "tab": a.get("tab"),
                    "version": str(a.get("version") or ""), "hash": str(a.get("hash") or ""), "stale": bool(a.get("stale")),
                    "read": a["id"] in read or d is not None,
                    "closed": {"outcome": d["outcome"], "reason": str(d.get("reason") or ""), "at": d["at"]} if d else None})
    return out


def acts_of(acts: list, tab: "str | None") -> list:
    """The actions that belong to one place: `tab` None is the board's own home, a tab is the repo a hub routes it to. An action
    carries the tab it was asked on, so a repo's order is never applied to another home's order of the same number."""
    return [a for a in acts if a["tab"] == tab]


def acts_in_tab(acts: list, tab: "str | None") -> list:
    """The actions a command sees under `--tab`: on a hub, those of that tab (the board's own home is its base tab); on a board
    that routes nothing, every action (there is one home)."""
    if tab is None or not routes():
        return acts
    return [a for a in acts if (a["tab"] or BASE_TABS[0]) == tab]


def order_hash(order: dict) -> str:
    """The state of one order as the owner sees it: 16 hex of its content (everything the state holds for it but this hash)."""
    body = {k: v for k, v in order.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()[:16]


def action_flags(acts: list, order_ids: set) -> tuple:
    """The orders the owner holds and the ones approved for dispatch, from the actions the orchestrator closed as applied (oldest
    first; a later release or park undoes). The ledger has no field for either, so the record of what was applied is it."""
    held, approved = set(), set()
    for a in acts:
        if not a["closed"] or a["closed"]["outcome"] != "applied":
            continue
        o, k = a["order"], a["kind"]
        if k == "hold":
            held.add(o)
        elif k == "release":
            held.discard(o)
        elif k == "approve":
            approved.add(o)
        elif k == "park":
            held.discard(o)
            approved.discard(o)
    return sorted(held & order_ids), sorted(approved & order_ids)


def action_view(acts: list) -> dict:
    """What the live state says of the actions: the open ones, and the newest closed ones (the page toasts when one closes)."""
    opened = [{k: a[k] for k in ("id", "order", "kind", "value", "at", "version", "hash", "stale", "read")} for a in acts if not a["closed"]]
    closed = sorted((a for a in acts if a["closed"]), key=lambda a: a["closed"]["at"], reverse=True)[:ACTIONS_DONE_SHOWN]
    shut = [{**{k: a[k] for k in ("id", "order", "kind", "value", "at")}, "outcome": a["closed"]["outcome"],
             "reason": a["closed"]["reason"], "doneAt": a["closed"]["at"]} for a in closed]
    return {"actions": opened, "actionsDone": shut}


def action_line(a: dict) -> str:
    """One open action as the orchestrator reads it: the order, what is asked, the state the owner saw."""
    v = clean(a["value"] or "")
    what = {"severity": f"severity -> {v}", "park": f"park until: {v}", "note": f"note: {v}"}.get(a["kind"], a["kind"])
    seen = f"saw state {a['hash'] or '-'} at {a['version'] or '-'}" + ("; the order had changed since" if a["stale"] else "")
    return f"{a['id']}  " + (f"[{a['tab']}] " if a.get("tab") else "") + f"WO-{a['order']}  {what}  ({seen})  {a['at']}"


def need_tab(tab: "str | None", cmd: str) -> None:
    """On a hub every action belongs to one repo's tab (the hub's own home is `--tab decisions`): without one the command would
    close or mark another repo's action."""
    if tab is None and routes():
        raise BoardError(f"{cmd} on a hub needs --tab T (the repo's tab; the hub's own home is --tab {BASE_TABS[0]})")


def cmd_actions(rest: list, tab: "str | None" = None) -> int:
    """List the open actions (oldest first) and mark each read: after this `summary` no longer counts them as new."""
    need_tab(tab, "actions")
    as_json = "--json" in rest
    if as_json:
        rest.remove("--json")
    if rest:
        raise BoardError("usage: actions [--json]")
    problems: list = []
    with file_lock():
        acts = [a for a in acts_in_tab(read_actions(problems), tab) if not a["closed"]]
        for a in acts:
            if not a["read"]:
                append_jsonl("actions-read.jsonl", {"action": a["id"], "at": iso(now_dt())})
    if as_json:
        print(json.dumps([{**a, "value": clean(a["value"]) if a["value"] is not None else None} for a in acts], ensure_ascii=True))
    else:
        for a in acts:
            print(action_line(a))
    for p in problems:
        print(f"problem: {clean(p)}", file=sys.stderr if as_json else sys.stdout)
    return 0


def cmd_action_done(rest: list, tab: "str | None" = None) -> int:
    """Close one open action: applied, or rejected with the reason the page shows the owner."""
    need_tab(tab, "action-done")
    reason = take(rest, "--rejected")
    if len(rest) != 1:
        raise BoardError("usage: action-done ID [--rejected REASON]")
    if reason is not None and not clean(reason):
        raise BoardError("--rejected needs the reason the owner will read")
    with file_lock():                          # one close per action, whoever is closing
        got = {a["id"]: a for a in acts_in_tab(read_actions([]), tab)}.get(rest[0])
        if got is None:
            raise BoardError(f"no action {rest[0]}" + (f" in tab {tab}" if tab else ""))
        if got["closed"]:
            raise BoardError(f"action {rest[0]} is already closed ({got['closed']['outcome']})")
        append_jsonl("actions-done.jsonl", {"action": rest[0], "outcome": "applied" if reason is None else "rejected",
                                            "reason": clean(reason or "")[:MAX_NOTE], "at": iso(now_dt())})
    print(f"closed {rest[0]} ({'applied' if reason is None else 'rejected'})")
    return 0


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
    with file_lock():                      # the server's inbox pass and a CLI card never pick the same `created`
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
    """Close the older open cards of the same kind and tab for the same item as `card`: "replaced by <id>"."""
    done = []
    for c in state()["cards"]:
        if c["id"] != card["id"] and c["tab"] == card["tab"] and c["kind"] == card["kind"] \
                and c.get("item") == card.get("item") and card.get("item") and c["status"] != "closed" \
                and c["created"] < card["created"]:
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


def agent_read(c: dict) -> None:
    """The agent reads a card's answer: it locks. A seat's card (`source: inbox`) is read by the mirror alone, so the
    owner keeps the minute to change an answer the seat has not been given."""
    if c["answer"] and c["status"] != "closed" and c.get("source") != "inbox":
        lock(c)                                    # None when a newer answer arrived: that one is pending


def answer_for(cid: str, tab: "str | None" = None) -> "dict | None":
    """`answer-for`: read (and so lock) a card's answer, then report the answer as it is NOW, never a superseded one.
    `valid` is true only when that answer is locked and its hash matches the card. With `tab`, a card of another tab
    is not found. -> the answer dict, or None."""
    c = card_by_id(cid)
    if not c or tab not in (None, c["tab"]) or not (c["answer"] or c["voided"]):
        return None
    agent_read(c)
    c = card_by_id(cid) or c
    a = c["answer"] or c["voided"]
    valid = bool(c["answer"] and c["locked"] and c["status"] != "closed"
                 and hmac.compare_digest(a["card_hash"], c["card_hash"]))
    return dict(a, note=clean(a.get("note", "")), valid=valid, status=c["status"], locked=c["locked"])


def _newest(cards: list, kind: str, key: str, value, tab: "str | None" = None) -> "dict | None":
    """A seat's card (`source: inbox`) never counts: a tool acts on what its own repo's agent asked, not on a proposal."""
    return next((c for c in reversed(cards) if c["kind"] == kind and c.get(key) == value
                 and c.get("source") != "inbox" and tab in (None, c["tab"])), None)


def approved(kind: str, key: str, value, go: "str | None" = None, tab: "str | None" = None) -> "dict | None":
    """The newest card of `kind` (in `tab`, on a hub) whose `key` field equals `value`, when it is not closed and its
    latest answer chose the go option against the card's current content AND that answer is locked. Otherwise None.
    Reading locks the
    answer it sees, then the card is read again: an answer that arrived in between is pending, and a pending answer
    never authorizes. A note-only answer is never a go; a newer card for the same item always blocks an older one."""
    go = go or GO.get(kind)
    if not go:
        raise BoardError(f"approved() needs go= for kind {kind!r}")
    c = _newest(state()["cards"], kind, key, value, tab)
    if c is None or c["status"] != "answered":
        return None
    lock(c)
    c = _newest(state()["cards"], kind, key, value, tab)
    if c is None or c["status"] != "answered" or not c["locked"]:
        return None
    a = c["answer"]
    if a["at"] > c["locked"]:
        return None                                        # a lock older than the answer it names is not a read of it
    if a["option"] == go and hmac.compare_digest(a["card_hash"], c["card_hash"]):
        return c
    return None


def claim(kind: str, key: str, value, go: "str | None", outcome: str, tab: "str | None" = None) -> "dict | None":
    """approved() and consume() as one step under the board's lock: the approved card, now closed with `outcome`, or
    None. Of two tools claiming the same approval, exactly one gets it. Act only after claim() returns the card."""
    with file_lock():
        c = approved(kind, key, value, go, tab)
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


# ------------------------------------------------------------------ the hub
def same_path(a, b) -> bool:
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def register_tab(tab: str, repo: str) -> str:
    """On a hub: add `tab` to board.json `tabs`, routed to `repo` in `routes`, and make inbox/ and outbox/<tab>/ (with a
    .gitignore for both). A tab already routed to another repo is refused; the same repo again changes nothing."""
    if not TAB_RE.fullmatch(tab) or tab in BASE_TABS:
        raise BoardError(f"a tab is a-z 0-9 - (1-24, starting with a letter) and not {BASE_TABS[0]!r}")
    if not Path(repo).is_dir():
        raise BoardError(f"--repo {repo} is not a folder")
    where = str(Path(repo).resolve())
    with file_lock():
        cfg = load_config()
        routes = cfg["routes"] if isinstance(cfg.get("routes"), dict) else {}
        if tab in routes and not same_path(routes[tab], where):
            raise BoardError(f"tab {tab!r} is already routed to {routes[tab]}")
        cfg["routes"] = dict(routes, **{tab: where})
        cfg["tabs"] = list(dict.fromkeys([*(cfg["tabs"] if isinstance(cfg.get("tabs"), list) else []), tab]))
        write_json(CONFIG, cfg)
    (HERE / "outbox" / tab).mkdir(parents=True, exist_ok=True)
    (HERE / "inbox").mkdir(exist_ok=True)
    if not (HERE / ".gitignore").exists():
        (HERE / ".gitignore").write_bytes(b"inbox/\noutbox/\n")
    return f"tab {tab} routed to {where}"


def _texts(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _texts(v)
    elif isinstance(x, list):
        for v in x:
            yield from _texts(v)


def request_problem(req) -> "str | None":
    """Why an inbox request is not a decision-card request, or None. A seat proposes a decision card and nothing else:
    no plan or send (the hub cannot bind files it did not receive), no details, no answer. Tab, title, body, options and
    group are then checked as any card is (`new_card`)."""
    if not isinstance(req, dict):
        return "not a JSON object"
    extra = sorted(set(req) - set(INBOX_KEYS))
    if extra:
        return f"unknown field {extra[0]!r}: a request has only {', '.join(INBOX_KEYS)} (a decision card)"
    opts = req.get("options")
    if not isinstance(opts, list) or not all(isinstance(o, dict) and set(o) == {"value", "label"} for o in opts):
        return "`options` must be a list of {value, label}"
    if len(opts) > 10 or any(len(str(x)) > n for x, n in [(req.get("title", ""), 200), (req.get("body", ""), MAX_NOTE),
                                                         (req.get("ref", ""), 40), *[(o["label"], 100) for o in opts]]):
        return "a field is over its size limit (title 200, body 4000, ref 40, 10 options, label 100)"
    if any(hidden(ch) for t in _texts(req) for ch in t):
        return "it holds invisible (bidi, zero-width or control) characters"
    return None


def reject(p: Path, why: str) -> None:
    """Move an invalid request to inbox/rejected/ and say why beside it; `state()` shows each reason as a problem."""
    folder = p.parent / "rejected"
    folder.mkdir(exist_ok=True)
    name = f"{now_dt():%Y%m%d-%H%M%S-%f}-{secrets.token_hex(2)}.json"
    os.replace(p, folder / name)
    (folder / (name + ".reason")).write_text(clean(f"{p.name}: {why}") + "\n", encoding="utf-8")


def ingest_inbox() -> list:
    """Turn each request file in <board dir>/inbox/ into a decision card marked `source: inbox`, or reject it (see
    `reject`). A request only ever creates a card: it carries no answer and none is made. -> the new card ids."""
    inbox = HERE / "inbox"
    try:
        files = sorted(p for p in inbox.iterdir() if p.suffix == ".json")[:INBOX_BATCH]
    except OSError:
        return []
    made = []
    with file_lock():                              # a busy lock raises here, so it never rejects a valid request
        for p in files:
            try:
                if p.is_symlink() or not p.is_file():
                    raise BoardError("not a plain file")
                with open(p, "rb") as f:
                    raw = f.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise BoardError(f"larger than {MAX_BODY} bytes")
                try:
                    req = json.loads(raw.decode("utf-8"))
                except ValueError:
                    raise BoardError("not UTF-8 JSON")
                why = request_problem(req)
                if why:
                    raise BoardError(why)
                card = new_card(req.get("tab"), "decision", req.get("title"), req.get("body"), req["options"],
                                extra=dict({"source": "inbox"}, **{k: req[k] for k in ("ref", "group") if k in req}))
            except (BoardError, OSError) as e:
                reject(p, str(e))
                continue
            p.unlink()
            made.append(card["id"])
    return made


def inbox_problems() -> list:
    """One problem line per rejected request (the owner or the agent clears them by deleting inbox/rejected/)."""
    try:
        reasons = sorted((HERE / "inbox" / "rejected").glob("*.reason"))
    except OSError:
        return []
    out = []
    for p in reasons[:20]:
        try:
            out.append("inbox request rejected: " + clean(p.read_text(encoding="utf-8", errors="replace")[:300]))
        except OSError:
            continue
    return out + ([f"{len(reasons) - 20} more rejected inbox requests"] if len(reasons) > 20 else [])


def mirror(now: "datetime | None" = None) -> list:
    """Write each answered seat card's answer to outbox/<tab>/<card id>.json once the answer is MIRROR_AFTER seconds old.
    Writing the mirror is the read: the answer is locked (read.jsonl) first, so the owner can change a fresh answer until
    then and never after. A mirror whose card changed, was voided or is gone is deleted. -> the ids newly mirrored."""
    cutoff = iso((now or now_dt()) - timedelta(seconds=MIRROR_AFTER))
    cards = {c["id"]: c for c in state()["cards"]}
    for f in (HERE / "outbox").glob("*/*.json"):
        if f.stem not in cards or cards[f.stem]["answer"] is None:
            f.unlink(missing_ok=True)
    done = []
    for c in cards.values():
        if c.get("source") != "inbox" or c["status"] != "answered" or c["answer"]["at"] > cutoff or lock(c) is None:
            continue
        a = c["answer"]
        entry = {"card": dict({k: clean(c[k]) for k in ("title", "ref") if k in c}, id=c["id"], tab=c["tab"]),
                 "card_hash": c["card_hash"], "answer": {"option": a["option"], "note": clean(a.get("note", ""))},
                 "answered_at": a["at"]}
        path = HERE / "outbox" / c["tab"] / f"{c['id']}.json"
        try:
            same = json.loads(path.read_text(encoding="utf-8")) == entry
        except (OSError, ValueError):
            same = False
        if not same:
            write_json(path, entry)
            done.append(c["id"])
    return done


def maintain() -> None:
    """The serving process's housekeeping: look at inbox/ every few seconds, mirror answers once a minute."""
    last = 0.0
    while True:
        try:
            ingest_inbox()
            if time.time() - last >= MIRROR_EVERY:
                mirror()
                last = time.time()
        except Exception as e:                     # one bad pass never ends the loop; the log says why
            print(f"maintain: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(INBOX_EVERY)


# ------------------------------------------------------------------ the live state (WO-153)
STREAM_MAX = 16          # open /api/events streams; the next one is refused with 503
FIRST_WAIT = 5.0         # seconds a stream request waits for the first state of its tab before it is refused with 503
STREAM_TICK = 0.25       # seconds a stream waits on its socket before it looks at the version again
HEARTBEAT = 15           # seconds of silence before a stream sends a comment line
WATCH_EVERY = 0.5        # seconds between the watcher's looks at the files
RESOLVED_SHOWN = 20      # the newest resolved orders listed (their count is exact)
SLICE_REF_RE = re.compile(r"(?:WO-?)?(\d{3})/(S\d+[a-z]?)", re.IGNORECASE)
CANARY_FIRST = 3         # seconds after the server starts before the first canary run
CANARY_EVERY = 300       # seconds between canary runs: it reads the whole home, so the state shows its last answer
CANARY_LIMIT = 120       # seconds a canary run may take before it is stopped and reported
CANARY_ON = os.environ.get("GITOS_BOARD_CANARY") != "0"   # a test that does not want the runs sets it off
CANARY = {"total": None, "at": None, "error": None}   # the last run, replaced whole by the canary thread
PROVIDER_LIMIT = 10      # seconds a provider may run before it is stopped and reported
PROVIDER_MAX_OUT = 256 * 1024   # bytes of JSON a provider may print
PROVIDER_EVERY = 5       # seconds between two sets of provider runs, whatever the watcher sees
PROVIDERS = {"ext": {}, "errors": [], "n": 0}   # the last provider runs, replaced whole by the provider thread
ENGINE_SCRIPTS = None    # the engine's scripts folder, when a caller (a test) names it; else found by engine_scripts()
_ENGINE_MODS: dict = {}


def engine_scripts() -> "Path | None":
    """The engine's `scripts/` folder, which holds the readers this board does not copy: the repo this home sits in when it is
    the engine's own checkout, the checkout this file sits in, else the installed skill. A folder counts only beside a VERSION."""
    here = Path(__file__).resolve()
    for cand in ([Path(ENGINE_SCRIPTS)] if ENGINE_SCRIPTS else
                 [HERE.parent.parent / "scripts", here.parent.parent.parent / "scripts",
                  Path.home() / ".claude" / "skills" / "gitos" / "scripts"]):
        if (cand / "ledger_index.py").is_file() and (cand.parent / "VERSION").is_file():
            return cand
    return None


def engine(filename: str):
    """An engine script, loaded BY PATH once (this file is copied into a home alone, so it cannot import its readers)."""
    mod = _ENGINE_MODS.get(filename)
    if mod is None:
        scripts = engine_scripts()
        if scripts is None:
            raise BoardError("the engine's scripts (ledger_index.py and the other readers) were not found")
        spec = importlib.util.spec_from_file_location("_gitos_board_" + Path(filename).stem.replace("-", "_"), scripts / filename)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ENGINE_MODS[filename] = mod
    return mod


def _fail(errors: list, section: str, e: Exception, ref: "str | None" = None) -> None:
    errors.append(dict({"section": section}, **({"ref": ref} if ref else {}), error=clean(f"{type(e).__name__}: {e}")[:300]))


def _dep(ref, nnn: str) -> str:
    """A `depends_on` entry as `S1` (a slice of this order), `NNN/S1` (another order's), else as written."""
    m = SLICE_REF_RE.fullmatch(str(ref).strip())
    if not m:
        return clean(ref)
    sid = "S" + m.group(2)[1:].lower()      # the letter of `S9b` stays lower-case, as the slice's own id has it
    return sid if m.group(1) == nnn else f"{m.group(1)}/{sid}"


def _listed(value) -> list:
    """A front-matter value that is a list, or one bare string, as a list."""
    return [value] if isinstance(value, str) and value else value if isinstance(value, list) else []


def run_canary() -> None:
    """Run the engine's canary on this home in its own process and keep its finding count in CANARY. The canary is read-only. A
    run that fails, times out or prints something else is kept as `error`, with the last good `total` left in place."""
    scripts, at = engine_scripts(), iso(now_dt())
    try:
        if scripts is None or not (scripts / "canary.py").is_file():
            raise BoardError("the engine's canary.py was not found")
        r = subprocess.run([sys.executable, "-I", str(scripts / "canary.py"), str(home_dir()), "--json"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=CANARY_LIMIT, stdin=subprocess.DEVNULL)
        total = json.loads(r.stdout)["total"]
        if not isinstance(total, int) or isinstance(total, bool):
            raise ValueError("no finding count in its output")
        CANARY.update(total=total, at=at, error=None)
    except subprocess.TimeoutExpired:
        CANARY.update(error=f"the canary did not finish in {CANARY_LIMIT} s")
    except Exception as e:
        CANARY.update(error=clean(f"{type(e).__name__}: {e}")[:200])


def _no_constant(name: str):
    raise ValueError(f"{name} is not JSON")


def _finite_float(text: str) -> float:
    """A JSON number with a fraction or exponent, refused when it overflows (`1e999` reads as infinity, which no page can parse)."""
    x = float(text)
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"{text} is not a finite number")
    return x


PROVIDER_PROCS: dict = {}      # the provider processes running now -> their Windows job (or None), for the board's stop
PROVIDER_LOCK = threading.Lock()


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype, k.CreateJobObjectW.argtypes = wintypes.HANDLE, [ctypes.c_void_p, wintypes.LPCWSTR]
    k.OpenProcess.restype, k.OpenProcess.argtypes = wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def provider_job(p):
    """Windows: a job object holding provider `p`, so that its whole tree can be ended even after `p` itself has exited (a tree
    walk from a dead parent finds nothing). None elsewhere (the provider is a process group leader there), or when it fails."""
    if sys.platform != "win32":
        return None
    try:
        k = _kernel32()
        job, h = k.CreateJobObjectW(None, None), k.OpenProcess(0x0101, False, p.pid)   # SET_QUOTA | TERMINATE
        ok = bool(job and h and k.AssignProcessToJobObject(job, h))
        if h:
            k.CloseHandle(h)
        if not ok and job:
            k.CloseHandle(job)
        return job if ok else None
    except (OSError, AttributeError, ValueError):
        return None


def kill_provider_tree(p, job=None) -> None:
    """End provider `p` and everything it started: its job (Windows; `taskkill /T /F` when it has none) or its process group."""
    try:
        if sys.platform == "win32":
            if job:
                _kernel32().TerminateJobObject(job, 1)
            else:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=5)
        else:
            os.killpg(p.pid, 9)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    with contextlib.suppress(OSError):
        p.kill()


def stop_providers() -> None:
    """The board's stop: every provider still running, and its tree, is ended."""
    with PROVIDER_LOCK:
        running = list(PROVIDER_PROCS.items())
    for p, job in running:
        kill_provider_tree(p, job)


def run_provider(path: Path, home: Path, halt: "threading.Event | None" = None) -> tuple:
    """One provider in its own `python -I -B -X utf8` process (argument 1 the home, working directory the home, no stdin; its own
    process group or job) with a time limit and a cap on what it may print. A timeout, a flood and the board's stop (`halt`
    set, `stop_providers`) end its whole tree, and so does a provider that exits and leaves a child holding its pipes. A pump
    thread owns its stream: the runner never closes one. -> (value, None) or (None, why). A provider is repo code run with
    the user's rights, like any tool in the home; this keeps its crash, hang, flood or garbage out of the board, it is not a sandbox."""
    if halt is not None and halt.is_set():
        return None, "the board is stopping"
    own = {"creationflags": 0x200} if sys.platform == "win32" else {"start_new_session": True}   # CREATE_NEW_PROCESS_GROUP
    try:
        p = subprocess.Popen([sys.executable, "-I", "-B", "-X", "utf8", str(path), str(home)], cwd=str(home),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **own)
    except OSError as e:
        return None, f"could not start: {e}"
    job = provider_job(p)
    with PROVIDER_LOCK:
        PROVIDER_PROCS[p] = job
        stopping = halt is not None and halt.is_set()
    if stopping:
        kill_provider_tree(p, job)
    out, err, flood = bytearray(), bytearray(), []

    def pump_out(stream):
        try:
            while True:
                b = stream.read1(65536)
                if not b:
                    return
                if len(out) + len(b) > PROVIDER_MAX_OUT:
                    flood.append(True)
                    kill_provider_tree(p, job)
                    return
                out.extend(b)
        except (OSError, ValueError):
            return
        finally:
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    def pump_err(stream):
        try:
            while True:
                b = stream.read1(4096)
                if not b:
                    return
                err.extend(b)
                del err[:-2000]
        except (OSError, ValueError):
            return
        finally:
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    threads = [threading.Thread(target=pump_out, args=(p.stdout,), daemon=True),
               threading.Thread(target=pump_err, args=(p.stderr,), daemon=True)]
    for t in threads:
        t.start()
    timed_out = False
    try:
        p.wait(timeout=PROVIDER_LIMIT)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_provider_tree(p, job)
        p.wait()
    finally:
        for wait in (0.2 if timed_out else 2, 2):
            end = time.monotonic() + wait
            for t in threads:
                t.join(max(0.0, end - time.monotonic()))
            if not any(t.is_alive() for t in threads):
                break
            kill_provider_tree(p, job)            # a child of the provider still holds a pipe: it goes too
        with PROVIDER_LOCK:
            PROVIDER_PROCS.pop(p, None)
        if job and not any(t.is_alive() for t in threads):
            with contextlib.suppress(OSError, ValueError):
                _kernel32().CloseHandle(job)
    if timed_out:
        return None, f"did not finish in {PROVIDER_LIMIT} s"
    if halt is not None and halt.is_set():
        return None, "the board is stopping"
    if flood:
        return None, f"printed more than {PROVIDER_MAX_OUT // 1024} KB"
    if p.returncode != 0:
        return None, f"exited {p.returncode}: {clean(bytes(err).decode('utf-8', 'replace'))[-200:]}"
    try:
        return json.loads(bytes(out).decode("utf-8"), parse_constant=_no_constant, parse_float=_finite_float), None
    except (ValueError, RecursionError) as e:
        return None, f"printed no single JSON value ({clean(str(e))[:80]})"


def run_providers(home: "Path | None" = None, halt: "threading.Event | None" = None) -> None:
    """Run every `<board dir>/providers/<name>.py` (concurrently) and replace PROVIDERS whole: each output is `ext[name]`; a
    provider that fails keeps its last good output (when it has one) and says why in `errors`; a removed one disappears."""
    home, prev = home or home_dir(), PROVIDERS["ext"]
    found = [n for n, _ in _plain_files(HERE / "providers", ".py")]
    ext, errors = {}, []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        got = list(pool.map(lambda n: run_provider(HERE / "providers" / f"{n}.py", home, halt), found))
    if halt is not None and halt.is_set():
        return                                       # the board stopped during the run: its results are not state
    for n, (value, why) in zip(found, got):
        if why is None:
            ext[n] = value
            continue
        if n in prev:
            ext[n] = prev[n]
        errors.append({"section": "provider", "ref": n, "error": clean(f"{why}" + ("; showing its last good output" if n in prev else ""))[:300]})
    PROVIDERS.update(ext=ext, errors=errors, n=PROVIDERS["n"] + 1)


def build_orders(home: Path, errors: list) -> dict:
    """The open and parked orders with their slices, the newest resolved ones, and the dependencies orders declare. Read through
    ledger_index (orders) and slice (slice files); a file that cannot be read is an error entry, the rest still show."""
    li, sl = engine("ledger_index.py"), engine("slice.py")
    wo, orders, links = home / "work-orders", [], []
    for nnn, f in sorted(li._orders(wo), key=lambda t: t[0]):
        try:
            info = li._info(f)
            meta = info["meta"]
            o = {"id": nnn, "title": clean(info["title"]), "sev": info["severity"],
                 "status": "parked" if li.is_parked(meta) else "open", "trigger": clean(meta.get("trigger", "")) or None,
                 "evidence": clean(meta.get("evidence", "")), "origin": clean(meta.get("origin", "")),
                 "pending": li.pending_text(meta) or None,
                 "landed": clean(meta.get("landed", "")) or None, "path": f.relative_to(home.parent).as_posix(), "slices": []}
            for d in _listed(meta.get("depends_on")):
                m = re.search(r"\d{3}", str(d))
                if m:
                    links.append({"from": m.group(0), "to": nnn})
            if f.name == "order.md":
                for num, p, m in sl.list_slices(f.parent):
                    name = p.stem.split("-", 1)[1] if "-" in p.stem else p.stem
                    o["slices"].append({"id": f"S{num}", "title": clean(name.replace("-", " ")),
                                        "state": clean(m.get("status") or "proposed"),
                                        "dependsOn": [_dep(d, nnn) for d in _listed(m.get("depends_on"))]})
            orders.append(o)
        except Exception as e:
            _fail(errors, "orders", e, f.relative_to(home).as_posix())
    done = sorted(li._orders(wo / "resolved"), key=lambda t: t[0], reverse=True)
    resolved = []
    for nnn, f in done[:RESOLVED_SHOWN]:
        try:
            info = li._info(f)
            resolved.append({"id": nnn, "title": clean(info["title"]), "sev": info["severity"],
                             "released": li.released(info["meta"]) or None, "path": f.relative_to(home.parent).as_posix()})
        except Exception as e:
            _fail(errors, "orders", e, f.relative_to(home).as_posix())
    parked = sum(1 for o in orders if o["status"] == "parked")
    return {"orders": orders, "links": links, "resolved": resolved, "engine": li._engine_version(home),
            "counts": {"open": len(orders) - parked, "parked": parked, "resolved": len(done)}}


def live_sprints(home: Path) -> frozenset:
    """The sprints whose driver is running now: a named sprint's id from a live claim, "" for a live exclusive sprint."""
    gs, cr = engine("gitos-sprint.py"), engine("compact_restore.py")
    live = {c["sprint"] for _, c, _, _ in gs.all_claims(home) if c and cr.record_alive(c)}
    excl, _ = gs.read_exclusive(home)
    return frozenset(live | ({""} if excl and cr.record_alive(excl) else set()))


def build_sprints(home: Path, cards: list, errors: list) -> list:
    """Each sprint with a log: state (running, closing, stopped, or stale when its log says running and no driver is), the
    orders it touched, its latest records and its open Stop card. Read through sprint_log and the driver's own claim reader."""
    sl, gs = engine("sprint_log.py"), engine("gitos-sprint.py")
    root, live = home / "sprint", live_sprints(home)
    try:
        named = sorted(d.name for d in root.iterdir() if d.is_dir() and sl.valid_id(d.name))
    except OSError:
        named = []
    claims = [(ref, c) for ref, c, _, _ in gs.all_claims(home) if c]
    open_cards = {c["id"] for c in cards if c["status"] != "closed"}
    out = []
    for sid in ([""] if (root / "log.jsonl").is_file() else []) + named:
        try:
            recs, folder = sl.read_records(home, sid), root / sid
            if not recs and sid not in live:
                continue
            refs = [m.group(1) for r in recs for m in [re.search(r"WO-?(\d+)", str(r.get("ref", "")))] if m]
            refs += [ref[3:] for ref, c in claims if c["sprint"] == sid]
            stopped = bool(recs) and recs[-1]["kind"] in ("stop", "error")
            state_ = "stopped" if stopped else (("closing" if (folder / "STOP").is_file() else "running") if sid in live else "stale")
            try:
                card = (folder / "stop-card.id").read_text(encoding="utf-8").strip()
            except OSError:
                card = ""
            out.append({"id": sid, "name": sid or "exclusive", "exclusive": not sid, "state": state_,
                        "orders": list(dict.fromkeys(refs)),
                        "current": next((clean(r["ref"]) for r in reversed(recs) if r.get("ref")), None),
                        "started": recs[0].get("t") if recs else None, "last": recs[-1].get("t") if recs else None,
                        "message": clean(recs[-1].get("msg", "")) if recs else "",
                        "stopCard": card if card in open_cards else None,
                        "recent": [{"t": r.get("t"), "kind": r["kind"], "ref": clean(r.get("ref", "")), "msg": clean(r.get("msg", ""))}
                                   for r in recs[-8:]]})
        except Exception as e:
            _fail(errors, "sprints", e, sid or "exclusive")
    return out


def build_loose_ends(home: Path) -> dict:
    rows = engine("loose_ends.py").rows_of(home)
    return {"count": len(rows), "rows": [{k: clean(r[k]) for k in ("id", "added", "source", "item", "state")} for r in rows]}


def build_records(home: Path, errors: list) -> list:
    """The brain's decision records as metadata only: title (front matter, else the file name), description, date, status,
    superseded-by. The page body is never kept."""
    li, out = engine("ledger_index.py"), []
    folder = home / "brain" / "wiki" / "decisions"
    for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            meta = li.parse_front_matter(f.read_text(encoding="utf-8", errors="replace"))[0]
            out.append({"slug": f.stem, "title": clean(meta.get("title") or f.stem), "description": clean(meta.get("description", "")),
                        "date": clean(meta.get("updated") or meta.get("date") or "") or None, "status": clean(meta.get("status", "")),
                        "supersededBy": clean(meta.get("superseded_by", "")) or None})
        except Exception as e:
            _fail(errors, "records", e, f.name)
    return out


def work_state(home: "Path | None", cards: list, tab: "str | None" = None, missing: str = "") -> dict:
    """What the live state holds beside the board's own cards (WO-153). Each part is read through the engine's reader of that
    file; a part that raises is an entry in `errors` and stays empty, never an exception. `tab` None is the board's own home;
    a hub's repo tab (WO-153/S7) reads only that repo's `home` (None, with `missing` saying why, when it has none) and holds
    none of the board's own views, providers, theme or canary, and only the actions asked on that tab."""
    errors: list = []
    out = {"orders": [], "links": [], "resolved": [], "engine": "", "counts": {"open": 0, "parked": 0, "resolved": 0},
           "sprints": [], "looseEnds": {"count": 0, "rows": []}, "records": [], "errors": errors,
           "canary": {"total": CANARY["total"], "at": CANARY["at"]}, "actions": [], "actionsDone": [], "held": [], "approved": [],
           "actionProblems": []}
    if tab is None:
        out.update(views=repo_views(), theme=theme_version(), ext=dict(PROVIDERS["ext"]))
        errors.extend(PROVIDERS["errors"])
    else:
        out.update(views=[], theme=None, ext={}, canary={"total": None, "at": None})
    acts: list = []
    try:
        acts = acts_of(read_actions(out["actionProblems"]), tab)
        out.update(action_view(acts))
    except Exception as e:
        _fail(errors, "actions", e)
    if tab is None and CANARY["error"]:
        errors.append({"section": "canary", "error": CANARY["error"]})
    if home is None:
        out["repoError"] = missing
        errors.append({"section": "home", "error": missing})
        return out
    if engine_scripts() is None:
        errors.append({"section": "engine", "error": "the engine's scripts (ledger_index.py and the other readers) were not found"})
        return out
    for name, fn in (("orders", lambda: build_orders(home, errors)), ("sprints", lambda: {"sprints": build_sprints(home, cards, errors)}),
                     ("looseEnds", lambda: {"looseEnds": build_loose_ends(home)}), ("records", lambda: {"records": build_records(home, errors)})):
        try:
            out.update(fn())
        except Exception as e:
            _fail(errors, name, e)
    for o in out["orders"]:
        o["hash"] = order_hash(o)
    out["held"], out["approved"] = action_flags(acts, {o["id"] for o in out["orders"]})
    return out


def repo_counts(st: dict, tab: str) -> dict:
    """What the hub's `all` view shows of one repo, from that repo's own state: counts only. The statuses are the page's (store.js
    derive): an order is parked, held, awaiting acceptance (landed, or every slice landed), or by its slices in progress, ready
    (a slice can start) or waiting; one with no slice waits on an open order it depends on, else it is ready."""
    orders = {o["id"]: o for o in st.get("orders", [])}
    held = set(st.get("held", []))
    n = {"open": 0, "active": 0, "ready": 0, "waiting": 0, "parked": 0}
    for oid, o in orders.items():
        if o["status"] == "parked":
            n["parked"] += 1
            continue
        n["open"] += 1
        sl = {x["id"]: x for x in o["slices"]}
        if oid in held or o.get("landed") or (sl and all(x["state"] == "landed" for x in sl.values())):
            continue
        if sl:
            states = [("ready" if all(sl.get(d, {}).get("state") == "landed" for d in x["dependsOn"]) else "waiting")
                      if x["state"] == "proposed" else x["state"] for x in sl.values()]
            k = "active" if any(t in ("in-progress", "implemented") for t in states) else "ready" if "ready" in states else "waiting"
        else:
            k = "waiting" if any(l["to"] == oid and l["from"] in orders for l in st.get("links", [])) else "ready"
        n[k] += 1
    return dict(n, sprints=sum(1 for x in st.get("sprints", []) if x["state"] in ("running", "closing")),
                needs=sum(1 for c in st.get("cards", []) if c["tab"] == tab and c["status"] == "needs"),
                errors=len(st.get("errors", [])))


def repo_row(tab: str, root: Path, kid: "Live | None") -> dict:
    """One repo of the hub's `all` view: its tab and name, and (from its own state, which is built from its own home only) its
    counts, or the reason its home cannot be read. A repo that fails says so in its row; the others are built as usual."""
    row = {"tab": tab, "name": clean(root.name or str(root))[:60]}
    if kid is None:
        return row
    try:
        ver, text = kid.cur                      # the kid's last state, read without waiting: its own watcher builds it
        if not ver:
            return dict(row, ok=False, error="reading")
        st = json.loads(text)
        if st.get("repoError"):
            return dict(row, ok=False, error=clean(st["repoError"])[:300])
        return dict(row, ok=True, error=None, **repo_counts(st, tab))
    except Exception as e:
        return dict(row, ok=False, error=clean(f"{type(e).__name__}: {e}")[:300])


def build_state(live: "Live | None" = None) -> dict:
    """The full live state: the board's own state (cards, notes, tabs, problems; unchanged) plus the ledger half of the board's own
    home. On a hub (`hub`) it also holds `repos`, one row per routed repo with counts only (WO-153/S7); a repo's orders are in its
    own tab's state (build_tab_state), never here."""
    s = state()
    s.update(work_state(home_dir(), s["cards"]))
    hide_controls(s)
    s["problems"] = s["problems"] + s.pop("actionProblems")
    rt = routes()
    s.update(hub=bool(rt), tab=None, repos=[repo_row(t, rt[t], live.kid(t) if live is not None else None) for t in tabs() if t in rt])
    return s


def build_tab_state(tab: str) -> dict:
    """The live state of one routed repo's tab: the board's cards and notes (one board, one owner), and the ledger half built from
    that repo's home only (`routes()[tab]`); nothing of the board's own home, views, providers or canary. A repo whose folder or
    home is gone is a state with `repoError` and no orders."""
    s = state()
    root = routes().get(tab)
    home = repo_home(root) if root is not None else None
    if root is None:
        why = f"{tab} is not a tab this board routes to a repo"
    elif not root.is_dir():
        why = f"the repo folder {root} cannot be read"
    else:
        why = f"{root} has no gitos home (.gitos, outputs/debug, .pipeline or docs/agents)"
    s.update(work_state(home, s["cards"], tab=tab, missing=why))
    hide_controls(s)
    s["problems"] = s["problems"] + s.pop("actionProblems")
    rt = routes()
    s.update(hub=True, tab=tab, name=clean(root.name if root is not None else tab),
             where=(home.relative_to(root).as_posix() if home is not None and root is not None else ""),
             repos=[{"tab": t, "name": clean(rt[t].name or str(rt[t]))[:60]} for t in tabs() if t in rt])
    return s


def _entries(path: Path, out: list) -> list:
    """Add (path, mtime, size) of each entry of `path` to `out`; -> its sub-directories. A missing folder adds nothing."""
    subs = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    st = e.stat()
                except OSError:
                    continue
                out.append((e.path, st.st_mtime_ns, st.st_size))
                if e.is_dir():
                    subs.append(Path(e.path))
    except OSError:
        pass
    return subs


def _home_signature(home: Path, out: list) -> tuple:
    """Add (path, mtime, size) of what a ledger home's state is built from to `out` (the home, its work-orders and their slices,
    resolved, the sprint folders and claims, the brain's decision pages); -> which sprint drivers are alive."""
    for d in (home, home / "work-orders" / "resolved", home / "sprint" / "claims", home / "brain" / "wiki" / "decisions"):
        _entries(d, out)
    for d in _entries(home / "work-orders", out):
        if d.name != "resolved":
            _entries(d, out)
            _entries(d / "slices", out)
    for d in _entries(home / "sprint", out):
        _entries(d, out)
    try:
        return tuple(sorted(live_sprints(home))) if (home / "sprint").is_dir() else ()
    except Exception:
        return ("?",)


def tab_signature(tab: str) -> tuple:
    """What one repo tab's state is built from: the board's cards and data, and that repo's home only."""
    out: list = []
    for d in (HERE, DATA, CARDS, HERE / "inbox" / "rejected"):
        _entries(d, out)
    root = routes().get(tab)
    home = repo_home(root) if root is not None else None
    alive = _home_signature(home, out) if home is not None else ()
    return tuple(out), alive, str(home or "")


def hub_signature(live: "Live") -> tuple:
    """watch_signature(), and on a hub the version each repo tab's state is at (so a change in one repo's home changes the hub's
    `all` view). It reads each tab's last version without waiting (a tab's own watcher builds it), so a repo whose home stalls
    never holds the hub."""
    sig = watch_signature()
    rt = routes()
    return sig + (tuple((t, live.kid(t).cur[0]) for t in sorted(rt)),) if rt else sig


def watch_signature() -> tuple:
    """Everything the live state is built from, as (path, mtime, size) of the files and folders it reads: the work-orders and
    their slices, INDEX and loose ends, the sprint folders, the brain's decision pages, the board's cards and data; plus which
    sprint drivers are alive, how many provider runs have finished and what the last canary run said. A change anywhere in it is a reason to build again (the new state may still equal the old one)."""
    out: list = []
    for d in (HERE, DATA, CARDS, HERE / "views", HERE / "providers", HERE / "inbox" / "rejected"):
        _entries(d, out)
    alive = _home_signature(home_dir(), out)
    return tuple(out), alive, PROVIDERS["n"], tuple(CANARY.values())


class Live:
    """The live state of this board, shared by every request and stream: built once per change, by one watcher thread (or by a
    `/api/state` request that finds the files changed since the last build). `version` is `<boot>.<n>`, bumped only when the
    state itself differs from the last build (its `now` aside), and never repeated by a restarted server."""

    def __init__(self, build=None, signature=None, every: "float | None" = None, root: "Live | None" = None):
        self.root = root or self                     # a hub's repo tab is a Live of its own under the hub's (see kid)
        self.build = build or (lambda: build_state(self))
        self.signature = signature or (lambda: hub_signature(self))
        self.every = every or WATCH_EVERY
        self.lock, self.sig, self.cmp = threading.Lock(), None, None
        self.cur = ("", "")                          # (version, the state as JSON text): replaced whole, read without the lock
        self.boot, self.n = (root.boot if root else secrets.token_hex(3)), 0
        self.halt, self.thread, self.canary, self.provider = threading.Event(), None, None, None
        self.slots, self.streams = threading.Lock(), 0
        self.kids, self.kids_lock = {}, threading.Lock()

    def kid(self, tab: str) -> "Live | None":
        """The live state of one routed repo's tab (a hub), built from that repo's home only and started on first use; None for a
        tab this board does not route. Every kid shares this one's boot, stream slots and version counter, so a version names
        one state of one tab and the 16-stream cap counts across the hub."""
        if self.root is not self or tab not in routes():
            return None
        with self.kids_lock:
            k = self.kids.get(tab)
            if k is None:
                k = self.kids[tab] = Live(build=lambda t=tab: build_tab_state(t), signature=lambda t=tab: tab_signature(t),
                                          every=self.every, root=self)
                if not self.halt.is_set():
                    k.start()
            return k

    def bump(self) -> int:
        """The next version number: one counter for the hub and all its tabs."""
        with self.root.slots:
            self.root.n += 1
            return self.root.n

    def refresh(self) -> tuple:
        """Build when the watched files changed (and the first time). -> (version, JSON text). A build that raises keeps the
        last state with an error entry and is tried again at the next look."""
        with self.lock:
            sig = self.signature()
            if sig == self.sig and self.cur[0]:
                return self.cur
            try:
                body, failed = self.build(), False
            except Exception as e:
                body, failed = json.loads(self.cur[1]) if self.cur[1] else {}, True
                body["errors"] = [x for x in body.get("errors", []) if x.get("section") != "state"]
                _fail(body["errors"], "state", e)
            body.pop("version", None)
            cmp = json.dumps({k: v for k, v in body.items() if k != "now"}, ensure_ascii=False)
            if cmp != self.cmp or not self.cur[0]:
                self.cmp = cmp
                body["version"] = f"{self.boot}.{self.bump()}"
                self.cur = (body["version"], json.dumps(body, ensure_ascii=False))
            self.sig = None if failed else sig
            return self.cur

    def start(self) -> None:
        with self.slots:
            if self.thread is None:
                self.thread = threading.Thread(target=self._watch, name="board-watcher", daemon=True)
                self.thread.start()
                if self.root is not self:
                    return                           # a repo tab has no canary and no providers: those are the board's own
                if CANARY_ON:
                    self.canary = threading.Thread(target=self._canary, name="board-canary", daemon=True)
                    self.canary.start()
                self.provider = threading.Thread(target=self._provide, name="board-providers", daemon=True)
                self.provider.start()

    def _watch(self) -> None:
        while not self.halt.wait(self.every):
            try:
                self.refresh()
            except Exception as e:                   # one bad look never ends the watcher; the log says why
                print(f"watcher: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def _canary(self) -> None:
        """The canary, off the watcher's thread (a run takes seconds): after a short wait, then every CANARY_EVERY seconds."""
        wait = CANARY_FIRST
        while not self.halt.wait(wait):
            run_canary()
            wait = CANARY_EVERY

    def _provide(self) -> None:
        """The providers, off the watcher's thread (a run takes up to PROVIDER_LIMIT s): run them once the watcher has built a
        state, and again whenever the files it watches have changed, but not within PROVIDER_EVERY seconds of the last run."""
        seen, last = None, -PROVIDER_EVERY
        while not self.halt.wait(self.every):
            sig = self.sig
            key = sig[:2] if isinstance(sig, tuple) else None     # the files and the live sprints, not the runs' own count
            if key is None or key == seen or time.monotonic() - last < PROVIDER_EVERY:
                continue
            seen, last = key, time.monotonic()
            try:
                run_providers(halt=self.halt)
            except Exception as e:                   # one bad pass never ends the thread; the log says why
                print(f"providers: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def stop(self) -> None:
        self.halt.set()
        for k in list(self.kids.values()):
            k.halt.set()
        if self.root is not self:
            return
        stop_providers()                             # a provider still running is ended with its tree

    def ready(self, wait: "float | None" = None) -> bool:
        """True once this Live holds a state, and on a hub once each of its tabs does. The watchers build them: wait for that for at
        most `wait` s (FIRST_WAIT) without taking any lock (a repo whose home stalls holds its own). A tab with no state by then is a
        "reading" row of the hub, not a reason to hold the hub. A Live with no watcher builds its first state here."""
        end = time.monotonic() + (FIRST_WAIT if wait is None else wait)
        for k in ([self] + [self.kid(t) for t in sorted(routes())] if self.root is self else [self]):
            if k is None or k.cur[0]:
                continue
            if k.thread is None:
                k.refresh()
            while not k.cur[0] and time.monotonic() < end and not k.halt.wait(0.05):
                pass
        return bool(self.cur[0])

    def take_slot(self) -> bool:
        if self.root is not self:
            return self.root.take_slot()             # one cap for the hub, whatever tab a stream is on
        with self.slots:
            if self.streams >= STREAM_MAX:
                return False
            self.streams += 1
            return True

    def free_slot(self) -> None:
        if self.root is not self:
            return self.root.free_slot()
        with self.slots:
            self.streams -= 1


# ------------------------------------------------------------------ the page (WO-153/S3)
# The page is the app in <board dir>/ui/ (index.html, app.js and the modules it imports, the style sheets). This file serves
# them as static files from 'self' and fills three placeholders in index.html: the title, the page token and the nonce of the
# script tags. Nothing else is served from there: a name is matched on the raw path (no decoding, no `..`).
UI_FILE_RE = re.compile(r"((?:views/)?[a-z0-9-]{1,40})\.(js|css)")
UI_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}
UI_MISSING = ("<!doctype html><meta charset=utf-8><title>Owner board</title><body>"
              "<h1>The board's page files are missing</h1><p>This board.py expects its page in a <code>ui/</code> folder beside it, "
              "and there is none. Run the engine's upgrade (<code>scaffold.py</code>) so it copies <code>ui/</code> next to "
              "board.py.</p></body>")


def page_csp(nonce: str) -> str:
    """The board page's policy: scripts and styles only from this origin (modules need 'self'; the nonce is on the entry tags),
    no inline style, a fetch only back to this origin, no frame at all, never framed itself."""
    return (f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def ui_file(rel: str) -> "bytes | None":
    """A file of ui/ named by the raw path after `/ui/`: only `name.js|css` or `views/name.js|css` of [a-z0-9-]; else None."""
    m = UI_FILE_RE.fullmatch(rel)
    if not m:
        return None
    folder, _, name = f"{m.group(1)}.{m.group(2)}".rpartition("/")
    folder = HERE / "ui" / folder if folder else HERE / "ui"
    try:
        if name not in os.listdir(folder) or not (folder / name).is_file():   # a device name (nul.js, con.css) is no file of ui/
            return None
        return (folder / name).read_bytes()
    except OSError:
        return None


def repo_file(rel: str) -> "tuple[bytes, str] | None":
    """A file of the repo's own `views/` named by the raw path after `/views/`: `<name>.js` of a listed view, or `theme.css`;
    else None (no decoding, no `..`, no sub-folder, no other file). -> (bytes, content type)."""
    if rel == "theme.css":
        if theme_version() is None:
            return None
        name, ctype = "theme.css", UI_TYPES["css"]
    else:
        m = re.fullmatch(r"([a-z0-9-]{1,32})\.js", rel)
        if not m or m.group(1) not in [n for n, _ in _plain_files(HERE / "views", ".js")]:
            return None
        name, ctype = rel, UI_TYPES["js"]
    try:
        return (HERE / "views" / name).read_bytes(), ctype
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    token = ""
    host = DEFAULT_HOST
    port = 0
    board_id = ""
    live = None
    timeout = 10
    server_version = "gitos-board"
    sys_version = ""

    def log_message(self, *a):
        pass

    def _names(self) -> tuple:
        """The Host values this server answers to: the address it is bound to, and `localhost` only for 127.0.0.1."""
        return (f"{self.host}:{self.port}",) + ((f"localhost:{self.port}",) if self.host == DEFAULT_HOST else ())

    def _host_ok(self) -> bool:
        return self.headers.get("Host") in self._names()

    def _send(self, code: int, body, ctype: str = "application/json; charset=utf-8", nonce: str = "none"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", page_csp(nonce))
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
            try:
                page = (HERE / "ui" / "index.html").read_text(encoding="utf-8")
            except OSError:
                return self._send(503, UI_MISSING, "text/html; charset=utf-8", nonce=nonce)
            page = page.replace("__TITLE__", html.escape("Owner board · " + home_dir().parent.name))                        .replace("__TOKEN__", self.token).replace("__NONCE__", nonce)
            return self._send(200, page, "text/html; charset=utf-8", nonce=nonce)
        if path.startswith("/ui/"):
            m = UI_FILE_RE.fullmatch(path[len("/ui/"):])
            data = ui_file(path[len("/ui/"):])
            if data is None:
                return self._err(404, "not found")
            return self._send(200, data, UI_TYPES[m.group(2)])
        if path == "/api/state":
            live = self._live()
            if live is None:
                return None
            live.ready()                                 # the first states, bounded; then the answer is the state as of now
            return self._send(200, live.refresh()[1])
        if path == "/api/events":
            return self._events()
        if path.startswith("/views/"):
            got = repo_file(path[len("/views/"):])
            if got is None:
                return self._err(404, "not found")
            return self._send(200, got[0], got[1])
        if path == "/api/identity":
            return self._send(200, json.dumps({"board_id": self.board_id, "home": str(home_dir())}))
        return self._err(404, "not found")

    def _live(self) -> "Live | None":
        """The live state this request names: the board's own, or with `?tab=T` (a hub) the state of the repo T is routed to,
        built from that repo's home only. T is never a path: it must be a tab `routes()` lists. Answers 400 or 404 itself and
        returns None when it names none."""
        q = self.path.partition("?")[2]
        want = parse_qs(q, keep_blank_values=True).get("tab") if q else None
        if want is None:
            return self.live
        if len(want) != 1 or not TAB_RE.fullmatch(want[0]):
            self._err(400, "tab must be one tab name")
            return None
        got = self.live.kid(want[0])
        if got is None:
            self._err(404, "no such repo tab")
        return got

    def _events(self):
        """The live stream (server-sent events): a `state` event with the version as its id on connect (unless the client's
        Last-Event-ID is already that version) and on each change, a comment every HEARTBEAT seconds of quiet. The stream waits
        on its own socket in STREAM_TICK turns, which both notices a closed tab and replaces the 10 s timeout every other
        request has; at most STREAM_MAX are open."""
        live = self._live()
        if live is None:
            return None
        if not live.ready():                             # the first state first: a slot is never held while a repo's home stalls
            return self._err(503, "state not ready")
        if not live.take_slot():
            return self._err(503, "too many open streams")
        try:
            sent, quiet = self.headers.get("Last-Event-ID") or "", time.monotonic()
            self.send_response(200)
            for k, v in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"),
                         ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"), ("X-Frame-Options", "DENY"),
                         ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")):
                self.send_header(k, v)
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(STREAM_TICK)
            self.wfile.write(b"retry: 3000\n\n")
            while not live.halt.is_set():
                version, text = live.cur
                if version != sent:
                    self.wfile.write(f"id: {version}\nevent: state\ndata: {text}\n\n".encode("utf-8"))
                    sent, quiet = version, time.monotonic()
                elif time.monotonic() - quiet >= HEARTBEAT:
                    self.wfile.write(b": heartbeat\n\n")
                    quiet = time.monotonic()
                try:
                    if not self.connection.recv(1):      # the client sends nothing after its request: empty means it left
                        break
                except socket.timeout:
                    pass
        except OSError:                                  # a reset, an abort or a send that timed out: the client is gone
            pass
        finally:
            live.free_slot()

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
        if self.headers.get("Origin") not in [f"http://{n}" for n in self._names()]:
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
        if path == "/api/action":
            try:
                return self._action(body, client)
            except BoardError as e:
                return self._err(503, str(e))
        if path == "/api/note":
            note, tab = body.get("note"), body.get("tab", BASE_TABS[0])
            if not isinstance(note, str) or not note.strip():
                return self._err(400, "empty note")
            if tab not in tabs():
                return self._err(400, "not one of the board's tabs")
            try:
                append_jsonl("notes.jsonl", dict({"note": note.strip()[:MAX_NOTE], "tab": tab, "at": iso(now_dt()),
                                                  "via": "board"}, **client))
            except BoardError as e:
                return self._err(503, str(e))
            return self._send(200, '{"ok":true}')
        return self._err(404, "not found")

    def _action(self, body: dict, client: dict):
        """One owner action: checked against the live state, then appended to data/actions.jsonl. No work-order file is touched."""
        kind, order = body.get("kind"), body.get("order")
        if kind not in ACTION_KINDS:
            return self._err(400, "not an action the board knows")
        if not isinstance(order, str) or not ORDER_ID_RE.fullmatch(order):
            return self._err(404, "no such order")
        tab = body.get("tab")
        if tab is not None and (not isinstance(tab, str) or tab not in routes()):
            return self._err(404, "no such repo tab")
        o = next((x for x in json.loads(self.live.kid(tab).refresh()[1] if tab else self.live.refresh()[1]).get("orders", [])
                  if x.get("id") == order), None)
        if o is None:
            return self._err(404, "no such order")
        value = body.get("value")
        if kind == "severity":
            if value not in ACTION_SEVERITY:
                return self._err(400, "not a severity")
        elif kind in ("park", "note"):
            if not isinstance(value, str) or not value.strip():
                return self._err(400, "a park or a note needs text")
            value = value.strip()[:MAX_NOTE]
        elif value is not None:
            return self._err(400, "this action takes no value")
        if kind == "park" and o.get("status") != "open":
            return self._err(409, "the order is not open")
        if kind == "unpark" and o.get("status") != "parked":
            return self._err(409, "the order is not parked")
        version, seen = body.get("version"), body.get("order_hash")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version) or not isinstance(seen, str) or not HASH16_RE.fullmatch(seen):
            return self._err(400, "the action must name the state the owner saw")
        with file_lock():
            if sum(1 for a in acts_of(read_actions([]), tab) if not a["closed"]) >= MAX_OPEN_ACTIONS:
                return self._err(429, "too many open actions; the orchestrator has to close some")
            dt = now_dt()
            aid = dt.strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(2)
            append_jsonl("actions.jsonl", dict({"id": aid, "order": order, "kind": kind, "value": value, "version": version,
                                                "hash": seen, "stale": not hmac.compare_digest(seen, str(o.get("hash"))),
                                                "at": iso(dt), "via": "board"}, **({"tab": tab} if tab else {}), **client))
        return self._send(200, json.dumps({"ok": True, "id": aid}))

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

    def __init__(self, address, handler):
        self.live = handler.live                  # the live state its requests share (see Live)
        super().__init__(address, handler)

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)  # skip HTTPServer's getfqdn(), which can stall for seconds
        self.server_name, self.server_port = self.server_address[:2]

    def serve_forever(self, poll_interval=0.5):
        self.live.start()
        super().serve_forever(poll_interval)

    def server_close(self):
        self.live.stop()                          # the open streams end at their next turn
        super().server_close()


def make_server(cfg: dict) -> Server:
    handler = type("BoardHandler", (Handler,), {"token": secrets.token_urlsafe(24), "host": host_of(cfg),
                                                "port": cfg["port"], "board_id": cfg["board_id"], "live": Live()})
    return Server((host_of(cfg), cfg["port"]), handler)


def serve() -> int:
    cfg = load_config()
    srv = make_server(cfg)
    write_json(DATA / "server.json", {"pid": os.getpid(), "port": cfg["port"], "started": iso(now_dt())})
    print(f"owner board at {url(cfg)} (Ctrl+C to stop)", flush=True)
    threading.Thread(target=maintain, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


# ------------------------------------------------------------------ ensure
def identity(host: str, port: int, timeout: float = 1.5) -> "dict | None":
    req = urllib.request.Request(f"http://{host}:{port}/api/identity", headers={"Host": f"{host}:{port}"})
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


def cmd_ensure(tab: "str | None" = None) -> int:
    """Start this home's board when it is not answering; never stops anything. Prints one line (that tab's counts, with
    --tab), and a Docker warning on stderr."""
    cfg = load_config()
    host, port = host_of(cfg), cfg["port"]
    ident = identity(host, port)
    if ident is None and not port_free(port, host):
        time.sleep(0.5)                      # a board that is still starting answers in a moment
        ident = identity(host, port)
    if ident is None:
        if not port_free(port, host):
            print(f"board: port {cfg['port']} is held by another program; the board was not started "
                  f"(free the port, or give this home a new port in {CONFIG})")
            return 1
        start_detached()
        deadline = time.time() + 15
        while time.time() < deadline and not is_mine(ident, cfg):
            time.sleep(0.2)
            ident = identity(host, port)
        if not is_mine(ident, cfg):
            print(f"board: did not start on port {cfg['port']}; see {DATA / 'serve.log'}")
            return 1
    elif not is_mine(ident, cfg):
        print(f"board: port {cfg['port']} answers for another board (not this home's board_id); "
              f"this board was not started")
        return 1
    c = counts(tab)
    line = (f"board: {url(cfg, tab)} · {c['open']} open · {c['new_answers']} new answers · {c['new_notes']} new notes")
    if c["new_actions"]:
        line += f" · {c['new_actions']} new action{'s' if c['new_actions'] != 1 else ''}"
    if c["acted"]:
        line += f" · {len(c['acted'])} waiting to be acted on"
    if c["problems"]:
        line += f" · {len(c['problems'])} problem(s) in its files"
    print(line)
    warning = docker_warning(cfg)
    if warning:
        print(warning, file=sys.stderr)
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


TAB_COMMANDS = ("ensure", "add-decision", "add-plan", "add-send", "list", "answer-for", "close", "notes", "summary", "actions", "action-done")


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
        tab = take(rest, "--tab")
        if tab is not None and cmd not in TAB_COMMANDS:
            raise BoardError(f"{cmd} takes no --tab")
        if tab is not None and tab not in tabs():
            raise BoardError(f"tab must be one of {list(tabs())}")
        if cmd == "serve" and not rest:
            return serve()
        if cmd == "ensure" and not rest:
            return cmd_ensure(tab)
        if cmd == "url" and not rest:
            print(url())
            return 0
        if cmd == "register-tab":
            repo = take(rest, "--repo")
            if len(rest) != 1 or not repo:
                raise BoardError("usage: register-tab TAB --repo PATH")
            print(register_tab(rest[0], repo))
            return 0
        if cmd == "add-decision":
            details, tech, old = take(rest, "--details"), take(rest, "--tech"), take(rest, "--replaces")
            tab = tab or BASE_TABS[0]
            extra = card_flags(rest)
            no_flags(rest)
            if len(rest) < 3:
                raise BoardError("usage: add-decision TITLE BODY value=Label ...")
            if old:
                prev = card_by_id(old)
                if prev is None or prev["status"] == "closed" or prev["tab"] != tab:
                    raise BoardError(f"--replaces: {old} is not an open card of tab {tab}; nothing was written")
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
            card = new_card(tab or BASE_TABS[0], "plan", rest[1],
                            "Nothing changes until you pick Apply it, and then only exactly this plan.",
                            [{"value": "apply", "label": "Apply it"},
                             {"value": "change", "label": "Change it (say how in the note)"},
                             {"value": "skip", "label": "Skip"}],
                            details=data.decode("utf-8"), extra=extra,
                            tech=text_of(tech) if tech else "")
            replaced = replace_older(card)
            print(f"card {card['id']} added to {card['tab']}: {card['title']}")
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
            card = new_card(tab or ("email" if "email" in tabs() else BASE_TABS[0]), "send", rest[1], body,
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
            ingest_inbox()
            s = state()
            for c in s["cards"]:
                if tab not in (None, c["tab"]) or (rest and c["status"] == "closed"):
                    continue
                print_card_line(c)
                agent_read(c)
            for p in s["problems"]:
                print(f"problem: {clean(p)}")
            return 0
        if cmd == "answer-for" and len(rest) == 1:
            got = answer_for(rest[0], tab)
            print(json.dumps(got, ensure_ascii=True) if got else "null")
            return 0 if got else 1
        if cmd == "summary" and not rest:
            print(json.dumps(summary(tab), ensure_ascii=True))
            return 0
        if cmd == "actions":
            return cmd_actions(rest, tab)
        if cmd == "action-done":
            return cmd_action_done(rest, tab)
        if cmd == "close" and len(rest) == 2:
            if tab and (card_by_id(rest[0]) or {}).get("tab") != tab:
                raise BoardError(f"no card {rest[0]} in tab {tab}")
            consume(rest[0], rest[1])
            print(f"closed {rest[0]}")
            return 0
        if cmd == "notes" and not rest:
            problems: list = []
            for n in read_jsonl("notes.jsonl", ("note",), problems):
                if tab in (None, note_tab(n)):
                    print(f"{n['at']}  {clean(n['note'])}")
            for p in problems:
                print(f"problem: {clean(p)}")
            set_mark(tab)
            return 0
    except BoardError as e:
        print(f"board: {e}", file=sys.stderr)
        return 2
    print(__doc__)
    return 2


def follow_sprint() -> None:
    """Resolve the board directory the way a named sprint's session needs it (see sprint_board_dir): called once when the module is
    loaded, so the CLI and a tool that loads this file by path and calls approved() / claim() reach the same board. An explicit
    set_dir() afterwards still wins."""
    target = sprint_board_dir()
    if target is not None and not same_path(target, HERE):
        set_dir(target)


try:
    follow_sprint()
except BoardError as _refusal:
    if __name__ != "__main__":
        raise
    print(f"board: {_refusal}", file=sys.stderr)
    raise SystemExit(2)

if __name__ == "__main__":
    raise SystemExit(main())
