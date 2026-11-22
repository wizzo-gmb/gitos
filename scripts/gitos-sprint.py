#!/usr/bin/env python3
"""gitos-sprint.py - run a repo's open work-orders in a visible Claude session that rotates itself. Standard library only.

    python gitos-sprint.py [REPO] [--autocompact TOKENS] [--effort LEVEL] [--model MODEL] [--add-dir DIR ...]
                           [--max-rotations N] [--orders 253,254]

Run it in a Windows terminal. It launches an interactive Claude session in the repo root with the sprint start prompt,
watches `<home>/sprint/ROTATE` and `<home>/sprint/STOP`, closes the session on either (writing `/exit` into the console,
then killing the process tree if it does not leave), starts a fresh session after a ROTATE, and ends after a STOP. The log
is `<home>/sprint/log.jsonl`; its page is the board's `sprint` tab; one Stop card there ends the sprint after the current
order. Every cap and stop below is code here, not an instruction to the model. Operator guide: references/sprint.md.

--orders limits the sprint to the listed open work-orders (numbers, comma-separated, a `WO-` prefix is accepted); without
it the candidates are the open orders marked `sprint: ready` in their front matter, and an unmarked order is never taken. An
order marked `sprint: no` is never a candidate. Either way the orchestrator skips, with a logged reason, the candidates that
are not sprint-eligible at run time (references/orchestrator/sprint.md, references/orchestrator/sprint-prep.md).

The start prompt asks for replies that are the role marker line alone.

Defaults: --autocompact 500k, --effort medium, --model opus[1m], --max-rotations 20. They apply to the orchestrator session
only. Permission mode is never passed (the operator's own setting applies) and no permission-bypass flag is ever passed.
Every repo file the driver parses (the layout, the board's config and route, the model-optimization config, each candidate
order's `sprint:` mark) is checked before the first launch and again at each rotation. A malformed one is a refusal, never a
silent fallback: the driver names the file, logs it and leaves a note under RESUME's *In flight* for the next interactive
orchestrator (`input_problems`).
Exit status: 0 the sprint ended on a stop signal, 1 it ended on an error, an interruption or a cap, 2 nothing was launched.
"""
from __future__ import annotations

import argparse
import ctypes
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sprint_log as slog  # noqa: E402

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
            "no-open-order", "stop-card")
CARD_TAB = "sprint"
CARD_OPTION = "stop=Stop after the current WO"
CARD_TITLE = "Stop the sprint after the current work-order"
CARD_BODY = ("The sprint finishes the order it is on, writes RESUME and stops. Pressing Stop is the only thing this card does; "
             "Ctrl-C in the terminal stops at once.")
IGNORE_LINES = ("sprint/", "board/local/sprint.html")      # relative to the home
INTERRUPT_MARK = "<!-- gitos-sprint-interrupted -->"
REFUSED_MARK = "<!-- gitos-sprint-refused -->"
SPRINT_MARKS = ("ready", "no")           # the values of an order's `sprint:` front matter key
REFUSAL_ITEMS_MAX = 4                    # problems named in one RESUME note, the rest counted
CARD_ID_RE = re.compile(r"card (\d{8}-\d{6}-\d{6}-[0-9a-f]{4}) added")
WO_RE = re.compile(r"WO-\d+(?:/S\d+)?")
HARNESS_PREFIXES = ("CLAUDE", "MCP_")
KEEP_ENV = (                          # operator configuration, not harness markers: these pass through the strip
    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_GIT_BASH_PATH", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
REF_JUNK_RE = re.compile(r"[^\w ./:#-]+")
ORDER_REF_MAX = 40
ORDER_ITEM_RE = re.compile(r"(?:wo-)?(\d+)", re.I)


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


def candidate_orders(orders: tuple, home: Path) -> tuple:
    """The orders a sprint may take, canonical and sorted: the operator's `--orders` list when there is one, else the open
    orders whose front matter says `sprint: ready`. An unmarked order is never a candidate by default."""
    if orders:
        return tuple(orders)
    marks = slog.open_order_marks(home)
    return tuple(f"WO-{n:03d}" for n in sorted(n for n, m in marks.items() if m == "ready"))


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
    a = ap.parse_args(argv)
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
    """Whether Claude has been told to trust `root` or a folder above it (hasTrustDialogAccepted in the operator's
    ~/.claude.json). Read only. -> (trusted, a reason when not)."""
    try:
        data = json.loads(Path(claude_json).read_text(encoding="utf-8-sig"))
        projects = data.get("projects")
    except (OSError, ValueError, AttributeError) as e:
        return False, f"cannot read {claude_json} ({e})"
    if not isinstance(projects, dict):
        return False, f"{claude_json} lists no projects"
    key = lambda p: os.path.normcase(os.path.normpath(str(p)))  # noqa: E731
    trusted = {key(k) for k, v in projects.items() if isinstance(v, dict) and v.get("hasTrustDialogAccepted") is True}
    here = Path(root).resolve()
    if any(key(p) in trusted for p in (here, *here.parents)):
        return True, ""
    return False, f"{here} is not trusted in {claude_json}"


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


def find_claude(env) -> "str | None":
    """The claude executable: an .exe on PATH, or the one an npm shim sits beside (a .cmd shim would put the prompt
    through cmd.exe quoting)."""
    found = shutil.which("claude", path=env.get("PATH"))
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


def home_file(home: Path, rel: str) -> str:
    """How a repo file is named in a refusal: its path below the repo root's home folder name (`.gitos/worktrees.json`)."""
    return f"{Path(home).name}/{rel}"


def input_problems(home: Path, listed: tuple = ()) -> list:
    """Every repo file the driver parses that is malformed, as (file, problem) pairs; [] when all are sound. The files are
    `worktrees.json` (through `worktree.load_layout`), `board/board.json`, `board-route.json`, `model-optimization.json`
    and the `sprint:` value of each candidate order (the `listed` orders of `--orders`, else every open order): anything
    but `ready` or `no` is refused, an empty value is no mark. A file that does not exist is not malformed. Read only."""
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
            cfg = json.loads(board.read_text(encoding="utf-8-sig"))
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
    if home is None:
        return [f"no gitos home found at {args.repo or Path.cwd()} (.gitos/ or a legacy home): run /gitos there first"]
    out = []
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
        out.append(f"{why}: open Claude in {root} once and accept the trust dialog (a prompt would wait behind it "
                   "unattended); this script never edits that file")
    if (home / "sprint" / "STOP").exists():
        out.append(f"{home / 'sprint' / 'STOP'} exists: read it, then delete it to start a sprint")
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
    marks = slog.open_order_marks(home)
    if args.orders:
        for ref in args.orders:
            if int(ref[3:]) not in marks:
                out.append(f"--orders {ref} is not an open work-order (it is resolved, parked or missing)")
            elif marks.get(int(ref[3:])) == "no":
                out.append(f"--orders {ref} is marked `sprint: no` in its front matter: remove the mark first, or leave it "
                           "out of --orders")
    elif "ready" not in marks.values():
        out.append("no order is marked `sprint: ready`; prepare orders in a normal orchestrator window "
                   "(references/orchestrator/sprint-prep.md), or pass --orders")
    for d in args.add_dir:
        if not Path(d).is_dir():
            out.append(f"--add-dir {d} is not a folder")
    if platform == "win32" and not (claude or find_claude(env)):
        out.append("the claude executable (claude.exe) was not found on PATH")
    return out


# ------------------------------------------------------------------------------------------------ launch
def strip_env(env) -> dict:
    """The child's environment: the driver's without any CLAUDE* or MCP_* variable (an inherited child-session marker
    turns transcripts off and an inherited compaction window beats the flag), the operator settings in KEEP_ENV excepted."""
    return {k: v for k, v in env.items()
            if k.upper() in KEEP_ENV or not k.upper().startswith(HARNESS_PREFIXES)}


def child_env(env, home: Path) -> dict:
    out = strip_env(env)
    out["GITOS_SPRINT"] = "1"                    # set after the strip: compact_restore.py reads it
    out["GITOS_SPRINT_HOME"] = str(home)         # sprint_log.py finds the home from any directory
    return out


def start_prompt(skill_dir: Path = SKILL_DIR, orders: tuple = ()) -> str:
    """One line, no quote marks: the router, the words `sprint mode`, the rules file, the log command and, once the candidate
    orders are resolved, that list."""
    s = Path(skill_dir).as_posix()
    allow = (f" Candidate orders for this sprint (the operator's --orders list, or else the open orders marked sprint: "
             f"ready): {', '.join(orders)}. Take no other order." if orders else "")
    return (f"/gitos resume, sprint mode: an unattended run started by the sprint driver, operator away. "
            f"The gitos skill is at {s}; read {s}/references/orchestrator/sprint.md and follow it. "
            f"Reply with the marker line only (orchestrator/sprint.md, Output). "
            f"Log progress with: python {s}/scripts/sprint_log.py add KIND MESSAGE --ref WO-N, where KIND is start "
            f"when you begin an order, done when you resolve it, or note, and MESSAGE is one short line.{allow}")


def build_command(claude: str, args, session_id: str, prompt: "str | None" = None) -> list:
    """The argument list (no shell). The prompt comes first so that the variadic --add-dir cannot swallow it. No permission mode
    is ever passed (the operator's own applies)."""
    cmd = [claude, prompt or start_prompt(orders=args.orders), "--model", args.model, "--effort", args.effort,
           "--autocompact", str(args.autocompact), "--session-id", session_id]
    for d in args.add_dir:
        cmd += ["--add-dir", str(d)]
    return cmd


def project_log_dir(root: Path, env) -> Path:
    base = Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    return base / re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).resolve()))


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

    def __init__(self, root: Path, home: Path, env, claude: str):
        self.root, self.home, self.env, self.claude = root, home, env, claude

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def now(self) -> float:
        return time.time()

    def say(self, text: str) -> None:
        print(text, flush=True)

    def launch(self, cmd: list, env: dict):
        return subprocess.Popen(cmd, cwd=str(self.root), env=env)

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
            return subprocess.run(["git", "-C", str(self.root), "-c", "core.quotepath=off", *argv], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None

    def snapshot(self, since: str = "") -> tuple:
        """What a sprint has to show for itself: (open orders, resolved orders, branch tips, HEAD, whether a commit
        since `since` (an earlier HEAD, "" for none) touched anything but RESUME, INDEX and the board). The checkpoint
        commits RESUME before every rotation, so HEAD alone always moves. The tips are the local branches matching `wo-*` and
        the `integration` and `branches` globs of the repo's own `<home>/worktrees.json` (see `layout_globs`)."""
        cp = self.git("rev-parse", "HEAD")
        head = cp.stdout.strip() if cp is not None and cp.returncode == 0 else ""
        tips = self.branch_tips()
        try:
            resolved = tuple(sorted(x.name for x in (Path(self.home) / "work-orders" / "resolved").iterdir()))
        except OSError:
            resolved = ()
        return (tuple(sorted(slog.open_orders(self.home))), resolved, tips, head, self.substantive(since, head))

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
        """Whether a commit in `since..head` touches a path other than <home>/RESUME.md, <home>/INDEX.md and <home>/board/.
        Unknown (git failed, `since` gone) counts as yes: a sprint is not called stuck on what could not be read."""
        if not since or not head or since == head:
            return False
        cp = self.git("log", "--name-only", "--format=", "--relative", f"{since}..{head}")
        if cp is None or cp.returncode != 0:
            return True
        try:
            rel = Path(self.home).resolve().relative_to(Path(self.root).resolve()).as_posix()
        except ValueError:
            rel = None
        ours = (f"{rel}/RESUME.md", f"{rel}/INDEX.md") if rel else ()
        return any(line.strip() and line.strip() not in ours and not (rel and line.strip().startswith(f"{rel}/board/"))
                   for line in cp.stdout.splitlines())

    def board(self, *argv: str) -> "subprocess.CompletedProcess":
        return subprocess.run([sys.executable, str(self.home / "board" / "board.py"), *argv], cwd=str(self.root),
                              capture_output=True, text=True, timeout=60)

    def cost(self, sessions: list) -> str:
        return slog.sprint_cost(self.root, sessions, self.env)

    def worktree_orders(self) -> list:
        try:
            out = subprocess.run(["git", "-C", str(self.root), "worktree", "list", "--porcelain"], capture_output=True,
                                 text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return re.findall(r"^branch refs/heads/wo-(\d+)", out, re.M)


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
    field) that touches more than RESUME, INDEX and the board: the checkpoint commit before each rotation moves HEAD, so
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
    """The order ref as it goes into RESUME: one short line of plain characters (the ref comes from the model's `--ref`)."""
    return " ".join(REF_JUNK_RE.sub(" ", str(order)).split())[:ORDER_REF_MAX]


def note_to_log(home: Path, msg: str) -> None:
    try:
        slog.add_record(home, "note", msg)
    except OSError:
        pass


def put_in_flight(home: Path, mark: str, note: str, failed: str) -> "Path | None":
    """Put `note` (the `mark` line, then one line) under RESUME's `## In flight` (the rest of the file untouched; an earlier note
    carrying the same mark is replaced; no RESUME or no such section: made). RESUME is read, then replaced in one step (a
    temp file beside it, `os.replace`); when it cannot be read or replaced it is left exactly as it is and `failed` (what the
    note was about) goes to the sprint log instead (-> None)."""
    path = Path(home) / "RESUME.md"
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
    except FileNotFoundError:
        text = "# RESUME (live session state)\n\n"
    except OSError as e:
        note_to_log(home, f"RESUME.md could not be read ({e}); {failed}")
        return None
    eol = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n?" + re.escape(mark) + r"\n[^\n]*\n", "", text)
    m = re.search(r"^##\s+In flight\b[^\n]*\n", text, re.M)
    if m:
        text = text[:m.end()] + "\n" + note + text[m.end():]
    else:
        text = text.rstrip("\n") + "\n\n## In flight\n\n" + note
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".RESUME-", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.replace("\n", eol).encode("utf-8"))
        os.replace(tmp, path)
    except OSError as e:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        note_to_log(home, f"RESUME.md could not be written ({e}); {failed}")
        return None
    return path


def write_interrupted_note(home: Path, when: str, order: str, how: str) -> "Path | None":
    """The interrupted note, by `put_in_flight`. It says what the driver knows and not that anything finished."""
    order = note_ref(order)
    note = (f"{INTERRUPT_MARK}\n- **Sprint interrupted at {when}** ({how}); last order in progress: "
            f"{order or 'unknown'}. The orchestrator did not checkpoint this: check the ledger, the worktrees and the "
            f"last commits before trusting the rest of this file.\n")
    return put_in_flight(home, INTERRUPT_MARK, note, f"interrupted at {when}, last order: {order or 'unknown'}")


def refusal_text(bad: list) -> str:
    """`<file>: <problem>` for the first REFUSAL_ITEMS_MAX malformed inputs, the rest counted. One line of plain text: a value
    that came from a repo file cannot carry markup into RESUME."""
    clean = lambda s: " ".join(str(s).replace("<", " ").replace(">", " ").split())  # noqa: E731
    shown = [clean(f"{name}: {problem}")[:240] for name, problem in bad[:REFUSAL_ITEMS_MAX]]
    if len(bad) > REFUSAL_ITEMS_MAX:
        shown.append(f"and {len(bad) - REFUSAL_ITEMS_MAX} more")
    return " | ".join(shown)


def write_refused_note(home: Path, when: str, bad: list) -> "Path | None":
    """The refusal note, by `put_in_flight`: the next interactive orchestrator reads RESUME at its first action."""
    fix = "fix it" if len(bad) == 1 else "fix them"
    note = (f"{REFUSED_MARK}\n- **Sprint refused {when}:** {refusal_text(bad)}; {fix} in a normal orchestrator window, "
            f"then rerun.\n")
    return put_in_flight(home, REFUSED_MARK, note, f"refused at {when}: {refusal_text(bad)}")


def report_refusal(home: Path, bad: list, when: "str | None" = None) -> str:
    """A refusal over a malformed input is reported back, not only printed: an `error` record in the sprint log when the log
    exists, and the note under RESUME's In flight. -> what became of the note, as a clause for the printed line."""
    when = when or datetime.now().astimezone().isoformat(timespec="seconds")
    if (Path(home) / slog.LOG_REL).is_file():
        try:
            slog.add_record(home, "error", f"refused: {refusal_text(bad)}")
        except OSError:
            pass
    wrote = write_refused_note(home, when, bad)
    return "RESUME carries a `sprint refused` note" if wrote else "RESUME was left as it is (the note is in the sprint log)"


def ensure_tab(home: Path, tab: str = CARD_TAB) -> bool:
    """Add `tab` to board.json `tabs` once, no BOM, every other key kept. -> True when the file changed."""
    path = Path(home) / "board" / "board.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON ({e})")
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} is not a JSON object")
    tabs = cfg.get("tabs") if isinstance(cfg.get("tabs"), list) else []
    if tab in tabs:
        return False
    cfg["tabs"] = [*tabs, tab]
    path.write_bytes((json.dumps(cfg, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return True


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


def ensure_ignored(root: Path, home: Path) -> bool:
    """Git-ignore the sprint folder and page through the repo's own `info/exclude`, which leaves every tracked file alone
    (a changed .gitignore would be a change in the repo the sprint is about to work in). -> True when a line was added."""
    path = git_exclude_path(root)
    if path is None:
        return False
    rel = Path(home).resolve().relative_to(Path(root).resolve()).as_posix()
    want = [f"/{rel}/{x}" for x in IGNORE_LINES]
    have = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    add = [w for w in want if w not in have]
    if not add:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(have) + ("\n" if have else "")
    path.write_text(body + "\n".join(["# gitos sprint mode (this machine's log and page)", *add]) + "\n",
                    encoding="utf-8", newline="\n")
    return True


# ------------------------------------------------------------------------------------------------ the sprint
class Sprint:
    def __init__(self, args, root: Path, home: Path, env, ops: Ops, claude: str):
        self.args, self.root, self.home, self.env, self.ops, self.claude = args, root, home, env, ops, claude
        self.listed = tuple(args.orders)         # the operator's --orders list; `run` replaces args.orders by the candidates
        self.sprint_dir = home / "sprint"
        self.stop_file, self.rotate_file = self.sprint_dir / "STOP", self.sprint_dir / "ROTATE"
        self.card_id = ""
        self.sessions: list = []
        self.rotations = 0
        self._last_rendered = None
        self._render_error = ""
        self._cost = ("", -1e9)

    # -- the log and its page
    def log(self, kind: str, msg: str, ref: str = "", session: str = "") -> None:
        slog.add_record(self.home, kind, msg, ref, session)
        self.render()

    def render(self, force: bool = False) -> None:
        """Write the page. A page that cannot be written (a locked or full disk, a folder in the way) is one `note` in the
        log, once per distinct failure, and the sprint carries on: the page is a view, not the sprint."""
        try:
            if self.render_page(force):
                self._render_error = ""
        except OSError as e:
            if str(e) != self._render_error:
                self._render_error = str(e)
                try:
                    slog.add_record(self.home, "note", f"the sprint page could not be written ({e})")
                except OSError:
                    pass
                self._last_rendered = self.log_signature()    # the note is not a reason to try the page again

    def log_signature(self):
        log = self.home / slog.LOG_REL
        try:
            return (log.stat().st_mtime_ns, log.stat().st_size)
        except OSError:
            return None

    def render_page(self, force: bool) -> bool:
        """-> True when the page was written, False when the log had not changed."""
        sig = self.log_signature()
        if sig == self._last_rendered and not force:
            return False
        self._last_rendered = sig
        text, at = self._cost
        if self.ops.now() - at >= COST_EVERY:
            text, at = self.ops.cost(self.sessions), self.ops.now()
            self._cost = (text, at)
        slog.render(self.home, self.root, cost=text)
        return True

    # -- the Stop card
    def post_card(self) -> None:
        old = (self.sprint_dir / "stop-card.id")
        if old.is_file():
            self.ops.board("close", old.read_text(encoding="utf-8").strip(), "superseded by a new sprint", "--tab", CARD_TAB)
        cp = self.ops.board("add-decision", CARD_TITLE, CARD_BODY, CARD_OPTION, "--tab", CARD_TAB, "--group", "action")
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
        cmd = build_command(self.claude, self.args, sid)
        proc = self.ops.launch(cmd, child_env(self.env, self.home))
        return proc, sid

    def transcript(self, sid: str) -> Path:
        return project_log_dir(self.root, self.env) / f"{sid}.jsonl"

    def close(self, proc, why: str, sid: str = "") -> dict:
        info = close_session(proc, self.ops, transcript=self.transcript(sid) if sid else None)
        left = info["survivors"]
        self.log("error" if left else "note",
                 f"closed ({why}) by {info['method']} in {info['seconds']} s; " +
                 (f"{len(left)} process(es) survived: {', '.join(map(str, left))}" if left else "no process left"))
        return info

    def end_stop(self, ident: str, reason: str, ref: str = "") -> int:
        msg = f"{ident}: {reason}" if ident else (reason or "STOP file with no text")
        found = WO_RE.search(reason)
        self.log("stop", msg, ref or (found.group(0) if found else ""))
        self.close_card(f"sprint ended: {ident or reason or 'stop'}")
        self.ops.say(f"\nsprint ended: {msg}. Log: {self.home / slog.LOG_REL}")
        return 0

    def end_error(self, kind: str, msg: str, note: bool, how: str = "") -> int:
        if note:
            order = last_order(slog.read_records(self.home), self.ops.worktree_orders())
            when = datetime.now().astimezone().isoformat(timespec="seconds")
            wrote = write_interrupted_note(self.home, when, order, how or msg)
            where = "RESUME carries an interrupted note" if wrote else "RESUME was left as it is (the note is in this log)"
            msg = f"{msg}; {where} (last order: {note_ref(order) or 'unknown'})"
        self.log(kind, msg)
        self.close_card(f"sprint ended: {msg}"[:140])
        self.ops.say(f"\nsprint ended: {msg}. Log: {self.home / slog.LOG_REL}")
        return 1

    def end_refused(self, bad: list) -> int:
        """The sprint ends because a repo file became malformed (read at a rotation): nothing is relaunched, the file is named
        in the log, on the console and in a note under RESUME's In flight."""
        where = report_refusal(self.home, bad)
        msg = f"sprint refused at a rotation: {refusal_text(bad)}"
        self.log("error", msg)
        self.close_card(f"sprint ended: {msg}"[:140])
        self.ops.say(f"\nsprint ended: {msg}; {where}. Log: {self.home / slog.LOG_REL}")
        return 1

    def run(self) -> int:
        a = self.args
        try:
            self.prepare()
            a.orders = candidate_orders(a.orders, self.home)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
            what = e if isinstance(e, (RuntimeError, ValueError)) else f"{type(e).__name__}: {e}"
            msg = f"{str(what)[:300]}; nothing was launched"
            try:
                slog.add_record(self.home, "error", msg)
            except OSError:
                pass
            self.ops.say(" ".join(f"sprint: {msg}".split()))
            return 2
        proc = None
        try:
            proc, sid = self.launch()
            allow = f" orders={','.join(a.orders)}" if a.orders else ""
            self.log("start", f"model={a.model} effort={a.effort} window={a.autocompact}{allow} session={sid}", session=sid)
            prev, streak = self.ops.snapshot(), 0
            while True:
                self.ops.sleep(POLL_SECONDS)
                self.render()
                if self.stop_file.exists():
                    self.settle(sid, proc)
                    ident, reason = parse_signal(self.stop_file.read_text(encoding="utf-8-sig", errors="replace"))
                    info = self.close(proc, "STOP", sid)
                    if info["survivors"]:
                        return self.end_error("error", "stopped with processes left", False)
                    return self.end_stop(ident, reason)
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
                proc, sid = self.launch()
                self.log("note", f"relaunched after rotation {self.rotations}: session {sid}", session=sid)
        except KeyboardInterrupt:
            if proc is not None:
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
        self.sprint_dir.mkdir(parents=True, exist_ok=True)
        slog.archive_previous(self.home)
        try:
            self.rotate_file.unlink()                # a ROTATE left by an earlier run is the driver's to clear
        except OSError:
            pass
        ensure_ignored(self.root, self.home)
        ensure_tab(self.home)
        self.post_card()

    def settle(self, sid: str, proc) -> None:
        """A signal file means the session is writing its last reply: wait until its log is quiet, then close (a session
        still not quiet at the cap is then killed, not typed into)."""
        if proc.poll() is None:
            wait_quiet(self.transcript(sid), self.ops)


def resolve_target(repo_arg: "str | None") -> "tuple[Path, Path | None, Path | None]":
    start = Path(repo_arg or Path.cwd()).resolve()
    found = slog.locate(start) if start.is_dir() else None
    if found is None:
        return start, None, None
    home, root = found
    return root, home, root


def main(argv=None, env=None, ops_factory=None) -> int:
    args = parse_args(argv)
    env = dict(os.environ if env is None else env)
    start, home, root = resolve_target(args.repo)
    claude = find_claude(env) if home is not None else None
    problems = preflight(args, env, root, home, claude=claude)
    if problems:
        for p in problems:
            print(f"sprint: {p}", file=sys.stderr)
        bad = input_problems(home, args.orders) if home is not None else []
        where = f"; {report_refusal(home, bad)}" if bad else ""
        print(f"sprint: nothing was launched{where}", file=sys.stderr)
        return 2
    ops = (ops_factory or Ops)(root, home, env, claude)
    return Sprint(args, root, home, env, ops, claude).run()


if __name__ == "__main__":
    sys.exit(main())
