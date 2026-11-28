#!/usr/bin/env python3
"""System One: the typed questions and decision tables the loose-ends drain runs on, answered by a helper.

Stdlib only. Library plus CLI. Detail and the "how to add a use" recipe: `references/system-one.md`. Question
wording and decision tables live ONLY in `system_one_questions.py` (the registry).

THE DRAIN: `drain <home> --export FILE` writes the questions of every `new` loose end; a helper dispatched on the
cheapest tier answers the file; `drain <home> --answers FILE` applies each use's table to the answers and writes the
proposals. Judgments come from the helper, decisions come from a table in code. An answer that is missing or not an
allowed word counts as `unsure`, never as a "no". Nothing here calls a model or opens a network connection.

The local model backend was retired in v75: a call to a removed command exits 2 with one sentence.

PUBLIC API (everything a use needs; later work-orders extend the registry, not this file)

    helper_export(items) -> dict                 the export document of a list state
    helper_apply(items, doc) -> {"outcomes": {ref: {"outcome", "confirm", "inputs"}}, "defaulted", "unknown"}
    drain_export(home, path) / drain_answers(home, doc)    the two steps of the drain
    require_reversible(result)                   raises ConfirmRequired on a `confirm` outcome
    registry_problems() -> [str]

ADDING A USE = one `register(...)` entry in the registry plus a CLI subcommand in the calling script that builds the
state, applies the table to the helper's answers and applies only `reversible` outcomes (guard with
`require_reversible`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from importlib import util as importlib_util
from pathlib import Path

RETIRED_SENTENCE = ("the local model was retired in v75; the drain runs on a helper: "
                    "system_one.py drain <home> --export FILE, then --answers FILE")
RETIRED_COMMANDS = ("status", "repo", "setup", "uses-check", "ask", "log", "migrate")
HELPER_MODEL = "helper"           # the `model:` line of a proposal answered by a dispatched helper


class ConfirmRequired(Exception):
    """A `confirm` outcome reached a caller that writes."""



def _registry():
    mod = sys.modules.get("system_one_questions")
    if mod is None:
        path = Path(__file__).resolve().with_name("system_one_questions.py")
        spec = importlib_util.spec_from_file_location("system_one_questions", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["system_one_questions"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("system_one_questions", None)
            raise
    return mod


def registry_problems() -> list:
    try:
        _registry()
        return []
    except Exception as e:
        return [f"{type(e).__name__}: {e}"]



def require_reversible(result: dict) -> None:
    """For callers that write: a `confirm` outcome is only ever reported, never applied."""
    if result.get("confirm"):
        raise ConfirmRequired(f"outcome {result.get('outcome')!r} needs confirmation; report it, "
                              f"do not apply it")



def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



# ------------------------------------------------------------------------------------- loose-ends items
# Code gathers the loose-ends items and the candidate pairs; the registry's `loose-end-*` uses judge them.
# The drain below is the only reader of the answers.
MAX_STATE = 1500                  # characters per item sent to the helper: small items are fast
MAX_PAIRS = 40
HUB_LIMIT = 4                     # a reference or path shared by more items than this is no signal
OVERLAP = 0.5                     # word-overlap (Jaccard) above which a pair becomes a candidate
_REF = re.compile(r"\b(?:WO-\d{3}|P\d+)\b")
_PATH = re.compile(r"[\w.-]+(?:/[\w.-]+)+|\b[\w-]+\.(?:py|md|json|js|html|sh|toml|ya?ml)\b")
_WORD = re.compile(r"[a-z][a-z0-9_-]{3,}")
_STOP = frozenset("that this with from have been will they them then than when which what where "
                  "would could should about into only also each every their there these those "
                  "work-order note notes item items file files".split())


def _canary():
    """canary.py, imported by path (the way canary imports its siblings); its parsers are reused."""
    mod = sys.modules.get("_gitos_canary_s1")
    if mod is None:
        path = Path(__file__).resolve().with_name("canary.py")
        spec = importlib_util.spec_from_file_location("_gitos_canary_s1", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_canary_s1"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_canary_s1", None)
            raise
    return mod


def _squash(s: str) -> str:
    return " ".join(str(s).split())


def _cap(s: str, n: int = MAX_STATE) -> str:
    s = _squash(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def _read_text(p: Path) -> "str | None":
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _title(text: str, fallback: str) -> str:
    for ln in text.splitlines():
        if ln.startswith("# "):
            return _squash(ln[2:])
    return fallback


def _wo_listing(home: Path, c) -> list:
    """[(nnn, path, resolved)] for every work-order file, open first."""
    out = []
    for sub, resolved in (("work-orders", False), ("work-orders/resolved", True)):
        d = home / sub
        for nnn, names in sorted(c._wo_files(d)[0].items()):
            out.append((nnn, d / names[0], resolved))
    return out


def _signals(text: str, own: str) -> tuple:
    refs = set(_REF.findall(text)) | {own}
    paths = set(_PATH.findall(text))
    words = {w for w in _WORD.findall(text.lower()) if w not in _STOP}
    return refs, paths, words


def _loose_ends():
    """loose_ends.py, imported by path (it imports this module back lazily, for the signals)."""
    mod = sys.modules.get("_gitos_loose_ends_s1")
    if mod is None:
        path = Path(__file__).resolve().with_name("loose_ends.py")
        spec = importlib_util.spec_from_file_location("_gitos_loose_ends_s1", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_loose_ends_s1"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_loose_ends_s1", None)
            raise
    return mod


def _loose_state(ref: str, item: str, source: str, age: "int | None") -> str:
    """What `loose-end-state` is asked: the item's text, its Source and its age in days."""
    when = f"{age} days old" if age is not None else "age unknown"
    return _cap(f"Loose end {ref} (from {source}, {when}): {item}")


def _join_item(j: dict) -> dict:
    return {"group": "loose-ends", "use": "loose-end-join", "ref": f"{j['item']}~{j['wo']}",
            "text": f"A {j['wo']}: {_cap(j['wo_text'], 500)}\nB {j['item']}: {_cap(j['item_text'], 300)}",
            "state": f"Work-order A ({j['wo']}): {_cap(j['wo_text'], 900)}\n"
                     f"Item B ({j['item']}): {_cap(j['item_text'], 300)}"}




def _loose_end_items(home: Path) -> tuple:
    """-> (items, new rows, open orders). Read from `<home>/loose-ends.md` with no flag. Each `new` item is
    asked `loose-end-state` (a row in any other state, or one whose State cannot be read, is asked nothing); the (item, open order) join pairs (the item's best three open orders by BM25, in progress or not, from references, paths and words)
    and the (item, item) bundle pairs are chosen by code (`loose_ends.candidates`). A `new` row a pile file already
    holds (a crash between the pile write and the row write) is asked nothing: the next write marks it `proposed:`."""
    le = _loose_ends()
    if not le.list_path(home).is_file():
        return [], [], []
    piled = _pile_ids(home)
    rows = [r for r in le.rows_of(home)
            if r["state"].strip() == le.STATE_NEW and le.ID_RE.fullmatch(r["id"]) and r["id"] not in piled]
    if not rows:
        return [], [], []
    cand = le.candidates(home, sm=sys.modules[__name__])
    items = [{"group": "loose-ends", "use": "loose-end-state", "ref": r["id"], "text": _cap(r["item"], 300),
              "state": _loose_state(r["id"], r["item"], r["source"], le.age_days(r["added"]))} for r in rows]
    for j in cand["join"]:
        items.append(_join_item(j))
    for b in cand["bundle"]:
        items.append({"group": "loose-ends", "use": "loose-end-bundle", "ref": f"{b['a']}~{b['b']}",
                      "text": f"A {b['a']}: {_cap(b['a_text'], 300)}\nB {b['b']}: {_cap(b['b_text'], 300)}",
                      "state": f"Item A ({b['a']}): {_cap(b['a_text'], 400)}\n"
                               f"Item B ({b['b']}): {_cap(b['b_text'], 400)}"})
    return items, rows, cand["orders"]


def _bundle_groups(results: list) -> list:
    """Groups of items that bundle, joined by code: [[L1, L2, L5], ...], every pair in a group agreed.
    A pair answered `bundle` is an edge; a group is a clique of those edges, never a chain. Bundling is not
    transitive (A~B and B~C say nothing about A and C), so a connected component is split greedily: items in
    id order, each taking the lowest-numbered unplaced item that agrees with every member so far; an item that
    agrees with only part of a group stays out of it (it may seed or join another group; one that agrees with
    nobody left is in no group). Deterministic: the same answers give the same groups."""
    agree: dict = {}
    for r in results:
        if r["use"] == "loose-end-bundle" and r["outcome"] == "bundle":
            a, b = r["ref"].split("~")
            if a != b:
                agree.setdefault(a, set()).add(b)
                agree.setdefault(b, set()).add(a)
    order = sorted(agree, key=lambda t: int(t[1:]))
    placed: set = set()
    groups: list = []
    for seed in order:
        if seed in placed:
            continue
        group = [seed]
        for x in order:
            if x != seed and x not in placed and x not in group and all(x in agree[m] for m in group):
                group.append(x)
        if len(group) > 1:
            placed.update(group)
            groups.append(sorted(group, key=lambda t: int(t[1:])))
    return sorted(groups, key=lambda g: int(g[0][1:]))


_TRIGGER = re.compile(r"\b(?:after|once|until|when|waits? (?:for|on)|following)\b[^.;]{3,70}", re.I)


def _fix_label(fix: dict) -> str:
    return fix["ref"] if fix["kind"] == "order" else f"commit {fix['ref']}"


def _drain_plan(results: list, bundles: list, fixed: "dict | None" = None) -> list:
    """One proposed next step per loose end, built by code from the answers: [{ref, step}]. A step the
    item's own state settles (`close`, `ask`, `park`) comes first; otherwise a `join` answer beats a
    bundle group, and a bundle beats `open` alone (an item still unsettled is `read it`). `fixed` is
    `loose_ends.fixed_elsewhere`: an item it names that is not settled as `ask` or `park` becomes a `close`
    step naming the fix (the item's own `closable` gets the fix attached), ahead of join, bundle and read.
    Nothing is applied."""
    best: dict = {}
    for r in results:
        if r["use"] == "loose-end-join" and r["outcome"] == "join":
            item, wo = r["ref"].split("~")
            best.setdefault(item, wo)
    plan = []
    for r in results:
        if r["use"] != "loose-end-state":
            continue
        ref, out = r["ref"], r["outcome"]
        group = next((g for g in bundles if ref in g), None)
        kind, wo = "read", None
        fix = (fixed or {}).get(ref)
        if out == "closable":
            step, kind = "close (confirm)", "close"
        elif out == "ask-operator":
            step, kind = "ask the operator", "ask"
        elif out == "park":
            m = _TRIGGER.search(r["text"])
            trig = _squash(m.group(0)) if m else "name the event"
            step, kind = f"park (trigger: {trig})", "park"
        elif fix:
            step, kind = f"close (confirm): possibly fixed by {_fix_label(fix)}", "close"
        elif ref in best:
            step, kind, wo = f"related open order: consider adding {best[ref]}", "join", best[ref]
        elif group:
            step, kind = "bundle with " + ", ".join(x for x in group if x != ref) + " -> new order", "bundle"
        else:
            step, kind = "read it", ("open" if out == "open" else "read")
        plan.append({"ref": ref, "step": step, "kind": kind, "wo": wo,
                     "fix": fix if kind == "close" else None})
    return sorted(plan, key=lambda p: int(p["ref"][1:]))


def _cause(r: dict, use: "str | None" = None) -> str:
    """Why an item escalated: the unsure questions, or the answers that conflict."""
    if r["outcome"] != "escalate":
        return ""
    reg = _registry()
    reads = reg.USES[use]["reads"](dict(r["inputs"])) if use in reg.USES and         set(r["inputs"]) == {q["id"] for q in reg.USES[use]["questions"]} else list(r["inputs"])
    unsure = [k for k in reads if r["inputs"].get(k) == "unsure"]
    if unsure:
        return "unsure: " + ", ".join(unsure)
    yes = [f"{k}={v}" for k, v in r["inputs"].items() if v == "yes"]
    return "conflict: " + (", ".join(yes) if yes else "no answer is yes")


# ------------------------------------------------------------------ the drain proposals (WO-098, WO-115)
# `drain --answers` is the one System One command that writes in the home. The list row is the authority: a proposed item's
# row reads `proposed: <kind>`, and one file per proposal under `<home>/drain/pending/` is its attachment (what was
# asked and found). Accept, decline and withdraw change the row and remove the file (git keeps it). No sentence is
# model-written: each is an item's own text or built by code from the answers.
DRAIN_DIR = "drain"
DRAIN_KINDS = ("join", "new-order", "ask", "park", "close", "read")
_TICKS = re.compile(r"`([^`\n]{2,60})`")
_DRAIN_ID = re.compile(r"[0-9a-f]{12}")


def _write_text_atomic(path: Path, text: str) -> None:
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".s1-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def drain_id(kind: str, items: list, wo: "str | None" = None) -> str:
    """A fingerprint of the proposal: its kind, its sorted item ids, and the target order for a join."""
    key = "|".join([kind, ",".join(sorted(items))] + ([wo] if kind == "join" and wo else []))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _group_context(home: Path, c, ids: list, rows: dict, orders: list) -> list:
    """Context gathered by code: the Source orders and their titles, paths and backticked names found in
    the items, open orders sharing those paths, the oldest item's age."""
    titles = {nnn: _title(_read_text(path) or "", path.stem) for nnn, path, _res in _wo_listing(home, c)}
    srcs, paths, names = [], [], []
    for ref in ids:
        r = rows[ref]
        for w in _REF.findall(r["source"] + " " + r["text"]):
            if w.startswith("WO-") and w not in srcs:
                srcs.append(w)
        paths += [x for x in _PATH.findall(r["text"]) if x not in paths]
        names += [x for x in _TICKS.findall(r["text"]) if x not in names]
    out = []
    if srcs:
        out.append("Source orders: " + "; ".join(f"{w} ({titles.get(w[3:], 'no such order')})" for w in srcs))
    if paths:
        out.append("Paths: " + ", ".join(f"`{x}`" for x in paths))
    if names:
        out.append("Names: " + ", ".join(f"`{x}`" for x in names))
    sharing = [o["ref"] for o in orders if any(x in o["text"] for x in paths)]
    if sharing:
        out.append("Open orders that share these paths: " + ", ".join(sharing))
    ages = [rows[r]["age"] for r in ids if rows[r]["age"] is not None]
    if ages:
        out.append(f"Oldest item: {max(ages)} days")
    return out


def _proposal_body(p: dict, rows: dict, ctx: list, titles: dict) -> list:
    out = ["", "## Items", ""]
    for ref in p["items"]:
        r = rows[ref]
        age = f"{r['age']} days old" if r["age"] is not None else "age unknown"
        added = f"added {r['added']}; " if r.get("added") and r["age"] is not None else ""
        out.append(f"- {ref} (Source: {r['source']}; {added}{age}): {r['text']}")
    if p["kind"] == "join":
        out += ["", "## Target", "", "- related open order: consider adding",
                f"- {p['wo']}: {titles.get(p['wo'], '')}"]
        if p.get("in_progress"):
            out.append(f"- target in progress: {p['in_progress']}")
    if p["kind"] == "park":
        out += ["", "## Trigger words found", "", f"- {p['trigger']}"]
    if p.get("fix"):
        f = p["fix"]
        when = f", {f['date']}" if f.get("date") else ""
        what = (f"{f['ref']} (resolved{when}): {f['title']}" if f["kind"] == "order"
                else f"commit {f['ref']} ({f['date']}): {f['title']}")
        out += ["", "## Possibly fixed elsewhere", "", f"- {what}",
                "- a match by code, not a decision: read the fix, then accept with `--reason` or decline"]
    if p["kind"] == "ask" and p.get("question"):
        out += ["", "## Question for the operator", "", f"- {p['question']}"]
    if p["kind"] == "read":
        out += ["", "## Unsure answers", "", f"- {p.get('cause') or 'the answers conflict'}"]
    if ctx:
        out += ["", "## Context", ""] + [f"- {x}" for x in ctx]
    return out


def _proposal_file(p: dict, created: str, updated: str, model: str, rows, ctx, titles) -> str:
    head = ["# Drain proposal " + p["id"], "", f"- id: {p['id']}", f"- kind: {p['kind']}",
            f"- items: {', '.join(p['items'])}"]
    if p["kind"] == "join":
        head.append(f"- target: {p['wo']}")
        if p.get("in_progress"):
            head.append(f"- target in progress: {p['in_progress']}")
    if p.get("fix"):
        head.append(f"- fix: {_fix_label(p['fix'])}")
    head += [f"- created: {created}", f"- updated: {updated}", f"- model: {model}"]
    return "\n".join(head + _proposal_body(p, rows, ctx, titles)) + "\n"


def _read_proposal(path: Path) -> "dict | None":
    text = _read_text(path)
    if text is None:
        return None
    meta = {}
    for ln in text.splitlines():
        m = re.match(r"- (id|kind|items|target|fix|created|updated|model): (.*)$", ln)
        if m and m.group(1) not in meta:
            meta[m.group(1)] = m.group(2).strip()
    if not meta.get("id") or not meta.get("kind"):
        return None
    meta["item_list"] = [x.strip() for x in meta.get("items", "").split(",") if x.strip()]
    meta["text"] = text
    return meta


def _drain_dirs(home: Path) -> dict:
    return {"pending": Path(home) / DRAIN_DIR / "pending"}


ITEM_LINE = re.compile(r"^- (L\d+) \(Source: (.*?); (?:added (\d{4}-\d\d-\d\d); )?(?:\d+ days old|age unknown)\): (.*)$")


def _proposal_rows(m: dict) -> list:
    """The list rows a pending proposal carries, as (id, added, source, item), from its `## Items` lines."""
    out = []
    for ln in m["text"].splitlines():
        r = ITEM_LINE.match(ln)
        if r:
            out.append((r.group(1), r.group(3) or "", r.group(2), r.group(4)))
    return out


def _pile_kinds(home: Path) -> dict:
    """{item id: the kind of the pending proposal that holds it}."""
    out: dict = {}
    pend = _drain_dirs(home)["pending"]
    for f in sorted(pend.glob("*.md")) if pend.is_dir() else []:
        m = _read_proposal(f) if _DRAIN_ID.fullmatch(f.stem) else None
        if m:
            for x in m["item_list"]:
                out.setdefault(x, m["kind"])
    return out


def _pile_ids(home: Path) -> set:
    """The item ids of every pending proposal."""
    return set(_pile_kinds(home))


def pending_holding(home, lid: str) -> list:
    """The ids of the pending proposals that hold item `lid`."""
    out = []
    pend = _drain_dirs(Path(home))["pending"]
    for f in sorted(pend.glob("*.md")) if pend.is_dir() else []:
        m = _read_proposal(f) if _DRAIN_ID.fullmatch(f.stem) else None
        if m and lid in m["item_list"]:
            out.append(f.stem)
    return out


def release_items(home, ids) -> dict:
    """Take routed items out of the pile: a pending proposal that holds only them is removed; one that holds
    others is rewritten without them, under the id its remaining items give (the old file goes after the new one
    is written, so a crash leaves a proposal, never a hole). The Context lines of a rewritten file stay as first
    written. -> {"withdrawn": [id], "edited": [(old id, new id)]}."""
    home, gone = Path(home), set(ids)
    pend = _drain_dirs(home)["pending"]
    done = {"withdrawn": [], "edited": []}
    for f in sorted(pend.glob("*.md")) if pend.is_dir() else []:
        m = _read_proposal(f) if _DRAIN_ID.fullmatch(f.stem) else None
        if not m or not gone & set(m["item_list"]):
            continue
        keep = [x for x in m["item_list"] if x not in gone]
        if not keep:
            f.unlink()
            done["withdrawn"].append(f.stem)
            continue
        wo = (m.get("target") or "").strip() or None
        new_id = drain_id(m["kind"], sorted(keep, key=lambda t: int(t[1:])), wo)
        lines = []
        for ln in m["text"].splitlines():
            row = ITEM_LINE.match(ln)
            if row and row.group(1) in gone:
                continue
            lines.append(ln)
        text = "\n".join(lines) + "\n"
        text = text.replace(f"# Drain proposal {m['id']}", f"# Drain proposal {new_id}", 1)
        text = re.sub(r"(?m)^- id: .*$", f"- id: {new_id}", text, count=1)
        text = re.sub(r"(?m)^- items: .*$", "- items: " + ", ".join(keep), text, count=1)
        text = re.sub(r"(?m)^- updated: .*$", f"- updated: {_now()}", text, count=1)
        _write_text_atomic(pend / f"{new_id}.md", text)
        if new_id != f.stem:
            f.unlink()
        done["edited"].append((f.stem, new_id))
    return done


def _drain_write(home: Path, model: str, loose_rows: list, orders: list, results: list) -> dict:
    """The proposals of the answered items, from the helper's answers."""
    c = _canary()
    le = _loose_ends()
    bundles = _bundle_groups(results)
    fixed = le.fixed_elsewhere(home, [r for r in loose_rows if r["state"].strip() == le.STATE_NEW], sm=sys.modules[__name__])
    plan = _drain_plan(results, bundles, fixed)
    cause = {r["ref"]: r["cause"] for r in results if r["use"] == "loose-end-state"}
    rows = {r["id"]: {"text": _squash(r["item"]), "source": r["source"], "age": le.age_days(r["added"]),
                      "added": r["added"]}
            for r in loose_rows}
    titles = {o["ref"]: o["title"] for o in orders}
    progress = {o["ref"]: {"worktree": "a worktree exists", "notes started": "its Implementer notes are started"
                           }.get(o["dispatched"], "") for o in orders}
    props: list = []
    for wo in sorted({p["wo"] for p in plan if p["kind"] == "join"}):
        props.append({"kind": "join", "items": [p["ref"] for p in plan if p["kind"] == "join" and p["wo"] == wo],
                      "wo": wo, "in_progress": progress.get(wo) or ""})
    for g in bundles:
        mem = [x for x in g if any(p["ref"] == x and p["kind"] == "bundle" for p in plan)]
        if mem:
            props.append({"kind": "new-order", "items": mem})
    for p in plan:
        if p["kind"] == "open":
            props.append({"kind": "new-order", "items": [p["ref"]]})
        elif p["kind"] in ("ask", "park", "close", "read"):     # an unsure item never vanishes: it is a `read`
            props.append({"kind": p["kind"], "items": [p["ref"]], "cause": cause.get(p["ref"], ""),
                          "fix": p.get("fix"), "trigger": (p["step"][len("park (trigger: "):-1] if p["kind"] == "park" else "")})
    # only rows still `new` now are proposed: one routed (removed) or set by hand while this run was asking is not
    live = {r["id"] for r in le.rows_of(home) if (le.parse_state(r["state"]) or ("",))[0] == "new"}
    for p in props:
        p["items"] = [x for x in p["items"] if x in live]
    props = [p for p in props if p["items"]]
    dirs = _drain_dirs(home)
    now = _now()
    written, keep = [], set()
    for p in props:
        p["items"] = sorted(p["items"], key=lambda t: int(t[1:]))
        p["id"] = drain_id(p["kind"], p["items"], p.get("wo"))
        keep.add(p["id"])
        path = dirs["pending"] / f"{p['id']}.md"
        old = _read_proposal(path) if path.is_file() else None
        ctx = _group_context(home, c, p["items"], rows, orders)
        created = old["created"] if old and old.get("created") else now
        text = _proposal_file(p, created, now, model, rows, ctx, titles)
        if old and re.sub(r"- updated: .*", "", old["text"]) == re.sub(r"- updated: .*", "", text):
            continue                                   # same proposal, same body: leave the file alone
        _write_text_atomic(path, text)
        written.append(p["id"])
    # the pile file is written above; only now does the row say `proposed:`. A crash between the two leaves a `new`
    # row a pile file holds; this step, on the next run, marks it.
    kinds = _pile_kinds(home)
    proposed = le.set_states(home, {r["id"]: f"proposed: {kinds[r['id']]}" for r in le.rows_of(home)
                                    if r["id"] in kinds and (le.parse_state(r["state"]) or ("",))[0] == "new"}) \
        if le.list_path(home).is_file() else []
    counts = {k: sum(1 for p in props if p["kind"] == k and p["id"] in keep) for k in DRAIN_KINDS}
    counts["pending"] = sum(counts.values())
    return {"counts": counts, "written": written, "proposed": proposed}


# ------------------------------------------------------------------ the drain by a helper
# The questions and tables, with the answers read from a file a dispatched helper wrote. Nothing here calls a
# model or handles a key: `--export` writes the questions, `--answers` reads the words and applies each use's
# table. The export and the answers belong to one list state, tied by a fingerprint.
EXPORT_FORMAT = "gitos-drain-export"
ANSWERS_FORMAT = "gitos-drain-answers"


def _fingerprint(items: list) -> str:
    """A sha256 (16 hex) over every item's ref, use and state text, in order: the list state of an export."""
    raw = json.dumps([[it["ref"], it["use"], it["state"]] for it in items], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _export_item(it: dict) -> dict:
    reg = _registry()
    allowed = {q["id"]: list(reg.input_domain(q)) for q in reg.USES[it["use"]]["questions"]}
    qs = reg.request_questions(it["use"])
    return {"ref": it["ref"], "use": it["use"], "state": it["state"],
            "questions": {qid: {**body, "allowed": allowed[qid]} for qid, body in qs.items()}}


def helper_export(items: list) -> dict:
    """The export document: every item to be answered, its questions and the allowed answers."""
    fp = _fingerprint(items)
    return {"format": EXPORT_FORMAT, "version": 1, "registry": _registry().REGISTRY_VERSION,
            "fingerprint": fp,
            "answers_file": {"format": ANSWERS_FORMAT, "fingerprint": fp,
                             "answers": {"<ref>": {"<question id>": "<one of its allowed answers>"}}},
            "items": [_export_item(it) for it in items]}


def _valid_answer(allowed: list, raw):
    """The answer when it is one of the allowed words, else `unsure`."""
    return raw if isinstance(raw, str) and raw in allowed else "unsure"


def helper_apply(items: list, doc) -> dict:
    """Apply each use's table to a helper's answers. `doc` is `{"fingerprint": F, "answers": {ref: {qid: word}}}`.
    An answer that is missing, not a string or not allowed counts as `unsure` for that question (counted,
    never an error). A document that is not of this list state raises ValueError before anything is applied.
    -> {"outcomes": {ref: {"outcome", "confirm", "inputs"}}, "defaulted": n, "unknown": [refs not in the list]}.
    `confirm` is true for an outcome a script only reports (see `require_reversible`)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("answers"), dict) \
            or not isinstance(doc.get("fingerprint"), str):
        raise ValueError("the answers file needs a `fingerprint` and an `answers` object: nothing was written, "
                         "export again")
    fp = _fingerprint(items)
    if doc["fingerprint"] != fp:
        raise ValueError(f"the answers belong to another list state (answers {doc['fingerprint']}, list now "
                         f"{fp}): nothing was written, export again")
    reg = _registry()
    out, defaulted = {}, 0
    for it in items:
        u = reg.USES[it["use"]]
        given = doc["answers"].get(it["ref"])
        given = given if isinstance(given, dict) else {}
        inputs = {}
        for q in u["questions"]:
            raw = given.get(q["id"])
            v = _valid_answer(list(reg.input_domain(q)), raw)
            if v != raw:
                defaulted += 1
            inputs[q["id"]] = v
        outcome = u["table"](dict(inputs))
        out[it["ref"]] = {"outcome": outcome, "confirm": u["outcomes"][outcome] == reg.CONFIRM, "inputs": inputs}
    known = {it["ref"] for it in items}
    return {"outcomes": out, "defaulted": defaulted, "unknown": sorted(k for k in doc["answers"] if k not in known)}


def _write_export(path, doc: dict) -> None:
    _write_text_atomic(Path(path), json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _read_answers(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"cannot read the answers file: {e}")
    except ValueError:
        raise ValueError("the answers file is not valid JSON: nothing was written")


def drain_export(home, path) -> dict:
    """Write the export file for the loose-ends items the drain would ask. -> {"items": n, "fingerprint": F}."""
    items = _loose_end_items(Path(home))[0]
    doc = helper_export(items)
    _write_export(path, doc)
    return {"items": len(items), "fingerprint": doc["fingerprint"]}


def drain_answers(home, doc) -> dict:
    """The drain from a helper's answers: the proposals are written through `_drain_write`.
    -> {"counts", "written", "proposed", "defaulted", "unknown"}. A stale or unreadable document raises
    ValueError with nothing written."""
    home = Path(home)
    items, loose_rows, orders = _loose_end_items(home)
    applied = helper_apply(items, doc)
    results = [{"group": it["group"], "use": it["use"], "ref": it["ref"],
                "outcome": applied["outcomes"][it["ref"]]["outcome"], "text": it["text"],
                "cause": _cause(applied["outcomes"][it["ref"]], it["use"])} for it in items]
    d = _drain_write(home, HELPER_MODEL, loose_rows, orders, results)
    d["defaulted"], d["unknown"] = applied["defaulted"], applied["unknown"]
    return d


def drain_status(home) -> "str | None":
    """One line, or None when there is no pending folder."""
    pend = _drain_dirs(home)["pending"]
    if not pend.is_dir():
        return None
    n = {k: 0 for k in DRAIN_KINDS}
    for f in pend.glob("*.md"):
        m = _read_proposal(f)
        if m and m["kind"] in n:
            n[m["kind"]] += 1
    line = (f"drain: {sum(n.values())} pending ({n['join']} join, {n['new-order']} new-order, "
            f"{n['ask']} ask, {n['park']} park, {n['close']} close, {n['read']} read)")
    news = sorted((m["id"], ", ".join(m["item_list"])) for m in (_read_proposal(f) for f in pend.glob("*.md"))
                  if m and m["kind"] == "new-order")
    if news:
        line += (f"\nnew-order proposals (approve them in one batch):\n"
                 + f"\n".join(f"  {i}: {items}" for i, items in news))
    return line


def _pending(home: Path, pid: str) -> dict:
    if not _DRAIN_ID.fullmatch(pid or ""):
        raise ValueError(f"{pid!r} is not a proposal id (12 hex characters)")
    src = _drain_dirs(home)["pending"] / f"{pid}.md"
    m = _read_proposal(src) if src.is_file() else None
    if m is None:
        raise ValueError(f"no pending proposal {pid} under {src.parent}")
    m["path"] = src
    return m


def _drain_dispose(home, m: dict, state: "str | None" = None, route: "str | None" = None) -> str:
    """Settle a pending proposal on the list, then remove its file (git keeps it). `state`: its items' rows take that
    State (written first: a crash leaves the file beside rows that are no longer `proposed:`, which the canary
    reports and a re-run clears). `route`: its items are routed and their rows leave the list (the file goes first:
    a crash leaves `proposed:` rows with no file, which the canary reports and `drop` clears). An item no longer on
    the list is skipped. -> what was done."""
    le = _loose_ends()
    on = {r["id"] for r in le.rows_of(home)}
    ids = [x for x in m["item_list"] if x in on]
    if state:
        le.set_states(home, {x: state for x in ids})
        m["path"].unlink()
        return f"{', '.join(ids) or 'no row'}: {state}"
    m["path"].unlink()
    le.remove_rows(home, ids)
    return f"{', '.join(ids) or 'no row'} -> {route}"


def _order_text(home: Path, nnn: str) -> str:
    """Everything an order holds: its file, or every file of its folder."""
    path = next(pth for n, pth, _r in _wo_listing(home, _canary()) if n == nnn)
    files = sorted(path.parent.rglob("*.md")) if path.name == "order.md" else [path]
    return "\n".join(_read_text(f) or "" for f in files)


def _slice_mod():
    """slice.py, imported by path."""
    mod = sys.modules.get("_gitos_slice_s3")
    if mod is None:
        spec = importlib_util.spec_from_file_location("_gitos_slice_s3", Path(__file__).resolve().with_name("slice.py"))
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_slice_s3"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_slice_s3", None)
            raise
    return mod


def _ask_question(m: dict) -> str:
    """The question an `ask` proposal carries, else its item's own text."""
    q = re.search(r"(?m)^## Question for the operator\s*\n\s*\n- (.+)$", m["text"])
    rows = _proposal_rows(m)
    return _squash(q.group(1)) if q else (_squash(rows[0][3]) if rows else "")


def drain_accept(home, pid: str, work_order: "str | None" = None, trigger: "str | None" = None,
                 reason: "str | None" = None, slice_name: "str | None" = None,
                 question: "str | None" = None, parked: "str | None" = None) -> str:
    """Accept a proposal by the act that carries it out; every check runs before anything changes.
    `join` / `new-order` (and a `read` or `ask` given `--work-order`): the open order WO-NNN takes the items. With
    `--slice NAME` they become a `proposed` slice with `origin:` naming them (`slice add`, which turns a single-file
    order into the folder form); without it the order must already name every item id (an order authored from the
    proposal, `origin: L3, L5`). The rows leave the list. `park` -> a parked work-order (`status: parked`, `trigger:`)
    takes them with `--work-order NNN`, as a `new-order` (`--trigger` is refused: `parked:` is retired); `ask` -> `waiting:
    <--question, else the proposal's question>`; `close` -> routed `closed: <--reason>`. A `read` takes any one of
    `--work-order`, `--trigger`, `--question`, `--reason`."""
    home = Path(home)
    m = _pending(home, pid)
    if parked:
        raise ValueError("--parked P<n> is retired: a parked item is a parked work-order; accept with --work-order NNN")
    kind = m["kind"]
    if kind == "park" and work_order:
        kind = "new-order"                         # a parked work-order (WO-116) takes the items
    if kind in ("read", "ask"):
        kind = ("new-order" if work_order else "park" if trigger else "close" if reason else
                "ask" if (question or kind == "ask") else None)
        if kind is None:
            raise ValueError("a read proposal is accepted with --work-order NNN, --question Q or --reason R")
    listing = {n: r for n, _p, r in _wo_listing(home, _canary())}

    def require_open(nnn: str) -> None:
        if nnn not in listing:
            raise ValueError(f"no work-order {nnn} under {home / 'work-orders'}: author it first")
        if listing[nnn]:
            raise ValueError(f"WO-{nnn} is resolved: a proposal is accepted into an open order, so nothing "
                             f"was changed (decline it, or author a new order)")
    if kind in ("join", "new-order"):
        if kind == "join" and m.get("target"):
            require_open(str(m["target"]).strip().lstrip("WwOo-").zfill(3))
        if not work_order:
            raise ValueError(f"a {kind} proposal is accepted with --work-order NNN (author the order first)")
        nnn = str(work_order).strip().lstrip("WwOo-").zfill(3)
        require_open(nnn)
        rows = _proposal_rows(m)
        if slice_name and slice_name.strip():
            sl = _slice_mod()
            try:
                origin = _squash("; ".join(f"{i}: {item}" for i, _a, _s, item in rows))[:400]
                sl.slice_add(home, nnn, slice_name.strip(), (), origin)
            except sl.SliceError as e:
                raise ValueError(str(e))
            return _drain_dispose(home, m, route=f"WO-{nnn} slice {slice_name.strip()}")
        text = _order_text(home, nnn)
        missing = [i for i, _a, _s, _t in rows if not re.search(rf"\b{re.escape(i)}\b", text)]
        if missing:
            raise ValueError(f"WO-{nnn} does not name {', '.join(missing)}: accept with --slice NAME (a proposed slice "
                             f"with origin:), or author the order naming the items (`origin: {', '.join(missing)}`); "
                             "nothing was changed")
        return _drain_dispose(home, m, route=f"WO-{nnn}")
    le = _loose_ends()
    if kind == "park":
        raise ValueError("a park proposal is accepted with --work-order NNN: `parked:` is retired, a parked item is "
                         "a parked work-order (front matter `status: parked`, `trigger: <restart trigger>`, `origin:` "
                         "naming the items); author it first, nothing was changed")
    if kind == "ask":
        st = le._state_text(f"waiting: {question or _ask_question(m)}")
        return _drain_dispose(home, m, state=st)
    if not (reason and len(reason.split()) >= 3):
        raise ValueError("a close proposal is accepted with --reason (a few words: what makes it done)")
    return _drain_dispose(home, m, route=f"closed: {_squash(reason)}")


def drain_decline(home, pid: str, reason: "str | None", route: "str | None" = None) -> str:
    """Decline a proposal. With `route` (WO-NNN | WO-NNN/SN | brain:<page> | closed:<why>, checked like
    `loose_ends.py drop`) the orchestrator has routed the items by hand and their rows leave the list; without it
    the rows read `declined: <reason>`, which the drain never proposes again."""
    if not reason or not reason.strip():
        raise ValueError("decline needs --reason")
    home, why = Path(home), _squash(reason)
    m = _pending(home, pid)
    if route:
        le = _loose_ends()
        try:
            dest = le.check_dest(home, route)
        except le.LooseEndsError as e:
            raise ValueError(str(e))
        return _drain_dispose(home, m, route=dest)
    return _drain_dispose(home, m, state=f"declined: {why}")


def drain_withdraw(home, pid: str) -> str:
    """Take a pending proposal back: its rows read `new` again and the file is removed, so the next drain asks them
    again."""
    return _drain_dispose(Path(home), _pending(Path(home), pid), state="new")


def _drain_cli(args) -> int:
    priv = argparse.ArgumentParser(prog="system_one.py drain", add_help=False)
    priv.add_argument("rest", nargs="*")
    priv.add_argument("--work-order")
    priv.add_argument("--parked")
    priv.add_argument("--trigger")
    priv.add_argument("--question")
    priv.add_argument("--reason")
    priv.add_argument("--route")
    priv.add_argument("--slice")
    priv.add_argument("--new-slice")
    priv.add_argument("--json", action="store_true")
    priv.add_argument("--export")
    priv.add_argument("--answers")
    try:
        ns = priv.parse_intermixed_args(list(args.rest))
    except SystemExit:
        return 2
    args.json = args.json or ns.json
    args.work_order, args.parked, args.reason, args.route = ns.work_order, ns.parked, ns.reason, ns.route
    args.slice = ns.slice or ns.new_slice           # `--new-slice` is the older spelling of `--slice`
    args.trigger, args.question = ns.trigger, ns.question
    rest = list(ns.rest)
    act = rest[0] if rest and rest[0] in ("accept", "decline", "defer", "withdraw", "status") else None
    try:
        if ns.export or ns.answers:
            if act is not None or len(rest) != 1 or (ns.export and ns.answers):
                print("drain: usage: drain <home> --export FILE | drain <home> --answers FILE", file=sys.stderr)
                return 2
            home = _resolve_home(rest[0])
            if ns.export:
                e = drain_export(home, ns.export)
                print(json.dumps(e) if args.json else
                      f"drain: exported {e['items']} items (fingerprint {e['fingerprint']}) to {ns.export}")
                return 0
            d = drain_answers(home, _read_answers(ns.answers))
            c = d["counts"]
            print(json.dumps(d) if args.json else
                  f"drain: {c['pending']} pending ({c['join']} join, {c['new-order']} new-order, {c['ask']} ask, "
                  f"{c['park']} park, {c['close']} close, {c['read']} read); {len(d['written'])} written, "
                  f"{len(d['proposed'])} rows marked proposed; {d['defaulted']} answers counted as unsure (missing or invalid)"
                  + (f"; {len(d['unknown'])} unknown refs ignored" if d["unknown"] else ""))
            return 0
        if act is None:
            if len(rest) == 1:
                print(RETIRED_SENTENCE, file=sys.stderr)       # `drain <home>` alone asked the local model
            else:
                print("drain: usage: drain <home> --export FILE | drain <home> --answers FILE | accept ID "
                      "(--work-order NNN [--slice NAME] | --question Q | --reason R) [ROOT] | decline ID --reason R "
                      "[--route DEST] [ROOT] | withdraw ID [ROOT] | defer ID [ROOT] | status [ROOT]", file=sys.stderr)
            return 2
        if act == "status":
            if len(rest) > 2:
                print("drain: status takes at most one ROOT", file=sys.stderr)
                return 2
            line = drain_status(_resolve_home(rest[1] if len(rest) == 2 else "."))
            if line:
                print(line)
            return 0
        if len(rest) not in (2, 3):
            print(f"drain: {act} needs an ID and at most one ROOT", file=sys.stderr)
            return 2
        home = _resolve_home(rest[2] if len(rest) == 3 else ".")
        if act == "defer":
            if not (_drain_dirs(home)["pending"] / f"{rest[1]}.md").is_file():
                print(f"drain: no pending proposal {rest[1]}", file=sys.stderr)
                return 2
            print(f"deferred: {rest[1]} (unchanged)")
            return 0
        if act == "withdraw":
            print(f"withdrawn: {rest[1]} -> {drain_withdraw(home, rest[1])}")
            return 0
        if act == "accept":
            dest = drain_accept(home, rest[1], args.work_order, args.trigger, args.reason, args.slice,
                                args.question, args.parked)
        else:
            dest = drain_decline(home, rest[1], args.reason, args.route)
        print(f"{'accepted' if act == 'accept' else 'declined'}: {rest[1]} -> {dest}")
        return 0
    except (OSError, ValueError) as e:
        print(f"drain: {e}", file=sys.stderr)
        return 2


# ------------------------------------------------------------------ the lenses (WO-087)
# `lenses` reads and prints: nothing is written in the repo or the global lens library, and no model is asked.
GLOBAL_LENS_ENV = "GITOS_GLOBAL_LENS_DIR"
_LENS_NEEDS = ("domain", "when-to-apply")


def _resolve_home(home) -> Path:
    home = Path(home)
    return home / ".gitos" if (home / ".gitos").is_dir() else home


def lens_layers(home, global_dir=None) -> list:
    """[(layer, dir)] for the repo's `<home>/agents` and the global library: `global_dir`, else the
    `GITOS_GLOBAL_LENS_DIR` variable, else `<skill>/agents` (two levels above this file)."""
    g = global_dir or os.environ.get(GLOBAL_LENS_ENV) or (Path(__file__).resolve().parents[1] / "agents")
    return [("repo", Path(home) / "agents"), ("global", Path(g))]


def _lenses_mod():
    """lenses.py (which lenses are active, WO-091), imported by path like the canary."""
    mod = sys.modules.get("_gitos_lenses_s1")
    if mod is None:
        path = Path(__file__).resolve().with_name("lenses.py")
        spec = importlib_util.spec_from_file_location("_gitos_lenses_s1", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_lenses_s1"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_lenses_s1", None)
            raise
    return mod


def gather_lenses(home, global_dir=None, active=None) -> dict:
    """{"lenses": [{name, layer, domain, when, applies_to}], "problems": [str]}. The repo wins a name
    collision. The canary's `check_lens_layer` finds the problems of each layer; a lens whose
    frontmatter lacks a domain or a when-to-apply cannot be judged and is reported, not skipped.
    `active` ({(layer, file stem)}), when given, limits the lenses to the repo's active set."""
    c = _canary()
    found: dict = {}
    problems: list = []
    for layer, d in lens_layers(home, global_dir):
        if not d.is_dir():
            continue
        if active is not None and not any(k[0] == layer for k in active):
            continue
        problems += [it["finding"] for it in c.check_lens_layer(d, layer)]
        for f in sorted(p for p in d.glob("*.md") if p.name != "index.md"):
            if active is not None and (layer, f.stem) not in active:
                continue
            fm = c.parse_frontmatter(_read_text(f) or "")
            name = (fm or {}).get("name") or f.stem
            if name in found:
                continue                                    # an earlier (repo) layer already holds it
            lacking = [k for k in _LENS_NEEDS if not (fm or {}).get(k)]
            if lacking:
                if not fm:
                    found[name] = None                      # no frontmatter: the canary reports it once
                    continue
                problems.append(f"{layer} agents/{f.name} cannot be judged: no "
                                f"{' or '.join(lacking)} -> fix its frontmatter")
                found[name] = None
                continue
            found[name] = {"name": name, "layer": layer, "domain": fm["domain"],
                           "when": fm["when-to-apply"], "applies_to": fm.get("applies-to", "")}
    return {"lenses": [v for v in found.values() if v], "problems": problems}


def _work_state(home: Path, wo: "str | None", text_file: "str | None") -> tuple:
    """(label, state) of the work to match lenses against."""
    if text_file:
        return "text", "Work: " + _cap(Path(text_file).read_text(encoding="utf-8"), 1200)
    c = _canary()
    nnn = str(wo).strip().lstrip("WwOo-").zfill(3)
    for n, path, _res in _wo_listing(home, c):
        if n == nnn:
            text = _read_text(path) or ""
            sev = next((ln.strip() for ln in (c.section_lines(text, "## Severity") or []) if ln.strip()), "")
            scope = _squash(" ".join(c.proposed_scope_lines(text) or []))
            return f"WO-{nnn}", (f"Work-order WO-{nnn}: {_title(text, path.stem)}\n"
                                 f"Severity: {_cap(sev, 200)}\nScope: {_cap(scope, 1000)}")
    raise ValueError(f"no work-order {nnn} under {home}")


def match_lenses(home, wo=None, text_file=None, global_dir=None) -> dict:
    """List the repo's active lenses with each one's domain and when-to-apply, plus the problems the
    canary's lens readers find. No model call (WO-098: matching a lens to the work stays with the
    reasoning model, which reads the list)."""
    home = Path(home)
    lm = _lenses_mod()
    cfg = lm.load(home)
    if cfg["state"] != "on":                          # lenses are opt-in per repo
        return {"registry": _registry().REGISTRY_VERSION, "work": "", "lenses": [], "off": True,
                "problems": [f"lenses.json: {cfg['error']}"] if cfg["error"] else []}
    label, _work = _work_state(home, wo, text_file)   # a missing work-order or text file still refuses
    act = {(a["layer"], a["name"]) for a in lm.active(home, global_dir)}
    g = gather_lenses(home, global_dir, act)
    rows = sorted(g["lenses"], key=lambda r: r["name"])
    return {"registry": _registry().REGISTRY_VERSION, "work": label, "lenses": rows,
            "problems": g["problems"]}


def format_lenses(d: dict) -> str:
    if d.get("off"):
        return "\n".join(["lenses are off for this repo"] + [f"problem: {p}" for p in d["problems"]])
    out = [f"== system-one lenses (registry v{d['registry']}): {len(d['lenses'])} active lenses; "
           f"you decide which apply to {d['work']} =="]
    for r in d["lenses"]:
        out.append(f"{r['name']}  [{r['layer']}]  domain: {_cap(r['domain'], 120)}  "
                   f"when: {_cap(r['when'], 300)}")
    if not d["lenses"]:
        out.append("no active lenses")
    for p in d["problems"]:
        out.append(f"problem: {p}")
    out.append("note: no model is asked; read each lens's when-to-apply against the work and apply "
               "the ones that match.")
    return "\n".join(out)


def _lenses_cli(args) -> int:
    home = _resolve_home(args.home)
    if bool(args.wo) == bool(args.text):
        print("lenses: give exactly one of --wo and --text", file=sys.stderr)
        return 2
    try:
        d = match_lenses(home, args.wo, args.text, args.global_dir)
    except (OSError, ValueError) as e:
        print(f"lenses: {e}", file=sys.stderr)
        return 2
    print(json.dumps(d) if args.json else format_lenses(d))
    return 0


# ------------------------------------------------------------------------------------- scope (WO-089)
_SCOPE_END = "every changed file still has to be read: this lists paths, it is not a check of the diff"
_PATHISH = re.compile(r"^[\w./*?\[\]{}-]+$")


def _wo_text(home: Path, wo: str) -> tuple:
    c = _canary()
    nnn = str(wo).strip().lstrip("WwOo-").zfill(3)
    for n, path, _res in _wo_listing(home, c):
        if n == nnn:
            return nnn, _read_text(path) or "", c
    raise ValueError(f"no work-order {nnn} under {home}")


def _scope_patterns(text: str, c) -> tuple:
    """(scope text, [path or glob the scope names], [path or glob its Not in scope names])."""
    body = "\n".join(c.proposed_scope_lines(text) or [])
    m = re.search(r"^[ \t]*\*\*not in scope", body, re.I | re.M)
    inside, outside = (body[:m.start()], body[m.start():]) if m else (body, "")

    def names(s: str) -> list:
        out = []
        for span in re.findall(r"`([^`\n]+)`", s):
            if _PATHISH.match(span) and ("/" in span or "*" in span or re.search(r"\.\w+$", span)
                                         or re.fullmatch(r"[A-Z][A-Z_]+", span)):
                out.append(span)
        return list(dict.fromkeys(out))
    return _squash(inside), names(inside), names(outside)


def _matches(path: str, pat: str) -> bool:
    import fnmatch
    if pat.endswith("/"):
        return path.startswith(pat)
    return (fnmatch.fnmatchcase(path, pat) or path.startswith(pat + "/")
            or ("/" not in pat and fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pat)))


def _git(root: Path, *args) -> "str | None":
    import subprocess
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    return p.stdout if p.returncode == 0 else None


def _default_range(root: Path, nnn: str, slice_id: "str | None" = None) -> "list[str]":
    """The ranges to digest, a list (empty = none found). The order's branches are `wo-NNN` and its slice
    branches `wo-NNN-sN` (all of them, or only `slice_id`'s when given). On one of them: to HEAD from the
    merge-base with main or master. Elsewhere: merge-base with HEAD to each of the order's branches."""
    import re
    cur = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    refs = (_git(root, "for-each-ref", "--format=%(refname:short)", f"refs/heads/wo-{nnn}",
                 f"refs/heads/wo-{nnn}-*") or "").split()
    pat = re.compile(rf"wo-{re.escape(nnn)}(-s\d+[a-z]?)?$", re.I)
    branches = [r for r in refs if pat.match(r)]
    if slice_id:
        branches = [r for r in branches if r.lower() == f"wo-{nnn}-{slice_id}".lower()]
    if branches and cur not in branches:
        out = []
        for br in branches:
            base = (_git(root, "merge-base", "HEAD", br) or "").strip()
            if base:
                out.append(f"{base}..{br}")
        return out
    for trunk in ("main", "master"):
        if trunk != cur and _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{trunk}") is not None:
            base = (_git(root, "merge-base", "HEAD", trunk) or "").strip()
            return [f"{base}..HEAD"] if base else []
    return []


def scope_check(home, wo: str, rng: "str | None" = None, slice_id: "str | None" = None) -> dict:
    """A code rule on the paths a work-order's scope names: a changed file the scope's Not in scope names
    is `forbidden`, one no scope path names is `outside-scope`. No model; writes nothing."""
    home = Path(home)
    nnn, text, c = _wo_text(home, wo)
    _scope, inside, forbidden = _scope_patterns(text, c)
    folder = next((pth.parent for n, pth, _r in _wo_listing(home, c) if n == nnn and pth.name == "order.md"), None)
    if folder is not None:      # a folder order: the scope lives in its slice files (`## Scope`)
        inside, forbidden = [], []
        for sf in sorted((folder / "slices").glob("*.md")):
            body = "\n".join(c.section_lines(_read_text(sf) or "", "## Scope") or [])
            _s, i, f = _scope_patterns("## Proposed fix scope\n" + body + "\n", c)
            inside += i
            forbidden += f
        forbidden = [x for x in dict.fromkeys(forbidden) if x not in inside]
    root = Path((_git(home, "rev-parse", "--show-toplevel") or str(home.parent)).strip())
    ranges = [rng] if rng else _default_range(root, nnn, slice_id)
    if not ranges:
        raise ValueError(f"no range for WO-{nnn}: no branch wo-{nnn} or wo-{nnn}-sN and no main/master; "
                         "pass --range A..B")
    files = []
    for one in ranges:
        names = _git(root, "diff", "--no-renames", "--name-only", one)
        if names is None:
            raise ValueError(f"git diff {one} failed under {root}")
        files += [x for x in names.splitlines() if x.strip() and x.strip() not in files]
    rng = ", ".join(ranges)
    try:
        own = home.resolve().relative_to(root.resolve()).as_posix() + f"/work-orders/WO-{nnn}-*.md"
    except ValueError:
        own = f"work-orders/WO-{nnn}-*.md"
    own_dir = own.rsplit("/", 1)[0] + f"/WO-{nnn}/"
    facts = []
    for f in files:
        hit = next((p for p in forbidden if _matches(f, p)), None)
        if hit:
            facts.append({"file": f, "class": "forbidden", "why": f"Not in scope names `{hit}`"})
        elif not any(_matches(f, p) for p in inside + [own, own_dir]):
            facts.append({"file": f, "class": "outside-scope", "why": "no path in the scope names it"})
    return {"wo": f"WO-{nnn}", "range": rng, "files": len(files), "facts": facts}


def format_scope(d: dict) -> str:
    out = [f"== system-one scope {d['wo']}: {d['range']}, {d['files']} files =="]
    for cls in ("forbidden", "outside-scope"):
        out += [f"{cls:<14}{f['file']}  ({f['why']})" for f in d["facts"] if f["class"] == cls]
    out.append(_SCOPE_END)
    return "\n".join(out)


def _scope_cli(args) -> int:
    home = _resolve_home(args.home)
    try:
        d = scope_check(home, args.wo, args.range, getattr(args, "slice", None))
    except (OSError, ValueError) as e:
        print(f"scope: {e}", file=sys.stderr)
        return 2
    print(json.dumps(d) if args.json else format_scope(d))
    return 0




def _repo_home(root) -> Path:
    root = Path(root)
    return root / ".gitos" if (root / ".gitos").is_dir() else root



# ------------------------------------------------------------------------------------- helper model
HELPER_DEFAULTS = {"claude": "haiku", "codex": "gpt-5.1-codex-mini"}   # the only place either name appears in code
HELPER_SOURCES = ("optimization", "default")                           # first match wins


def _mo_mod():
    """model_optimization.py, imported by path like the lenses module."""
    mod = sys.modules.get("_gitos_mo_s1")
    if mod is None:
        path = Path(__file__).resolve().with_name("model_optimization.py")
        spec = importlib_util.spec_from_file_location("_gitos_mo_s1", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_mo_s1"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_mo_s1", None)
            raise
    return mod


def detect_harness(environ=None) -> "str | None":
    """`claude` when `CLAUDECODE` is set. No Codex session variable is established, so Codex is never
    guessed: pass `--harness codex`."""
    env = os.environ if environ is None else environ
    return "claude" if env.get("CLAUDECODE") else None


def _helper_optimization(home: Path, harness: str) -> "str | None":
    try:
        mo = _mo_mod()
        cfg = mo.load_config(home)
    except Exception:
        return None
    if cfg.get("enabled") is not True:
        return None
    mapping = cfg["harnesses"].get(harness)
    if not mapping:
        return None
    return mapping["choices"][mo.tier_choices(mapping, "light")[0]]["model"]


def helper_model(home, harness: "str | None") -> "tuple[str, str] | None":
    """(model, source) for this repo's helper on `harness`, or None. Sources, first match wins:
    the model-optimization light choice, the shipped default."""
    if not harness:
        return None
    home = Path(home)
    finders = {"optimization": lambda: _helper_optimization(home, harness),
               "default": lambda: HELPER_DEFAULTS.get(harness)}
    for src in HELPER_SOURCES:
        model = finders[src]()
        if model:
            return model, {"optimization": "model-optimization light choice", "default": "shipped default"}[src]
    return None


def _helper_cli(args) -> int:
    home = _repo_home(args.root)
    if not home.is_dir():
        print(f"helper: no home under {args.root}", file=sys.stderr)
        return 2
    harness = args.harness or detect_harness()
    found = helper_model(home, harness)
    if found is None:
        print(f"helper: no model for harness '{harness or 'unknown'}'; ask the operator which of their available "
              f"models is the cheapest, and dispatch the helper on it", file=sys.stderr)
        return 3
    print(f"helper: {found[0]} ({harness}; {found[1]})")
    return 0


# ------------------------------------------------------------------ eval of the drain (WO-098)
_DRAIN_STATES = ("closable", "ask-operator", "park", "open")


def _drain_points(path: str) -> list:
    """The JSONL items of a drain eval file; a malformed line raises ValueError naming the line."""
    pts = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            p = json.loads(line)
        except ValueError:
            raise ValueError(f"line {n}: not valid JSON")
        ok = (isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"].strip()
              and isinstance(p.get("text"), str) and p["text"].strip()
              and isinstance(p.get("source", ""), str)
              and (p.get("age_days") is None or (isinstance(p.get("age_days"), int)
                                                 and not isinstance(p.get("age_days"), bool)))
              and p.get("expect_state") in _DRAIN_STATES
              and (p.get("expect_join") is None or isinstance(p.get("expect_join"), str)))
        if not ok:
            raise ValueError(f"line {n}: needs id, text, expect_state (one of {', '.join(_DRAIN_STATES)}), "
                             f"and expect_join (WO-NNN or null)")
        pts.append(p)
    ids = [p["id"] for p in pts]
    if len(set(ids)) != len(ids):
        raise ValueError("an id is used on two lines")
    return pts


def _eval_state_items(pts: list) -> list:
    return [{"group": "loose-ends", "use": "loose-end-state", "ref": p["id"], "text": _squash(p["text"]),
             "state": _loose_state(p["id"], _squash(p["text"]), p.get("source") or "unknown", p.get("age_days"))}
            for p in pts]


def _eval_join_items(pts: list, home) -> list:
    """Each (item, open order) pair once, as the drain chooses them: `_join_item` plus its `item` and `wo`."""
    out, asked = [], set()
    cand = _loose_ends().join_candidates(
        home, [(p["id"], p["text"]) for p in pts], sm=sys.modules[__name__])["join"]
    for j in cand:
        j2 = {**_join_item(j), "item": j["item"], "wo": j["wo"]}
        if j2["ref"] not in asked:                       # each pair is asked once per run
            asked.add(j2["ref"])
            out.append(j2)
    return out


def _eval_report(pts: list, state_out: dict, join_out: list) -> dict:
    """Score the answers against the labels. `state_out` {id: outcome}; `join_out` [(pair, outcome)]."""
    rows = [{"id": p["id"], "expect_state": p["expect_state"], "outcome": state_out[p["id"]],
             "handed_back": state_out[p["id"]] == "escalate", "expect_join": p.get("expect_join"),
             "join": None} for p in pts]
    by = {r["id"]: r for r in rows}
    for j2, outcome in join_out:
        if outcome == "join" and by[j2["item"]]["join"] is None:
            by[j2["item"]]["join"] = j2["wo"]            # the best join of an item: its first `join` pair
    settled = [r for r in rows if not r["handed_back"]]
    right = sum(1 for r in settled if r["outcome"] == r["expect_state"])
    said = [r for r in rows if r["join"]]
    wanted = [r for r in rows if r["expect_join"]]
    return {"registry": _registry().REGISTRY_VERSION, "count": len(rows),
            "handed_back": len(rows) - len(settled),
            "hand_back_rate": (len(rows) - len(settled)) / len(rows) if rows else 0.0,
            "settled": len(settled), "settled_correct": right,
            "state_accuracy": right / len(settled) if settled else None,
            "join_said": len(said), "join_right": sum(1 for r in said if r["join"] == r["expect_join"]),
            "join_precision": (sum(1 for r in said if r["join"] == r["expect_join"]) / len(said)
                               if said else None),
            "join_wanted": len(wanted), "join_found": sum(1 for r in wanted if r["join"] == r["expect_join"]),
            "join_recall": (sum(1 for r in wanted if r["join"] == r["expect_join"]) / len(wanted)
                            if wanted else None),
            "points": rows}



def eval_export(path: str, home, out_path) -> dict:
    """The labelled set as an export file (see `helper_export`); the labels are not in it. No model call."""
    pts = _drain_points(path)
    items = _eval_state_items(pts) + _eval_join_items(pts, Path(home))
    doc = helper_export(items)
    _write_export(out_path, doc)
    return {"items": len(items), "fingerprint": doc["fingerprint"]}


def eval_answers(path: str, home, doc) -> dict:
    """Score a helper's answers to `eval_export`'s file against the labels. A stale document raises ValueError."""
    pts = _drain_points(path)
    home = Path(home)
    states = _eval_state_items(pts)
    joins = _eval_join_items(pts, home)
    applied = helper_apply(states + joins, doc)
    out = applied["outcomes"]
    d = _eval_report(pts, {it["ref"]: out[it["ref"]]["outcome"] for it in states},
                     [(j2, out[j2["ref"]]["outcome"]) for j2 in joins])
    d["defaulted"] = applied["defaulted"]
    return d


def format_drain_eval(d: dict) -> str:
    def pct(x):
        return "n/a" if x is None else f"{100 * x:.0f}%"
    return "\n".join([
        f"== system-one eval-drain (registry v{d['registry']}): {d['count']} items ==",
        f"hand-back rate: {d['handed_back']} of {d['count']} ({pct(d['hand_back_rate'])})",
        f"state accuracy (settled items): {d['settled_correct']} of {d['settled']} ({pct(d['state_accuracy'])})",
        f"join precision: {d['join_right']} of {d['join_said']} ({pct(d['join_precision'])})",
        f"join recall: {d['join_found']} of {d['join_wanted']} ({pct(d['join_recall'])})"])


def _eval_drain_cli(args) -> int:
    try:
        if args.export and args.answers:
            print("eval-drain: --export and --answers are two steps; give one", file=sys.stderr)
            return 2
        if args.export:
            e = eval_export(args.file, _resolve_home(args.home), args.export)
            print(json.dumps(e) if args.json else
                  f"eval-drain: exported {e['items']} items (fingerprint {e['fingerprint']}) to {args.export}")
            return 0
        if args.answers:
            d = eval_answers(args.file, _resolve_home(args.home), _read_answers(args.answers))
            print(json.dumps(d) if args.json else
                  format_drain_eval(d) + f"\nanswers counted as unsure (missing or invalid): {d['defaulted']}")
            return 0
        print(RETIRED_SENTENCE, file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"eval-drain: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"eval-drain: cannot read {args.file}: {e}", file=sys.stderr)
        return 2


def main(argv: "list | None" = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")        # Windows consoles default to cp1252
        except (AttributeError, OSError):
            pass
    given = sys.argv[1:] if argv is None else list(argv)
    if given and (given[0] in RETIRED_COMMANDS or (given[0] == "helper" and "--set" in given)):
        print(RETIRED_SENTENCE, file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="system_one.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    hp = sub.add_parser("helper", help="the drain helper's model for this repo and where it came from (no model call)")
    hp.add_argument("root", nargs="?", default=".", metavar="ROOT")
    hp.add_argument("--harness", help="claude or codex (default: detected from the environment)")
    dr = sub.add_parser("drain", help="<home> --export FILE | <home> --answers FILE: the drain by a helper (the "
                                      "answers step is the one command that writes in the home); also: accept ID | "
                                      "decline ID | withdraw ID | defer ID | status")
    dr.add_argument("rest", nargs=argparse.REMAINDER,
                    help="<home> --export FILE; <home> --answers FILE; accept ID --work-order NNN [--slice NAME] | "
                         "--question Q | --reason R [ROOT]; decline ID --reason R [--route DEST] [ROOT]; "
                         "withdraw ID [ROOT]; defer ID [ROOT]; status [ROOT]")
    dr.add_argument("--json", action="store_true")
    ed = sub.add_parser("eval-drain", help="export the drain's questions on labelled loose ends for a helper "
                                           "(--export), or score its answers against the labels (--answers)")
    ed.add_argument("file", help="JSONL: id, text, source, age_days, expect_state "
                                 "(closable|ask-operator|park|open), expect_join (WO-NNN or null)")
    ed.add_argument("--home", required=True, help="the home directory (or the repo root that holds it) whose open orders are the join candidates")
    ed.add_argument("--export", metavar="OUT", help="write the questions of the labelled set to OUT for a helper")
    ed.add_argument("--answers", metavar="IN", help="score a helper's answers file against the labels")
    ed.add_argument("--json", action="store_true")
    ln = sub.add_parser("lenses", help="list the active lenses with their domain and when-to-apply (no model call, writes nothing)")
    ln.add_argument("home", help="the home directory (or the repo root that holds it)")
    ln.add_argument("--wo", help="a work-order number")
    ln.add_argument("--text", help="a text file describing the work")
    ln.add_argument("--global-dir", help=f"the global lens library (default: ${GLOBAL_LENS_ENV}, "
                                         f"else <skill>/agents)")
    ln.add_argument("--json", action="store_true")
    sc = sub.add_parser("scope", help="advisory scope check of a work-order's diff (writes nothing)")
    sc.add_argument("home", help="the home directory (or the repo root that holds it)")
    sc.add_argument("wo", help="a work-order number")
    sc.add_argument("--range", help="A..B (default: merge-base to the branch wo-NNN and its slice branches wo-NNN-sN)")
    sc.add_argument("--slice", help="SN: only that slice's branch wo-NNN-sN (default: the order and all its slices)")
    sc.add_argument("--json", action="store_true")
    if given and not given[0].startswith("-") and given[0] not in sub.choices:
        print(f"system_one.py: unknown command {given[0]!r}; run system_one.py --help", file=sys.stderr)
        return 2
    args = ap.parse_args(argv)
    if args.cmd == "helper":
        return _helper_cli(args)
    if args.cmd == "drain":
        return _drain_cli(args)
    if args.cmd == "eval-drain":
        return _eval_drain_cli(args)
    if args.cmd == "lenses":
        return _lenses_cli(args)
    return _scope_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
