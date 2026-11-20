#!/usr/bin/env python3
"""cost_report.py - where a repo's Claude Code session spend goes: orchestrator window versus workers, by model.

Reads Claude Code's own session logs, read-only, stdlib only. `~/.claude/projects/<project-dir>/<session>.jsonl` is the
main window; its workers are `<project-dir>/<session>/subagents/*.jsonl`. Each `message.id` is counted once per session.
Dollars come from a small approximate price table (override with --prices FILE); shares are the reliable part.

  python cost_report.py [--project DIR | --repo PATH] [--since YYYY-MM-DD] [--top N] [--prices FILE] [--json]

Exit 1 with one sentence when the folder is missing or the log layout is not the one this reads (never zeros).
A model that matches no price family is shown as `unpriced` with its tokens, never as $0.00.
The costliest-workers list puts unpriced workers first (by tokens), then priced ones by dollars.
Subcommands other than the report go in COMMANDS (dispatched on the first argument); `ccusage status|set` keeps this
machine's answer to the one-time ccusage offer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Approximate $/Mtok by model family (input, cache read, cache write, output), fitted once to ccusage session rows; a label, not a quote.
DEFAULT_PRICES = {
    "opus": {"input": 2.0, "cache_read": 0.2, "cache_write": 5.0, "output": 17.0},
    "sonnet": {"input": 1.0, "cache_read": 0.1, "cache_write": 2.5, "output": 10.0},
    "haiku": {"input": 0.4, "cache_read": 0.1, "cache_write": 0.4, "output": 2.3},
    "fable": {"input": 2.0, "cache_read": 0.2, "cache_write": 15.5, "output": 37.0},
}
BRIEF_CHARS = 70
NOTE = ("Dollars are approximate (price table, not a bill); shares between orchestrator, workers and models are "
        "the reliable figures.")


class LayoutError(Exception):
    """The log folder is missing or not the layout this tool reads."""


def family(model: str, prices: dict) -> str:
    low = (model or "").lower()
    for fam in prices:
        if fam in low:
            return fam
    return "unpriced"


def cost(usage: dict, fam: str, prices: dict) -> float:
    p = prices.get(fam)
    if not p:
        return 0.0
    return (usage["input"] * p.get("input", 0) + usage["cache_read"] * p.get("cache_read", 0)
            + usage["cache_write"] * p.get("cache_write", 0) + usage["output"] * p.get("output", 0)) / 1e6


def read_lines(path: Path):
    """Yield the parsed JSON objects of a jsonl file; a malformed (e.g. truncated last) line is skipped."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def _first_line(content) -> str:
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return ""
    for ln in content.splitlines():
        if ln.strip():
            return ln.strip()[:BRIEF_CHARS]
    return ""


def read_file(path: Path, seen: set | None = None) -> dict:
    """One log file -> its unique assistant messages (ids already in `seen`, from earlier files of the session, are skipped), dispatches, compactions, first timestamp, first user line."""
    msgs: dict = {}
    order: list = []
    sent: dict = {}
    compactions = 0
    first_ts = None
    brief = None
    for o in read_lines(path):
        if first_ts is None and isinstance(o.get("timestamp"), str):
            first_ts = o["timestamp"]
        t = o.get("type")
        if t == "system" and o.get("subtype") == "compact_boundary":
            compactions += 1
        elif t == "user" and brief is None and isinstance(o.get("message"), dict):
            brief = _first_line(o["message"].get("content"))
        elif t == "assistant" and isinstance(o.get("message"), dict):
            m = o["message"]
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            mid = m.get("id") or o.get("uuid")
            if mid not in msgs:
                order.append(mid)
            msgs[mid] = {  # a streamed message repeats: keep the last, count once
                "model": m.get("model") or "unknown",
                "input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
                "cache_read": int(u.get("cache_read_input_tokens") or 0),
                "cache_write": int(u.get("cache_creation_input_tokens") or 0)}
            sent[mid] = []  # the last copy of a streamed message wins, with its dispatches
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    sent[mid].append((inp.get("model") or "omitted", inp.get("effort") or "omitted"))
    if seen is not None:  # a forked worker log can replay its parent's messages: one session counts each id once
        order = [i for i in order if i not in seen]
        seen.update(order)
    dispatches = [d for i in order for d in sent[i]]
    return {"msgs": [msgs[i] for i in order], "dispatches": dispatches, "compactions": compactions,
            "first_ts": first_ts, "brief": brief or "", "mtime": path.stat().st_mtime}


def pct(vals: list, q: float) -> int:
    if not vals:
        return 0
    s = sorted(vals)
    return int(s[min(len(s) - 1, int(q * len(s)))])


def summarise(rec: dict, prices: dict) -> dict:
    by_model: dict = defaultdict(lambda: {"turns": 0, "usd": 0.0, "tokens": 0, "priced": True})
    ctx = []
    for m in rec["msgs"]:
        fam = family(m["model"], prices)
        bm = by_model[m["model"]]
        bm["priced"] = fam != "unpriced"
        bm["turns"] += 1
        bm["usd"] += cost(m, fam, prices)
        bm["tokens"] += m["input"] + m["output"] + m["cache_read"] + m["cache_write"]
        ctx.append(m["input"] + m["cache_read"] + m["cache_write"])
    models = {k: dict(v) for k, v in by_model.items()}
    return {"usd": sum(v["usd"] for v in models.values()), "turns": len(ctx), "models": models,
            "tokens": sum(v["tokens"] for v in models.values()),
            "median_ctx": int(statistics.median(ctx)) if ctx else 0, "p90_ctx": pct(ctx, 0.9),
            "model": max(models, key=lambda k: models[k]["turns"]) if models else "unknown",
            "priced": family(max(models, key=lambda k: models[k]["turns"]), prices) != "unpriced" if models else True}


def session_start(rec: dict) -> datetime:
    ts = rec["first_ts"]
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.fromtimestamp(rec["mtime"], tz=timezone.utc)


def build_report(project: Path, since, top: int, prices: dict) -> dict:
    if not project.is_dir():
        raise LayoutError(f"no project log folder at {project}")
    mains = sorted(project.glob("*.jsonl"))
    if not mains:
        raise LayoutError(f"{project} holds no <session>.jsonl files: not the Claude Code project-log layout")
    sessions, seen_usage, empty = [], False, 0
    all_workers, disp = [], Counter()
    for f in mains:
        seen: set = set()
        main = read_file(f, seen)
        seen_usage = seen_usage or bool(main["msgs"])
        start = session_start(main)
        if since and start.date() < since:
            continue
        workers = []
        for wf in sorted((project / f.stem / "subagents").glob("*.jsonl")):
            w = read_file(wf, seen)
            seen_usage = seen_usage or bool(w["msgs"])
            s = summarise(w, prices)
            s["brief"], s["id"] = w["brief"], wf.stem
            workers.append(s)
        orch = summarise(main, prices)
        if not orch["turns"] and not workers:
            empty += 1
            continue
        wmodels: dict = defaultdict(lambda: {"count": 0, "usd": 0.0, "tokens": 0, "priced": True})
        for w in workers:
            wmodels[w["model"]]["count"] += 1
            wmodels[w["model"]]["usd"] += w["usd"]
            wmodels[w["model"]]["tokens"] += w["tokens"]
            wmodels[w["model"]]["priced"] = w["priced"]
        disp.update(main["dispatches"])
        all_workers += [dict(w, session=f.stem) for w in workers]
        sessions.append({"session": f.stem, "start": start.isoformat(), "orchestrator": orch,
                         "compactions": main["compactions"], "workers_count": len(workers),
                         "workers_usd": sum(w["usd"] for w in workers),
                         "workers_by_model": {k: dict(v) for k, v in wmodels.items()}})
    if not seen_usage:
        raise LayoutError("no assistant message with usage found in any log: the Claude Code log format may have "
                          "changed, refusing to print zeros")
    if not sessions:
        raise LayoutError("no session with any usage starts on or after --since")
    sessions.sort(key=lambda x: x["start"])
    # An unpriced worker costs $0 only because nothing prices it, so it is not ranked by dollars: unpriced
    # workers come first (by tokens), then the priced ones by dollars.
    costliest = sorted(all_workers, key=lambda w: (w["priced"], -w["tokens"] if not w["priced"] else -w["usd"]))[:top]
    return {"project": str(project), "note": NOTE, "prices": prices, "sessions": sessions, "empty_sessions": empty,
            "totals": {"orchestrator_usd": sum(s["orchestrator"]["usd"] for s in sessions),
                       "workers_usd": sum(s["workers_usd"] for s in sessions),
                       "workers": len(all_workers),
                       "median_worker_turns": int(statistics.median([w["turns"] for w in all_workers]))
                       if all_workers else 0,
                       "median_worker_ctx": int(statistics.median([w["median_ctx"] for w in all_workers]))
                       if all_workers else 0,
                       "workers_by_model": _merge(s["workers_by_model"] for s in sessions)},
            "costliest_workers": [{k: w[k] for k in ("session", "id", "usd", "turns", "median_ctx", "model", "priced", "tokens",
                                                       "brief")}
                                  for w in costliest],
            "dispatches": [{"model": m, "effort": e, "count": n} for (m, e), n in sorted(disp.items())]}


def _merge(parts) -> dict:
    out: dict = defaultdict(lambda: {"count": 0, "usd": 0.0, "tokens": 0, "priced": True})
    for p in parts:
        for k, v in p.items():
            out[k]["count"] += v["count"]
            out[k]["usd"] += v["usd"]
            out[k]["tokens"] += v["tokens"]
            out[k]["priced"] = v["priced"]
    return {k: dict(v) for k, v in out.items()}


def money(usd: float, priced: bool, tokens: int) -> str:
    """Dollars, or `unpriced` with its tokens when the model matches no price family (never a false $0.00)."""
    return f"${usd:.2f}" if priced else f"unpriced ({tokens:,} tokens)"


def render(r: dict) -> str:
    out = [f"Project: {r['project']}", f"Note: {r['note']}", ""]
    for s in r["sessions"]:
        o = s["orchestrator"]
        out.append(f"Session {s['session']} (start {s['start'][:10]})")
        out.append(f"  orchestrator ${o['usd']:.2f}  turns {o['turns']}  context median {o['median_ctx']:,} "
                   f"p90 {o['p90_ctx']:,}  compactions {s['compactions']}")
        for m, v in sorted(o["models"].items()):
            out.append(f"    {m}: {money(v['usd'], v['priced'], v['tokens'])} ({v['turns']} turns)")
        out.append(f"  workers {s['workers_count']}  ${s['workers_usd']:.2f}")
        for m, v in sorted(s["workers_by_model"].items()):
            out.append(f"    {m}: {v['count']} workers {money(v['usd'], v['priced'], v['tokens'])}")
    if r["empty_sessions"]:
        out.append(f"({r['empty_sessions']} sessions without usage not listed)")
    t = r["totals"]
    spread = (f" (median worker: {t['median_worker_turns']} turns, context {t['median_worker_ctx']:,})"
              if t["workers"] else "")
    out += ["", f"Total: orchestrator ${t['orchestrator_usd']:.2f}, {t['workers']} workers ${t['workers_usd']:.2f}{spread}"]
    for m, v in sorted(t["workers_by_model"].items()):
        out.append(f"  workers on {m}: {v['count']} {money(v['usd'], v['priced'], v['tokens'])}")
    if any(not v["priced"] for s in r["sessions"] for v in list(s["orchestrator"]["models"].values())
           + list(s["workers_by_model"].values())):
        out.append("  Unpriced models are left out of the dollar totals; add them with --prices.")
    out += ["", "Costliest workers:"]
    if any(not w["priced"] for w in r["costliest_workers"]):
        out.append("  (unpriced workers are listed first, by tokens; the rest by dollars)")
    for w in r["costliest_workers"]:
        out.append(f"  {money(w['usd'], w['priced'], w['tokens'])}  {w['turns']} turns  ctx {w['median_ctx']:,}  {w['model']}  {w['brief']}")
    out += ["", "Dispatches by (model, effort):"]
    for d in r["dispatches"]:
        out.append(f"  {d['model']} / {d['effort']}: {d['count']}")
    return "\n".join(out)


def project_dir_for_repo(repo: Path, root: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    for d in root.iterdir() if root.is_dir() else []:
        if d.name.lower() == name.lower():
            return d
    raise LayoutError(f"no Claude Code project folder for {repo} under {root}")


def run_report(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="cost_report.py", description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", help="a project log folder (~/.claude/projects/<dir>)")
    g.add_argument("--repo", help="a repo path; its project folder is found under ~/.claude/projects")
    ap.add_argument("--since", help="only sessions starting on or after YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--prices", help="JSON file: {family: {input, cache_read, cache_write, output}} in $/Mtok")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        since = datetime.strptime(a.since, "%Y-%m-%d").date() if a.since else None
        prices = DEFAULT_PRICES
        if a.prices:
            prices = json.loads(Path(a.prices).read_text(encoding="utf-8"))
        project = (Path(a.project) if a.project
                   else project_dir_for_repo(Path(a.repo), Path.home() / ".claude" / "projects"))
        report = build_report(project, since, a.top, prices)
    except LayoutError as e:
        print(f"cost_report: {e}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f"cost_report: cannot read an input ({e})", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if a.json else render(report))
    return 0


STORE_NAME = "gitos-ccusage.json"
ANSWERS = ("declined", "installed")


def claude_home(arg=None) -> Path:
    """The Claude home the machine answer lives in: --claude-home, else CLAUDE_CONFIG_DIR, else ~/.claude."""
    return Path(arg or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def stored_answer(home: Path) -> "str | None":
    """The recorded ccusage answer (`declined` | `installed`) or None when there is none; ValueError when unreadable."""
    path = Path(home) / STORE_NAME
    if not path.is_file():
        return None
    try:
        pref = json.loads(path.read_text(encoding="utf-8")).get("preference")
    except (ValueError, OSError, AttributeError) as e:
        raise ValueError(f"{path} is unreadable ({e})")
    if pref not in ANSWERS:
        raise ValueError(f"{path} holds preference {pref!r}, expected one of {', '.join(ANSWERS)}")
    return pref


def ccusage_state(home: Path, which=shutil.which) -> str:
    """installed (on PATH) | declined | missing (recorded installed, not on PATH) | unasked."""
    if which("ccusage"):
        return "installed"
    pref = stored_answer(home)
    return {"declined": "declined", "installed": "missing"}.get(pref, "unasked")


def run_ccusage(argv: list, which=shutil.which) -> int:
    ap = argparse.ArgumentParser(prog="cost_report.py ccusage", description="This machine's answer to the ccusage offer.")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("status", help="print installed, declined, missing or unasked")
    st = sub.add_parser("set", help="record the answer")
    st.add_argument("answer", choices=ANSWERS)
    for sp in sub.choices.values():
        sp.add_argument("--claude-home", default=None)
    a = ap.parse_args(argv)
    home = claude_home(a.claude_home)
    try:
        if a.action == "status":
            print(ccusage_state(home, which))
            return 0
        if a.answer == "installed" and not which("ccusage"):
            print("cost_report: ccusage is not on PATH; install it first, then record it", file=sys.stderr)
            return 1
        home.mkdir(parents=True, exist_ok=True)
        (home / STORE_NAME).write_text(json.dumps({"preference": a.answer}) + chr(10), encoding="utf-8")
    except (ValueError, OSError) as e:
        print(f"cost_report: {e}", file=sys.stderr)
        return 1
    print(f"ccusage: {a.answer}")
    return 0


COMMANDS: dict = {"ccusage": run_ccusage}  # name -> callable(argv) -> exit code, dispatched on the first argument


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    return run_report(argv)


if __name__ == "__main__":
    sys.exit(main())
