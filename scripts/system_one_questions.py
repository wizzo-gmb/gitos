"""The System One question registry: the ONE place question wording and decision tables live.

Stdlib only. Imported by `system_one.py`; nothing else defines a question.

HOW TO ADD A USE (one registry entry, then a CLI subcommand in the caller's script):

    register(
        "my_use",
        questions=[
            question("is_dup", "noul",
                     "The new note restates something already recorded.",
                     {"true": "Same claim, same subject, same scope.",
                      "false": "A different claim, subject or scope."}),
        ],
        table=lambda i: "merge" if i["is_dup"] == "yes" else
                        "keep" if i["is_dup"] == "no" else "escalate",
        outcomes={"merge": CONFIRM, "keep": REVERSIBLE, "escalate": REVERSIBLE},
    )

  * `questions`: a list of `question(...)` dicts. `type` is `noul` (a yes/no; `p` is P(true)) or
    `choice` (`criteria` maps each choice name to when it applies).
  * `table(inputs)`: a pure function from the SETTLED inputs `{question_id: value}` to an outcome
    name. A noul input is `"yes"`, `"no"` or `"unsure"`. A choice input is the chosen name, or
    `"unsure"` when the top probability is under the `yes` threshold.
  * `outcomes`: every outcome the table can return, flagged `REVERSIBLE` (a script may apply it)
    or `CONFIRM` (it is only ever REPORTED; a person or the reasoning model confirms it by reading
    the item). `escalate` is reserved: always reversible, meaning "hand it up the cascade".
  * EVERY combination of inputs is enumerated at load time (including `unsure`). A combination the
    table raises on, or maps to an unlisted outcome, is a load-time error (`RegistryError`), and
    a combination with an `unsure` input the decision reads must map to `escalate` (`reads(inputs)`
    names the answers a decision uses; the default is all of them, `loose-end-state` narrows it).
  * Bump `REGISTRY_VERSION` when a question's wording or a table changes: the call log records it,
    so a log row is comparable only to rows of the same version.

WORDING RULES (the vendor's, kept here because they are the part that rots):
  * ONE judgment per question. Two ideas in one question is two questions.
  * Concrete and observable: say what is on the page, not what the author meant.
  * A true (yes) answer means yes: phrase every noul as a statement that is true or false.
  * No case-specific clauses. An unsure answer is fixed with better state or a smaller question,
    never with wording tuned to the one item that went wrong.
"""

from __future__ import annotations

import itertools

REGISTRY_VERSION = 14

REVERSIBLE = "reversible"
CONFIRM = "confirm"
ESCALATE = "escalate"
SETTLED_NOUL = ("yes", "no", "unsure")

USES: dict[str, dict] = {}


class RegistryError(Exception):
    """The registry is malformed. Raised at import time, so a bad entry never loads."""


def question(qid: str, qtype: str, instructions: str, criteria: "dict | None" = None) -> dict:
    return {"id": qid, "type": qtype, "instructions": instructions, "criteria": criteria}


def request_questions(use: str) -> dict:
    """The `questions` object of a request for this use: `{id: {type, instructions, criteria}}`."""
    out = {}
    for q in USES[use]["questions"]:
        body = {"type": q["type"], "instructions": q["instructions"]}
        if q["criteria"] is not None:
            body["criteria"] = q["criteria"]
        out[q["id"]] = body
    return out


def input_domain(q: dict) -> tuple:
    if q["type"] == "noul":
        return SETTLED_NOUL
    return tuple(q["criteria"]) + ("unsure",)


def register(name: str, questions: list, table, outcomes: dict, reads=None) -> None:
    """`reads(inputs) -> [question ids]` (default: all) names the answers a decision actually uses;
    only an unsure answer among them must map to `escalate` and costs a second pass (WO-094)."""
    reads = reads or (lambda i: list(i))
    if name in USES:
        raise RegistryError(f"use {name!r} registered twice")
    if not questions:
        raise RegistryError(f"use {name!r} has no questions")
    seen = set()
    for q in questions:
        if q["id"] in seen:
            raise RegistryError(f"use {name!r}: duplicate question id {q['id']!r}")
        seen.add(q["id"])
        if q["type"] not in ("noul", "choice"):
            raise RegistryError(f"use {name!r}: question {q['id']!r} has type {q['type']!r}; "
                                f"tables take noul or choice")
        if not q["instructions"] or not isinstance(q["instructions"], str):
            raise RegistryError(f"use {name!r}: question {q['id']!r} has no instructions")
        if q["type"] == "choice" and not (isinstance(q["criteria"], dict) and q["criteria"]):
            raise RegistryError(f"use {name!r}: choice question {q['id']!r} needs criteria")
    outcomes = dict(outcomes)
    outcomes.setdefault(ESCALATE, REVERSIBLE)
    for o, flag in outcomes.items():
        if flag not in (REVERSIBLE, CONFIRM):
            raise RegistryError(f"use {name!r}: outcome {o!r} is flagged {flag!r}")
    if outcomes[ESCALATE] != REVERSIBLE:
        raise RegistryError(f"use {name!r}: `escalate` must be reversible")
    ids = [q["id"] for q in questions]
    for combo in itertools.product(*(input_domain(q) for q in questions)):
        inputs = dict(zip(ids, combo))
        try:
            got = table(dict(inputs))
        except Exception as e:
            raise RegistryError(f"use {name!r}: table fails on {inputs} ({type(e).__name__}: {e})")
        if got not in outcomes:
            raise RegistryError(f"use {name!r}: table maps {inputs} to {got!r}, "
                                f"which is not a declared outcome")
        if any(inputs[k] == "unsure" for k in reads(dict(inputs))) and got != ESCALATE:
            raise RegistryError(f"use {name!r}: {inputs} has an unsure input that is read and must "
                                f"map to `escalate`, not {got!r}")
    USES[name] = {"questions": list(questions), "table": table, "outcomes": outcomes, "reads": reads}


# ------------------------------------------------------------------------------------- the uses
# `probe`: used by `system_one.py status` and the selftest gate. It judges nothing real.
register(
    "probe",
    questions=[
        question("is_greeting", "noul",
                 "The text is a greeting.",
                 {"true": "The text greets someone, such as hello or good morning.",
                  "false": "The text is anything else."}),
    ],
    table=lambda i: {"yes": "greeting", "no": "other"}.get(i["is_greeting"], ESCALATE),
    outcomes={"greeting": REVERSIBLE, "other": REVERSIBLE},
)


# ------------------------------------------------------------------ the ledger uses (WO-085)
# Code gathers the facts and builds a small state per item; the model answers; the table decides.
# Each question stands alone: the model sees one question and one state, never the other questions.
# `parked-trigger`: does an open Parked row's restart trigger look fired? It only orders the digest.
register(
    "parked-trigger",
    questions=[
        question("fired", "noul",
                 "The event named as the restart trigger has happened, according to the commit "
                 "subjects, work-order titles or version listed after the row.",
                 {"true": "A listed commit subject, work-order title or version states the event "
                          "the trigger names.",
                  "false": "Nothing listed states that event; the trigger needs something that is "
                           "not listed."}),
    ],
    table=lambda i: {"yes": "fired", "no": "waiting"}.get(i["fired"], ESCALATE),
    outcomes={"fired": REVERSIBLE, "waiting": REVERSIBLE},
)

# `duplicate`: a candidate pair chosen by code (shared references, shared paths, word overlap).
# The model only confirms; `fold` is a confirm outcome.
register(
    "duplicate",
    questions=[
        question("same_item", "noul",
                 "Item A and item B describe the same piece of work.",
                 {"true": "Both ask for the same change to the same thing, so doing one makes the "
                          "other unnecessary.",
                  "false": "They ask for different changes, or the same area with different goals."}),
    ],
    table=lambda i: {"yes": "fold", "no": "distinct"}.get(i["same_item"], ESCALATE),
    outcomes={"fold": CONFIRM, "distinct": REVERSIBLE},
)


# ------------------------------------------------------------------ intake and board uses (WO-086)
# SEVERITY IS A `choice` OVER THE FOUR LEVEL NAMES, each level described as a situation: tables
# keep taking noul and choice inputs only, so no registry extension was needed. Screening is split
# into three one-question uses (area, severity, engine-change) rather than one three-question use:
# an unsure input forces a whole use to `escalate`, and each judgment should print or not on its own.
# Every outcome only ANNOTATES a listing, so all are reversible.
PROPOSAL_AREAS = {
    "canary": "The proposal is about the canary's checks, categories or reporting.",
    "ledger": "The proposal is about work-orders, the index, resume files or how work is recorded.",
    "federation": "The proposal is about sharing proposals, the registry or intake between repos.",
    "model-optimization": "The proposal is about choosing or recording which model runs a task.",
    "harness": "The proposal is about the scripts that dispatch, run or verify agent work.",
    "brain": "The proposal is about the orchestrator's memory notes and how they are kept.",
    "roles-and-docs": "The proposal is about role instructions, reference text or documentation.",
    "operator-pages": "The proposal is about the owner board or the decisions page an operator reads.",
    "other": "The proposal is about something that none of the other areas covers.",
}
PROPOSAL_SEVERITIES = {
    "low": "Cosmetic, convenience or defensive cleanup; nothing is wrong today.",
    "medium": "Logs or reports mislead, the engine's description drifts from what is deployed, "
              "or a risk exists but nothing has gone wrong yet.",
    "high": "The engine silently gives wrong results that people then act on, or a boundary "
            "that isolates or secures something is broken.",
    "critical": "A user could be harmed, data is corrupted or lost, a production system is down, "
                "or money or personal health data is at risk.",
}
CARD_GROUPS = {
    "close-or-keep-open": "The card asks whether finished or stale work should be closed or kept open.",
    "decisions": "The card asks the operator to choose between ways of doing something.",
    "your-actions": "The card asks the operator to do a step that only the operator can do.",
    "parked-work": "The card is about work waiting for a later event, with no action due now.",
}


def _name_or_escalate(qid: str):
    return lambda i: ESCALATE if i[qid] == "unsure" else i[qid]


register(
    "proposal-area",
    questions=[question("area", "choice", "Which area of the engine does the proposal concern?",
                        PROPOSAL_AREAS)],
    table=_name_or_escalate("area"),
    outcomes={a: REVERSIBLE for a in PROPOSAL_AREAS},
)

register(
    "proposal-severity",
    questions=[question("severity", "choice",
                        "Which situation does the proposal describe, if it is left unaddressed?",
                        PROPOSAL_SEVERITIES)],
    table=_name_or_escalate("severity"),
    outcomes={s: REVERSIBLE for s in PROPOSAL_SEVERITIES},
)

register(
    "proposal-engine-change",
    questions=[question("asks_engine_change", "noul",
                        "The proposal asks for a change to the engine's own scripts or reference text.",
                        {"true": "It names a script, check, command or reference text to add, "
                                 "alter or remove.",
                         "false": "It reports an observation or asks about a project's own code "
                                  "or data."})],
    table=lambda i: {"yes": "engine-change", "no": "no-engine-change"}.get(i["asks_engine_change"],
                                                                           ESCALATE),
    outcomes={"engine-change": REVERSIBLE, "no-engine-change": REVERSIBLE},
)

# `proposal-duplicate`: one (proposal, work-order) pair chosen by code. An annotation only.
register(
    "proposal-duplicate",
    questions=[question("same_ask", "noul",
                        "Item A and item B ask for the same change to the same thing.",
                        {"true": "Both ask for the same change, so doing one makes the other "
                                 "unnecessary.",
                         "false": "They ask for different changes, or the same area with "
                                  "different goals."})],
    table=lambda i: {"yes": "likely-duplicate", "no": "distinct"}.get(i["same_ask"], ESCALATE),
    outcomes={"likely-duplicate": REVERSIBLE, "distinct": REVERSIBLE},
)

# `card-group`: which group of the board a card belongs to. It never picks an option.
register(
    "card-group",
    questions=[question("group", "choice", "Which group does the card belong to?", CARD_GROUPS)],
    table=_name_or_escalate("group"),
    outcomes={g: REVERSIBLE for g in CARD_GROUPS},
)


# ------------------------------------------------------------------ brain uses (WO-087)
# `brain-duplicate`: one page pair chosen by code (shared tags, title tokens, shared links).
# `merge-candidate` is a confirm outcome: pages are never merged on a model's word.
register(
    "brain-duplicate",
    questions=[question("same_claim", "noul",
                        "Page A and page B state the same claim about the same subject.",
                        {"true": "Both pages say the same thing, so one of them could replace the "
                                 "other without losing a fact.",
                         "false": "They state different claims, or cover different subjects or "
                                  "scopes."})],
    table=lambda i: {"yes": "merge-candidate", "no": "distinct"}.get(i["same_claim"], ESCALATE),
    outcomes={"merge-candidate": CONFIRM, "distinct": REVERSIBLE},
)


# ------------------------------------------------------------------ diagnostic scan uses (WO-088)
# `line-anomaly`: one log-line template (code reduced the log first). `line-family`: for a template
# judged abnormal or unsure, which anomaly family it falls in; the family names and one-line
# descriptions are PARSED from references/anomaly-families.md at run time (`set_line_families`),
# never typed here. Outcomes only ANNOTATE a reading order, so all are reversible.
NO_FAMILY = "no-family"
_FAMILIES_FILE = None            # set below; the default reference file, beside this script


def parse_families(path) -> dict:
    """{name: one-line description} from the numbered `## N. Title` headings of the reference file."""
    import re
    from pathlib import Path
    text = Path(path).read_text(encoding="utf-8")
    out: dict = {}
    parts = re.split(r"(?m)^## (\d+)\.\s+(.+?)\s*$", text)
    for k in range(1, len(parts) - 2, 3):
        title, body = parts[k + 1], parts[k + 2]
        short = re.sub(r"\([^)]*\)", "", title.lower()).replace("'", "")
        name = re.sub(r"[^a-z0-9]+", "-", short).strip("-")[:60].strip("-")
        bullet = re.search(r"(?m)^- (.+(?:\n  .+)*)", body)
        hint = " ".join(bullet.group(1).split())[:140] if bullet else ""
        out[name] = f"The line points at: {title.strip()}." + (f" For example: {hint}" if hint else "")
    return out


def set_line_families(criteria: dict) -> None:
    """(Re)register `line-family` over the given {name: description} families."""
    if not criteria:
        raise RegistryError("line-family needs at least one family")
    USES.pop("line-family", None)
    crit = dict(criteria)
    register(
        "line-family",
        questions=[
            question("family", "choice",
                     "Which anomaly family does the log line template point at?", crit),
            question("fits_a_family", "noul",
                     "The log line template fits one of the listed anomaly families.",
                     {"true": "The template shows evidence that one of the families describes.",
                      "false": "The template is a failure or oddity that none of the families "
                               "describes."}),
        ],
        table=lambda i: ESCALATE if "unsure" in i.values() else
        (i["family"] if i["fits_a_family"] == "yes" else NO_FAMILY),
        outcomes={**{f: REVERSIBLE for f in crit}, NO_FAMILY: REVERSIBLE},
    )


register(
    "line-anomaly",
    questions=[question("abnormal", "noul",
                        "The log line template is abnormal output for this system.",
                        {"true": "The template reports a failure, a skipped or inconsistent "
                                 "step, or something the recorded normal output does not "
                                 "describe.",
                         "false": "The template matches the normal output described in the "
                                  "state."})],
    table=lambda i: {"yes": "abnormal", "no": "normal"}.get(i["abnormal"], ESCALATE),
    outcomes={"abnormal": REVERSIBLE, "normal": REVERSIBLE},
)

try:
    from pathlib import Path as _P
    _FAMILIES_FILE = _P(__file__).resolve().parent.parent / "references" / "anomaly-families.md"
    set_line_families(parse_families(_FAMILIES_FILE))
except OSError:
    set_line_families({"other": "The template fits no family that could be read from the reference."})


# ------------------------------------------------------------------ loose-ends uses (WO-093)
# Candidates are chosen by code (`loose_ends.py candidates`); the model only confirms a pair. `join`
# and `bundle` are reversible: the orchestrator still writes the order (or the new one) itself.
register(
    "loose-end-join",
    questions=[question("joins", "noul",
                        "Item B is about the same part of the product as work order A, so whoever does or "
                        "plans order A should look at it.",
                        {"true": "B concerns the same feature, screen, data, component or rule that order A "
                                 "works on, even if order A does not mention it.",
                         "false": "B concerns a different feature or area; order A's work would not touch it."})],
    table=lambda i: {"yes": "join", "no": "separate"}.get(i["joins"], ESCALATE),
    outcomes={"join": REVERSIBLE, "separate": REVERSIBLE},
)

# `loose-end-pick`: the model's title pick for what words cannot find. The options are the open orders' titles,
# named by their WO id; `system_one.pick_orders` builds them per call, so the registry carries a sample (it is what
# `uses-check` sends). It only proposes candidates: `loose-end-join` still decides.
PICK_SAMPLE = {"WO-001": "Sample order about sorting a list.", "WO-002": "Sample order about a settings page.",
               "WO-003": "Sample order about uploading files."}
register(
    "loose-end-pick",
    questions=[question("order", "choice",
                        "Which of these work orders is about the same part of the product as this item?",
                        PICK_SAMPLE)],
    table=_name_or_escalate("order"),
    outcomes={n: REVERSIBLE for n in PICK_SAMPLE},
)

register(
    "loose-end-bundle",
    questions=[question("bundles", "noul",
                        "One work order could do item A and item B together, because they change "
                        "the same thing for related reasons.",
                        {"true": "Both items change the same file, rule or behaviour for connected "
                                 "reasons, so one order would be smaller than two.",
                         "false": "They change different things, or for unrelated reasons."})],
    table=lambda i: {"yes": "bundle", "no": "apart"}.get(i["bundles"], ESCALATE),
    outcomes={"bundle": REVERSIBLE, "apart": REVERSIBLE},
)


# ------------------------------------------------------------------ the lean drain (WO-098)
# `loose-end-state`: one item of `<home>/loose-ends.md`. Three nouls about the item text alone, read in order: an item that says it is done
# is `closable` (confirm) whatever the other two say; otherwise one that asks the owner is `ask-operator`;
# otherwise one that waits on a named event is `park`; all three no is `open`. `superseded` is not an outcome:
# an item another order covers is found by `loose-end-join` or `duplicate`, which see the other order.
def _loose_end_state_reads(i: dict) -> list:
    r = ["says_done"]
    if i["says_done"] == "no":
        r.append("needs_operator")
        if i["needs_operator"] == "no":
            r.append("waits_on_event")
    return r


def _loose_end_state(i: dict) -> str:
    if i["says_done"] == "yes":
        return "closable"
    if i["says_done"] != "no":
        return ESCALATE
    if i["needs_operator"] == "yes":
        return "ask-operator"
    if i["needs_operator"] != "no":
        return ESCALATE
    return {"yes": "park", "no": "open"}.get(i["waits_on_event"], ESCALATE)


register(
    "loose-end-state",
    questions=[
        question("says_done", "noul",
                 "The item says the work it describes is already complete.",
                 {"true": "It states that the change was made, merged, fixed or shipped.",
                  "false": "It describes work still to do, asks something, or says nothing about "
                           "completion."}),
        question("needs_operator", "noul",
                 "The item asks the owner a question or waits for the owner's decision.",
                 {"true": "It poses a question to the owner, or says nothing can go on until the owner "
                          "picks, approves or answers.",
                  "false": "It names work someone can start without asking the owner first."}),
        question("waits_on_event", "noul",
                 "The item can only start after a named event.",
                 {"true": "It names an event that must come first, such as a release, a tool being "
                          "installed, or another change landing.",
                  "false": "Nothing named has to happen before the work can start."}),
    ],
    table=_loose_end_state,
    outcomes={"closable": CONFIRM, "ask-operator": REVERSIBLE, "park": REVERSIBLE, "open": REVERSIBLE},
    reads=_loose_end_state_reads,
)
