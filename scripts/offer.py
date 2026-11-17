#!/usr/bin/env python3
"""offer.py - the one consent round (WO-115). Standard library only.

Every opt-in this engine has is asked in ONE round, at inception (after the scaffold) and at upgrade. This computes
which of them are still unanswered by calling each subsystem's own check, and prints ONE question batch shaped for
AskUserQuestion (like `harness.py popup`). The tool computes what to ask; the orchestrator asks it and applies the
answers with the commands the batch names. NOTHING HERE WRITES.

    offer.py [ROOT] [--home DIR] [--registry DIR] [--claude-home DIR] [--claude-json FILE] [--text]

An answered question is never asked again, because a question exists only while its store lacks the answer:

    model optimization   <home>/model-optimization.json has `preference: unasked` (or no file)   [model_optimization.py]
    lenses               no <home>/lenses.json, and a lens exists to turn on                      [lenses.py]
    System One           no repo choice in <home>/system-one.json, and a server is configured
                         on this machine or answers on the default endpoint                        [system_one.py]
    federation           `federation.py offer` says there is something to offer (declining stores
                         nothing, so it is computed fresh each time)                              [federation.py]
    legacy registers     a register file not yet imported or declined (two asked per round)       [loose_ends.py]
    harness popup        `harness.py audit` holds removal candidates (the popup's sync questions
                         come with them)                                                          [harness.py]

Nothing to ask prints nothing (stdout empty, exit 0). A check that cannot run is said on stderr ("offer: X not read
(reason)") and its question is not asked; it is never reported as "nothing to ask". Output is JSON:
`questions` (AskUserQuestion shape, in order), `calls` (the indexes of `questions` for each consecutive
AskUserQuestion call, at most four a call: still one round, nothing runs between the calls), `entries` (per
question: id, the commands each answer runs, `if_unanswered`, `follow_up`), `not_read`. `--text` prints the same as a
numbered list for a harness with no question UI. A stored answer removed brings its question back.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib import util as importlib_util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")
MAX_PER_CALL = 4                    # AskUserQuestion: 1-4 questions a call
MAX_LEGACY = 2                      # register files asked in one round; the rest stay pending for the next
SUBPROCESS_TIMEOUT_S = 60


class NotRead(Exception):
    """A check could not run. Said, never counted as an empty offer."""


def _mod(name: str):
    key = f"_gitos_offer_{name}"
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib_util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
        mod = importlib_util.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return mod


def resolve_home(root, home=None) -> "Path | None":
    if home:
        h = Path(home)
        return h if h.is_dir() else None
    for rel in HOMES:
        if (Path(root) / rel).is_dir():
            return Path(root) / rel
    return None


def _q(question: str, header: str, options: list, multi: bool = False) -> dict:
    return {"question": question, "header": header[:12], "multiSelect": multi,
            "options": [{"label": l, "description": d} for l, d in options]}


def _cmd(script: str, *args) -> str:
    parts = ["python", (SCRIPTS / script).as_posix(), *[a.as_posix() if isinstance(a, Path) else str(a) for a in args]]
    return " ".join(f'"{p}"' if " " in p else p for p in parts)


def _entry(eid: str, question: dict, apply: dict, if_unanswered=None, follow_up: str = "", **extra) -> dict:
    return {"id": eid, "questions": [question], "apply": apply, "if_unanswered": if_unanswered or [],
            "follow_up": follow_up, **extra}


# ------------------------------------------------------------------ the checks (each asks its own subsystem)
def check_model_optimization(root, home, **_) -> list:
    mo = _mod("model_optimization")
    try:
        pref = mo.load_config(home)["preference"]
    except mo.Invalid as e:
        raise NotRead(f"model optimization setting: {e}")
    if pref != "unasked":
        return []
    return [_entry(
        "model-optimization",
        _q("Model optimization for this repo? Enabled routes implementers to models by task and can keep "
           "repo-local model-selection lessons; Disabled does neither. No answer is recorded as skipped (off).",
           "Model opt", [("Disabled (default)", "Records the choice; no routing, no lessons."),
                         ("Enabled", "Routes implementers by task; then configure a harness mapping "
                                     "(references/model-optimization.md).")]),
        {"Disabled (default)": [_cmd("model_optimization.py", "disable", root)],
         "Enabled": [_cmd("model_optimization.py", "enable", root)]},
        if_unanswered=[_cmd("model_optimization.py", "skip", root)],
        follow_up="Enabled without a usable mapping is setup incomplete: configure one before dispatching.")]


def check_lenses(root, home, **_) -> list:
    ln = _mod("lenses")
    cfg = ln.load(home)
    if cfg["state"] != "missing":
        return []
    repo = ln.lens_names(home / "agents")
    glob = ln.lens_names(ln.global_dir())
    if not repo and not glob:
        return []
    opts = [("Leave lenses off (default)", "Records off; nothing is applied.")]
    apply = {"Leave lenses off (default)": [_cmd("lenses.py", "disable", "--root", root)]}
    if repo:
        label = "Turn lenses on"
        opts.append((label, f"Activates this repo's own lenses ({', '.join(repo[:4])}"
                            f"{', ...' if len(repo) > 4 else ''})."))
        apply[label] = [_cmd("lenses.py", "enable", "--root", root)]
    follow = ""
    if glob:
        label = "Turn on and pick global lenses"
        opts.append((label, f"Then name the ones to select from: {', '.join(glob[:6])}"
                            f"{', ...' if len(glob) > 6 else ''}."))
        apply[label] = [_cmd("lenses.py", "enable", "--root", root)]
        follow = (f"After '{label}': ask which global lenses (`<skill>/agents/index.md` has each one's domain), then "
                  + _cmd("lenses.py", "select", "--root", root, "NAME..."))
    return [_entry("lenses", _q("Use lenses (operator-imported guidance the roles apply by domain) in this repo?",
                                "Lenses", opts), apply, follow_up=follow)]


def _so_detected() -> bool:
    try:
        r = subprocess.run([sys.executable, str(SCRIPTS / "system_one.py"), "setup", "--detect"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=SUBPROCESS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        raise NotRead(f"system_one setup --detect: {type(e).__name__}")
    return bool(r.stdout.strip())


def check_system_one(root, home, **_) -> list:
    so = _mod("system_one")
    state, _detail = so.repo_choice(home)
    if state != "missing":
        return []                       # on / off answered; malformed and retired are `migrate`'s and the canary's
    configured = (so.system_home() / so.CONFIG_NAME).is_file()
    if not configured and not _so_detected():
        return []
    yes = [_cmd("system_one.py", "repo", "on", root)]
    if not configured:
        yes.insert(0, _cmd("system_one.py", "setup", "--write"))
    return [_entry(
        "system-one",
        _q("Use System One in this repo? A small local model drains the loose-ends list (routine yes/no judgments "
           "for scripts, nothing else); the repo's text goes to the configured endpoint.", "System One",
           [("No (default)", "Records off; nothing is sent."),
            ("Yes", "Records on" + ("" if configured else " after setting up the server that answered") + ".")]),
        {"No (default)": [_cmd("system_one.py", "repo", "off", root)], "Yes": yes})]


def check_federation(root, home, registry=None, **_) -> list:
    cmd = [sys.executable, str(SCRIPTS / "federation.py"), "offer", str(root), "--json", "--home", str(home)]
    if registry:
        cmd += ["--registry", str(registry)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=SUBPROCESS_TIMEOUT_S)
        doc = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        raise NotRead(f"federation offer: {type(e).__name__}")
    if doc is None:
        raise NotRead(f"federation offer: exit {r.returncode}")
    if not doc.get("ask"):
        return []
    fed = _cmd("federation.py", "offer", root)
    if doc.get("kind") == "enable":
        return [_entry(
            "federation",
            _q(f"{doc.get('siblings', 0)} other gitos repo(s) on this machine are federated; this one is not. "
               "Federate so work that belongs to a sibling can go there? Declining stores nothing.", "Federation",
               [("Leave federation off", "Nothing is written; the offer is computed again next time."),
                ("Join the default group", "consultable off (siblings cannot read this brain), accept-proposals on "
                                           "(a sibling can queue a proposal you adjudicate)."),
                ("Pick a group", "Lists the groups on this machine, then asks the two exposure flags.")]),
            {"Leave federation off": [], "Join the default group": [_cmd("federation.py", "enable", root)],
             "Pick a group": []},
            follow_up=f"After 'Pick a group': run `{fed}` and follow references/federation.md -> Asking is a PROMPT "
                      f"(group pick, then the two exposure flags).")]
    return [_entry(
        "federation",
        _q(f"{len(doc.get('groups') or [])} federation group(s) on this machine that this repo is not in. Join one? "
           "Declining stores nothing.", "Federation",
           [("Leave as is", "Nothing is written; the offer is computed again next time."),
            ("Show the groups", "Lists them; then one question: which to join.")]),
        {"Leave as is": [], "Show the groups": []},
        follow_up=f"After 'Show the groups': run `{fed}` and follow references/federation.md -> Already federated, "
                  f"and a new group exists (`federation set --groups` REPLACES the set).")]


def check_legacy(root, home, **_) -> list:
    le = _mod("loose_ends")
    pending = le.legacy_pending(home)
    out = []
    for i, rel in enumerate(pending[:MAX_LEGACY], start=1):
        path = (Path(root) / rel).as_posix()
        out.append(_entry(
            f"legacy-{i}",
            _q(f"{rel} looks like a loose-ends register. Import its rows into the loose-ends list and drain them? "
               "The file itself is never edited.", f"Legacy {i}",
               [("Import and drain", "Adds each row as a new item, then the drain runs over the list."),
                ("Decline", "Records the answer so this file is not asked about again.")]),
            {"Import and drain": [_cmd("loose_ends.py", "import", "--root", root, path)],
             "Decline": [_cmd("loose_ends.py", "legacy", "decline", path, "--root", root)]},
            follow_up="After an import: run the drain (references/roles/orchestrator.md -> Draining the loose ends)."))
    if len(pending) > MAX_LEGACY:
        out[-1]["follow_up"] += f" {len(pending) - MAX_LEGACY} more register file(s) are asked in the next round."
    return out


def check_harness(root, home, claude_home=None, claude_json=None, harness_popup=None, **_) -> list:
    if harness_popup is None:
        h = _mod("harness")
        ch, cj = h.claude_paths(claude_home, claude_json)
        try:
            audit = h.audit(Path(root), home, ch, cj, h.DEFAULT_CONTEXT_WINDOW, None)
        except Exception as e:           # an unreadable Claude home is a source not read, not an empty popup
            raise NotRead(f"harness audit: {type(e).__name__}: {e}")
        if not (audit.get("removal") or {}).get("candidates"):
            return []
        harness_popup = h.popup_questions(audit["removal"], sync=audit["claude_ai_sync"])
    qs = list(harness_popup.get("questions") or [])
    if not qs:
        return []
    return [{"id": "harness-popup", "questions": qs, "apply": {},
             "if_unanswered": [], "follow_up":
             "Only ticked removal candidates go to `harness.py sync --confirm NAME` (the batch's label_to_name maps a "
             "label back to its name); only a sync answer of Turn off or Turn back on goes to `sync` as the flag "
             "sync_flags maps it to. Show the dry run, then `--apply` on the operator's word. Nothing is pre-selected "
             "and silence applies nothing.",
             "label_to_name": harness_popup.get("label_to_name", {}), "sync_flags": harness_popup.get("sync_flags", {})}]


CHECKS = (("model-optimization", check_model_optimization), ("lenses", check_lenses),
          ("system-one", check_system_one), ("federation", check_federation),
          ("legacy-registers", check_legacy), ("harness", check_harness))


# ------------------------------------------------------------------ the batch
def compute(root, home=None, **kw) -> dict:
    """The batch for ROOT: {questions, calls, entries, not_read}; `questions` is empty when nothing is unanswered."""
    root = Path(root).resolve()
    home = resolve_home(root, home)
    if home is None:
        raise NotRead(f"no gitos home under {root}: scaffold the repo first")
    entries, not_read = [], []
    for name, fn in CHECKS:
        try:
            entries += fn(root, home, **kw)
        except NotRead as e:
            not_read.append(f"{name}: {e}")
        except Exception as e:           # a crashed check is reported as itself, never as "nothing to ask"
            not_read.append(f"{name}: {type(e).__name__}: {e}")
    questions = []
    for e in entries:
        e["at"] = list(range(len(questions), len(questions) + len(e["questions"])))
        questions += e.pop("questions")
    calls = [list(range(i, min(i + MAX_PER_CALL, len(questions)))) for i in range(0, len(questions), MAX_PER_CALL)]
    return {"questions": questions, "calls": calls, "entries": entries, "not_read": not_read}


def render_text(batch: dict) -> str:
    out = []
    for n, q in enumerate(batch["questions"], start=1):
        out.append(f"{n}. {q['question']}")
        for j, o in enumerate(q["options"], start=1):
            out.append(f"   {chr(96 + j)}) {o['label']} - {o['description']}")
    return "\n".join(out)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(prog="offer.py", description="The one consent round: every unanswered opt-in.")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--home", default=None)
    ap.add_argument("--registry", default=None, help="federation tenants directory override")
    ap.add_argument("--claude-home", default=None)
    ap.add_argument("--claude-json", default=None)
    ap.add_argument("--text", action="store_true", help="a numbered text list instead of JSON")
    a = ap.parse_args(argv)
    try:
        batch = compute(a.root, a.home, registry=a.registry, claude_home=a.claude_home, claude_json=a.claude_json)
    except NotRead as e:
        print(f"offer: {e}", file=sys.stderr)
        return 2
    for line in batch["not_read"]:
        print(f"offer: {line} (not read; its question is not asked)", file=sys.stderr)
    if not batch["questions"]:
        return 0
    print(render_text(batch) if a.text else json.dumps(batch, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
