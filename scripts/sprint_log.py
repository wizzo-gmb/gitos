#!/usr/bin/env python3
"""sprint_log.py - the sprint log of one gitos home. Standard library only.

    python sprint_log.py add KIND MESSAGE [--ref WO-NNN] [--session ID]    append one line to <home>/sprint/log.jsonl

The log is append-only JSON lines `{"t", "kind", "ref", "msg"}` (plus `session` where a session id is known); KIND is one of
start, done, note, stop, rotate, error, and a message is cut at 140 characters. The board's Sprints view
reads the log; no page is written.

The home comes from GITOS_SPRINT_HOME (the sprint driver sets it, so the orchestrator may call this from any directory,
a worktree included), else from the working directory by the router's home detection. A GITOS_SPRINT_HOME that is not a gitos
home (no `work-orders/` folder, no `INDEX.md` beside a `sprint/` folder: a repo root, say) is refused, and nothing is written.

A named sprint (GITOS_SPRINT_ID, set by the driver beside GITOS_SPRINT_HOME) has its own log `<home>/sprint/<id>/log.jsonl`
and archive `<home>/sprint/<id>/archive/`; the commands above act on
that sprint's. Without the id they act on the exclusive sprint's paths, as before.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compact_restore  # noqa: E402  (the router's home list)

KINDS = ("start", "done", "note", "stop", "rotate", "error")
MSG_MAX = 140
DENIED_TRIES = 10                        # attempts at a log file another process holds open (a Windows sharing violation)
LOG_REL = Path("sprint") / "log.jsonl"
ARCHIVE_REL = Path("sprint") / "archive"
HOME_ENV = "GITOS_SPRINT_HOME"
ID_ENV = compact_restore.SPRINT_ID_ENV


def locate(start) -> "tuple[Path, Path] | None":
    """(home, repo root) for a directory by the router's home detection, or None. The walk stops at the repo root."""
    here = Path(start).resolve()
    for directory in (here, *here.parents):
        for rel in compact_restore.HOMES:
            if (directory / rel).is_dir():
                return directory / rel, directory
        if (directory / ".git").exists():
            return None
    return None


def is_gitos_home(path) -> bool:
    """Whether `path` is a gitos home (`.gitos/` or a legacy home): it holds `work-orders/`, or an `INDEX.md` beside a `sprint/`
    folder. A repo root (or any other folder) is not one: a log must never be written into it."""
    p = Path(path)
    return (p / "work-orders").is_dir() or ((p / "INDEX.md").is_file() and (p / "sprint").is_dir())


def valid_id(sid) -> bool:
    return (isinstance(sid, str) and bool(compact_restore.SPRINT_ID_RE.fullmatch(sid))
            and sid not in compact_restore.SPRINT_RESERVED_IDS)


def sprint_folder(home: Path, sid: str = "") -> Path:
    """`<home>/sprint/<id>/` for a named sprint, `<home>/sprint/` for the exclusive one."""
    return compact_restore.sprint_dir(home, sid)


def log_path(home: Path, sid: str = "") -> Path:
    return sprint_folder(home, sid) / LOG_REL.name


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clean_msg(msg) -> str:
    """One line, cut at MSG_MAX characters."""
    return " ".join(str(msg).split())[:MSG_MAX]


def retry_denied(fn):
    """`fn()`, again (bounded: `DENIED_TRIES`, 20 to 150 ms apart) while it raises PermissionError: on Windows a file another process
    holds open (the board serving the page, a reader of the log) is denied to a replace, a move or an open for a moment."""
    for attempt in range(DENIED_TRIES):
        try:
            return fn()
        except PermissionError:
            if attempt == DENIED_TRIES - 1:
                raise
            time.sleep(min(0.02 * (attempt + 1), 0.15) + random.uniform(0, 0.02))


def add_record(home: Path, kind: str, msg, ref: "str | None" = None, session: "str | None" = None,
               when: "str | None" = None, sid: str = "") -> dict:
    """Append one line to the log (creating `sprint/`), return the record. ValueError for a kind outside KINDS. `sid` is the
    named sprint whose log it is ("" for the exclusive sprint's)."""
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}, not {kind!r}")
    rec = {"t": when or now_iso(), "kind": kind, "ref": ref or "", "msg": clean_msg(msg)}
    if session:
        rec["session"] = session
    path = log_path(home, sid) if sid else Path(home) / LOG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with retry_denied(lambda: open(path, "a", encoding="utf-8", newline="\n")) as fh:
        fh.write(line)
    return rec


def read_records(home: Path, sid: str = "") -> list:
    """The log's records in file order; a line that is not a JSON object is skipped."""
    path = log_path(home, sid) if sid else Path(home) / LOG_REL
    out = []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind") in KINDS:
            out.append(rec)
    return out


def archive_previous(home: Path, stamp: "str | None" = None, sid: str = "") -> "Path | None":
    """Move a non-empty log to `sprint/archive/<stamp>.jsonl` (`sprint/<id>/archive/` for a named sprint). -> the new path, or
    None when there was nothing to move."""
    log = log_path(home, sid) if sid else Path(home) / LOG_REL
    if not log.is_file() or log.stat().st_size == 0:
        return None
    dest = (sprint_folder(home, sid) / ARCHIVE_REL.name if sid else Path(home) / ARCHIVE_REL) / f"{stamp or datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while dest.exists():
        dest = dest.with_name(f"{dest.stem.split('+')[0]}+{n}.jsonl")
        n += 1
    retry_denied(lambda: os.replace(log, dest))
    return dest


def open_orders(home: Path) -> list:
    """The open (not parked) order numbers, from the ledger's own reader."""
    try:
        import ledger_index
        return [row.split("|")[1].strip() for row in ledger_index.open_rows(Path(home))]
    except Exception:
        return []


def open_order_marks(home: Path) -> dict:
    """{order number: its front matter `sprint:` value, lower case, "" when it has none} of the open (not parked) orders, read
    with the ledger's own reader. An unreadable ledger gives {}."""
    try:
        import ledger_index as li
        out = {}
        for nnn, f in li._orders(Path(home) / "work-orders"):
            meta = li._info(f)["meta"]
            if not li.is_parked(meta):
                out[int(nnn)] = str(meta.get("sprint", "")).strip().lower()
        return out
    except Exception:
        return {}


def sprint_mark_values(home: Path) -> list:
    """[(order number, the order file's path below the home, its front matter `sprint:` value as written)] of the open (not
    parked) orders, an order without the key giving "". Unlike `open_order_marks` it raises when the ledger cannot be read,
    so a caller can refuse instead of reading nothing as no mark."""
    import ledger_index as li
    home = Path(home)
    out = []
    for nnn, f in li._orders(home / "work-orders"):
        meta = li._info(f)["meta"]
        if not li.is_parked(meta):
            out.append((int(nnn), Path(f).relative_to(home).as_posix(), str(meta.get("sprint", "")).strip()))
    return out


def session_ids(records: list) -> list:
    seen = []
    for r in records:
        s = r.get("session")
        if isinstance(s, str) and s and s not in seen:
            seen.append(s)
    return seen


def sprint_cost(root: Path, sessions: list, env=None) -> str:
    """The sprint's cost line from cost_report.py for these session ids ("" when there is nothing to read). The projects
    folder is under CLAUDE_CONFIG_DIR when `env` (default: this process's environment) sets it, else under ~/.claude."""
    if not sessions:
        return ""
    try:
        import cost_report as cr
        cfg = (os.environ if env is None else env).get("CLAUDE_CONFIG_DIR")
        project = cr.project_dir_for_repo(Path(root), (Path(cfg) if cfg else Path.home() / ".claude") / "projects")
        orch = workers = 0.0
        unpriced = False
        for sid in sessions:
            f = project / f"{sid}.jsonl"
            if not f.is_file():
                continue
            seen: set = set()
            main = cr.summarise(cr.read_file(f, seen), cr.DEFAULT_PRICES)
            orch += main["usd"]
            unpriced = unpriced or not main["priced"]
            for wf in sorted((project / sid / "subagents").glob("*.jsonl")):
                w = cr.summarise(cr.read_file(wf, seen), cr.DEFAULT_PRICES)
                workers += w["usd"]
                unpriced = unpriced or not w["priced"]
        text = f"${orch + workers:.2f} (orchestrator ${orch:.2f}, workers ${workers:.2f}; approximate)"
        return text + ("; some models unpriced" if unpriced else "")
    except Exception:
        return ""


def state_of(records: list) -> str:
    if not records:
        return "no log yet"
    last = records[-1]
    if last["kind"] == "stop":
        return "stopped: " + last.get("msg", "")
    if last["kind"] == "error":
        return "stopped on an error: " + last.get("msg", "")
    return "running"


class NotAHome(Exception):
    """GITOS_SPRINT_HOME names a folder that is not a gitos home."""


def home_from_env_or_cwd() -> "tuple[Path, Path] | None":
    env = os.environ.get(HOME_ENV)
    if env and Path(env).is_dir():
        home = Path(env)
        if not is_gitos_home(home):
            raise NotAHome(f"{HOME_ENV} {env!r} is not a gitos home (no work-orders/ folder, no INDEX.md beside a sprint/ folder): "
                           "refusing to write a sprint log there")
        return home, home.parent
    return locate(Path.cwd())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sprint_log.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="append a log line")
    add.add_argument("kind", choices=KINDS)
    add.add_argument("message")
    add.add_argument("--ref", default="", help="the order, WO-NNN")
    add.add_argument("--session", default="")
    a = ap.parse_args(argv)
    try:
        found = home_from_env_or_cwd()
    except NotAHome as e:
        print(f"sprint_log: {e}", file=sys.stderr)
        return 1
    if found is None:
        print(f"sprint_log: no gitos home here (set {HOME_ENV} or run inside the repo)", file=sys.stderr)
        return 1
    home, root = found
    sid = os.environ.get(ID_ENV, "")
    if sid and not valid_id(sid):
        print(f"sprint_log: {ID_ENV} {sid!r} is not a sprint id", file=sys.stderr)
        return 1
    try:
        rec = add_record(home, a.kind, a.message, a.ref, a.session, sid=sid)
        print(f"{rec['t']} {rec['kind']} {rec['ref']} {rec['msg']}".rstrip())
    except OSError as e:
        print(f"sprint_log: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
