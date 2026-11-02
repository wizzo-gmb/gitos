"""Restore working state after a compaction or a `/clear`, and back-stop a missed resolution.

Two hooks in one file, one entry: `SessionStart` matched on `compact|clear` restores, and `Stop`
asks once when a work order has landed unresolved or RESUME is behind the ledger (see
`stop_output`). The text below describes the restore half.

See references/roles/orchestrator.md, *Rotation triggers*. Compaction summarizes the conversation
and everything a hook added earlier, so the state the engine depends on (the live resume, the
standing rules, the role marker, this repo's federation presence) is lost exactly when a long
window needs it. The client documents that a `SessionStart` hook whose matcher is the `compact`
source runs after compaction and that its plain stdout is added to the compacted context. This
is that hook. It runs at EVERY compaction, not once, because what a hook added earlier is itself
summarized away.

WHAT IT NEVER DOES. It does not trigger compaction, it does not read the transcript, and it does
not estimate context size: none of those is documented as available to a hook or a model, and a
trigger that cannot be measured is a wish. The one thing it measures is the number of times IT
has run for a session, which is the number of compactions that session has had.

ALWAYS EXITS 0 AND FAILS SILENT. Output is plain stdout and nothing else. No home, a malformed
payload, an unreadable file or a crash all print nothing, and the session proceeds. The entry is
registered without `onFailure: "block"`.

CAPPED. The client caps a hook's plain stdout at 10,000 characters and replaces anything over
that with a file path and a short preview, which would defeat the purpose. The total is held
under OUTPUT_CAP, and the live resume is the one part that is truncated to fit.

DEFEATABLE BY CONFIGURATION. `disableAllHooks` in any settings file, and `allowManagedHooksOnly`
in a managed organization, switch hooks off. Claude Code only: a Codex session never runs this.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

EVENT = "SessionStart"
STOP_EVENT = "Stop"
# A matcher of plain names is a list of exact strings, so this fires on exactly these two sources.
MATCHER = "compact|clear"
SOURCES = ("compact", "clear")
HOOK_MATCHERS = {EVENT: MATCHER}
STOP_MATCHERS = {STOP_EVENT: None}
# The client truncates plain stdout over 10,000 characters; stay well under it.
OUTPUT_CAP = 9000
RESUME_FILENAME = "RESUME.md"
STANDING_RULES_REL = Path("brain") / "wiki" / "concepts" / "standing-rules.md"
COUNT_PREFIX = "gitos-compact-count-"
STOP_PREFIX = "gitos-stop-seen-"
OPEN_WO_CAP = 10
WORKTREE_CAP = 8
ROTATE_AT = 2
# The engine's detection order (model_optimization.HOMES).
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")


def find_home(cwd):
    """The gitos home for a working directory, walking up to the repo root. -> Path or None.

    Checks each directory from `cwd` upward in the engine's home order, and stops after the
    first directory holding a `.git` entry (the repo root). Nothing found means no output.
    """
    if not isinstance(cwd, str) or not cwd:
        return None
    here = Path(cwd).resolve()
    if not here.is_dir():
        return None
    for directory in (here, *here.parents):
        for rel in HOMES:
            candidate = directory / rel
            if candidate.is_dir():
                return candidate
        if (directory / ".git").exists():
            return None
    return None


def count_path(root, session_id):
    """Per-user temp file counting compactions for one session in one repo.

    Outside the repo on purpose, keyed by a digest like the dispatch receipt: it is session
    state, not repo content, and a clone must never arrive holding it.
    """
    key = f"{Path(root).resolve()}|{session_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"{COUNT_PREFIX}{digest[:16]}.txt"


def bump_count(root, session_id):
    """Record one more compaction for this session. -> the new count (1 on any failure)."""
    path = count_path(root, session_id)
    try:
        current = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        current = 0
    try:
        path.write_text(str(current + 1), encoding="utf-8")
    except OSError:
        pass
    return current + 1


def _git(root, *args):
    """-> stdout text, or None when git is absent, fails or times out."""
    try:
        cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


def is_linked_worktree(root):
    """True when `root` is a linked git worktree (its git dir differs from the common one)."""
    out = _git(root, "rev-parse", "--absolute-git-dir", "--git-common-dir")
    lines = out.splitlines() if out else []
    if len(lines) < 2:
        return False
    try:
        git_dir = Path(lines[0]).resolve()
        common = Path(lines[1])
        common = (common if common.is_absolute() else Path(root) / common).resolve()
    except OSError:
        return False
    return git_dir != common


def _canary():
    """The sibling canary.py loaded by path, or None. Shared logic lives there, not here."""
    path = Path(__file__).resolve().parent / "canary.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_gitos_restore_canary", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _worktree_lines(root, home):
    """The live-facts lines for worktrees and lingering branches, classed by worktree.py (through
    the canary, which owns the shared classification). -> list of lines, [] when there is nothing
    to say, or None when the classification is unavailable (the caller falls back to a bare list).
    """
    canary = _canary()
    if canary is None:
        return None
    try:
        mod, inv = canary.worktree_inventory(home)
    except Exception:
        return None
    if inv is None:
        return None
    items = inv["items"]
    with_tree = [i for i in items if i["path"]]
    branch_only = [i for i in items if not i["path"]]
    out = []
    if with_tree:
        shown = ", ".join(f"{Path(i['path']).name} [{i['branch']}] {i['class']}"
                          for i in with_tree[:WORKTREE_CAP])
        more = len(with_tree) - WORKTREE_CAP
        out.append(f"Worktrees: {shown}{f' (+{more} more)' if more > 0 else ''}.")
    if branch_only:
        parts = []
        for cls in ("reapable", "abandoned"):
            names = [i["name"] for i in branch_only if i["class"] == cls]
            if names:
                parts.append(f"{cls} {', '.join(names[:WORKTREE_CAP])}"
                             f"{f' (+{len(names) - WORKTREE_CAP} more)' if len(names) > WORKTREE_CAP else ''}")
        if parts:
            out.append("Branches with no worktree: " + "; ".join(parts) + ".")
    return out


def live_facts(root, home):
    """Current branch, worktrees and open work orders, read now. -> a list of lines.

    Read fresh at hook time because they are exactly what the RESUME text may have outlived.
    A git failure is stated and the rest carries on.
    """
    lines = []
    branch = _git(root, "branch", "--show-current")
    if branch is None:
        lines.append("Live facts: git could not be read, so the branch and worktrees are unknown.")
    else:
        branch = branch.strip()
        if not branch:
            head = (_git(root, "rev-parse", "--short", "HEAD") or "").strip()
            branch = f"(detached HEAD{' at ' + head if head else ''})"
        lines.append(f"Live facts: branch {branch}.")
        classed = _worktree_lines(root, home)
        listing = _git(root, "worktree", "list", "--porcelain") if classed is None else None
        if classed:
            lines.extend(classed)
        if listing is not None:
            trees, current = [], None
            for line in listing.splitlines():
                if line.startswith("worktree "):
                    current = [Path(line[9:]).name, "(detached)"]
                    trees.append(current)
                elif line.startswith("branch ") and current is not None:
                    current[1] = line[7:].replace("refs/heads/", "", 1)
            if len(trees) > 1:
                shown = ", ".join(f"{n} [{b}]" for n, b in trees[:WORKTREE_CAP])
                more = len(trees) - WORKTREE_CAP
                lines.append(f"Worktrees: {shown}{f' (+{more} more)' if more > 0 else ''}.")
    canary = _canary()
    if canary is not None:
        try:
            by_nnn, _ = canary._wo_files(home / "work-orders")
            names = [f"{n} {names[0]}" for n, names in sorted(by_nnn.items())]
        except Exception:
            names = None
        if names is not None:
            if names:
                more = len(names) - OPEN_WO_CAP
                lines.append("Open work orders (work-orders/): " + "; ".join(names[:OPEN_WO_CAP])
                             + (f" (+{more} more)" if more > 0 else "") + ".")
            else:
                lines.append("Open work orders (work-orders/): none.")
    return lines


def refreshed_value(text):
    """The `Refreshed:` value a RESUME states, or None."""
    for line in text.splitlines():
        stripped = line.strip().lstrip("*_> ").strip()
        if stripped.lower().startswith("refreshed:"):
            return stripped.split(":", 1)[1].strip().strip("*_ ") or None
    return None


def freshness_lines(root, resume_path, text, cleared=False):
    """RESUME freshness from git. -> a list of lines (one or two)."""
    stamp = refreshed_value(text)
    head = f"RESUME freshness: Refreshed: {stamp if stamp else 'not stated'}."
    status = _git(root, "status", "--porcelain", "--", str(resume_path))
    last = _git(root, "log", "-1", "--format=%H", "--", str(resume_path))
    if status is None or last is None:
        return [head + " Freshness is unknown (git could not be read)."]
    dirty = bool(status.strip())
    last = last.strip()
    behind = None
    if last:
        count = _git(root, "rev-list", "--count", f"{last}..HEAD")
        if count is None or not count.strip().isdigit():
            return [head + " Freshness is unknown (git could not be read)."]
        behind = int(count.strip())
    detail = []
    if behind is not None:
        detail.append(f"{behind} commit(s) since it last changed")
    else:
        detail.append("it has no commit history")
    if dirty:
        detail.append("it has uncommitted edits")
    lines = [head + " " + "; ".join(detail) + "."]
    if dirty or behind or behind is None:
        lines.append("RESUME.md is behind the work it points at: check it against the live facts "
                     "below and refresh it before relying on it." if cleared else
                     "Refresh RESUME.md now, while this summary is fresh: it is behind the "
                     "work it points at.")
    return lines


def build_output(payload):
    """The text to print for a compact payload, or None for no output at all."""
    if not isinstance(payload, dict):
        return None
    source = payload.get("source")
    if source is not None and source not in SOURCES:
        return None
    cleared = source == "clear"
    found = locate(payload)
    if found is None:
        return None
    home, root = found

    skill = Path(__file__).resolve().parent.parent
    why = ("this fresh window starts with neither the router nor the brief" if cleared else
           "a compaction keeps only a summary of files read and the start of an invoked skill")
    marker = (f"The conversation was just {'cleared' if cleared else 'compacted'}. Before anything "
              f"else, re-read in full, with the Read tool, the gitos router {skill / 'SKILL.md'} "
              "and then the brief for the role you are working in, with <role> one of orchestrator, "
              "implementer, diagnostic or inception (the router tells you which): "
              f"{skill / 'references' / 'roles'}{os.sep}<role>.md. The directives must be re-read: "
              f"{why}. Keep your first-line role marker (`[gitos · <role> · <focus>]`) in every "
              "reply and run canary.py to confirm state.")
    tail = []
    resume = home / RESUME_FILENAME
    resume_text = None
    try:
        resume_text = resume.read_text(encoding="utf-8-sig")
    except OSError:
        resume_text = None
    if resume_text is not None:
        tail.extend(freshness_lines(root, resume, resume_text, cleared))
    tail.extend(live_facts(root, home))
    rules = home / STANDING_RULES_REL
    if rules.is_file():
        tail.append(f"Re-read the standing rules now: {rules}. \"Don't do X\" constraints are "
                    f"what {'a clear' if cleared else 'compaction'} loses.")
    # A clear starts a fresh window: it is not a compaction, so it neither counts nor rotates.
    count = 0
    if not cleared:
        session = payload.get("session_id")
        count = bump_count(root, session if isinstance(session, str) else "")
        tail.append(f"Compaction count for this session: {count}.")
    if count >= ROTATE_AT:
        tail.append("This is the second compaction or later in this window, which is a "
                    "rotation trigger: checkpoint RESUME.md, tell the operator a fresh window "
                    "is ready, and stop (references/roles/orchestrator.md, Rotation triggers).")

    parts = [marker]
    if resume_text is not None:
        fixed = len(marker) + sum(len(t) for t in tail) + 200
        budget = max(0, OUTPUT_CAP - fixed - 250)
        body = resume_text.strip()
        if len(body) > budget:
            cut = len(body) - budget
            body = (body[:budget].rstrip() + f"\n[RESUME truncated: {cut} of {len(body)} "
                    f"characters cut; full file at {resume}]")
        parts.append(f"--- {RESUME_FILENAME} ---\n{body}\n--- end {RESUME_FILENAME} ---")
    parts.extend(tail)
    out = "\n".join(parts)
    return out[:OUTPUT_CAP - 1]


def locate(payload):
    """(home, repo root) for a payload's cwd, or None when the hook must stay silent.

    Silent with no home and in a linked worktree: a worker's window is not the orchestrator's,
    and the worktree holds its own copy of the ledger that would only mislead.
    """
    home = find_home(payload.get("cwd"))
    if home is None:
        return None
    root = home.parent
    if home.name == "debug" and home.parent.name == "outputs":
        root = home.parent.parent
    elif home.name == "agents" and home.parent.name == "docs":
        root = home.parent.parent
    if is_linked_worktree(root):
        return None
    return home, root


# The role signal for the `Stop` backstop. The hook cannot know the role directly; the one
# per-turn signal it is handed is `last_assistant_message`, and every gitos reply opens with a
# role marker. COST: an orchestrator whose marker slipped, or a window that never used one, gets no
# backstop (it fails quiet); the instruction is also worded to be ignored by any other role.
ORCHESTRATOR_MARKER_RE = re.compile(r"\[gitos[^A-Za-z0-9\]]{1,8}orchestrator\b", re.IGNORECASE)


def stop_state(home, canary):
    """The unresolved-state findings for a home. -> (state key, instruction) or None."""
    keys, asks = [], []
    for item in canary.landed_unresolved(home):
        keys.append(f"landed:{item['nnn']}")
        asks.append(f"WO-{item['nnn']} has landed but is still open in work-orders/")
    stale = canary.resume_stale_item(home)
    if stale is not None:
        keys.append(f"stale:{stale['newer']}@{stale.get('newer_mtime', 0)}")
        asks.append(f"RESUME.md is older than {stale['newer']}")
    resolve_asks = list(asks)
    # A reapable worktree that is still on disk. Branch-only leftovers are the canary's to report
    # (it also covers abandoned ones, which need the operator and are never raised here).
    reap = []
    try:
        reap = [f for f in canary.worktree_items(home) if f["kind"] == "worktree-reapable"
                and f.get("has_worktree")]
    except Exception:
        reap = []
    for f in reap:
        keys.append(f"reap:{f['name']}")
        asks.append(f"the worktree {f['name']} is merged and clean")
    tail = []
    if resolve_asks:
        tail.append("finish the resolution now: move the order to work-orders/resolved/, update its "
                    "INDEX row, replace RESUME.md wholesale, then run canary.py")
    if reap:
        target = reap[0]["nnn"] if len(reap) == 1 and reap[0]["nnn"] else "--merged"
        tail.append(f"reap {'it' if len(reap) == 1 else 'them'} with "
                    f"`python <skill>/scripts/worktree.py reap {target}`")
    if not keys:
        return None
    text = ("gitos: " + "; ".join(asks) + ". If you are the orchestrator, "
            + ", then ".join(tail) + ". An implementer or any other role ignores this.")
    return "|".join(keys), text


def stop_seen_path(root, session_id):
    """Per-user temp file listing the states this session was already told about."""
    key = f"{Path(root).resolve()}|{session_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"{STOP_PREFIX}{digest[:16]}.txt"


def stop_output(payload):
    """The JSON for a `Stop` payload, or None for no output at all.

    LOOP GUARD, two layers. `stop_hook_active` true means the client is already continuing
    because of a stop hook, so this prints nothing. Independently, each distinct state is raised
    once per session: the state is recorded BEFORE anything is printed, and a record that cannot
    be written means no output, so a failing temp dir can never turn into a nag every turn. The
    client also caps consecutive stop-hook continuations. Uses `additionalContext`, the
    non-error way to ask Claude for one more action. Never writes to the repo.
    """
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not ORCHESTRATOR_MARKER_RE.search(message[:400]):
        return None
    found = locate(payload)
    if found is None:
        return None
    home, root = found
    if not (home / RESUME_FILENAME).is_file():
        return None
    canary = _canary()
    if canary is None:
        return None
    state = stop_state(home, canary)
    if state is None:
        return None
    key, text = state
    session = payload.get("session_id")
    path = stop_seen_path(root, session if isinstance(session, str) else "")
    try:
        seen = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        seen = []
    if key in seen:
        return None
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(key + "\n")
    except OSError:
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": STOP_EVENT,
                                              "additionalContext": text}}, ensure_ascii=False)


def heartbeat_own(payload):
    """Refresh THIS repo's own federation record through the existing code. Never raises.

    Only when `<home>/federation.json` exists. All of its output is swallowed and a failure
    changes nothing else; nothing but this repo's own record is written.
    """
    try:
        home = find_home(payload.get("cwd")) if isinstance(payload, dict) else None
        if home is None or not (home / "federation.json").is_file():
            return
        path = Path(__file__).resolve().parent / "federation.py"
        if not path.is_file():
            return
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec = importlib.util.spec_from_file_location("_gitos_compact_federation", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            module.heartbeat(home)
    except BaseException:
        pass


def hook_command(stream):
    """The client-event entry point. ALWAYS returns 0; stdout carries the restore text or nothing."""
    try:
        # The client writes UTF-8; a Windows console stream decodes it with the locale codepage,
        # which garbles the role marker's separator. Read the bytes when the stream has them.
        raw = (stream.buffer.read().decode("utf-8-sig", errors="replace")
               if hasattr(stream, "buffer") else stream.read())
        payload = json.loads(raw or "null")
        if isinstance(payload, dict) and payload.get("hook_event_name") == STOP_EVENT:
            text = stop_output(payload)
            if text is not None:
                sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
                sys.stdout.buffer.flush()
            return 0
        text = build_output(payload)
        if text is not None:
            heartbeat_own(payload)
            sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
    except BaseException:
        pass
    return 0


# --------------------------------------------------------------------------- registration
# SELF-LOCATING, like the dispatch gate's bootstrap: the file it lands in is committed, so an
# absolute path would be one machine's truth travelling to every clone. Any failure is swallowed.
HOOK_BOOTSTRAP = (
    "import importlib.util, pathlib, sys\n"
    "try:\n"
    "    p = pathlib.Path.home() / '.claude/skills/gitos/scripts/compact_restore.py'\n"
    "    spec = importlib.util.spec_from_file_location('gitos_compact_restore', p)\n"
    "    mod = importlib.util.module_from_spec(spec)\n"
    "    spec.loader.exec_module(mod)\n"
    "    mod.hook_command(sys.stdin)\n"
    "except BaseException:\n"
    "    pass\n"
)


def hook_entry(event=EVENT):
    """The entry this hook registers: the same `args` on every event, which is its identity.

    Neither `async` nor `onFailure` is set. The `Stop` entry carries no status message, which
    would flash at the end of every turn.
    """
    entry = {"type": "command", "command": "python", "args": ["-I", "-c", HOOK_BOOTSTRAP],
             "statusMessage": "gitos: restoring working state after compaction or clear"}
    if event == STOP_EVENT:
        del entry["statusMessage"]
    return entry


def _engine():
    path = Path(__file__).resolve().parent / "model_optimization.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_gitos_compact_model_optimization", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def ensure_hook(root, engine=None):
    """Register this hook in `<root>/.claude/settings.json`. -> (status, detail).

    Reuses the optimization helper's writer, which appends beside whatever it finds and is
    idempotent on the entry's `args`.
    """
    engine = _engine() if engine is None else engine
    if engine is None:
        return "skipped", "model_optimization.py not found beside compact_restore.py"
    status, detail = engine.ensure_settings_hook(root, entry=hook_entry(), matchers=HOOK_MATCHERS)
    if status == "skipped":
        return status, detail
    stop_status, _ = engine.ensure_settings_hook(root, entry=hook_entry(STOP_EVENT),
                                                 matchers=STOP_MATCHERS)
    migrated = _widen_matcher(root, engine)
    added = []
    if status != "present":
        added.append(detail)
    if stop_status in ("appended", "created"):
        added.append(STOP_EVENT)
    if migrated:
        added.append(f"matcher widened to {MATCHER}")
    if not added:
        return "present", detail
    return ("created" if status == "created" else "appended"), ", ".join(added)


def _widen_matcher(root, engine):
    """Upgrade an older `compact`-only registration of THIS hook in place. -> True if changed.

    The engine's writer recognises an entry by its `args` and then leaves it alone, so an entry
    registered before `clear` existed would stay on `compact` for ever. Rewriting its matcher here
    keeps it one entry firing once per event. If the old group also holds some other command, ours
    is moved into a group of its own so that command's scope does not widen with it.
    """
    path = Path(root) / ".claude" / "settings.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        groups = doc["hooks"][EVENT]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not isinstance(groups, list):
        return False
    args = hook_entry()["args"]
    changed, result = False, []
    for group in groups:
        mine = isinstance(group, dict) and group.get("matcher") == "compact" \
            and isinstance(group.get("hooks"), list) \
            and [h for h in group["hooks"] if isinstance(h, dict) and h.get("args") == args]
        if not mine:
            result.append(group)
            continue
        changed = True
        others = [h for h in group["hooks"] if h not in mine]
        if others:
            result.append({**group, "hooks": others})
            result.append({"matcher": MATCHER, "hooks": mine})
        else:
            result.append({**group, "matcher": MATCHER})
    if not changed:
        return False
    doc["hooks"][EVENT] = result
    engine.write_json_atomic(path, doc)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Restore working state after compaction.")
    parser.add_argument("command", choices=("hook", "install"))
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args(argv)
    if args.command == "hook":
        return hook_command(sys.stdin)
    root = Path(args.root).resolve()
    status, detail = ensure_hook(root)
    print(f"gitos compact restore: {status} in {root / '.claude' / 'settings.json'}"
          f"{f' - {detail}' if detail else ''}")
    return 0 if status != "skipped" else 3


if __name__ == "__main__":
    raise SystemExit(main())
