#!/usr/bin/env python3
"""gitos-sprint.py - run a repo's open work-orders in a visible Claude session that rotates itself. Standard library only.

    python gitos-sprint.py [REPO] [--autocompact TOKENS] [--effort LEVEL] [--model MODEL] [--add-dir DIR ...]
                           [--max-rotations N] [--orders 253,254] [--id NAME] [--window]

Run it in a Windows terminal, or add --window and an orchestrator (or any caller) gets the sprint in a new visible PowerShell
window instead (`launch_window`). It launches an interactive Claude session in the repo root with the sprint start prompt,
watches `<home>/sprint/ROTATE` and `<home>/sprint/STOP`, closes the session on either (writing `/exit` into the console,
then killing the process tree if it does not leave), starts a fresh session after a ROTATE, and ends after a STOP. The log
is `<home>/sprint/log.jsonl`; its page is the board's `sprint` tab; one Stop card there ends the sprint after the current
order. Every cap and stop below is code here, not an instruction to the model. Operator guide: references/sprint.md.

--orders limits the sprint to the listed open work-orders (numbers, comma-separated, a `WO-` prefix is accepted); without
it the candidates are the open orders marked `sprint: ready` in their front matter, and an unmarked order is never taken. An
order marked `sprint: no` is never a candidate. Either way the orchestrator skips, with a logged reason, the candidates that
are not sprint-eligible at run time (references/orchestrator/sprint.md, references/orchestrator/sprint-prep.md).
Before anything is launched a folder order must also have a `ready` slice whose dependencies are landed (`slice_problem`, read by
`slice.py`'s own reader): a listed order without one is refused, one line naming it and why; an unlisted marked one is skipped with
the same line; with no order left nothing is launched.

The start prompt asks for replies that are the role marker line alone.

Defaults: --autocompact 500k, --effort medium, --model opus[1m], --max-rotations 20. They apply to the orchestrator session
only. Permission mode is never passed (the operator's own setting applies) and no permission-bypass flag is ever passed.
Every repo file the driver parses (the layout, the board's config and route, the model-optimization config, the guard file,
each candidate order's `sprint:` mark) is checked before the first launch and again at each rotation. A malformed one is a
refusal, never a silent fallback: the driver names the file, logs it and leaves a note in the sprint's state file for the next
interactive orchestrator (`input_problems`).
A sprint keeps its own state in `<home>/sprint/STATE.md` and never writes RESUME.md (the driver's notes go there; an interactive
window folds it into RESUME at its first action). A new sprint is refused while an earlier one's STATE.md exists. A repo may
declare `<home>/sprint-guard.json` (`guard_config`): the driver runs its command before every launch and after every close, and
anything but exit 0 stops the sprint (`guard-failed`) with no further launch. The same file may set `settle_s` (a wait after every
close, before the after-close guard) and `busy_max_s` (turns on the BUSY lease: while the repo's own tooling has `<home>/sprint/BUSY`
live, a ROTATE or a STOP file does not close the session; `live_lease`, `defer_close`).
--id NAME (`[a-z0-9-]{1,32}`, with --orders) makes a named sprint: several named sprints run in one home at once, each in its
own terminal, on disjoint orders. A named sprint keeps its state under `<home>/sprint/<id>/` (STATE.md, log.jsonl, STOP, ROTATE,
BUSY, archive/), has its own Stop card (the board's Sprints view shows it), and claims each of its orders in
`<home>/sprint/claims/WO-NNN.json` (`{"sprint", "pid", "since", "start"}`) for as long as its driver runs. It is refused when another live
sprint holds one of its orders, when its own STATE.md is unfolded, or while an exclusive sprint runs. A sprint without --id is the
exclusive sprint: today's paths, refused while any named sprint runs (it keeps `<home>/sprint/EXCLUSIVE` while it runs, so a named
one can see it). A claim whose process is gone is stale (the pid is dead, or the pid now belongs to a process with another start
time; a claim carries `start` beside `pid`): a new sprint takes it over and says so in its STATE.md.
A named sprint runs in its own git worktree, `<repo>.worktrees/sprint-<id>` on branch `sprint-<id>`, made from the main branch's tip
(`main`, else `master`, else the branch the checkout is on); its session starts there and its order merges land on that branch. The
claims, `sprint/<id>/`, the log, the page and the board stay in the main checkout's home (the session gets it as GITOS_SPRINT_HOME).
When the sprint ends the worktree and branch are removed if the branch is in the main branch and the worktree is clean, else both are
left and STATE.md says so. The exclusive sprint runs in the main checkout, as always.
A driver that exits on any path it controls (a signal, an error, a Ctrl-C) ends its session's process tree first; one killed hard cannot,
so the session's own hooks (`compact_restore.py`, `slice_guard.py`) notice the driver pid is gone and end the session at their next run.
A named sprint's clean end (STOP id `no-open-order` or `stop-card`, the guard passed, nothing left over, no driver note in STATE.md) moves
its STATE.md and STOP into `sprint/<id>/archive/` so the same id can start again; any other end leaves them for the operator to read.
The exclusive sprint's STATE.md is always left: an interactive window folds it into RESUME.md first. An emptied
`<repo>.worktrees/sprint-<id>.worktrees` folder, and an emptied `<repo>.worktrees`, are removed when the sprint ends.
--window: after every pre-launch check has passed in the calling process (a refusal is printed there and nothing opens), the driver
starts itself again, with the same arguments minus the flag, in a new PowerShell console (`-NoExit`, the repo root as the working
directory), prints one line naming the window's pid and the sprint id, and exits 0. Windows only. The window gets the PATH repaired
(`repaired_path`: the registry's Machine and User `Path` merged in, the folder holding claude.exe first when it is not on PATH).
`find_claude` looks on PATH first, then on the PATH rebuilt from the registry, then in the install folders (`claude_known_folders`);
a claude.exe found off PATH has its folder put first on the PATH the session gets (`claude_on_path`).
Exit status: 0 the sprint ended on a stop signal, 1 it ended on an error, an interruption, a cap or a failed guard, 2 nothing
was launched.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import fnmatch
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compact_restore  # noqa: E402
import sprint_log as slog  # noqa: E402
import slice as slicemod  # noqa: E402

SKILL_DIR = HERE.parent
DEFAULT_AUTOCOMPACT = 500_000
DEFAULT_EFFORT = "medium"
DEFAULT_MODEL = "opus[1m]"
DEFAULT_MAX_ROTATIONS = 20
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MIN_WINDOW = 200_000
PLAIN_WINDOW, LONG_WINDOW = 200_000, 1_000_000
POLL_SECONDS = 2.0
QUIET_SECONDS = 6.0          # the session's log must be this still before it is closed
QUIET_CAP_SECONDS = 90.0
EXIT_WAIT_SECONDS = 20.0     # how long /exit gets before the process tree is killed
KEY_GAP_SECONDS = 0.4
COST_EVERY = 30.0
STUCK_AFTER = 2              # rotations in a row with the ledger unchanged
STOP_IDS = ("operator-decision", "outward-action", "implementer-blocker", "part0-no-go", "verify-failed-twice",
            "no-open-order", "stop-card", "guard-failed")
CARD_TAB = "sprint"
CARD_OPTION = "stop=Stop after the current WO"
CARD_TITLE = "Stop the sprint after the current work-order"
CARD_BODY = ("The sprint finishes the order it is on, writes its state and stops. Pressing Stop is the only thing this card does; "
             "Ctrl-C in the terminal stops at once.")
IGNORE_LINES = ("sprint/", "board/local/sprint.html")      # relative to the home
INTERRUPT_MARK = "<!-- gitos-sprint-interrupted -->"
REFUSED_MARK = "<!-- gitos-sprint-refused -->"
SPRINT_MARKS = ("ready", "no")           # the values of an order's `sprint:` front matter key
REFUSAL_ITEMS_MAX = 4                    # problems named in one note, the rest counted
STATE_REL = Path("sprint") / "STATE.md"  # the sprint's own state, relative to the home; RESUME.md is never written
NOTES_HEADING = "## Notes for the operator"
GUARD_MARK = "<!-- gitos-sprint-guard -->"
GUARD_FILE = "sprint-guard.json"         # the repo's optional guard command, relative to the home
GUARD_KEYS = ("command", "timeout_s", "settle_s", "busy_max_s")
GUARD_TIMEOUT_DEFAULT, GUARD_TIMEOUT_MAX = 120, 900
GUARD_NUMBER_KEYS = (("settle_s", 0, 600), ("busy_max_s", 1, 3600))     # (key, least, most) in seconds, both optional
BUSY_FILE = "BUSY"                       # the repo's own lease file, in `<home>/sprint/`
SETTLE_STEP = 1.0                        # the settle wait sleeps in steps this long, so Ctrl-C is heard
GUARD_TAIL_LINES, GUARD_TAIL_CHARS = 5, 300
CARD_ID_RE = re.compile(r"card (\d{8}-\d{6}-\d{6}-[0-9a-f]{4}) added")
WO_RE = re.compile(r"WO-\d+(?:/S\d+[a-z]?)?")
HARNESS_PREFIXES = ("CLAUDE", "MCP_")
KEEP_ENV = (                          # operator configuration, not harness markers: these pass through the strip
    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_GIT_BASH_PATH", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
REF_JUNK_RE = re.compile(r"[^\w ./:#-]+")
ORDER_REF_MAX = 40
ORDER_ITEM_RE = re.compile(r"(?:wo-)?(\d+)", re.I)
CLAIMS_DIR = "claims"                    # `<home>/sprint/claims/WO-NNN.json`, one per order a live named sprint holds
EXCLUSIVE_FILE = "EXCLUSIVE"             # `<home>/sprint/EXCLUSIVE`, `{"pid", "since"}`: the exclusive sprint is running
SPRINT_ID = ""                           # the named sprint this process drives, set by `main` (the default of `report_refusal`)
WORKTREE_PREFIX = "sprint-"              # a named sprint's worktree folder and branch: `sprint-<id>`
GIT_LONG = 120                           # seconds a worktree add or remove may take (a big checkout)
WORKTREE_MARK = "<!-- gitos-sprint-worktree -->"            # STATE.md: an earlier run's worktree was reused
WORKTREE_LEFT_MARK = "<!-- gitos-sprint-worktree-left -->"   # STATE.md: the worktree and branch were left in place
NOTE_MARK_PREFIX = "<!-- gitos-sprint-"      # every note the driver writes into STATE.md starts its mark with this
CLEAN_STOPS = ("no-open-order", "stop-card")  # the STOP ids of a sprint that finished or was stopped by the operator: nothing waits on a reader
EXIT_SIGNALS = ("SIGTERM", "SIGBREAK", "SIGHUP")   # a driver ended by one of these still ends its session (a hard kill cannot be caught)


# ------------------------------------------------------------------------------------------------ flags
def parse_tokens(text: str) -> int:
    """`500k`, `1M`, `200000` -> tokens. A bare number up to 1000 is thousands, as the CLI reads it."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", str(text))
    if not m:
        raise argparse.ArgumentTypeError(f"{text!r} is not a token count (500k, 1M, 200000)")
    n, unit = float(m.group(1)), m.group(2).lower()
    if unit == "k":
        n *= 1000
    elif unit == "m":
        n *= 1_000_000
    elif n <= 1000:
        n *= 1000
    return int(n)


pid_alive = compact_restore.pid_alive            # liveness lives in compact_restore.py: worktree.py's lock and the canary read it too
process_start, record_alive = compact_restore.process_start, compact_restore.record_alive


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def own_start() -> dict:
    """`{"start": this process's start time}` for a claim or the exclusive marker; empty when it cannot be read (the record is then
    judged by its pid alone, as one written before start times were kept is)."""
    start = process_start(os.getpid())
    return {"start": start} if start else {}


CLAIM_TRIES = 5     # attempts to claim one order whose claim keeps vanishing under the link
READ_TRIES = 6      # attempts to read a claim that is delete-pending (a Windows PermissionError on read)
REMOVE_TRIES = 10   # attempts to remove a claim file another process still holds open (a Windows sharing violation)
SHARED_TRIES = 10   # attempts to read or replace a shared file another process holds open (a denied read or replace)
PARSE_TRIES = 5     # attempts to read a shared JSON file that does not parse (another process is writing it)
EDIT_TRIES = 5      # attempts to make a read-modify-write of a shared file stick against a writer that does not take the lock
LOCK_WAIT_S = 10.0  # seconds a driver waits for the short lock of a shared file's read-modify-write before going on without it
GIT_TRIES = 10      # attempts at a git command that meets another git process at work (its lock file, or a file it is rewriting)
WORKTREE_ARCHIVE = "worktree-archive"  # worktree.py's archive folder under a home: a worker's kept files
LOCK_SUFFIX = ".gitos-lock"     # `<shared file><suffix>`: the short lock of that file's read-modify-write
# What git says while another git process of the same repo is at work: a lock file it holds (`.lock ... File exists`, `could not lock`),
# the config file it is replacing (`unable to access '.git/config': Permission denied`), a worktree it is still making
# (`failed to read .git/worktrees/<name>/commondir`). All pass in milliseconds; git itself does not retry.
GIT_BUSY_RE = re.compile(
    r"could not lock|unable to (?:create|lock) '[^']*\.lock'|cannot lock ref|another git process seems to be running"
    r"|\.lock'?: (?:file exists|permission denied)"
    r"|unable to access '[^']*': permission denied|error occurred while reading the configuration"
    r"|failed to read [^\n]*[\\/]worktrees[\\/]", re.I)


def claims_dir(home: Path) -> Path:
    return Path(home) / "sprint" / CLAIMS_DIR


def read_claim(path: Path) -> "tuple[dict | None, str]":
    """One claim file -> ({"sprint", "pid", "since"} and, since R2, "start"; "") or (None, why it is not a claim)."""
    attempt = 0
    while True:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            break
        except PermissionError as e:              # a claim being deleted is denied for a moment (delete-pending): read it again
            attempt += 1
            if attempt < READ_TRIES:
                time.sleep(min(0.02 * attempt, 0.1) + random.uniform(0, 0.02))
                continue
            return None, f"cannot be read ({str(e).splitlines()[0] if str(e) else type(e).__name__})"
        except (OSError, ValueError) as e:
            return None, f"cannot be read ({str(e).splitlines()[0] if str(e) else type(e).__name__})"
    if (not isinstance(data, dict) or not isinstance(data.get("sprint"), str) or isinstance(data.get("pid"), bool)
            or not isinstance(data.get("pid"), int) or not isinstance(data.get("since"), str)):
        return None, 'is not a claim (`{"sprint": id, "pid": driver pid, "since": time}`)'
    return data, ""


def all_claims(home: Path) -> list:
    """[(order ref, the claim, the claim's problem, the file)] of every `WO-NNN.json` in the claims folder; a file that is not a
    claim has claim None and its problem."""
    out = []
    try:
        files = sorted(claims_dir(home).glob("WO-*.json"))
    except OSError:
        return out
    for f in files:
        claim, why = read_claim(f)
        out.append((f.stem, claim, why, f))
    return out


def claim_text(ref: str, claim: dict) -> str:
    return f'{ref} is claimed by sprint "{claim["sprint"]}" (pid {claim["pid"]}, since {plain_line(claim["since"])[:30]})'


def sprint_conflicts(home: Path, sid: str, orders: tuple) -> list:
    """Every reason sprint `sid` (named) or the exclusive sprint (`sid` "") may not start now, one sentence each, read only: a live
    claim on one of its orders by another sprint, the same id already running, an exclusive sprint running, a claim file of its
    orders that is no claim. A claim whose pid is dead is stale and no reason. A claim of this very process is this sprint's own."""
    out = []
    me = os.getpid()
    if not sid:
        excl, _ = read_exclusive(home)
        if excl and excl["pid"] != me and record_alive(excl):
            out.append(f"another exclusive sprint (no --id) is running (pid {excl['pid']}, since {plain_line(excl.get('since', ''))[:30]}): "
                       "only one exclusive sprint runs at a time")
        for ref, claim, _, _ in all_claims(home):
            if claim and record_alive(claim) and claim["pid"] != me:
                out.append(f'a named sprint is running ("{claim["sprint"]}", pid {claim["pid"]}): the exclusive sprint '
                           "cannot start while one runs")
                break
        return out
    excl, _ = read_exclusive(home)
    if excl and record_alive(excl) and excl["pid"] != me:
        out.append(f"an exclusive sprint (no --id) is running (pid {excl['pid']}): a named sprint cannot start while it runs")
    same = None
    for ref, claim, why, f in all_claims(home):
        if claim is None:
            if ref in orders:
                out.append(f"{home_file(home, f'sprint/{CLAIMS_DIR}/{f.name}')} {why}: remove it, then rerun")
        elif record_alive(claim) and not (claim["sprint"] == sid and claim["pid"] == me):
            if ref in orders and claim["sprint"] != sid:
                out.append(f"--orders {claim_text(ref, claim)}: another sprint is working it")
            elif claim["sprint"] == sid and same is None:
                same = claim
    if same:
        out.append(f'sprint "{sid}" is already running (pid {same["pid"]}): pick another --id')
    return out


def read_exclusive(home: Path) -> "tuple[dict | None, str]":
    try:
        data = load_json(Path(home) / "sprint" / EXCLUSIVE_FILE)
    except (OSError, ValueError):
        return None, ""
    return (data, "") if isinstance(data, dict) and isinstance(data.get("pid"), int) else (None, "")


def remove_file(path: Path) -> str:
    """Remove `path` -> "" when it is gone (or already was), else why it could not be. On Windows a file is not removed while any
    process holds it open without delete sharing (another driver's scan of the claims reads every claim): such a PermissionError
    (WinError 32) passes in milliseconds, so it is retried (`REMOVE_TRIES`, a short growing backoff, about a second at the most). Any
    other error is the answer at once."""
    why = ""
    for attempt in range(REMOVE_TRIES):
        try:
            os.unlink(path)
            return ""
        except FileNotFoundError:
            return ""
        except PermissionError as e:
            why = f"{type(e).__name__}: {plain_line(str(e))}"[:200]
            time.sleep(min(0.02 * (attempt + 1), 0.15) + random.uniform(0, 0.02))
        except OSError as e:
            return f"{type(e).__name__}: {plain_line(str(e))}"[:200]
    return why


def pause(attempt: int) -> None:
    """The short growing wait between two attempts at a file another process holds (20 to 150 ms, jittered)."""
    time.sleep(min(0.02 * (attempt + 1), 0.15) + random.uniform(0, 0.02))


def retry_denied(fn, tries: int = SHARED_TRIES):
    """`fn()`, called again (bounded, `pause`) while it raises PermissionError: on Windows a file another process holds open is denied to
    a replace or a read for a moment. The last PermissionError is raised; any other error at once."""
    for attempt in range(tries):
        try:
            return fn()
        except PermissionError:
            if attempt == tries - 1:
                raise
            pause(attempt)


def replace_file(tmp, path) -> None:
    """`os.replace(tmp, path)`, retried while a reader holds `path` open (a sharing violation)."""
    retry_denied(lambda: os.replace(tmp, path))


def put_json_file(path: Path, data: dict, exclusive: bool) -> None:
    """Write `data` as one JSON line, whole: a finished temp file in the same folder is moved onto `path`, so a reader never meets
    it empty or half written. `exclusive`: the temp file is hard-linked into place (atomic and exclusive, as the merge lock is
    made) and FileExistsError is raised when `path` is there; where links are not available the file is created exclusively and
    then written. Not exclusive: it replaces `path` in one step."""
    text = (json.dumps(data) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".claim-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text)
        if not exclusive:
            replace_file(tmp, path)
            return
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            fd2 = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd2, "wb") as fh:
                fh.write(text)
    finally:
        remove_file(Path(tmp))


def write_whole(path: Path, data: bytes, prefix: str = ".shared-") -> None:
    """Write `data` to `path` whole: a finished temp file in the same folder is moved onto it, so a reader never meets it empty or
    half written (a file written in place is). The temp file never stays."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        replace_file(tmp, path)
    except BaseException:
        remove_file(Path(tmp))
        raise


def load_json(path: Path):
    """The JSON in `path` (UTF-8, a BOM allowed), read again (bounded, `pause`) while the read is denied or the text does not parse:
    another process is rewriting the file. FileNotFoundError at once; the last PermissionError or ValueError when it stays so."""
    for attempt in range(PARSE_TRIES):
        try:
            return json.loads(retry_denied(lambda: Path(path).read_text(encoding="utf-8-sig")))
        except ValueError:
            if attempt == PARSE_TRIES - 1:
                raise
            pause(attempt)


def lock_record(lock: Path) -> "dict | None":
    """The record in a `file_guard` lock, or None when the lock is gone or cannot be read as one."""
    try:
        rec = json.loads(lock.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def retire_lock(lock: Path, holder: dict) -> bool:
    """Remove the stale lock `lock` that `holder` (the record just read) made, once, for one taker at a time: the removal is done under
    `<lock>.retire` (made exclusively), and only while the lock still holds `holder`'s record, so a taker that read the same dead record
    later cannot remove the lock another taker has made in between. -> True when the stale lock is gone and the caller makes its own;
    False when someone else is at it or the lock is no longer `holder`'s: the caller decides again from what is there now. A `.retire`
    left by a taker that died is cleared by the next one."""
    gate = lock.with_name(lock.name + ".retire")
    try:
        put_json_file(gate, {"pid": os.getpid(), "since": utc_stamp(), **own_start()}, True)
    except FileExistsError:
        other = lock_record(gate)
        if other is not None and isinstance(other.get("pid"), int) and not record_alive(other):
            remove_file(gate)
        return False
    except OSError:
        return False
    try:
        if lock_record(lock) != holder:
            return False
        return not remove_file(lock)
    finally:
        remove_file(gate)


@contextlib.contextmanager
def file_guard(target: Path, wait: "float | None" = None):
    """A short exclusive lock on a read-modify-write of the shared file `target`: `<target>.gitos-lock`, made whole and exclusively
    (as a claim is) with this process's pid and start. A lock whose process is gone (`record_alive`) is a leftover and is taken over,
    under `retire_lock`, which re-reads it so a taker never removes the lock another taker has just made.
    A holder that stays past `wait` seconds is not waited for (a stuck process must not stop a start): the edit goes on unlocked and the
    callers verify what they wrote. Yields whether the lock is held; it never outlives the block."""
    lock = target.with_name(target.name + LOCK_SUFFIX)
    held, end, attempt = False, time.monotonic() + (LOCK_WAIT_S if wait is None else wait), 0
    while True:
        try:
            put_json_file(lock, {"pid": os.getpid(), "since": utc_stamp(), **own_start()}, True)
            held = True
            break
        except FileExistsError:
            pass
        except OSError:                                    # no folder to lock in, or no right to: no lock
            break
        try:
            holder = json.loads(lock.read_text(encoding="utf-8-sig"))
            gone = isinstance(holder, dict) and isinstance(holder.get("pid"), int) and not record_alive(holder)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):                      # being made or removed right now: not a leftover
            gone = False
        if gone and not retire_lock(lock, holder):
            continue
        if time.monotonic() >= end:
            break
        pause(attempt)
        attempt += 1
    try:
        yield held
    finally:
        if held:
            remove_file(lock)


def claim_one(home: Path, path: Path, ref: str, sid: str, mine: dict):
    """Claim one order's file for `mine` -> "claimed" (the file was free) or the claim it replaced (a dead one's, or this very process's
    own). A claim held by a live process of another sprint is RuntimeError. A dead claim is taken over under `file_guard`, after a
    re-read that must still show the very record this taker judged dead: two takers that read the same dead claim cannot both replace
    it, the second finds the first's claim there and decides again from it."""
    where = home_file(home, f"sprint/{CLAIMS_DIR}/{path.name}")
    for attempt in range(CLAIM_TRIES):
        try:
            put_json_file(path, mine, True)
            return "claimed"
        except FileExistsError:
            pass
        old, why = read_claim(path)
        if old is None:
            if not path.exists():                     # its holder rolled back between the link and the read: the order is free
                time.sleep(random.uniform(0.01, 0.05))
                continue
            raise RuntimeError(f"{where} {why}: remove it, then rerun")
        if record_alive(old) and not (old["sprint"] == sid and old["pid"] == mine["pid"]):
            raise RuntimeError(f"--orders {claim_text(ref, old)}: another sprint is working it")
        with file_guard(path):
            if read_claim(path)[0] != old:            # replaced or removed since we read it: decide again from what is there now
                continue
            try:
                put_json_file(path, mine, False)
            except Exception as e:                    # e.g. a Windows sharing violation while a reader holds the file
                raise RuntimeError(f"--orders {claim_text(ref, old)}: its stale claim {where} could not be taken over "
                                   f"({type(e).__name__}: {plain_line(str(e))}): rerun, or remove the file")
        now, _ = read_claim(path)
        if now is None or now["sprint"] != sid or now["pid"] != mine["pid"]:
            raise RuntimeError(f"--orders {ref} was claimed by another sprint a moment ago")
        return old
    raise RuntimeError(f"--orders {ref} was contended: its claim kept vanishing under {CLAIM_TRIES} attempts "
                       "(other sprints claiming and rolling back): rerun")


def claim_orders(home: Path, sid: str, orders: tuple) -> list:
    """Write `<home>/sprint/claims/WO-NNN.json` for each order of named sprint `sid`, this process as the holder. A claim held by
    a live process of another sprint (or by this id elsewhere) is RuntimeError naming the order and the holder, and nothing of
    this sprint's stays written (a claim the rollback cannot remove is removed again, and said, by `Sprint.run`); a claim whose pid
    is dead is replaced (`claim_one`). -> [(order, the stale claim it replaced)]."""
    cdir = claims_dir(home)
    cdir.mkdir(parents=True, exist_ok=True)
    mine = {"sprint": sid, "pid": os.getpid(), "since": utc_stamp(), **own_start()}
    taken = []
    try:
        for ref in orders:
            old = claim_one(home, cdir / f"{ref}.json", ref, sid, mine)
            if old != "claimed" and not (old["sprint"] == sid and old["pid"] == mine["pid"]):
                taken.append((ref, old))
    except BaseException:
        release_claims(home, sid)
        raise
    return taken


def release_claims(home: Path, sid: str) -> list:
    """Remove the claims this process holds for sprint `sid`, each retried while another process holds it open (`remove_file`); a
    claim of another sprint, or of this id under another pid, stays. -> [(claim file, why)] of those still there, for the caller to say."""
    left = []
    for _, claim, _, f in all_claims(home):
        if claim and claim["sprint"] == sid and claim["pid"] == os.getpid():
            why = remove_file(f)
            if why:
                left.append((f, why))
    return left


def mark_exclusive(home: Path) -> None:
    """Mark this process as the exclusive sprint: `sprint/EXCLUSIVE` is created exclusively (as a claim is), so a second exclusive sprint
    never replaces the first's marker. An existing marker whose process is gone (or that is no marker) is taken over under `file_guard`
    after a re-read; one held by a live other process is RuntimeError naming it."""
    path = Path(home) / "sprint" / EXCLUSIVE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = {"pid": os.getpid(), "since": utc_stamp(), **own_start()}
    for attempt in range(CLAIM_TRIES):
        try:
            put_json_file(path, mine, True)
            return
        except FileExistsError:
            pass
        with file_guard(path):
            data, _ = read_exclusive(home)
            if data and record_alive(data) and data["pid"] != os.getpid():
                raise RuntimeError(f"another exclusive sprint (no --id) is running (pid {data['pid']}, since "
                                   f"{plain_line(data.get('since', ''))[:30]}): only one exclusive sprint runs at a time")
            if path.exists():
                why = remove_file(path)
                if why:
                    raise RuntimeError(f"{home_file(home, f'sprint/{EXCLUSIVE_FILE}')} is a leftover that cannot be removed: {why}")
        pause(attempt)
    raise RuntimeError(f"{home_file(home, f'sprint/{EXCLUSIVE_FILE}')} could not be taken: another start keeps winning it")


def unmark_exclusive(home: Path) -> list:
    """Remove this process's exclusive marker (as `release_claims` removes a claim) -> [(file, why)] when it is still there."""
    data, _ = read_exclusive(home)
    if data and data["pid"] == os.getpid():
        path = Path(home) / "sprint" / EXCLUSIVE_FILE
        why = remove_file(path)
        if why:
            return [(path, why)]
    return []


# ------------------------------------------------------------------------------------------------ the sprint worktree
def run_git_once(root, *argv: str, timeout: float = 30) -> tuple:
    """`git -C root ...` once -> (return code, stdout, stderr); the code is None when git is absent or times out."""
    try:
        cp = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None, "", ""
    return cp.returncode, cp.stdout, cp.stderr


def git_busy(err: str) -> bool:
    """Whether git's complaint `err` is another git process of this repo at work (`GIT_BUSY_RE`), which passes."""
    return bool(GIT_BUSY_RE.search(err or ""))


def run_git(root, *argv: str, timeout: float = 30, between=None) -> tuple:
    """`git -C root ...` -> (return code, stdout, stderr); the code is None when git is absent or times out. Run again (`GIT_TRIES`
    attempts, a doubling wait from 50 ms to 1 s, jittered) while git's complaint is `git_busy`: sprints started or ended at the same
    moment share one repo, and git does not wait for the other's lock or half-made file itself. `between()` runs before each new
    attempt (to clear what the refused one left). Any other failure, and the last busy one, is the answer."""
    for attempt in range(GIT_TRIES):
        rc, out, err = run_git_once(root, *argv, timeout=timeout)
        if rc in (0, None) or attempt == GIT_TRIES - 1 or not git_busy(err):
            return rc, out, err
        time.sleep(min(0.05 * 2 ** attempt, 1.0) + random.uniform(0, 0.05))
        if between:
            between()


def main_branch(root) -> str:
    """The main branch of the repo at `root`, read as `worktree.py` reads its default branch (`_merge_targets`): `main`, else
    `master`, else (neither exists) the branch the checkout is on. "" when there is none (a detached HEAD)."""
    for name in ("main", "master"):
        if run_git(root, "rev-parse", "--verify", "-q", f"refs/heads/{name}")[0] == 0:
            return name
    rc, out, _ = run_git(root, "symbolic-ref", "--short", "-q", "HEAD")
    return out.strip() if rc == 0 else ""


def sprint_branch(sid: str) -> str:
    return f"{WORKTREE_PREFIX}{sid}"


def sprint_worktree_path(root: Path, home: Path, sid: str) -> Path:
    """Where named sprint `sid`'s worktree is: `worktree.py new`'s root (the layout's `root`, else the sibling
    `<repo name>.worktrees`) and `sprint-<id>` in it."""
    import worktree
    try:
        layout = worktree.load_layout(home)
    except (OSError, ValueError, worktree.LayoutError):          # a malformed worktrees.json is refused by `input_problems`
        layout = {"root": None}
    return worktree.layout_root(root, layout) / sprint_branch(sid)


def same_path(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def worktree_state(root: Path, path: Path, branch: str) -> "tuple[str, str]":
    """What is at a named sprint's worktree path and branch now, read only: ("fresh", "") when neither exists, ("leftover", "") when
    `path` is a worktree of this repo on `branch` (an earlier run's; the caller has seen no live claim of this sprint), else
    ("refused", the reason): the path is something else, the branch exists with no worktree there, or the worktree is of another
    branch or is gone from disk."""
    rc, out, _ = run_git(root, "worktree", "list", "--porcelain")
    if rc != 0:
        return "refused", f"git could not list the worktrees of {root}"
    mine = None
    for block in out.split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "worktree" in fields and same_path(fields["worktree"], path):
            mine = fields
    if mine is not None:
        if mine.get("branch") != f"refs/heads/{branch}":
            return "refused", f"{path} is a worktree of {mine.get('branch', 'a detached HEAD')}, not of {branch}: pick another --id"
        if not Path(path).is_dir():
            return "refused", f"{path} is registered as a worktree but its folder is gone: run `git worktree prune`, then rerun"
        return "leftover", ""
    if Path(path).exists():
        return "refused", f"{path} exists and is not a worktree of this repo: move it away or pick another --id"
    if run_git(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[0] == 0:
        return "refused", f"branch {branch} exists with no worktree at {path}: delete it (`git branch -D {branch}`) or pick another --id"
    return "fresh", ""


def worktree_problems(root: Path, home: Path, sid: str) -> list:
    """Every reason a named sprint cannot get its worktree now, read only: started in a linked worktree, no main branch with a commit,
    something else at its path or branch."""
    import worktree
    if worktree.is_linked(root):
        return [f"{root} is a linked worktree: start a named sprint in the repo's main checkout"]
    base = main_branch(root)
    if not base or run_git(root, "rev-parse", "--verify", "-q", f"refs/heads/{base}^{{commit}}")[0] != 0:
        return [f"{root} has no main branch with a commit (`main`, `master` or the branch checked out): a named sprint's worktree "
                "starts from its tip"]
    state, why = worktree_state(root, sprint_worktree_path(root, home, sid), sprint_branch(sid))
    return [why] if state == "refused" else []


def add_worktree(root: Path, path: Path, branch: str, base: str) -> None:
    """Create the worktree: `git worktree add -b <branch> <path> <base>`. Another sprint's `worktree add` or `remove` at the same moment can
    make git refuse (a lock file, a worktree not yet whole): it is tried again (`run_git`), after `clear_partial` has taken away
    what the refused attempt left. RuntimeError with git's own words when it still fails."""
    rc, _, err = run_git(root, "worktree", "add", "-b", branch, str(path), base, timeout=GIT_LONG,
                         between=lambda: clear_partial(root, path, branch))
    if rc != 0:
        raise RuntimeError(f"git worktree add {path} failed ({plain_line(err)[:200] or 'no output'})")


def clear_partial(root: Path, path: Path, branch: str) -> None:
    """What a refused `worktree add` of ours may have left: a half-made worktree folder and its new branch (neither existed when the add
    began: `worktree_state` said fresh, and a sprint id runs once)."""
    if Path(path).exists():
        run_git(root, "worktree", "remove", "--force", str(path), timeout=GIT_LONG)
    if run_git(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[0] == 0:
        run_git(root, "branch", "-D", branch)


def discard_worktree(root: Path, path: Path, branch: str) -> None:
    """Undo `add_worktree` of a worktree no session has touched."""
    run_git(root, "worktree", "remove", "--force", str(path), timeout=GIT_LONG)
    run_git(root, "branch", "-D", branch)


def keep_worktree_archive(root: Path, path: Path, home: Path) -> str:
    """Before a sprint worktree goes: copy what its own `<home>/worktree-archive/` holds (git-ignored, so the clean-tree check does
    not see it) into the main home's `worktree-archive/`. An entry already there is never overwritten: the copy gets the next free
    name (`<name>-2`). -> "" when nothing was lost, else why the worktree must stay."""
    try:
        rel = Path(home).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return ""
    src, dest = Path(path) / rel / WORKTREE_ARCHIVE, Path(home) / WORKTREE_ARCHIVE
    if not src.is_dir():
        return ""
    try:
        entries = sorted(src.iterdir())
        if entries:
            dest.mkdir(parents=True, exist_ok=True)
        for e in entries:
            target, n = dest / e.name, 1
            while os.path.lexists(target):
                n += 1
                target = dest / f"{e.name}-{n}"
            if e.is_dir() and not e.is_symlink():
                shutil.copytree(e, target, symlinks=True)
            else:
                shutil.copy2(e, target, follow_symlinks=False)
    except (OSError, shutil.Error) as e:
        return f"its {WORKTREE_ARCHIVE} folder could not be copied to {plain_line(dest)} ({plain_line(str(e))[:160]})"
    return ""


def remove_worktree(root: Path, path: Path, branch: str, home: "Path | None" = None) -> str:
    """Remove a finished sprint's worktree and branch when that loses nothing: the branch is in the main branch (landed, or never
    moved), the worktree has no uncommitted or untracked file and its own `worktree-archive/` (given the main `home`) is copied to
    the main home first. -> "" when both are gone, else why they were left."""
    base = main_branch(root)
    if not base:
        return "there is no main branch to compare the sprint branch with"
    rc, out, err = run_git(path, "status", "--porcelain")
    if rc != 0:
        return f"git could not read the worktree's state ({plain_line(err)[:120]})"
    if out.strip():
        return f"the worktree has {len([x for x in out.splitlines() if x.strip()])} uncommitted or untracked path(s)"
    rc, out, _ = run_git(root, "rev-list", "--count", f"{base}..{branch}")
    if rc != 0:
        return f"git could not compare {branch} with {base}"
    if out.strip() != "0":
        return f"{branch} has {out.strip()} commit(s) that {base} does not (they have not landed)"
    if home is not None:
        why = keep_worktree_archive(root, path, home)
        if why:
            return why
    rc, _, err = run_git(root, "worktree", "remove", str(path), timeout=GIT_LONG)
    if rc != 0:
        return f"git worktree remove failed ({plain_line(err)[:160] or 'no output'})"
    rc, _, err = run_git(root, "branch", "-D", branch)
    return "" if rc == 0 else f"the worktree is gone but the branch could not be deleted ({plain_line(err)[:160]})"


def prune_empty_folders(root: Path, path: Path) -> None:
    """After a sprint's worktree is gone (or left): remove its emptied workers' folder `<path>.worktrees` and then the emptied
    `<repo>.worktrees` that held it. Only a default-named `<repo>.worktrees` is removed (a layout root the repo chose is its own), and
    only while it is empty: `rmdir` refuses a folder that holds anything. Never raises."""
    for folder in (Path(str(path) + ".worktrees"), Path(path).parent):
        if folder == Path(path).parent and folder.name != f"{Path(root).name}.worktrees":
            continue
        try:
            folder.rmdir()
        except OSError:
            pass


def unwritten_part(path: Path) -> str:
    """The heading of the first section of a slice file whose body still says `(to be written)`, or ""."""
    heading = ""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif "(to be written)" in line.lower():
            return heading
    return ""


def slice_problem(home: Path, ref: str) -> str:
    """Why a sprint cannot dispatch anything from order `ref` ("WO-NNN"), one line, or "" when it can. A single-file order has no
    slices and is eligible. A folder order is eligible when `slice.py`'s own reader (`slice_next`) finds a `ready` slice whose
    dependencies are all landed; the reason is the first slice that is not finished: its status and what its file still lacks,
    or the dependency a ready slice waits on."""
    try:
        found = slicemod.find_order(Path(home), ref[3:])
        if not found or not found[2]:
            return ""
        hit, waiting = slicemod.slice_next(Path(home), ref)
        if hit:
            return ""
        slices = slicemod.list_slices(found[0])
    except (slicemod.SliceError, OSError, ValueError) as e:
        return f"its slices cannot be read ({type(e).__name__}: {e})"
    for num, path, meta in slices:
        status = str(meta.get("status", "")).strip() or "no status"
        if status in ("landed", "dropped"):
            continue
        if status == "ready":
            note = next((w for w in waiting if w.startswith(f"{ref}/S{num} ")), "")
            if note:
                return f"no slice is ready to dispatch ({note.split('/', 1)[1]})"
        part = unwritten_part(path)
        return f"no slice is ready to dispatch (S{num} {status}" + (f", {part} to be written)" if part else ")")
    return "no slice is ready to dispatch (every slice is landed or dropped, or the order has none)"


def ready_marked(home: Path) -> tuple:
    """The open orders marked `sprint: ready`, canonical and sorted."""
    return tuple(f"WO-{n:03d}" for n in sorted(n for n, m in slog.open_order_marks(home).items() if m == "ready"))


def skipped_orders(home: Path) -> list:
    """[(order, why)] of the orders marked `sprint: ready` that have no slice to dispatch (`slice_problem`)."""
    return [(ref, why) for ref in ready_marked(home) for why in [slice_problem(home, ref)] if why]


def candidate_orders(orders: tuple, home: Path) -> tuple:
    """The orders a sprint may take, canonical and sorted: the operator's `--orders` list when there is one, else the open
    orders whose front matter says `sprint: ready` and that have a slice to dispatch (`slice_problem`). An unmarked order is
    never a candidate by default."""
    if orders:
        return tuple(orders)
    return tuple(ref for ref in ready_marked(home) if not slice_problem(home, ref))


def parse_orders(text: str) -> tuple:
    """`253,254`, `WO-253, wo-254` -> ("WO-253", "WO-254"): canonical, in the order given, without repeats. An item that is
    not an order number, an empty item or the number 0 is refused."""
    out: list = []
    for item in str(text).split(","):
        m = ORDER_ITEM_RE.fullmatch(item.strip())
        if not m or int(m.group(1)) == 0:
            raise argparse.ArgumentTypeError(f"{item.strip()!r} is not a work-order number (253 or WO-253, comma-separated)")
        ref = f"WO-{int(m.group(1)):03d}"
        if ref not in out:
            out.append(ref)
    return tuple(out)


def parse_id(text: str) -> str:
    """A sprint id: `[a-z0-9-]{1,32}`, and not a name that already lives under `<home>/sprint/` (`SPRINT_RESERVED_IDS`)."""
    if not compact_restore.SPRINT_ID_RE.fullmatch(str(text)):
        raise argparse.ArgumentTypeError(f"{text!r} is not a sprint id (1 to 32 characters of a-z, 0-9 and -)")
    if text in compact_restore.SPRINT_RESERVED_IDS:
        raise argparse.ArgumentTypeError(f"{text!r} is a reserved name (the sprint directory already has a folder or file called that): "
                                         f"pick another --id. Reserved ids: {', '.join(compact_restore.SPRINT_RESERVED_IDS)}")
    return str(text)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="gitos-sprint.py", description=__doc__.split("\n")[0])
    ap.add_argument("repo", nargs="?", default=None, help="the repo root (default: the current directory)")
    ap.add_argument("--autocompact", type=parse_tokens, default=DEFAULT_AUTOCOMPACT, metavar="TOKENS",
                    help="auto-compact window of the session: 200k to the model's context (default 500k)")
    ap.add_argument("--effort", choices=EFFORTS, default=DEFAULT_EFFORT, help="orchestrator effort (default medium)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"orchestrator model (default {DEFAULT_MODEL})")
    ap.add_argument("--add-dir", action="append", default=[], metavar="DIR", help="an extra directory (repeatable)")
    ap.add_argument("--max-rotations", type=int, default=DEFAULT_MAX_ROTATIONS, metavar="N",
                    help="rotations allowed before the sprint ends (default 20)")
    ap.add_argument("--orders", type=parse_orders, default=(), metavar="NUMS",
                    help="work only these open orders (253,254 or WO-253,WO-254); default: every open order")
    ap.add_argument("--id", type=parse_id, default=None, metavar="NAME",
                    help="a named sprint (needs --orders): runs beside other named sprints on disjoint orders; default: the "
                         "exclusive sprint")
    ap.add_argument("--window", action="store_true",
                    help="after the checks pass, start this sprint in a new visible PowerShell window and exit (Windows only)")
    a = ap.parse_args(argv)
    a.argv = list(sys.argv[1:] if argv is None else argv)
    a.id = a.id or ""
    if a.max_rotations < 0:
        ap.error("--max-rotations is 0 or more")
    return a


def model_window(model: str) -> int:
    """The context window of a model name: the 1M variants carry `[1m]`; anything else is taken as 200k."""
    return LONG_WINDOW if re.search(r"\[1m\]$|-1m$", model.strip().lower()) else PLAIN_WINDOW


# ------------------------------------------------------------------------------------------------ preflight
def claude_json_path(env) -> Path:
    cfg = env.get("CLAUDE_CONFIG_DIR")
    return (Path(cfg) / ".claude.json") if cfg else Path.home() / ".claude.json"


def is_trusted(root: Path, claude_json: Path) -> "tuple[bool, str]":
    """Whether Claude has been told to trust `root` itself (hasTrustDialogAccepted on the repo root's own key in the operator's
    ~/.claude.json). A trusted folder above it does not count: Claude Code does not inherit the trust, so a session started in an
    untrusted repo under a trusted parent waits at the trust dialog. Read only. -> (trusted, a reason when not)."""
    try:
        data = load_json(Path(claude_json))                 # live sessions rewrite this file: a read in the middle is read again
        projects = data.get("projects")
    except (OSError, ValueError, AttributeError) as e:
        return False, f"cannot read {claude_json} ({e})"
    if not isinstance(projects, dict):
        return False, f"{claude_json} lists no projects"
    key = lambda p: os.path.normcase(os.path.normpath(str(p)))  # noqa: E731
    trusted = {key(k) for k, v in projects.items() if isinstance(v, dict) and v.get("hasTrustDialogAccepted") is True}
    here = Path(root).resolve()
    if key(here) in trusted:
        return True, ""
    return False, f"{here} is not trusted in {claude_json} (it needs its own entry: a trusted parent folder does not count)"


def route_problem(home: Path) -> "tuple[str, str]":
    """What the home's `board-route.json` says about a sprint, read the way board.py `route()` reads it: -> (kind, text).
    No file or mode `local` is a repo with its own board: ("", ""). Mode `hub` is ("hub", ...): refused, nothing to fix. A file
    that cannot be read, does not parse or names no known mode is ("malformed", ...): the board itself would refuse it."""
    path = Path(home) / "board-route.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "", ""
    except OSError as e:
        return "malformed", f"cannot be read ({e}): fix or remove it"
    try:
        route = json.loads(raw)
    except ValueError:
        return "malformed", "is not JSON: fix or remove it"
    mode = route.get("mode") if isinstance(route, dict) else None
    if mode == "hub":
        return "hub", f"sprint mode does not support hub-routed repos yet ({path.name} says mode `hub`)"
    if mode != "local":
        return "malformed", "`mode` is `local` or `hub`: fix or remove it"
    return "", ""


def ceiling_model(home: Path):
    """The ceiling model of the repo's model-optimization mapping, None when the mapping is off or names no Claude lead.
    Raises ValueError when the config is unreadable (a refusal, not a pass); the message is the problem, without the file."""
    path = Path(home) / "model-optimization.json"
    if not path.is_file():
        return None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        if cfg.get("enabled") is not True:
            return None
        mapping = cfg["harnesses"]["claude"]
        model = mapping["choices"][mapping["ceiling"]]["model"]
    except KeyError:
        return None
    except (OSError, ValueError, TypeError, AttributeError) as e:
        raise ValueError(f"is unreadable ({e})")
    if model is not None and not isinstance(model, str):
        raise ValueError("is unreadable (the ceiling model is not a string)")
    return model


def same_model(a: str, b: str) -> bool:
    import dispatch_guard
    return dispatch_guard.same_model(a, b)


def model_family(model: str) -> str:
    """The family of a model name, "haiku", "sonnet" or "opus" (`opus[1m]`, `claude-haiku-4-5`), "" for any other name."""
    low = str(model).lower()
    return next((f for f in ("haiku", "sonnet", "opus") if f in low), "")


def lead_without_worker(home: Path, model: str, effort: str) -> str:
    """The refusal text when the orchestrator pair `model`/`effort` could dispatch no worker under the repo's own dispatch rule, else
    "". The rule is the guard's: with the model-optimization mapping on, a worker is a choice of the claude mapping for which
    `worker_refusal` (the one `select` and the dispatch guard apply, read-only here) finds nothing against the lead pair, whose
    rank is the ceiling's. Where the mapping does not judge (off, no claude harness, does not validate, or `--model` is not its
    ceiling) the rule itself is applied, with the families haiku < sonnet < opus: a same-model worker runs at strictly lower effort,
    a lower-model worker at up to `high`, so the lowest family at the lowest effort `--effort` accepts has none. An unknown model:
    nothing is said."""
    import dispatch_guard
    engine = dispatch_guard._engine()
    try:
        if engine is None:
            raise LookupError
        config = engine.load_config(Path(home))
        mapping = (config.get("harnesses") or {}).get("claude") if config.get("enabled") is True else None
        if not isinstance(mapping, dict):
            raise LookupError
        ceiling = mapping["choices"][mapping["ceiling"]]
        if not dispatch_guard.same_model(model, ceiling["model"]):
            raise LookupError
        models = mapping["catalog"]["models"]
        for choice in mapping["choices"].values():
            if engine.worker_refusal(choice, model, effort, ceiling, engine.has_no_effort_levels(models.get(choice["model"]))) is None:
                return ""
    except Exception:
        if model_family(model) == "haiku" and effort == EFFORTS[0]:
            return (f"--model {model} --effort {effort}: haiku is the lowest model family and {effort} the lowest effort, so the "
                    "lead has no worker pair (a worker on the lead's model must run at lower effort, a lower model does not exist) "
                    "and every dispatch would be refused; raise --effort (medium or above), or use a higher model (sonnet, opus)")
        return ""
    return (f"--model {model} --effort {effort} leaves the lead no worker pair strictly below it in this repo's model-optimization "
            "mapping (a worker on the lead's model runs at lower effort, a lower model at any effort up to high): every dispatch "
            "would be refused; raise --effort, or choose a model with a lower tier")


def claude_in_path(path: "str | None") -> "str | None":
    """The claude executable `which` finds on this PATH string: an .exe, or the one an npm shim sits beside (a .cmd shim would
    put the prompt through cmd.exe quoting)."""
    found = shutil.which("claude", path=path)
    if not found:
        return None
    if found.lower().endswith(".exe"):
        return found
    shim = Path(found).resolve().parent
    for cand in (shim / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe",
                 shim / "claude.exe"):
        if cand.is_file():
            return str(cand)
    return None if sys.platform == "win32" else found


def claude_in_dir(folder) -> "str | None":
    """claude.exe in one folder: directly, or in the npm package folder below it (`node_modules/@anthropic-ai/claude-code/bin`)."""
    folder = Path(folder)
    for cand in (folder / "claude.exe", folder / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"):
        if cand.is_file():
            return str(cand)
    return None


def env_lookup(env, name: str) -> "str | None":
    for k, v in env.items():
        if k.upper() == name.upper():
            return v
    return os.environ.get(name)


def expand_vars(text: str, env) -> str:
    """`%NAME%` in a registry value, looked up in env then in this process; an unknown name is left as written."""
    return re.sub(r"%([^%]+)%", lambda m: env_lookup(env, m.group(1)) or m.group(0), text)


def registry_path(env=None) -> str:
    """The Machine and User `Path` from the Windows registry, expanded and joined with `;` ("" off Windows or when unreadable): what a
    fresh terminal would have, whatever PATH this process inherited."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    parts = []
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            parts.append(expand_vars(value, env or os.environ))
    return ";".join(parts)


def claude_known_folders(env) -> list:
    """Where the install methods put claude.exe: the npm global folder (`%APPDATA%/npm`, with the package below it) and the native
    installer's `%USERPROFILE%/.local/bin` (code.claude.com/docs/en/setup)."""
    profile = env_lookup(env, "USERPROFILE") or str(Path.home())
    appdata = env_lookup(env, "APPDATA") or str(Path(profile) / "AppData" / "Roaming")
    return [Path(appdata) / "npm", Path(profile) / ".local" / "bin"]


def path_entries(path: "str | None") -> list:
    return [e.strip().strip('"') for e in (path or "").split(os.pathsep) if e.strip()]


def find_claude(env) -> "str | None":
    """The claude executable: on PATH first, then on the PATH rebuilt from the registry, then in the known install folders."""
    found = claude_in_path(env.get("PATH"))
    if found:
        return found
    for folder in [*path_entries(registry_path(env)), *claude_known_folders(env)]:
        found = claude_in_dir(folder)
        if found:
            return found
    return None


def claude_not_found(env) -> str:
    """The refusal when find_claude comes back empty: it names every place that was tried."""
    folders = ", ".join(str(f) for f in claude_known_folders(env))
    return ("the claude executable (claude.exe) was not found on PATH, on the PATH rebuilt from the registry (Machine and User Path), "
            f"or in the install folders {folders}")


def claude_on_path(env, claude: "str | None") -> dict:
    """env with the folder holding `claude` first on its PATH when `claude` is an absolute path PATH does not reach, so the session's
    own `claude` calls and hooks work too. Any other env comes back as a copy."""
    out = dict(env)
    if claude and Path(claude).is_absolute() and not claude_in_path(env.get("PATH")):
        key = next((k for k in out if k.upper() == "PATH"), "PATH")
        folder = str(Path(claude).parent)
        out[key] = os.pathsep.join([folder, *path_entries(out.get(key))])
    return out


def repaired_path(env) -> str:
    """env's PATH with every registry Path entry it lacks appended (same-folder spellings compared case-insensitively)."""
    have = path_entries(env.get("PATH"))
    seen = {os.path.normcase(os.path.normpath(e)) for e in have}
    for e in path_entries(registry_path(env)):
        norm = os.path.normcase(os.path.normpath(e))
        if norm not in seen:
            seen.add(norm)
            have.append(e)
    return os.pathsep.join(have)


HOOK_SCRIPTS_MARK = ".claude/skills/gitos/scripts/"      # the self-locating bootstrap every gitos hook carries (WO-166)


def hook_commands(root: "Path | None") -> list:
    """The distinct `command` values of the gitos hooks in `<root>/.claude/settings.json`, in file order ([] when the file is absent,
    unreadable or registers none): a gitos hook is one whose args hold the bootstrap that loads a script from the skill folder."""
    out = []
    try:
        doc = json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return out
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    for groups in (hooks.values() if isinstance(hooks, dict) else ()):
        for group in (groups if isinstance(groups, list) else ()):
            for h in (group.get("hooks") if isinstance(group, dict) and isinstance(group.get("hooks"), list) else ()):
                if isinstance(h, dict) and isinstance(h.get("command"), str) and h["command"] not in out                         and any(isinstance(a, str) and HOOK_SCRIPTS_MARK in a for a in (h.get("args") or ())):
                    out.append(h["command"])
    return out


def resolve_command(command: str, path: "str | None") -> "str | None":
    """Where a hook `command` runs from: itself when it is an absolute file, else the first PATH folder holding it (with a PATHEXT
    suffix too). Not `shutil.which`: on Windows that searches the current directory first, which a session does not."""
    if Path(command).is_absolute():
        return command if Path(command).is_file() else None
    exts = [""] + [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for folder in path_entries(path):
        for ext in exts:
            cand = Path(folder) / (command + ext)
            if cand.is_file():
                return str(cand)
    return None


def session_path(args, env) -> str:
    """The PATH the session will get: this env's PATH, and with --window the registry Path entries it lacks appended (launch_window)."""
    return repaired_path(env) if getattr(args, "window", False) else (env.get("PATH") or "")


def hook_problem(args, env, root: "Path | None") -> str:
    """One sentence naming a gitos hook command the session could not run, and where it looked; "" when each can run (WO-166)."""
    if root is None:
        return ""
    path = session_path(args, env)
    for command in hook_commands(root):
        if not resolve_command(command, path):
            folders = path_entries(path)
            where = f"looked in {len(folders)} folder{'' if len(folders) == 1 else 's'} on PATH"                 + (f", first {', '.join(folders[:2])}" if folders else "")
            return (f"the gitos hook command `{command}` in .claude/settings.json is not found on the PATH the session will get "
                    f"({where}{'' if getattr(args, 'window', False) else '; --window adds the registry Path'}), so every hook would "
                    "fail or go silent: re-run scaffold.py in the repo to rewrite it to the `py` launcher, or put its folder on PATH")
    return ""


def optimization_engine():
    """model_optimization.py (the hook writer's shared helper), or None."""
    import dispatch_guard
    return dispatch_guard._engine()


def registry_paths() -> tuple:
    engine = optimization_engine()
    return engine.registry_paths() if engine else ("", "")


def path_advisory_line(platform: str = sys.platform) -> str:
    """The one advisory line when the registry PATH is near the length Windows drops, else ""."""
    engine = optimization_engine() if platform == "win32" else None
    return engine.path_advisory(registry_paths()) if engine else ""


def home_file(home: Path, rel: str) -> str:
    """How a repo file is named in a refusal: its path below the repo root's home folder name (`.gitos/worktrees.json`)."""
    return f"{Path(home).name}/{rel}"


def guard_config(home: Path) -> "tuple[dict | None, str]":
    """The repo's guard command, `<home>/sprint-guard.json`: `{"command": ["argv", ...], "timeout_s": N}` (`timeout_s` optional,
    default 120, at most 900; `settle_s`, 0 to 600, and `busy_max_s`, 1 to 3600, optional and in the result only when present;
    no other key). -> (config, "") for a sound file, (None, "") when there is no file, and
    (None, the problem) when it cannot be read, does not parse or has the wrong shape (a malformed input: `input_problems`
    refuses it). The command is an argv run with no shell; the engine ships no guard and gives it no meaning."""
    path = Path(home) / GUARD_FILE
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, ""
    except OSError as e:
        return None, f"cannot be read ({e})"
    try:
        cfg = json.loads(raw)
    except ValueError as e:
        return None, f"is not valid JSON ({str(e).splitlines()[0] if str(e) else type(e).__name__})"
    if not isinstance(cfg, dict):
        return None, "is not a JSON object"
    extra = sorted(set(cfg) - set(GUARD_KEYS))
    if extra:
        return None, f"has an unknown key `{extra[0]}` (only {', '.join(f'`{k}`' for k in GUARD_KEYS)})"
    cmd = cfg.get("command")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
        return None, "`command` is a non-empty list of non-empty strings (the argv, run with no shell)"
    t = cfg.get("timeout_s", GUARD_TIMEOUT_DEFAULT)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 < t <= GUARD_TIMEOUT_MAX:
        return None, f"`timeout_s` is a number above 0 and at most {GUARD_TIMEOUT_MAX}"
    out = {"command": list(cmd), "timeout_s": t}
    for key, least, most in GUARD_NUMBER_KEYS:
        if key in cfg:
            v = cfg[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not least <= v <= most:
                return None, f"`{key}` is a number of seconds from {least} to {most}"
            out[key] = v
    return out, ""


def read_busy(home: Path, sid: str = "") -> "tuple[str, float, str]":
    """The BUSY lease file `<home>/sprint/BUSY`, read fresh: one line, an ISO-8601 UTC deadline (a `Z` or an offset is read, a
    bare time is taken as UTC). -> ("none", 0, "") when there is no file, ("lease", the deadline in epoch seconds, the line) for a
    sound one and ("bad", 0, why) for one that cannot be read or does not parse: that is no lease."""
    try:
        raw = (compact_restore.sprint_dir(home, sid) / BUSY_FILE).read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        return "none", 0.0, ""
    except OSError as e:
        return "bad", 0.0, f"cannot be read ({e})"
    line = (raw.strip().splitlines() or [""])[0].strip()
    try:
        when = datetime.fromisoformat(line[:-1] + "+00:00" if line.endswith(("Z", "z")) else line)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return "lease", when.timestamp(), line
    except (ValueError, OverflowError, OSError):
        return "bad", 0.0, f"is not an ISO-8601 deadline ({plain_line(line)[:40]!r})"


def busy_identity(home: Path, sid: str = "") -> "tuple[str, int] | None":
    """What makes one BUSY file this lease and not another: its content and modification time; None when there is no readable file."""
    path = compact_restore.sprint_dir(home, sid) / BUSY_FILE
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace"), path.stat().st_mtime_ns
    except OSError:
        return None


def input_problems(home: Path, listed: tuple = ()) -> list:
    """Every repo file the driver parses that is malformed, as (file, problem) pairs; [] when all are sound. The files are
    `worktrees.json` (through `worktree.load_layout`), `board/board.json`, `board-route.json`, `model-optimization.json`,
    `sprint-guard.json` (`guard_config`) and the `sprint:` value of each candidate order (the `listed` orders of `--orders`,
    else every open order): anything but `ready` or `no` is refused, an empty value is no mark. A file that does not exist is
    not malformed. Read only."""
    import worktree
    home = Path(home)
    out = []
    try:
        worktree.load_layout(home)
    except worktree.LayoutError as e:
        text = str(e)
        lead = f"{worktree.LAYOUT_FILE}: "
        out.append((home_file(home, worktree.LAYOUT_FILE), text[len(lead):] if text.startswith(lead) else text))
    except (OSError, ValueError) as e:
        out.append((home_file(home, worktree.LAYOUT_FILE), f"cannot be read ({e})"))
    board = home / "board" / "board.json"
    if board.is_file():
        try:
            cfg = load_json(board)                          # another driver may be adding its tab: read again before refusing
            problem = "" if isinstance(cfg, dict) else "is not a JSON object"
        except (OSError, ValueError) as e:
            problem = f"is not valid JSON ({str(e).splitlines()[0] if str(e) else type(e).__name__})"
        if problem:
            out.append((home_file(home, "board/board.json"), problem))
    kind, text = route_problem(home)
    if kind == "malformed":
        out.append((home_file(home, "board-route.json"), text))
    try:
        ceiling_model(home)
    except ValueError as e:
        out.append((home_file(home, "model-optimization.json"), str(e)))
    _, guard_problem = guard_config(home)
    if guard_problem:
        out.append((home_file(home, GUARD_FILE), guard_problem))
    try:
        wanted = {int(ref[3:]) for ref in listed}
        for nnn, rel, value in slog.sprint_mark_values(home):
            if (not wanted or nnn in wanted) and value.lower() not in ("", *SPRINT_MARKS):
                out.append((home_file(home, rel), f"`sprint: {value}` is not `ready` or `no`: set one of them or remove the key"))
    except Exception as e:                    # an order file the ledger cannot read is a refusal, not a pass
        out.append((home_file(home, "work-orders"), f"cannot be read ({type(e).__name__}: {e})"))
    return out


def preflight(args, env, root: "Path | None", home: "Path | None", platform: str = sys.platform,
              claude_json: "Path | None" = None, claude: "str | None" = None) -> list:
    """Every reason nothing may be launched, one sentence each; [] when the sprint may start."""
    sid = getattr(args, "id", "") or ""
    STATE_REL = Path("sprint") / sid / "STATE.md" if sid else globals()["STATE_REL"]   # this sprint's own state file
    if home is None:
        return [f"no gitos home found at {args.repo or Path.cwd()} (.gitos/ or a legacy home): run /gitos there first"]
    out = []
    if not slog.is_gitos_home(home):
        return [f"{home} is not a gitos home (no work-orders/ folder, no INDEX.md beside a sprint/ folder): the sprint's log and state "
                "would be written there"]
    if platform != "win32":
        out.append("sprint mode drives the session through the Windows console; other platforms are not supported yet")
    bad = input_problems(home, args.orders)
    out.extend(f"{name}: {problem}" for name, problem in bad)
    route_kind, route_text = route_problem(home)
    if route_kind == "hub":
        out.append(route_text)
    if not (home / "board" / "board.py").is_file() or not (home / "board" / "board.json").is_file():
        out.append(f"{home / 'board'} holds no board.py and board.json: the Stop card needs the owner board "
                   "(run /gitos upgrade there)")
    ok, why = is_trusted(root, claude_json or claude_json_path(env))
    if not ok:
        out.append(f"{why}: open Claude Code once in {root} itself (the repo root, not a parent folder) and accept the trust prompt "
                   "(a session would wait behind it unattended); this script never edits that file")
    stop = compact_restore.sprint_dir(home, sid) / "STOP"
    if stop.exists():
        out.append(f"{stop} exists: read it, then delete it to start a sprint")
    if (home / STATE_REL).exists():
        out.append(f"{home / STATE_REL} exists from an earlier sprint: fold it in a normal orchestrator window first "
                   "(its first action folds it into RESUME.md)")
    window = model_window(args.model)
    if args.autocompact < MIN_WINDOW:
        out.append(f"--autocompact {args.autocompact} is below {MIN_WINDOW}: a window that small thrashes (compacts "
                   "again and again) on a repo's baseline context")
    elif args.autocompact > window:
        out.append(f"--autocompact {args.autocompact} is above the {window}-token context of --model {args.model}")
    try:
        ceiling = ceiling_model(home)
    except ValueError:                        # already refused above, with its file named
        ceiling = None
    try:
        mismatch = bool(ceiling) and not same_model(args.model, ceiling)
    except Exception as e:                    # a model name the guard cannot read is a refusal, not a traceback
        out.append(f"the model-optimization ceiling {ceiling!r} could not be compared with --model ({e})")
        mismatch = False
    if mismatch:
        out.append(f"--model {args.model} is not the ceiling model of this repo's model-optimization mapping "
                   f"({ceiling}): dispatches would be refused")
    why = lead_without_worker(home, args.model, args.effort)
    if why:
        out.append(why)
    out.extend(sprint_conflicts(home, sid, tuple(args.orders)))
    if sid and root is not None:
        out.extend(worktree_problems(root, home, sid))
    if sid and not args.orders:
        out.append("--id needs --orders: a named sprint works only the orders it lists")
    marks = slog.open_order_marks(home)
    if args.orders:
        for ref in args.orders:
            if int(ref[3:]) not in marks:
                out.append(f"--orders {ref} is not an open work-order (it is resolved, parked or missing)")
            elif marks.get(int(ref[3:])) == "no":
                out.append(f"--orders {ref} is marked `sprint: no` in its front matter: remove the mark first, or leave it "
                           "out of --orders")
            else:
                why = slice_problem(home, ref)
                if why:
                    out.append(f"--orders {ref} is refused: {why}")
    elif "ready" not in marks.values():
        out.append("no order is marked `sprint: ready`; prepare orders in a normal orchestrator window "
                   "(references/orchestrator/sprint-prep.md), or pass --orders")
    if not args.orders and "ready" in marks.values() and not candidate_orders((), home):
        out.append("no order marked `sprint: ready` has a slice to dispatch: write or ready its slices in a normal orchestrator "
                   "window (references/orchestrator/sprint-prep.md), or pass --orders")
    for d in args.add_dir:
        if not Path(d).is_dir():
            out.append(f"--add-dir {d} is not a folder")
    if platform == "win32" and not (claude or find_claude(env)):
        out.append(claude_not_found(env))
    if getattr(args, "window", False) and platform != "win32":
        out.append("--window opens a PowerShell console and works on Windows only")
    if platform == "win32":
        why = hook_problem(args, env, root)
        if why:
            out.append(why)
    return out


# ------------------------------------------------------------------------------------------------ launch
def strip_env(env) -> dict:
    """The child's environment: the driver's without any CLAUDE* or MCP_* variable (an inherited child-session marker
    turns transcripts off and an inherited compaction window beats the flag), the operator settings in KEEP_ENV excepted."""
    return {k: v for k, v in env.items()
            if k.upper() in KEEP_ENV or not k.upper().startswith(HARNESS_PREFIXES)}


def child_env(env, home: Path, sid: str = "", worktree: "Path | None" = None, orders: tuple = ()) -> dict:
    out = strip_env(env)
    out["GITOS_SPRINT"] = "1"                    # set after the strip: compact_restore.py reads it
    out["GITOS_SPRINT_HOME"] = str(home)         # the main checkout's home: sprint_log.py and the hooks find `sprint/` there
    for k in (compact_restore.SPRINT_ID_ENV, compact_restore.SPRINT_PID_ENV, compact_restore.SPRINT_WORKTREE_ENV,
              compact_restore.SPRINT_ORDERS_ENV):
        out.pop(k, None)                         # the exclusive sprint never inherits a named one's id
    out[compact_restore.SPRINT_PID_ENV] = str(os.getpid())   # every sprint session: its driver's pid, the hooks end the session when it is gone
    if orders:                                   # the orders this sprint works: its Stop hook asks about no other
        out[compact_restore.SPRINT_ORDERS_ENV] = ",".join(orders)
    if sid:                                      # a named sprint: its id (the hooks and the merge lock read it with the pid)
        out[compact_restore.SPRINT_ID_ENV] = sid
        if worktree is not None:                 # and the worktree it runs in (the hooks speak there, in a linked worktree)
            out[compact_restore.SPRINT_WORKTREE_ENV] = str(worktree)
    return out


def start_prompt(skill_dir: Path = SKILL_DIR, orders: tuple = (), sid: str = "", worktree: "Path | None" = None,
                 home: "Path | None" = None) -> str:
    """One line, no quote marks: the router, the words `sprint mode`, the rules file, the log command and, once the candidate
    orders are resolved, that list."""
    s = Path(skill_dir).as_posix()
    allow = (f" Candidate orders for this sprint (the operator's --orders list, or else the open orders marked sprint: "
             f"ready): {', '.join(orders)}. Take no other order." if orders else "")
    if sid:
        folder = f"{Path(home).as_posix()}/sprint/{sid}/" if home is not None else f"sprint/{sid}/ under the gitos home"
        allow += (f" You are sprint {sid}, one of possibly several in this home: your state, log and signals are in {folder} "
                  f"(STATE.md, STOP, ROTATE, BUSY), never in sprint/ itself and never in your worktree; GITOS_SPRINT_ID={sid} is set, "
                  f"so sprint_log.py logs to your own log. The sprint's owner board is $GITOS_SPRINT_HOME/board/board.py: run "
                  f"python $GITOS_SPRINT_HOME/board/board.py for every card and never the board.py of your worktree.")
        if worktree is not None:
            allow += (f" You work in your own git worktree {Path(worktree).as_posix()} on branch {sprint_branch(sid)}: resolve each order "
                      f"there and commit it there; an order reaches the main branch only through python {s}/scripts/worktree.py land, "
                      "never by merging, committing or editing in the main checkout. "
                      "Land with worktree.py land --wait <seconds>; a land refusal is a Stop card, never a retry loop.")
    return (f"/gitos resume, sprint mode: an unattended run started by the sprint driver, operator away. "
            f"The gitos skill is at {s}; read {s}/references/orchestrator/sprint.md and follow it. "
            f"Reply with the marker line only (orchestrator/sprint.md, Output). "
            f"Log progress with: python {s}/scripts/sprint_log.py add KIND MESSAGE --ref WO-N, where KIND is start "
            f"when you begin an order (log it after the Stop card and STOP file check for that order, never before), done when you "
            f"resolve it, or note, and MESSAGE is one short line.{allow}")


def build_command(claude: str, args, session_id: str, prompt: "str | None" = None, worktree: "Path | None" = None,
                  home: "Path | None" = None) -> list:
    """The argument list (no shell). The prompt comes first so that the variadic --add-dir cannot swallow it. No permission mode
    is ever passed (the operator's own applies)."""
    cmd = [claude, prompt or start_prompt(orders=args.orders, sid=getattr(args, "id", "") or "", worktree=worktree, home=home),
           "--model", args.model, "--effort", args.effort,
           "--autocompact", str(args.autocompact), "--session-id", session_id]
    for d in args.add_dir:
        cmd += ["--add-dir", str(d)]
    return cmd


LOG_NAME_MAX = 200      # the CLI's longest project folder name before it shortens it (observed, `claude` 2.1.332)


def log_name_hash(text: str) -> str:
    """The CLI's short hash of a path: a 32-bit string hash over UTF-16 code units (h = 31*h + unit), absolute value, base 36."""
    raw, h = text.encode("utf-16-le"), 0
    for i in range(0, len(raw), 2):
        h = (h * 31 + int.from_bytes(raw[i:i + 2], "little")) & 0xFFFFFFFF
    h = h - (1 << 32) if h >= 1 << 31 else h
    n, digits = abs(h), ""
    while n:
        n, r = divmod(n, 36)
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + digits
    return digits or "0"


def project_log_dir(root: Path, env) -> Path:
    """The folder the CLI keeps a repo's session logs in: every character that is not a letter or digit becomes `-`; a name
    longer than LOG_NAME_MAX is cut there and `-` plus `log_name_hash` of the whole path is added (probed, not documented)."""
    base = Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    path = str(Path(root).resolve())
    name = re.sub(r"[^A-Za-z0-9]", "-", path)
    if len(name) > LOG_NAME_MAX:
        name = f"{name[:LOG_NAME_MAX]}-{log_name_hash(path)}"
    return base / name


# ------------------------------------------------------------------------------------------------ windows plumbing
def _k32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def console_send(text: str, enter: bool) -> None:
    """Type `text` (then Enter) into this process's console input, which the session shares. Windows only."""
    from ctypes import wintypes

    class KeyEvent(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD), ("wVirtualKeyCode", wintypes.WORD),
                    ("wVirtualScanCode", wintypes.WORD), ("UnicodeChar", wintypes.WCHAR),
                    ("dwControlKeyState", wintypes.DWORD)]

    class Union(ctypes.Union):
        _fields_ = [("KeyEvent", KeyEvent)]

    class InputRecord(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", Union)]

    k32 = _k32()
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise OSError(f"cannot open the console input (error {ctypes.get_last_error()})")
    try:
        chars = list(text) + (["\r"] if enter else [])
        recs = (InputRecord * (2 * len(chars)))()
        for i, ch in enumerate(chars):
            vk = 0x0D if ch == "\r" else 0
            for j, down in enumerate((True, False)):
                r = recs[2 * i + j]
                r.EventType = 1
                r.Event.KeyEvent = KeyEvent(down, 1, vk, 0, ch, 0)
        written = wintypes.DWORD(0)
        if not k32.WriteConsoleInputW(h, recs, len(recs), ctypes.byref(written)):
            raise OSError(f"WriteConsoleInputW failed (error {ctypes.get_last_error()})")
    finally:
        k32.CloseHandle(h)


def process_table() -> dict:
    """{pid: (parent pid, image name)} of every process now."""
    if sys.platform != "win32":
        out = subprocess.run(["ps", "-e", "-o", "pid=,ppid=,comm="], capture_output=True, text=True).stdout
        table = {}
        for line in out.splitlines():
            p = line.split(None, 2)
            if len(p) == 3 and p[0].isdigit() and p[1].isdigit():
                table[int(p[0])] = (int(p[1]), p[2].strip())
        return table
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    k32 = _k32()
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    table = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return table


def descendants(pid: int, table: dict) -> dict:
    """{pid: image name} of every process below `pid` in a process table."""
    found: dict = {}
    todo = [pid]
    while todo:
        cur = todo.pop()
        for p, (parent, name) in table.items():
            if parent == cur and p not in found and p != pid:
                found[p] = name
                todo.append(p)
    return found


def kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    for p in [*descendants(pid, process_table()), pid]:
        try:
            os.kill(p, 9)
        except OSError:
            pass


def survivors_of(snapshot: dict, table: dict) -> dict:
    """The processes of `snapshot` ({pid: name}) still in `table` under the same name (a reused pid is not one)."""
    return {p: n for p, n in snapshot.items() if p in table and table[p][1] == n}


# ------------------------------------------------------------------------------------------------ the loop's seams
class Ops:
    """Everything the loop does to the world, so a test can replace it. The defaults are the real thing."""

    sid = ""                                   # the named sprint this driver runs, set by `Sprint`
    orders = ()                                # that sprint's claimed `--orders` (WO-NNN), set by `Sprint`: what its progress is counted over
    work_root = None                           # a named sprint's worktree and its home: where the session runs and the ledger is read
    work_home = None                           # (None: the exclusive sprint, which runs in `root`)

    def __init__(self, root: Path, home: Path, env, claude: str):
        self.root, self.home, self.env, self.claude = root, home, env, claude

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def now(self) -> float:
        return time.time()

    def say(self, text: str) -> None:
        print(text, flush=True)

    def launch(self, cmd: list, env: dict):
        return subprocess.Popen(cmd, cwd=str(self.work_root or self.root), env=env)

    def send_exit(self) -> None:
        console_send("/exit", enter=False)
        time.sleep(KEY_GAP_SECONDS)
        console_send("", enter=True)

    def kill_tree(self, pid: int) -> None:
        kill_tree(pid)

    def table(self) -> dict:
        return process_table()

    def mtime(self, path: Path) -> "float | None":
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def git(self, *argv: str) -> "subprocess.CompletedProcess | None":
        try:
            return subprocess.run(["git", "-C", str(self.work_root or self.root), "-c", "core.quotepath=off", *argv], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None

    def snapshot(self, since: str = "") -> tuple:
        """What a sprint has to show for itself: (open orders, resolved orders, branch tips, HEAD, whether a commit
        since `since` (an earlier HEAD, "" for none) touched anything but RESUME, INDEX and the board). A checkpoint commit
        (the regenerated INDEX and board) moves HEAD before a rotation, so HEAD alone is not progress. The tips are the local branches matching `wo-*` and
        the `integration` and `branches` globs of the repo's own `<home>/worktrees.json` (see `layout_globs`)."""
        cp = self.git("rev-parse", "HEAD")
        head = cp.stdout.strip() if cp is not None and cp.returncode == 0 else ""
        tips = self.branch_tips()
        try:
            resolved = tuple(sorted(x.name for x in (Path(self.work_home or self.home) / "work-orders" / "resolved").iterdir()))
        except OSError:
            resolved = ()
        opened = tuple(sorted(slog.open_orders(self.work_home or self.home)))
        if self.sid:
            opened, resolved, tips = self.own_progress(opened, resolved, tips)
        return (opened, resolved, tips, head, self.substantive(since, head))

    def own_progress(self, opened: tuple, resolved: tuple, tips: tuple) -> tuple:
        """A named sprint's share of `snapshot`'s first three fields: the open and resolved orders among its claimed `--orders`, and the
        tips of its own `sprint-<id>` branch and of its claimed orders' branches (`wo-NNN` and `wo-NNN-<slice>`). Another sprint's orders,
        branches and landings are not this sprint's progress."""
        mine = {int(re.sub(r"\D", "", o) or -1) for o in self.orders}
        num = lambda text, pat: int(m.group(1)) if (m := re.match(pat, text)) else -1          # noqa: E731
        opened = tuple(o for o in opened if num(str(o), r"\D*(\d+)") in mine)
        resolved = tuple(r for r in resolved if num(r, r"WO-(\d+)") in mine)
        fmt = "--format=%(refname) %(objectname)"
        area = self.worker_branches()
        cp = self.git("for-each-ref", fmt, "refs/heads/")
        own = {x for x in cp.stdout.splitlines() if x and (x.split(" ")[0] == f"refs/heads/sprint-{self.sid}"
               or x.split(" ")[0] in area
               or num(x.split(" ")[0][len("refs/heads/"):], r"wo-(\d+)(?:-|$)") in mine)} if cp is not None and cp.returncode == 0 else set()
        return opened, resolved, tuple(sorted(own))

    def worker_branches(self) -> set:
        """`refs/heads/<name>` of every branch checked out in a worktree under `<sprint worktree>.worktrees/`, where workers made from
        this sprint's worktree live, whatever the branch is called."""
        cp = self.git("worktree", "list", "--porcelain")
        if cp is None or cp.returncode != 0 or self.work_root is None:
            return set()
        norm = lambda p: os.path.normcase(os.path.realpath(p))                                     # noqa: E731
        area = norm(str(self.work_root) + ".worktrees") + os.sep
        found, path = set(), ""
        for line in cp.stdout.splitlines():
            if line.startswith("worktree "):
                path = norm(line[len("worktree "):])
            elif line.startswith("branch ") and path.startswith(area):
                found.add(line[len("branch "):].strip())
        return found

    def branch_tips(self) -> tuple:
        """`refs/heads/<name> <sha>`, sorted, of every local `wo-*` branch (git's own pattern, as before) and of every local
        branch matching a glob the repo declares (`layout_globs`)."""
        fmt = "--format=%(refname) %(objectname)"
        cp = self.git("for-each-ref", fmt, "refs/heads/wo-*")
        tips = {x for x in cp.stdout.splitlines() if x} if cp is not None and cp.returncode == 0 else set()
        globs = layout_globs(self.home)
        if globs:
            cp = self.git("for-each-ref", fmt, "refs/heads/")
            if cp is not None and cp.returncode == 0:
                tips |= {x for x in cp.stdout.splitlines()
                         if x and any(fnmatch.fnmatchcase(x.split(" ")[0][len("refs/heads/"):], g) for g in globs)}
        return tuple(sorted(tips))

    def substantive(self, since: str, head: str) -> bool:
        """Whether a commit in `since..head` touches a path other than <home>/RESUME.md, <home>/INDEX.md, <home>/board/ and the
        sprint's own state file (git-ignored, so none normally does).
        Unknown (git failed, `since` gone) counts as yes: a sprint is not called stuck on what could not be read."""
        STATE_REL = Path("sprint") / self.sid / "STATE.md" if self.sid else globals()["STATE_REL"]   # this sprint's own state file
        if not since or not head or since == head:
            return False
        cp = self.git("log", "--name-only", "--format=", "--relative", f"{since}..{head}")
        if cp is None or cp.returncode != 0:
            return True
        try:
            rel = Path(self.work_home or self.home).resolve().relative_to(Path(self.work_root or self.root).resolve()).as_posix()
        except ValueError:
            rel = None
        ours = (f"{rel}/RESUME.md", f"{rel}/INDEX.md", f"{rel}/{STATE_REL.as_posix()}") if rel else ()
        return any(line.strip() and line.strip() not in ours and not (rel and line.strip().startswith(f"{rel}/board/"))
                   for line in cp.stdout.splitlines())

    def guard(self, argv: list, timeout_s: float, env: dict) -> "tuple[bool, str, str]":
        """Run the repo's guard command: no shell, the repo root as the working directory, `env` as the environment, no
        console input. Only exit 0 passes. -> (passed, what happened ("exit 1", "timed out after 5 s", "could not be run
        (...)"), the last lines of its output). A command that outlives `timeout_s` has its process tree killed."""
        try:
            proc = subprocess.Popen(argv, cwd=str(self.root), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        except (OSError, ValueError) as e:
            return False, f"could not be run ({e})", ""
        try:
            out, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.kill_tree(proc.pid)
            try:
                out, _ = proc.communicate(timeout=10)
            except subprocess.SubprocessError:
                out = ""
            return False, f"timed out after {timeout_s:g} s", guard_tail(out)
        return proc.returncode == 0, f"exit {proc.returncode}", guard_tail(out)

    def board(self, *argv: str) -> "subprocess.CompletedProcess":
        return subprocess.run([sys.executable, str(self.home / "board" / "board.py"), *argv], cwd=str(self.root),
                              capture_output=True, text=True, timeout=60)

    def cost(self, sessions: list) -> str:
        return slog.sprint_cost(self.work_root or self.root, sessions, self.env)

    def worktree_orders(self) -> list:
        try:
            out = subprocess.run(["git", "-C", str(self.root), "worktree", "list", "--porcelain"], capture_output=True,
                                 text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return re.findall(r"^branch refs/heads/wo-(\d+)", out, re.M)


def plain_line(value) -> str:
    """One line of plain text: markup characters and control characters removed, whitespace collapsed. A value that came from
    a repo file or a command's output cannot carry markup into the state file."""
    text = "".join(" " if c in "<>" or ord(c) < 32 or ord(c) == 127 else c for c in str(value))
    return " ".join(text.split())


def guard_tail(output: str) -> str:
    """The last GUARD_TAIL_LINES non-empty lines of a command's output as one plain line, cut at GUARD_TAIL_CHARS (the end is kept)."""
    lines = [x for x in (plain_line(x) for x in str(output or "").splitlines()) if x]
    return " | ".join(lines[-GUARD_TAIL_LINES:])[-GUARD_TAIL_CHARS:]


def layout_globs(home: Path) -> tuple:
    """The branch-name globs the repo declares as its own work branches: the `integration` and `branches` lists of
    `<home>/worktrees.json`, read by `worktree.load_layout` as `worktree.py` reads them; nothing is built in. No file gives
    none; one that cannot be read gives none here, because `input_problems` has already refused it (before the first launch and
    at each rotation), so this never decides anything for a malformed file."""
    import worktree
    try:
        lay = worktree.load_layout(home)
        extra = [*lay["integration"], *lay["branches"]]
    except (OSError, ValueError, KeyError, worktree.LayoutError):
        extra = []
    return tuple(dict.fromkeys(extra))


def wait_quiet(path: Path, ops: Ops, quiet: float = QUIET_SECONDS, cap: float = QUIET_CAP_SECONDS) -> bool:
    """Wait until `path` (the session's log) has not changed for `quiet` seconds, at most `cap` seconds: a session that
    wrote its signal is still finishing its last reply. -> True when it went quiet, False at the cap."""
    start = ops.now()
    while True:
        m = ops.mtime(path)
        if m is None:                       # no log to watch: a plain pause
            ops.sleep(quiet)
            return True
        if ops.now() - m >= quiet:
            return True
        if ops.now() - start >= cap:
            return False
        ops.sleep(1.0)


def mid_turn(transcript: "Path | None", ops: Ops, quiet: float = QUIET_SECONDS) -> bool:
    """Whether the session's log was written within `quiet` seconds: it is in a turn, and a key typed into its console
    may land in a dialog (a permission prompt, a menu) instead of the prompt. No log to look at: not mid-turn."""
    m = ops.mtime(transcript) if transcript is not None else None
    return m is not None and ops.now() - m < quiet


def close_session(proc, ops: Ops, wait_s: float = EXIT_WAIT_SECONDS, transcript: "Path | None" = None) -> dict:
    """Close the session: `/exit` into the console, up to `wait_s` for it to leave, else kill its process tree; then check
    that nothing it started is left (killing what is). A session that is mid-turn (its `transcript` not quiet) is not
    typed into: it goes straight to the kill. -> {method, seconds, survivors: {pid: name}}."""
    before = descendants(proc.pid, ops.table())
    t0 = ops.now()
    if proc.poll() is not None:
        method = "already-exited"
    else:
        busy = mid_turn(transcript, ops)
        if not busy:
            try:
                ops.send_exit()
            except Exception:
                pass
            while proc.poll() is None and ops.now() - t0 < wait_s:
                ops.sleep(0.25)
        if proc.poll() is None:
            ops.kill_tree(proc.pid)
            method = "taskkill-/T-/F" + (" (session mid-turn, /exit not typed)" if busy else "")
            for _ in range(20):
                if proc.poll() is not None:
                    break
                ops.sleep(0.25)
        else:
            method = "graceful-/exit"
    left = {}
    for _ in range(12):
        left = survivors_of(before, ops.table())
        if not left:
            break
        ops.sleep(0.25)
    for pid in left:
        ops.kill_tree(pid)
    if left:
        ops.sleep(1.0)
        left = survivors_of(before, ops.table())
    return {"method": method, "seconds": round(ops.now() - t0, 1), "survivors": left}


# ------------------------------------------------------------------------------------------------ signals and notes
def parse_signal(text: str) -> "tuple[str, str]":
    """The first line of a STOP file: `<id>: <reason>` -> (id, reason). A line without a known id -> ("", the line)."""
    line = (text.strip().splitlines() or [""])[0].strip()
    m = re.match(r"^([a-z][a-z0-9-]*):\s*(.*)$", line)
    if m and m.group(1) in STOP_IDS:
        return m.group(1), m.group(2)
    return "", line


def read_first_line(path: Path) -> str:
    try:
        return (path.read_text(encoding="utf-8-sig", errors="replace").strip().splitlines() or [""])[0].strip()
    except OSError:
        return ""


def stuck(prev: "tuple | None", cur: tuple, streak: int) -> "tuple[bool, int]":
    """The no-progress cap: `streak` rotations in a row with nothing to show, `cur` and `prev` being `Ops.snapshot()` results.
    Progress is a change in the open orders, the resolved orders or a branch tip (`wo-*` and the repo's declared ones), or a commit (the snapshot's last
    field) that touches more than RESUME, INDEX and the board: a checkpoint commit before a rotation moves HEAD, so
    HEAD alone is not progress. -> (stuck, the new streak)."""
    same = prev is not None and cur[:3] == prev[:3] and not cur[4]
    streak = streak + 1 if same else 0
    return streak >= STUCK_AFTER, streak


def last_order(records: list, worktree_orders: list) -> str:
    """The order in progress when the sprint was cut: the last logged `start` with no `done` for it after, else the one
    open order worktree, else ''."""
    active = None
    for r in records:
        if r["kind"] == "start" and r.get("ref"):
            active = r["ref"]
        elif r["kind"] == "done" and r.get("ref") == active:
            active = None
    if active:
        return active
    return f"WO-{worktree_orders[0]}" if len(worktree_orders) == 1 else ""


def note_ref(order: str) -> str:
    """The order ref as it goes into the state file: one short line of plain characters (the ref comes from the model's `--ref`)."""
    return " ".join(REF_JUNK_RE.sub(" ", str(order)).split())[:ORDER_REF_MAX]


def note_to_log(home: Path, msg: str, sid: str = "") -> None:
    try:
        slog.add_record(home, "note", msg, sid=sid)
    except OSError:
        pass


STATE_HEADER = ("# STATE (sprint state)\n\nThe sprint's own state: the driver and the sprint's orchestrator write it, never RESUME.md. "
                "An interactive orchestrator folds it into RESUME.md at its first action and then moves it to "
                "`sprint/archive/` (references/orchestrator/first-action.md).\n\n")


def put_note(home: Path, mark: str, note: str, failed: str, sid: "str | None" = None) -> "Path | None":
    """Put `note` (the `mark` line, then one line) under `## Notes for the operator` in the sprint's state file,
    `<home>/sprint/STATE.md` (the rest of the file untouched; an earlier note carrying the same mark is replaced; no file or no
    such section: made). The driver writes only here and never to RESUME.md. The file is read, then replaced in one step (a temp
    file beside it, `os.replace`); when it cannot be read or replaced it is left exactly as it is and `failed` (what the note was
    about) goes to the sprint log instead (-> None)."""
    sid = SPRINT_ID if sid is None else sid          # the sprint this process drives (`Sprint.run` and `main` set it)
    path = compact_restore.sprint_dir(home, sid) / STATE_REL.name
    try:
        text = retry_denied(path.read_bytes).decode("utf-8-sig", errors="replace")
    except FileNotFoundError:
        text = STATE_HEADER
    except OSError as e:
        note_to_log(home, f"{STATE_REL.name} could not be read ({e}); {failed}", sid)
        return None
    eol = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n?" + re.escape(mark) + r"\n[^\n]*\n", "", text)
    m = re.search(r"^" + re.escape(NOTES_HEADING) + r"\b[^\n]*\n", text, re.M)
    if m:
        text = text[:m.end()] + "\n" + note + text[m.end():]
    else:
        text = text.rstrip("\n") + "\n\n" + NOTES_HEADING + "\n\n" + note
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".STATE-", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.replace("\n", eol).encode("utf-8"))
        replace_file(tmp, path)
    except OSError as e:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        note_to_log(home, f"{STATE_REL.name} could not be written ({e}); {failed}", sid)
        return None
    return path


def write_interrupted_note(home: Path, when: str, order: str, how: str, sid: str = "") -> "Path | None":
    """The interrupted note, by `put_note`. It says what the driver knows and not that anything finished."""
    order = note_ref(order)
    note = (f"{INTERRUPT_MARK}\n- **Sprint interrupted at {when}** ({how}); last order in progress: "
            f"{order or 'unknown'}. The orchestrator did not checkpoint this: check the ledger, the worktrees and the "
            f"last commits before trusting the rest of this file.\n")
    return put_note(home, INTERRUPT_MARK, note, f"interrupted at {when}, last order: {order or 'unknown'}", sid)


def refusal_text(bad: list) -> str:
    """`<file>: <problem>` for the first REFUSAL_ITEMS_MAX malformed inputs, the rest counted. One line of plain text: a value
    that came from a repo file cannot carry markup into the state file."""
    shown = [plain_line(f"{name}: {problem}")[:240] for name, problem in bad[:REFUSAL_ITEMS_MAX]]
    if len(bad) > REFUSAL_ITEMS_MAX:
        shown.append(f"and {len(bad) - REFUSAL_ITEMS_MAX} more")
    return " | ".join(shown)


def write_refused_note(home: Path, when: str, bad: list, sid: str = "") -> "Path | None":
    """The refusal note, by `put_note`: the next interactive orchestrator folds it into RESUME at its first action."""
    fix = "fix it" if len(bad) == 1 else "fix them"
    note = (f"{REFUSED_MARK}\n- **Sprint refused {when}:** {refusal_text(bad)}; {fix} in a normal orchestrator window, "
            f"then rerun.\n")
    return put_note(home, REFUSED_MARK, note, f"refused at {when}: {refusal_text(bad)}", sid)


def survivors_text(left: dict) -> str:
    """The processes that outlived a close (and the kill), as one plain sentence; "" for none."""
    if not left:
        return ""
    return plain_line(f"{len(left)} process(es) survived the close: {', '.join(f'{p} {n}' for p, n in left.items())}.")


def write_guard_note(home: Path, when: str, text: str, survivors: str = "", sid: str = "") -> "Path | None":
    """The guard note, by `put_note`: the command, how it ended and the last lines of its output (`text`), and the processes that
    survived the same close (`survivors`, a sentence). An empty `text` is a guard that passed on a close that left survivors."""
    if text:
        note = (f"{GUARD_MARK}\n- **Sprint guard failed {when}:** {plain_line(text)}. The sprint stopped (`guard-failed`) and "
                f"launched nothing after it: look at what the guard guards before the next sprint." +
                (f" {survivors}" if survivors else "") + "\n")
        return put_note(home, GUARD_MARK, note, f"guard failed at {when}: {plain_line(text)} {survivors}".rstrip(), sid)
    note = (f"{GUARD_MARK}\n- **Sprint closed with processes left {when}:** {survivors} The guard after the close passed. The "
            f"sprint ended as an error: look at those processes before the next sprint.\n")
    return put_note(home, GUARD_MARK, note, f"closed with processes left at {when}: {survivors}", sid)


def report_refusal(home: Path, bad: list, when: "str | None" = None, sid: "str | None" = None) -> str:
    """A refusal over a malformed input is reported back, not only printed: an `error` record in the sprint log when the log
    exists, and the note in the sprint's state file. -> what became of the note, as a clause for the printed line."""
    when = when or datetime.now().astimezone().isoformat(timespec="seconds")
    sid = SPRINT_ID if sid is None else sid
    if slog.log_path(home, sid).is_file():
        try:
            slog.add_record(home, "error", f"refused: {refusal_text(bad)}", sid=sid)
        except OSError:
            pass
    wrote = write_refused_note(home, when, bad, sid)
    return ("STATE.md carries a `sprint refused` note" if wrote
            else "no state file was written (the note is in the sprint log)")


def ensure_tab(home: Path, tab: str = CARD_TAB) -> bool:
    """Add `tab` to board.json `tabs` once, no BOM, every other key kept. -> True when the file changed. board.json is shared by every
    driver and the board: it is read again while another process is writing it (`load_json`), written whole (`write_whole`), and the
    read-modify-write runs under `file_guard`, so two drivers adding their tabs both stay. A writer that takes no lock may still
    overwrite it with an older copy: the file is read back, and the tab added again (`EDIT_TRIES`) when it is not there."""
    path = Path(home) / "board" / "board.json"
    changed = False
    with file_guard(path):
        for _ in range(EDIT_TRIES):
            try:
                cfg = load_json(path)
            except ValueError as e:
                raise ValueError(f"{path} is not valid JSON ({e})")
            if not isinstance(cfg, dict):
                raise ValueError(f"{path} is not a JSON object")
            tabs = cfg.get("tabs") if isinstance(cfg.get("tabs"), list) else []
            if tab in tabs:
                return changed
            cfg["tabs"] = [*tabs, tab]
            write_whole(path, (json.dumps(cfg, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            changed = True
    raise RuntimeError(f"{path} kept losing the `{tab}` tab ({EDIT_TRIES} attempts): another process keeps rewriting it")


def git_exclude_path(root: Path) -> "Path | None":
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    p = Path(out)
    return p if p.is_absolute() else Path(root) / p


def ensure_ignored(root: Path, home: Path, sid: str = "") -> bool:
    """Git-ignore the sprint folder and page through the repo's own `info/exclude`, which leaves every tracked file alone
    (a changed .gitignore would be a change in the repo the sprint is about to work in). -> True when a line was added."""
    path = git_exclude_path(root)
    if path is None:
        return False
    rel = Path(home).resolve().relative_to(Path(root).resolve()).as_posix()
    want = [f"/{rel}/{x}" for x in (*IGNORE_LINES, "board/local/sprint-*.html" if sid else None) if x]
    added = False
    with file_guard(path):               # the exclude file is every sprint's and the operator's: one writer at a time, written whole
        for _ in range(EDIT_TRIES):
            try:
                have = retry_denied(lambda: path.read_text(encoding="utf-8", errors="replace")).splitlines()
            except FileNotFoundError:
                have = []
            add = [w for w in want if w not in have]
            if not add:
                return added
            body = "\n".join(have) + ("\n" if have else "")
            write_whole(path, (body + "\n".join(["# gitos sprint mode (this machine's log and page)", *add]) + "\n").encode("utf-8"))
            added = True
    raise RuntimeError(f"{path} kept losing the sprint's ignore lines ({EDIT_TRIES} attempts): another process keeps rewriting it")


# ------------------------------------------------------------------------------------------------ the sprint
class Sprint:
    def __init__(self, args, root: Path, home: Path, env, ops: Ops, claude: str):
        self.args, self.root, self.home, self.env, self.ops, self.claude = args, root, home, env, ops, claude
        self.listed = tuple(args.orders)         # the operator's --orders list; `run` replaces args.orders by the candidates
        self.sid = getattr(args, "id", "") or ""
        self.sprint_dir = compact_restore.sprint_dir(home, self.sid)
        self.log_path = slog.log_path(home, self.sid) if self.sid else home / slog.LOG_REL
        if self.sid:
            ops.sid, ops.orders = self.sid, self.listed
        self.taken: list = []                    # stale claims this sprint replaced: (order, the stale claim)
        self.worktree = None                     # a named sprint's own worktree (a Path) once `make_worktree` has it
        self.work_root, self.work_home = root, home     # where the session runs and whose ledger it works on (the worktree's, if named)
        self.reused = False                      # the worktree was an earlier run's leftover
        self.stop_file, self.rotate_file = self.sprint_dir / "STOP", self.sprint_dir / "ROTATE"
        self.card_id = ""
        self.guard = None                        # the repo's guard command (`guard_config`), read once at the start
        self.settle_s, self.busy_max_s = 0, None  # from the guard file: the wait after a close; the BUSY lease's longest hold
        self.spent = set()                       # BUSY leases (content, mtime) that ended by deadline or busy_max_s: never deferred on again
        self.defer_since = None                  # when the close now being held back by a live lease was first held back
        self.settle_interrupted = False          # Ctrl-C was pressed during a settle wait (the sprint ends after that close)
        self.sessions: list = []
        self.live = None                         # the session process while one runs: the driver ends it on any way out
        self.clean_end = False                   # the sprint ended on a stop that leaves nothing for the operator to read
        self.rotations = 0

    # -- the log
    def log(self, kind: str, msg: str, ref: str = "", session: str = "") -> None:
        slog.add_record(self.home, kind, msg, ref, session, sid=self.sid)

    # -- the Stop card
    def post_card(self) -> None:
        title = f"Stop sprint {self.sid} after the current work-order" if self.sid else CARD_TITLE
        body = f"Sprint {self.sid}. {CARD_BODY} It stops only this sprint." if self.sid else CARD_BODY
        old = (self.sprint_dir / "stop-card.id")
        if old.is_file():
            self.ops.board("close", old.read_text(encoding="utf-8").strip(), "superseded by a new sprint", "--tab", CARD_TAB)
        cp = self.ops.board("add-decision", title, body, CARD_OPTION, "--tab", CARD_TAB, "--group", "action")
        m = CARD_ID_RE.search(cp.stdout or "")
        if cp.returncode != 0 or not m:
            raise RuntimeError(f"the Stop card could not be posted ({(cp.stderr or cp.stdout).strip()[:200]})")
        self.card_id = m.group(1)
        (self.sprint_dir / "stop-card.id").write_text(self.card_id + "\n", encoding="utf-8")

    def card_pressed(self) -> bool:
        if not self.card_id:
            return False
        try:
            cp = self.ops.board("answer-for", self.card_id, "--tab", CARD_TAB)
            return cp.returncode == 0 and json.loads(cp.stdout).get("option") == "stop"
        except (ValueError, AttributeError, OSError, subprocess.SubprocessError):
            return False

    def close_card(self, outcome: str) -> None:
        if self.card_id:
            try:
                self.ops.board("close", self.card_id, outcome[:140], "--tab", CARD_TAB)
            except (OSError, subprocess.SubprocessError):     # a board that does not answer must not end the ending
                pass
            try:
                (self.sprint_dir / "stop-card.id").unlink()
            except OSError:
                pass

    # -- one session
    def launch(self):
        sid = str(uuid.uuid4())
        self.sessions.append(sid)
        cmd = build_command(self.claude, self.args, sid, worktree=self.worktree, home=self.home)
        proc = self.ops.launch(cmd, self.session_env())
        self.live = proc
        return proc, sid

    def session_env(self) -> dict:
        """The environment of the session and of the guard: a named sprint's id, driver pid, main home and worktree; the exclusive one's as before."""
        if self.sid:
            return child_env(self.env, self.home, self.sid, self.worktree, tuple(self.args.orders))
        return child_env(self.env, self.home, orders=tuple(self.args.orders))

    def transcript(self, sid: str) -> Path:
        return project_log_dir(self.work_root, self.env) / f"{sid}.jsonl"

    def live_lease(self, proc) -> "tuple[bool, str]":
        """Whether the repo's BUSY lease holds a close now. It is off unless the guard file sets `busy_max_s` (a stray BUSY file
        is then ignored). A lease is live while the file parses, its deadline is ahead and the close has been held back for less
        than `busy_max_s`; it is over once the file is gone, the deadline passed, `busy_max_s` reached or the session exited. A BUSY
        file that does not parse is not a lease. -> (live, the deadline text when live, else why it is not or no longer live)."""
        if self.busy_max_s is None:
            return False, ""
        if proc.poll() is not None:
            return False, "the session exited"
        kind, deadline, text = read_busy(self.home, self.sid)
        if kind == "none":
            return False, "BUSY was removed"
        if kind == "bad":
            return False, f"BUSY is not a lease ({text})"
        ident = busy_identity(self.home, self.sid)
        if ident in self.spent:
            return False, "this BUSY lease is spent"
        now = self.ops.now()
        if deadline <= now:
            self.spend(ident, "its deadline")
            return False, "the BUSY deadline passed"
        if self.defer_since is not None and now - self.defer_since >= self.busy_max_s:
            self.spend(ident, "busy_max_s")
            return False, f"busy_max_s {self.busy_max_s:g} s reached"
        return True, plain_line(text)[:40]

    def spend(self, ident, by: str) -> None:
        """A lease that ended by its deadline or by `busy_max_s` is spent: remembered by its identity for the rest of the sprint
        (never deferred on again; a BUSY rewritten with new content or time is a new lease) and reported once in STATE.md."""
        if ident is None or ident in self.spent:
            return
        self.spent.add(ident)
        mark = f"<!-- gitos-sprint-busy-{len(self.spent)} -->"
        note = (f"{mark}\n- A BUSY lease was left behind and ended by {by}; the repo's tooling should remove it when its action "
                f"settles.\n")
        put_note(self.home, mark, note, f"a BUSY lease was left behind and ended by {by}")

    def tidy_busy(self) -> None:
        """Before a launch (no session is running): a BUSY file that is spent, or whose deadline has passed, is moved to
        `<home>/sprint/archive/BUSY-<timestamp>` with a sprint-log note, so a stale lease never reaches the next session. A live
        lease, a file that does not parse and any BUSY file without `busy_max_s` are left alone."""
        if self.busy_max_s is None:
            return
        kind, deadline, _ = read_busy(self.home, self.sid)
        ident = busy_identity(self.home, self.sid)
        if kind != "lease" or ident is None:
            return
        if ident not in self.spent:
            if deadline > self.ops.now():
                return
            self.spend(ident, "its deadline")
        arch = self.sprint_dir / "archive"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest, n = arch / f"{BUSY_FILE}-{stamp}", 1
        try:
            arch.mkdir(parents=True, exist_ok=True)
            while dest.exists():
                n += 1
                dest = arch / f"{BUSY_FILE}-{stamp}-{n}"
            os.replace(self.sprint_dir / BUSY_FILE, dest)
        except OSError as e:
            self.log("note", f"a spent BUSY lease could not be archived ({e})")
            return
        self.log("note", f"a spent BUSY lease was archived to {arch.relative_to(self.home).as_posix()}/{dest.name} before the launch")

    def defer_close(self, proc) -> bool:
        """Called when a ROTATE or STOP file asks for a close: True while a live lease holds it back (one `note` when it starts,
        one when it ends). Ctrl-C, the driver's own stops and a session that has exited never come here."""
        live, text = self.live_lease(proc)
        if live:
            if self.defer_since is None:
                self.defer_since = self.ops.now()
                self.log("note", f"close deferred: BUSY until {text}")
            return True
        if self.defer_since is not None:
            self.log("note", f"BUSY lease over ({text}); closing")
        elif text.startswith("BUSY is not a lease"):
            self.log("note", f"{text}; closing as usual")
        return False

    def wait_settle(self) -> str:
        """The wait after a close, before the after-close guard: `settle_s` seconds (none when 0), logged. A Ctrl-C during it
        does not cut it short: the wait is finished and the guard runs, and the sprint ends after that close. A second Ctrl-C
        stops at once. -> "" normally, else the guard-failed text saying the guard did not run."""
        wait = self.settle_s
        if not wait:
            return ""
        self.log("note", f"settling {wait:g} s before the after-close guard")
        end, presses = self.ops.now() + wait, 0
        while end - self.ops.now() > 0:
            try:
                self.ops.sleep(min(end - self.ops.now(), SETTLE_STEP))
            except KeyboardInterrupt:
                presses += 1
                self.settle_interrupted = True
                if presses >= 2:
                    return plain_line(f"after close: the guard did not run (Ctrl-C twice during the {wait:g} s settle wait)")
                self.ops.say("Ctrl-C: finishing the settle wait, then the guard runs and the sprint ends (Ctrl-C again skips the guard)")
        return ""

    def close(self, proc, why: str, sid: str = "") -> dict:
        self.defer_since = None
        info = close_session(proc, self.ops, transcript=self.transcript(sid) if sid else None)
        left = info["survivors"]
        self.log("error" if left else "note",
                 f"closed ({why}) by {info['method']} in {info['seconds']} s; " +
                 (f"{len(left)} process(es) survived: {', '.join(map(str, left))}" if left else "no process left"))
        skipped = self.wait_settle() if self.guard is not None else ""
        # after every close, a force-kill included, once the repo's outside state has had its settle time
        info["guard"] = self.fail_guard(skipped, left) if skipped else self.run_guard("after close", left)
        if self.settle_interrupted and why not in ("Ctrl-C", "driver error"):
            raise KeyboardInterrupt
        return info

    def fail_guard(self, text: str, survivors: "dict | None" = None) -> str:
        """A guard that did not pass (`text`): a `stop` record `guard-failed: ...` and the STATE.md note, with the processes
        that survived the same close when there were any. -> `text`."""
        self.log("stop", f"guard-failed: {text}")
        write_guard_note(self.home, datetime.now().astimezone().isoformat(timespec="seconds"), text, survivors_text(survivors or {}),
                         self.sid)
        return text

    def run_guard(self, when: str, survivors: "dict | None" = None) -> str:
        """Run the repo's guard command (none declared: nothing happens). -> "" when it passed, else one line saying which
        command failed and how (also logged as a `stop` record `guard-failed: ...` and put in STATE.md as a note). The caller
        launches nothing after a failure. `survivors` (processes that outlived the close this run follows) are named in the same
        STATE.md note, whatever the guard said."""
        if self.guard is None:
            return ""
        cmd, limit = self.guard["command"], self.guard["timeout_s"]
        passed, what, tail = self.ops.guard(cmd, limit, self.session_env())
        if passed:
            if survivors:
                write_guard_note(self.home, datetime.now().astimezone().isoformat(timespec="seconds"), "", survivors_text(survivors),
                                 self.sid)
            return ""
        return self.fail_guard(plain_line(f"{when}: `{' '.join(cmd)}` {what}" + (f"; last output: {tail}" if tail else "")), survivors)

    def end_guard_failed(self, text: str) -> int:
        """The sprint ends because the guard did not pass: no launch follows. A STOP file is left for the operator unless one is
        there already. Exit 2 when nothing was launched yet, else 1."""
        if not self.stop_file.exists():
            try:
                self.stop_file.write_text(f"guard-failed: {text}"[:200] + "\n", encoding="utf-8")
            except OSError:
                pass
        self.close_card("sprint ended: guard-failed")
        self.ops.say(f"\nsprint ended: guard-failed: {text}; STATE.md carries a note. Log: {self.log_path}")
        return 1 if self.sessions else 2

    def end_stop(self, ident: str, reason: str, ref: str = "") -> int:
        msg = f"{ident}: {reason}" if ident else (reason or "STOP file with no text")
        found = WO_RE.search(reason)
        self.log("stop", msg, ref or (found.group(0) if found else ""))
        self.clean_end = ident in CLEAN_STOPS
        self.close_card(f"sprint ended: {ident or reason or 'stop'}")
        self.ops.say(f"\nsprint ended: {msg}. Log: {self.log_path}")
        return 0

    def end_error(self, kind: str, msg: str, note: bool, how: str = "") -> int:
        if note:
            order = last_order(slog.read_records(self.home, self.sid), self.ops.worktree_orders())
            when = datetime.now().astimezone().isoformat(timespec="seconds")
            wrote = write_interrupted_note(self.home, when, order, how or msg, self.sid)
            where = "STATE.md carries an interrupted note" if wrote else "no state file was written (the note is in this log)"
            msg = f"{msg}; {where} (last order: {note_ref(order) or 'unknown'})"
        self.log(kind, msg)
        self.close_card(f"sprint ended: {msg}"[:140])
        self.ops.say(f"\nsprint ended: {msg}. Log: {self.log_path}")
        return 1

    def end_refused(self, bad: list) -> int:
        """The sprint ends because a repo file became malformed (read at a rotation): nothing is relaunched, the file is named
        in the log, on the console and in a note in STATE.md."""
        where = report_refusal(self.home, bad, sid=self.sid)
        msg = f"sprint refused at a rotation: {refusal_text(bad)}"
        self.log("error", msg)
        self.close_card(f"sprint ended: {msg}"[:140])
        self.ops.say(f"\nsprint ended: {msg}; {where}. Log: {self.log_path}")
        return 1

    def run(self) -> int:
        """Run the sprint. The claims (or the exclusive marker) it took in `prepare` are released on every way out."""
        global SPRINT_ID
        SPRINT_ID, before = self.sid, SPRINT_ID
        try:
            return self.run_sprint()
        finally:
            SPRINT_ID = before
            self.end_session()
            if self.sid:
                self.finish_worktree()
                self.note_unreleased(release_claims(self.home, self.sid))
            else:
                self.note_unreleased(unmark_exclusive(self.home))
            self.archive_clean_end()

    def end_session(self) -> None:
        """On every way out of the driver: a session still running (the driver is leaving by a path that did not close it) has its
        process tree killed, so it never runs on with no driver and no claim. Never raises."""
        proc, self.live = self.live, None
        try:
            if proc is None or proc.poll() is not None:
                return
            self.ops.kill_tree(proc.pid)
            msg = "the driver left with its session still running: the session's process tree was ended"
            slog.add_record(self.home, "error", msg, sid=self.sid)
            self.ops.say(f"sprint: {msg}")
        except Exception:
            pass

    def archive_clean_end(self) -> None:
        """After a named sprint's clean end (`clean_end`), move STATE.md and STOP to `sprint/<id>/archive/<name>-<stamp>` so the same id can
        start again (the exclusive sprint's STATE.md is the interactive window's to fold, and stays). A STATE.md that carries a note of the
        driver's (a left worktree, a takeover, a guard failure) is for the operator to read first: both files stay, and the log says so.
        Never raises."""
        if not self.clean_end or not self.sid:
            return
        try:
            state = self.sprint_dir / STATE_REL.name
            try:
                held = NOTE_MARK_PREFIX in state.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                held = False
            if held:
                self.log("note", "STATE.md carries a note for the operator: it and STOP stay in place; read them before the next start")
                return
            arch = self.sprint_dir / "archive"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            for f in (state, self.stop_file):
                if not f.exists():
                    continue
                arch.mkdir(parents=True, exist_ok=True)
                dest, n = arch / f"{f.stem}-{stamp}{f.suffix}", 1
                while dest.exists():
                    n += 1
                    dest = arch / f"{f.stem}-{stamp}-{n}{f.suffix}"
                retry_denied(lambda: os.replace(f, dest))
            self.ops.say(f"sprint: clean end, STATE.md and STOP moved to {arch.relative_to(self.home).as_posix()}/ so sprint {self.sid} can start again")
        except Exception as e:
            try:
                slog.add_record(self.home, "note", f"the clean end's STATE.md and STOP could not be archived ({e})", sid=self.sid)
            except OSError:
                pass

    def run_sprint(self) -> int:
        a = self.args
        try:
            self.prepare()
            a.orders = candidate_orders(a.orders, self.home)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
            what = e if isinstance(e, (RuntimeError, ValueError)) else f"{type(e).__name__}: {e}"
            msg = f"{str(what)[:300]}; nothing was launched"
            try:
                slog.add_record(self.home, "error", msg, sid=self.sid)
            except OSError:
                pass
            self.ops.say(" ".join(f"sprint: {msg}".split()))
            return 2
        proc = None
        try:
            failed = self.run_guard("before launch")
            if failed:
                return self.end_guard_failed(failed)
            self.tidy_busy()
            proc, sid = self.launch()
            allow = f" orders={','.join(a.orders)}" if a.orders else ""
            self.log("start", f"model={a.model} effort={a.effort} window={a.autocompact}{allow} session={sid}", session=sid)
            prev, streak = self.ops.snapshot(), 0
            while True:
                self.ops.sleep(POLL_SECONDS)
                if (self.stop_file.exists() or self.rotate_file.exists()) and self.defer_close(proc):
                    continue
                if self.stop_file.exists():
                    self.settle(sid, proc)
                    ident, reason = parse_signal(self.stop_file.read_text(encoding="utf-8-sig", errors="replace"))
                    info = self.close(proc, "STOP", sid)
                    if info["survivors"]:
                        return self.end_error("error", "stopped with processes left", False)
                    ended = self.end_stop(ident, reason)
                    self.clean_end = self.clean_end and not info["guard"]
                    return 1 if info["guard"] else ended
                signalled = self.rotate_file.exists()
                if signalled:
                    self.settle(sid, proc)
                    reason = read_first_line(self.rotate_file) or "no reason given"
                elif proc.poll() is not None:
                    code = proc.returncode - (1 << 32) if proc.returncode > 0x7FFFFFFF else proc.returncode
                    info = self.close(proc, "exited", sid)
                    return self.end_error("error", f"the session exited without a signal (code {code})", True,
                                          f"the session exited with code {code} and wrote no STOP or ROTATE")
                else:
                    continue
                info = self.close(proc, "ROTATE", sid)
                if info["survivors"]:
                    return self.end_error("error", "rotation stopped with processes left", False)
                if info["guard"]:
                    return self.end_guard_failed(info["guard"])
                self.rotations += 1
                cur = self.ops.snapshot(prev[3])
                is_stuck, streak = stuck(prev, cur, streak)
                prev = cur
                try:
                    self.rotate_file.unlink()
                except OSError:
                    pass
                self.log("rotate", f"rotation {self.rotations}: {reason}")
                if self.stop_file.exists():
                    return self.end_stop(*parse_signal(self.stop_file.read_text(encoding="utf-8-sig", errors="replace")))
                if self.card_pressed():
                    self.stop_file.write_text("stop-card: operator pressed Stop\n", encoding="utf-8")
                    return self.end_stop("stop-card", "operator pressed Stop")
                bad = input_problems(self.home, self.listed)
                if bad:
                    return self.end_refused(bad)
                if is_stuck:
                    return self.end_error("stop", f"stuck: {STUCK_AFTER} rotations in a row with no order opened or "
                                          "resolved, no wo-* branch moved and no commit beyond RESUME/INDEX/board", False)
                if self.rotations > a.max_rotations:
                    return self.end_error("stop", f"--max-rotations {a.max_rotations} reached", False)
                failed = self.run_guard("before relaunch")
                if failed:
                    return self.end_guard_failed(failed)
                self.tidy_busy()
                proc, sid = self.launch()
                self.log("note", f"relaunched after rotation {self.rotations}: session {sid}", session=sid)
        except KeyboardInterrupt:
            if proc is not None and not self.settle_interrupted:       # else the close that was interrupted is done
                self.close(proc, "Ctrl-C", self.sessions[-1])
            return self.end_error("stop", "Ctrl-C in the terminal", True, "Ctrl-C in the terminal")
        except Exception as e:                       # never leave a session running behind a driver that fell over
            if proc is not None:
                self.close(proc, "driver error", self.sessions[-1])
            return self.end_error("error", f"driver error {type(e).__name__}: {e}", True, "the sprint driver failed")

    def prepare(self) -> None:
        """Everything before the first launch that can fail on the repo's own files: -> raises one of RuntimeError (the
        Stop card), ValueError (a board.json that does not parse), OSError and SubprocessError (a board that does not
        answer), which `run` turns into a one-line refusal."""
        self.guard, problem = guard_config(self.home)
        if problem:
            raise ValueError(f"{home_file(self.home, GUARD_FILE)}: {problem}")
        if self.guard:
            self.settle_s, self.busy_max_s = self.guard.get("settle_s", 0), self.guard.get("busy_max_s")
        self.sprint_dir.mkdir(parents=True, exist_ok=True)
        self.take_place()
        if self.sid:
            self.make_worktree()
        slog.archive_previous(self.home, sid=self.sid)
        self.note_takeovers()
        self.note_leftover()
        self.say_archived_state()
        try:
            self.rotate_file.unlink()                # a ROTATE left by an earlier run is the driver's to clear
        except OSError:
            pass
        ensure_ignored(self.root, self.home, self.sid)
        ensure_tab(self.home)
        self.post_card()

    def take_place(self) -> None:
        """Before anything else is touched: a named sprint claims its orders, the exclusive sprint marks itself, and each then looks
        at the other side (the record is written first, so two sprints starting at once cannot both miss the other). RuntimeError
        names the order and the holder, or the other kind of sprint."""
        if self.sid:
            self.taken = claim_orders(self.home, self.sid, self.listed)
            problems = [p for p in sprint_conflicts(self.home, self.sid, self.listed)
                        if p.startswith(("an exclusive", f'sprint "{self.sid}" is already'))]
        else:
            mark_exclusive(self.home)
            problems = sprint_conflicts(self.home, "", ())
        if problems:
            raise RuntimeError(problems[0])

    def make_worktree(self) -> None:
        """A named sprint's own worktree, `<repo>.worktrees/sprint-<id>` on branch `sprint-<id>`, from the main branch's tip (git
        directly; `worktree.py` does not know sprints). An earlier run's leftover of this id (no live claim: this sprint holds them) is
        reused; any other thing at that path or branch is RuntimeError. A fresh worktree must hold every `--orders` order as open: an
        order that exists only in the main checkout's working tree is not in the tip, and the worktree is undone with the refusal."""
        path, branch = sprint_worktree_path(self.root, self.home, self.sid), sprint_branch(self.sid)
        state, why = worktree_state(self.root, path, branch)
        if state == "refused":
            raise RuntimeError(why)
        base = main_branch(self.root)
        if state == "fresh":
            add_worktree(self.root, path, branch, base)
        self.reused = state == "leftover"
        self.worktree = path
        self.work_root = path
        self.work_home = path / Path(self.home).resolve().relative_to(Path(self.root).resolve())
        self.ops.work_root, self.ops.work_home = self.work_root, self.work_home
        if state == "fresh":
            marks = slog.open_order_marks(self.work_home)
            missing = [ref for ref in self.listed if int(ref[3:]) not in marks]
            if missing:
                discard_worktree(self.root, path, branch)
                self.worktree = None
                raise RuntimeError(f"--orders {', '.join(missing)} is not an open work-order at the tip of {base}: a sprint worktree is "
                                   f"made from that tip, so commit the order there first")

    def note_leftover(self) -> None:
        if self.reused:
            note = (f"{WORKTREE_MARK}\n- This sprint reused the worktree an earlier run of sprint {self.sid} left: {plain_line(self.worktree)} "
                    f"on branch {sprint_branch(self.sid)}. Check what it holds (git status, git log) before trusting it.\n")
            put_note(self.home, WORKTREE_MARK, note, f"reused the leftover worktree {self.worktree}", self.sid)
            try:
                slog.add_record(self.home, "note", f"reused the leftover worktree {self.worktree}", sid=self.sid)
            except OSError:
                pass

    def say_archived_state(self) -> None:
        """A named sprint whose last end was a Stop card moved its STATE.md aside (`archive_clean_end`): the start says where it is, so
        the next run can read where the last one stopped. Says nothing for any other earlier end. Never raises."""
        if not self.sid:
            return
        try:
            arch = self.sprint_dir / "archive"
            stops, states = sorted(arch.glob("STOP-*")), sorted(arch.glob("STATE-*.md"))
            if not stops or not states or not stops[-1].read_text(encoding="utf-8-sig", errors="replace").startswith("stop-card"):
                return
            self.ops.say(f"sprint: sprint {self.sid} was last ended by a Stop card; its STATE.md is archived at "
                         f"{states[-1].relative_to(self.home).as_posix()}. Read it if this run should pick up where that one stopped.")
        except Exception:
            pass

    def finish_worktree(self) -> None:
        """At the end of a named sprint, on every way out: remove its worktree and branch when the branch is in the main branch and the
        worktree is clean; else leave both and say so in the log and in STATE.md. Never raises."""
        if self.worktree is None:
            return
        path, branch = self.worktree, sprint_branch(self.sid)
        try:
            why = remove_worktree(self.root, path, branch, self.home)
        except Exception as e:                          # a cleanup that fails is a worktree left, not a sprint that crashes
            why = f"cleanup failed ({type(e).__name__}: {e})"
        prune_empty_folders(self.root, path)
        if why:
            msg = f"worktree {path} and branch {branch} left in place: {plain_line(why)}"
            try:
                slog.add_record(self.home, "note", msg, sid=self.sid)
            except OSError:
                pass
            put_note(self.home, WORKTREE_LEFT_MARK, f"{WORKTREE_LEFT_MARK}\n- **Sprint worktree left:** {plain_line(msg)}. Land what it holds "
                     "(worktree.py land) or discard it, then remove the worktree and the branch.\n", msg, self.sid)
            self.ops.say(f"sprint: {msg}")
        else:
            self.worktree = None

    def note_unreleased(self, left: list) -> None:
        """A claim (or the exclusive marker) that could not be removed at the end, after its retries, is said in the sprint log, in
        STATE.md and on the console, never dropped. Its pid is then dead, so the next sprint takes it over as a stale claim; the note
        says to remove the file. Never raises."""
        for f, why in left:
            try:
                msg = f"{f.name} could not be removed at the end of the sprint ({why})"
                try:
                    slog.add_record(self.home, "note", msg, sid=self.sid)
                except OSError:
                    pass
                mark = f"<!-- gitos-sprint-release-{f.stem} -->"
                put_note(self.home, mark, f"{mark}\n- **A claim was left behind:** {plain_line(msg)}; {plain_line(f)} names this sprint and a "
                         "pid that is gone, so the next sprint on that order takes it over as stale; remove the file to clear it.\n", msg, self.sid)
                self.ops.say(f"sprint: {msg}")
            except Exception:
                pass

    def note_takeovers(self) -> None:
        """A claim whose holder had died, and that this sprint replaced, is said in the sprint log and in STATE.md."""
        for ref, old in self.taken:
            msg = (f'claim on {ref} taken over: sprint "{old["sprint"]}" (pid {old["pid"]}, since {plain_line(old["since"])[:30]}) '
                   "is not running")
            try:
                slog.add_record(self.home, "note", msg, ref, sid=self.sid)
            except OSError:
                pass
            mark = f"<!-- gitos-sprint-claim-{ref} -->"
            put_note(self.home, mark, f"{mark}\n- A stale claim was taken over: {plain_line(msg)}; check that order's worktree "
                     "and branch before trusting them.\n", msg, self.sid)

    def settle(self, sid: str, proc) -> None:
        """A signal file means the session is writing its last reply: wait until its log is quiet, then close (a session
        still not quiet at the cap is then killed, not typed into)."""
        if proc.poll() is None:
            log = self.transcript(sid)
            if self.ops.mtime(log) is None:
                self.ops.say(f"sprint: no session log at {log}; the quiet wait before the close is a plain pause")
            wait_quiet(log, self.ops)


def resolve_target(repo_arg: "str | None") -> "tuple[Path, Path | None, Path | None]":
    start = Path(repo_arg or Path.cwd()).resolve()
    found = slog.locate(start) if start.is_dir() else None
    if found is None:
        return start, None, None
    home, root = found
    return root, home, root


def main(argv=None, env=None, ops_factory=None) -> int:
    global SPRINT_ID
    args = parse_args(argv)
    SPRINT_ID = args.id
    try:
        return run_main(args, env, ops_factory)
    finally:
        SPRINT_ID = ""


LONG_OPTIONS = ("--autocompact", "--effort", "--model", "--add-dir", "--max-rotations", "--orders", "--id", "--window")


def option_name(token: str) -> "str | None":
    """The long option a command-line token names (an unambiguous prefix counts, as argparse reads it), or None."""
    if not token.startswith("--") or len(token) < 3:
        return None
    name = token.split("=", 1)[0]
    if name in LONG_OPTIONS:
        return name
    hits = [o for o in LONG_OPTIONS if o.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def window_argv(raw: list, root: Path) -> list:
    """The driver's own arguments for the window: `raw` without --window, the repo named by its root and each --add-dir made
    absolute (the window starts in the repo root, not where this call was made). Every other option is a single option and value."""
    out, expect = [], None
    for tok in raw:
        if expect:
            out.append(str(Path(tok).resolve()) if expect == "--add-dir" else tok)
            expect = None
            continue
        name = option_name(tok)
        if name == "--window":
            continue
        if name and "=" in tok:
            key, value = tok.split("=", 1)
            out.append(f"{key}={Path(value).resolve()}" if name == "--add-dir" else tok)
        elif name:
            out.append(tok)
            expect = name
        elif tok.startswith("-") and tok != "-":
            out.append(tok)
        else:
            out.append(str(root))
    return out


def ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def powershell_exe(env) -> str:
    root = env_lookup(env, "SystemRoot") or env_lookup(env, "windir") or r"C:\Windows"
    cand = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(cand) if cand.is_file() else (shutil.which("powershell.exe", path=env.get("PATH")) or "powershell.exe")


def window_command(args, root: Path, env) -> list:
    """The command line that starts this sprint in its own PowerShell console: the driver again, the same arguments minus --window."""
    argv = window_argv(list(args.argv), root)
    title = f"gitos sprint {args.id or 'exclusive'}"
    text = (f"$Host.UI.RawUI.WindowTitle = {ps_quote(title)}; "
            + "& " + " ".join(ps_quote(a) for a in [sys.executable, str(Path(__file__).resolve()), *argv]))
    return [powershell_exe(env), "-NoLogo", "-NoExit", "-Command", text]


def spawn_window(cmd: list, cwd: Path, env: dict) -> int:
    """Start cmd in a new visible console; -> its pid."""
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, creationflags=subprocess.CREATE_NEW_CONSOLE).pid


def launch_window(args, root: Path, env) -> int:
    """--window, after the preflight passed: the sprint in a new PowerShell window, with the repaired PATH (and no session markers).
    One line names the window and the sprint; exit 0."""
    child = strip_env(env)
    for k in (compact_restore.SPRINT_ID_ENV, compact_restore.SPRINT_PID_ENV, compact_restore.SPRINT_WORKTREE_ENV,
              compact_restore.SPRINT_ORDERS_ENV, "GITOS_SPRINT", "GITOS_SPRINT_HOME"):
        child.pop(k, None)
    key = next((k for k in child if k.upper() == "PATH"), "PATH")
    child[key] = repaired_path(child)
    try:
        pid = spawn_window(window_command(args, root, child), root, child)
    except OSError as e:
        print(f"sprint: the PowerShell window could not be started ({e}); nothing was launched", file=sys.stderr)
        return 2
    print(f"sprint: launched PowerShell window pid {pid} for sprint {args.id or 'exclusive'} in {root}", flush=True)
    return 0


def run_main(args, env, ops_factory) -> int:
    env = dict(os.environ if env is None else env)
    start, home, root = resolve_target(args.repo)
    claude = find_claude(env) if home is not None else None
    env = claude_on_path(env, claude)
    if home is not None and not args.orders:
        for ref, why in skipped_orders(home):
            print(f"sprint: skipped {ref}: {why}", file=sys.stderr)
    advisory = path_advisory_line()
    if advisory:
        print(f"sprint: {advisory}", file=sys.stderr)
    problems = preflight(args, env, root, home, claude=claude)
    if problems:
        for p in problems:
            print(f"sprint: {p}", file=sys.stderr)
        bad = input_problems(home, args.orders) if home is not None else []
        where = f"; {report_refusal(home, bad)}" if bad else ""
        print(f"sprint: nothing was launched{where}", file=sys.stderr)
        return 2
    if args.window:
        return launch_window(args, root, env)
    ops = (ops_factory or Ops)(root, home, env, claude)
    with exit_signals():
        return Sprint(args, root, home, env, ops, claude).run()


@contextlib.contextmanager
def exit_signals():
    """A driver ended by SIGTERM, SIGBREAK or SIGHUP leaves as `SystemExit`, so `Sprint.run` ends its session on the way out. Handlers
    are put back afterwards; where signals cannot be set (not the main thread) nothing is changed."""
    old = {}

    def leave(number, _frame):
        raise SystemExit(f"sprint: the driver was ended by signal {number}")

    for name in EXIT_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                old[sig] = signal.signal(sig, leave)
            except (ValueError, OSError):
                pass
    try:
        yield
    finally:
        for sig, handler in old.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    sys.exit(main())
