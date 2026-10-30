"""Dispatch-boundary tier gate: refuse an unrouted subagent dispatch, in Claude.

See references/model-optimization.md, *The dispatch requirement*. The tier policy chooses a
model/effort pair per task; this is the mechanism at the boundary where that choice must hold.

WHY A HOOK AND NOT A DIRECTIVE. The obligation has to bind the TOOL, not the role. A mechanism
keyed to "the orchestrator dispatches" misses every sub-dispatch by construction: a dispatched
worker is a full agent with the dispatch tool available, and a measured sub-dispatch went out
with neither component set while the worker was executing an order about unfailable assertions.
The client's tool-call event binds the tool, so it reaches the orchestrator, the worker, and an
agent three levels down, identically.

THE DECISION CHANNEL, AND WHY THIS NEVER BLOCKS BY ACCIDENT. On the tool-call event a refusal
is a JSON object on stdout; a nonzero exit ALSO refuses. So this gate speaks only through
stdout and ALWAYS exits 0: a crash, an absent engine, an unreadable configuration or an
unparseable announcement print nothing and the dispatch proceeds. The entry is registered
WITHOUT `onFailure: "block"` and WITHOUT `async` - the first would turn a broken gate into a
refusal, and an async hook's decision fields are documented as having no effect at all, so an
async "gate" is not a gate. A gate that blocks deliberately must be exact about when, which
means every unknown resolves to allow.

IT NEVER SAYS "allow" EITHER. A pass prints nothing. An explicit allow would bypass the rest of
the permission system, which this has no standing to do - it has one question to answer, and
"no opinion" is the honest answer to every other one.

TWO STRENGTHS, AND THE DIFFERENCE MATTERS. Presence of a model/effort pair proves a route was
TYPED, not that it matches the tier the work-order derives. So:

  * THE FLOOR, always on, no configuration required: both components must be set. This is the
    measured defect - a dispatch with a model and no effort key at all, and one with neither.
  * THE TIER BINDING, on only where the repo HAS a tier to bind to (optimization enabled with a
    configured mapping): the pair must match a routing RECEIPT that `select` authorized. A
    receipt is single-use and short-lived, because a stale receipt that authorizes every later
    dispatch is an assertion that cannot go red - see
    .gitos/brain/wiki/concepts/assertions-that-cannot-go-red.md.

WHAT THIS DOES NOT COVER, stated rather than implied:
  * CLAUDE ONLY. The tool-call event is a Claude Code surface. A Codex session never runs this,
    so there the requirement is prose and nothing refuses a violation.
  * DEFEATABLE BY CONFIGURATION. `disableAllHooks` in any settings file, and
    `allowManagedHooksOnly` in a managed organization, switch hooks off; an operator report
    names `--bare` as a third, which the published hooks page does not confirm. A strong
    guardrail, not a proof.
  * REPO SCOPE DOES NOT REACH OTHER REPOS. A gate written into a repo's committed settings is
    blind to every session outside it. The machine-wide install is the layer that covers those.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time

TOOL = "Agent"
EVENT = "PreToolUse"
# A full-context fork inherits the lead's pair and `select` refuses to route one, so demanding a
# route for a fork would redden on correct behaviour.
INHERITING_TYPES = ("fork",)
RECEIPT_SCHEMA = 1
# Short enough that a receipt cannot outlive the turn that earned it, long enough that composing
# a real dispatch after `select` does not race the clock.
RECEIPT_TTL_SECONDS = 900
# A receipt issued "in the future" means the clock moved, not that the route is fresher than it
# is. Small tolerance for an unsynchronized clock; beyond it the receipt is not evidence.
RECEIPT_SKEW_SECONDS = 60
RECEIPT_PREFIX = "gitos-dispatch-receipt-"


def _engine():
    """This engine's optimization helper, loaded from beside this file BY PATH, or None.

    By path rather than by `import` so it resolves the same however this script was reached.
    None means the tier binding cannot run at all - the floor below needs no configuration and
    stays on regardless, which is the point of having a floor.
    """
    path = Path(__file__).resolve().parent / "model_optimization.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_gitos_guard_model_optimization", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def receipt_path(root):
    """Where this repo's routing receipt lives: OUTSIDE the repo, in the per-user temp dir.

    Outside on purpose. A receipt is a single-use token for one dispatch in one session - it is
    not repo content, must never travel in a commit, and keeping it out of the tree means no
    `.gitignore` line to lay and nothing for a clone to arrive holding. Keyed by a digest of
    the resolved root so two checkouts never read each other's token.
    """
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"{RECEIPT_PREFIX}{digest[:16]}.json"


def write_receipt(root, value):
    path = receipt_path(root)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_receipt(root):
    """-> (receipt, None) or (None, reason). A reason is a refusal, never an exception."""
    path = receipt_path(root)
    if not path.exists():
        return None, "no routing receipt exists for this repo"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, f"the routing receipt could not be read ({type(exc).__name__})"
    if not isinstance(value, dict) or value.get("schema_version") != RECEIPT_SCHEMA:
        return None, "the routing receipt is not a receipt this engine wrote"
    for key in ("tier", "model", "effort"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            return None, f"the routing receipt carries no {key}"
    if not isinstance(value.get("uses_remaining"), int):
        return None, "the routing receipt carries no use count"
    if not isinstance(value.get("issued_at"), (int, float)):
        return None, "the routing receipt carries no issue time"
    return value, None


def receipt_status(value, now=None):
    """Whether a well-formed receipt may still authorize a dispatch. -> None, or a reason.

    THE TWO WAYS A RECEIPT GOES STALE, and both are the whole reason a receipt is safe to bind
    to. SINGLE USE: `select` authorizes one dispatch, so the second dispatch behind one receipt
    is unauthorized even though the token on disk looks valid. EXPIRY: a route derived from a
    session baseline that an announced change may since have invalidated is not evidence after
    its window. Without these a receipt is exactly the assertion that cannot go red - it would
    sit on disk approving every later dispatch, including the mis-tiered one.
    """
    now = time.time() if now is None else now
    if value["uses_remaining"] <= 0:
        return "its routing receipt was already spent on an earlier dispatch (receipts are single-use)"
    age = now - float(value["issued_at"])
    if age > RECEIPT_TTL_SECONDS:
        return (f"its routing receipt expired {int(age - RECEIPT_TTL_SECONDS)}s ago "
                f"(receipts last {RECEIPT_TTL_SECONDS}s)")
    if age < -RECEIPT_SKEW_SECONDS:
        return "its routing receipt is dated in the future; the clock moved, so it is not evidence"
    return None


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": EVENT, "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


ADVICE = ("Derive the tier from the work-order's countable properties "
          "(references/model-optimization.md, *Mapping + ceiling*), then pass BOTH `model` and "
          "`effort` on the dispatch. This binds the tool, so it applies to a sub-dispatch too. "
          "A full-context fork inherits the lead and is exempt.")


def decide(payload, engine=None, now=None):
    """The one decision. -> a deny document, or None meaning "no opinion, proceed".

    Every branch that cannot establish a violation returns None. That asymmetry is deliberate:
    this gate's cost of a false refusal is a blocked dispatch an operator did nothing wrong to
    earn, and its cost of a missed one is the staleness that preceded it.
    """
    if not isinstance(payload, dict):
        return None
    # BLAST RADIUS. A gate that reaches past its own tool is a defect in itself, so anything
    # that is not this tool's call is none of this gate's business.
    if payload.get("tool_name") != TOOL:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool_input.get("subagent_type") in INHERITING_TYPES:
        return None

    def routed(key):
        value = tool_input.get(key)
        return isinstance(value, str) and bool(value.strip())

    # THE FLOOR. Detected by KEY PRESENCE, which is what the announcement makes possible: the
    # requested effort appears in the tool input only when one was set, so a half-routed
    # dispatch is distinguishable from a routed one rather than being guessed at from a value.
    missing = [key for key in ("model", "effort") if not routed(key)]
    if missing:
        named = " and ".join(f"`{key}`" for key in missing)
        return deny(f"This dispatch sets no {named}, so no task tier was chosen for it - it "
                    f"inherits the lead's pair, which is the ceiling. {ADVICE}")

    # THE TIER BINDING, where there is a tier to bind to. A repo with optimization off has no
    # configured mapping and no `select` decision to compare against, so there is nothing here
    # to be exact about; the floor already refuses the measured defect. Off has never meant
    # "spend the ceiling by default", and the floor is what makes that true.
    engine = _engine() if engine is None else engine
    if engine is None:
        return None
    root = payload.get("cwd")
    if not isinstance(root, str) or not Path(root).is_dir():
        return None
    try:
        home = engine.home_path(root)
        if not home.is_dir() or not engine.load_config(home)["enabled"]:
            return None
    except Exception:
        return None

    value, reason = read_receipt(root)
    if value is None:
        return deny(f"Optimization is enabled here and {reason}, so nothing establishes that "
                    f"this pair is the tier this work needs - a typed pair proves a route was "
                    f"written down, not that it was derived. Run `select`, record its "
                    f"dispatch-ready decision with `dispatch_guard.py record`, then dispatch.")
    stale = receipt_status(value, now)
    if stale is not None:
        return deny(f"This dispatch is not authorized: {stale}. Re-run `select` for THIS "
                    f"dispatch and record the decision again; a receipt that outlived its "
                    f"dispatch would authorize every later one, including a mis-tiered one.")
    pair = (tool_input.get("model").strip(), tool_input.get("effort").strip())
    if pair != (value["model"], value["effort"]):
        return deny(f"This dispatch requests {pair[0]}/{pair[1]}, but the recorded route for "
                    f"tier `{value['tier']}` is {value['model']}/{value['effort']}. Dispatch "
                    f"the pair `select` authorized, or re-derive the tier and re-run `select`.")
    # Authorized - and therefore SPENT. Consumed on the pass path, so the next dispatch needs
    # its own decision. A failed write is swallowed: a token that cannot be spent must not
    # become a refusal.
    try:
        write_receipt(root, {**value, "uses_remaining": value["uses_remaining"] - 1})
    except OSError:
        pass
    return None


def hook_command(stream):
    """The client-event entry point. ALWAYS returns 0; stdout carries a refusal or nothing.

    The broad guard is the gate's fail-open half and is not laxity: this string is committed
    into repos and the engine beside it can be older, newer or absent, so anything it cannot
    decide must leave the dispatch alone.
    """
    try:
        payload = json.loads(stream.read() or "null")
        decision = decide(payload)
        if decision is not None:
            print(json.dumps(decision, ensure_ascii=False))
    except Exception as exc:
        print(f"gitos dispatch guard: inert - {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- registration
# SELF-LOCATING, for the same reason the currency hook's bootstrap is: the file it lands in is
# COMMITTED, so an absolute path would be one machine's truth travelling to every clone. It
# calls the entry point DIRECTLY rather than through the argument parser, so an engine with no
# such entry point raises and is swallowed instead of a parser exiting nonzero - and on this
# event a nonzero exit is a refused dispatch.
HOOK_BOOTSTRAP = (
    "import importlib.util, pathlib, sys\n"
    "try:\n"
    "    p = pathlib.Path.home() / '.claude/skills/gitos/scripts/dispatch_guard.py'\n"
    "    spec = importlib.util.spec_from_file_location('gitos_dispatch_guard', p)\n"
    "    guard = importlib.util.module_from_spec(spec)\n"
    "    spec.loader.exec_module(guard)\n"
    "    guard.hook_command(sys.stdin)\n"
    "except BaseException:\n"
    "    pass\n"
)
HOOK_MATCHERS = {EVENT: TOOL}


def hook_entry():
    """The one entry this gate registers.

    NEITHER `async` NOR `onFailure` IS SET, and both omissions are load-bearing. An async
    hook's `permissionDecision` is documented as having no effect, so an async gate silently
    stops being a gate. `onFailure: "block"` would make the gate's own breakage a refusal,
    which is precisely the accidental block this design exists to rule out.
    """
    return {"type": "command", "command": "python", "args": ["-I", "-c", HOOK_BOOTSTRAP],
            "statusMessage": "gitos: every dispatch names a task tier"}


def ensure_hook(root, engine=None):
    """Register this gate in `<root>/.claude/settings.json`. -> (status, detail).

    REUSES the optimization helper's writer rather than carrying a second one: that writer is
    parameterized by entry and events exactly so a sibling gate passes two arguments instead of
    copying it, and it registers BESIDE whatever it finds without losing either hook.
    """
    engine = _engine() if engine is None else engine
    if engine is None:
        return "skipped", "model_optimization.py not found beside dispatch_guard.py"
    return engine.ensure_settings_hook(root, entry=hook_entry(), matchers=HOOK_MATCHERS)


def receipt_from_select(decision, uses=1):
    """Turn a `select` decision into a receipt. Raises ValueError on anything else.

    The receipt is derived from the HELPER'S decision, never from flags a caller types, which
    is what makes it evidence of a route rather than a second place to assert one. Only
    `dispatch-ready` qualifies: blocked and recommendation-only are refusals, and
    recommendation-only in particular means no certified optimized dispatch.
    """
    if not isinstance(decision, dict):
        raise ValueError("a select decision must be a JSON object")
    status = decision.get("status")
    if status != "dispatch-ready":
        raise ValueError(f"select returned {status!r}; only a dispatch-ready decision "
                         f"authorizes a dispatch")
    requested = decision.get("requested")
    if not isinstance(requested, dict) or not isinstance(requested.get("model"), str) \
            or not isinstance(requested.get("effort"), str):
        raise ValueError("the select decision names no requested model/effort pair")
    tier = decision.get("tier")
    if not isinstance(tier, str) or not tier.strip():
        raise ValueError("the select decision names no tier")
    if not isinstance(uses, int) or uses < 1:
        raise ValueError("a receipt must authorize at least one dispatch")
    session = decision.get("session")
    return {"schema_version": RECEIPT_SCHEMA, "tier": tier,
            "model": requested["model"], "effort": requested["effort"],
            "session_id": session.get("session_id") if isinstance(session, dict) else None,
            "issued_at": time.time(), "uses_remaining": uses}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dispatch-boundary tier gate (Claude only).")
    parser.add_argument("command", choices=("hook", "record", "show", "install", "install-user"))
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--select", help="a `select` decision JSON file, or - for stdin; "
                                        "only a dispatch-ready decision authorizes a dispatch")
    parser.add_argument("--uses", type=int, default=1,
                        help="dispatches this receipt authorizes (default 1; receipts are "
                             "single-use by design)")
    args = parser.parse_args(argv)

    if args.command == "hook":
        # The repo comes from the announcement, not from argv, so one committed command string
        # serves every repo and every checkout.
        return hook_command(sys.stdin)
    if args.command == "install-user":
        # MACHINE-WIDE, and only ever on this explicit name. It edits the operator's own
        # settings, which is their decision to make and not a side effect of any other command.
        status, detail = ensure_hook(Path.home())
        print(f"gitos dispatch guard: {status} in {Path.home() / '.claude' / 'settings.json'}"
              f"{f' - {detail}' if detail else ''}")
        print("Every session on this machine now names a task tier at dispatch, including "
              "sessions in repos that have no gitos home. Claude Code only.")
        return 0 if status != "skipped" else 3
    root = Path(args.root).resolve()
    if args.command == "install":
        status, detail = ensure_hook(root)
        print(f"gitos dispatch guard: {status} in {root / '.claude' / 'settings.json'}"
              f"{f' - {detail}' if detail else ''}")
        return 0 if status != "skipped" else 3
    if args.command == "show":
        value, reason = read_receipt(root)
        if value is None:
            print(json.dumps({"status": "none", "reason": reason,
                              "path": str(receipt_path(root))}, indent=2))
            return 3
        stale = receipt_status(value)
        print(json.dumps({"status": "spent-or-expired" if stale else "usable",
                          "reason": stale, "path": str(receipt_path(root)),
                          "receipt": value}, indent=2, ensure_ascii=False))
        return 3 if stale else 0
    # record
    if not args.select:
        print("record requires --select with a `select` decision (or - for stdin)",
              file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.read() if args.select == "-" else \
            Path(args.select).read_text(encoding="utf-8-sig")
        value = receipt_from_select(json.loads(raw), args.uses)
    except (OSError, ValueError) as exc:
        print(f"gitos dispatch guard: no receipt written - {exc}", file=sys.stderr)
        return 2
    path = write_receipt(root, value)
    print(json.dumps({"status": "recorded", "path": str(path), "receipt": value},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
