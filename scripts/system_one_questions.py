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
    a combination with an `unsure` input must map to `escalate`.
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

REGISTRY_VERSION = 9

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


def register(name: str, questions: list, table, outcomes: dict) -> None:
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
        if "unsure" in combo and got != ESCALATE:
            raise RegistryError(f"use {name!r}: {inputs} has an unsure input and must map to "
                                f"`escalate`, not {got!r}")
    USES[name] = {"questions": list(questions), "table": table, "outcomes": outcomes}


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
def _any_unsure(i: dict) -> bool:
    return "unsure" in i.values()


def _note_route(i: dict) -> str:
    if _any_unsure(i) or i["deviation"] == "yes":
        return ESCALATE
    owed, durable, done = i["names_owed_work"], i["durable_fact"], i["already_done"]
    if owed == "yes":
        return ESCALATE if durable == "yes" else "follow-up"
    if durable == "yes":
        return "brain"
    if done == "yes":
        return "reject"
    return ESCALATE


# `note-route`: one line of an implementer note. A suggestion only; the orchestrator writes the
# Adjudication block. `reject` is a confirm outcome (a note is never dropped on a model's word).
register(
    "note-route",
    questions=[
        question("names_owed_work", "noul",
                 "The note says some work is still to be done by someone.",
                 {"true": "It names a task, fix, check or change that has not been done yet.",
                  "false": "It reports only what was done, what was found or how something works, "
                           "and names nothing left to do."}),
        question("durable_fact", "noul",
                 "The note states something that is now true about the system and that a person "
                 "starting later work would need to know.",
                 {"true": "A rule, behaviour, location, limit or convention, stated as a fact that "
                          "stays true after this order.",
                  "false": "It reports a step of this order's work, gives an opinion, or names a "
                           "task left to do."}),
        question("already_done", "noul",
                 "The note reports something that was completed within the work-order it belongs to.",
                 {"true": "A past-tense statement of a change made or a check run.",
                  "false": "It states a rule, a task still to do, or a question."}),
        question("deviation", "noul",
                 "The note reports that the work departed from what the work-order asked for.",
                 {"true": "It says something was done differently, skipped, added beyond the order, "
                          "or could not be done.",
                  "false": "It says the order was followed as written, or does not mention the "
                           "order's scope."}),
    ],
    table=_note_route,
    outcomes={"follow-up": REVERSIBLE, "brain": REVERSIBLE, "reject": CONFIRM},
)

# `note-trigger`: asked only for a note routed `follow-up`, to suggest a Parked row or the loose-ends
# list (WO-093: a follow-up with no trigger is drained with the rest, so it can join an open order).
register(
    "note-trigger",
    questions=[
        question("has_trigger", "noul",
                 "The note names an event that must happen before the follow-up work can start.",
                 {"true": "A named event, such as a release, a tool becoming available, a count "
                          "being reached or another change landing.",
                  "false": "The work can start whenever someone chooses; no event is named."}),
    ],
    table=lambda i: {"yes": "parked", "no": "loose-end"}.get(i["has_trigger"], ESCALATE),
    outcomes={"parked": REVERSIBLE, "loose-end": REVERSIBLE},
)

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


def _row_state(i: dict) -> str:
    if _any_unsure(i):
        return ESCALATE
    sc, risky = i["state_class"], i["money_or_safety"] == "yes"
    if sc == "info":
        return "note-only"
    if sc == "finished":
        clean = i["says_done"] == "yes" and i["several_items"] == "no" and not risky
        return "closable" if clean else "unsettled"
    if sc == "replaced":
        return "unsettled" if risky else "superseded"
    if i["says_done"] == "yes":
        return "unsettled"
    if sc == "open":
        return "needs-work" if i["next_step_named"] == "yes" else "unsettled"
    return {"active": "in-progress", "proof": "waiting-proof", "owner": "waiting-owner",
            "external": "waiting-external"}[sc]


# `row-state`: one row of a register. `closable` and `superseded` are confirm outcomes.
register(
    "row-state",
    questions=[
        question("state_class", "choice",
                 "Which state does the row describe?",
                 {"open": "Work remains and nobody is working on it now.",
                  "active": "Someone is working on it now.",
                  "proof": "It is built and waits for a test or a measurement.",
                  "owner": "It waits for a decision or an action from the owner or operator.",
                  "external": "It waits for something outside the project, such as a vendor, a "
                              "release or a service.",
                  "finished": "The row says the work is complete.",
                  "replaced": "The row says another item replaces it.",
                  "info": "It is a note or a fact with nothing to do."}),
        question("next_step_named", "noul",
                 "The row names the next concrete step.",
                 {"true": "A specific action someone can take next, such as a command to run, a "
                          "file to change or a person to ask.",
                  "false": "Only a topic or a problem is named, with no action."}),
        question("says_done", "noul",
                 "The row says the item is complete.",
                 {"true": "It states the item was completed, merged, fixed or shipped.",
                  "false": "It says nothing about completion, or says work remains."}),
        question("several_items", "noul",
                 "The row covers more than one separate piece of work.",
                 {"true": "It lists two or more tasks that could be done independently.",
                  "false": "It describes a single task."}),
        question("money_or_safety", "noul",
                 "The row concerns money, personal data, security or physical safety.",
                 {"true": "It mentions spending, payment, credentials, private data, a security "
                          "hole or a risk of harm.",
                  "false": "It concerns none of these."}),
        question("user_visible", "noul",
                 "The row concerns something a user of the product sees or does.",
                 {"true": "A screen, message, command output, setting or behaviour a user meets.",
                  "false": "Internal only, such as tooling, tests, notes or process."}),
        question("severe", "noul",
                 "The row says something is broken now or that work cannot continue.",
                 {"true": "A failure, a crash, a wrong result or a blocker is stated as current.",
                  "false": "Nothing is described as broken or blocked."}),
    ],
    table=_row_state,
    outcomes={"needs-work": REVERSIBLE, "in-progress": REVERSIBLE, "waiting-proof": REVERSIBLE,
              "waiting-owner": REVERSIBLE, "waiting-external": REVERSIBLE, "closable": CONFIRM,
              "superseded": CONFIRM, "note-only": REVERSIBLE, "unsettled": REVERSIBLE},
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


# ------------------------------------------------------------------ label-routed points (WO-085 rev 1)
# A point written under a *Follow-ups* or *Process notes* label needs fewer questions than a point
# with no label: the label already says what kind of point it is. Code decides the label rule
# (`system_one.py`); these two uses are the questions that remain.
def _followup_point(i: dict) -> str:
    if _any_unsure(i):
        return ESCALATE
    if i["already_done"] == "yes":
        return "reject"
    return "parked" if i["has_trigger"] == "yes" else "loose-end"


register(
    "followup-point",
    questions=[
        question("already_done", "noul",
                 "The note reports something that was completed within the work-order it belongs to.",
                 {"true": "A past-tense statement of a change made or a check run.",
                  "false": "It states a rule, a task still to do, or a question."}),
        question("has_trigger", "noul",
                 "The note names an event that must happen before the follow-up work can start.",
                 {"true": "A named event, such as a release, a tool becoming available, a count "
                          "being reached or another change landing.",
                  "false": "The work can start whenever someone chooses; no event is named."}),
    ],
    table=_followup_point,
    outcomes={"parked": REVERSIBLE, "loose-end": REVERSIBLE, "reject": CONFIRM},
)

register(
    "process-point",
    questions=[
        question("names_owed_work", "noul",
                 "The note says some work is still to be done by someone.",
                 {"true": "It names a task, fix, check or change that has not been done yet.",
                  "false": "It reports only what was done, what was found or how something works, "
                           "and names nothing left to do."}),
    ],
    table=lambda i: {"yes": "follow-up", "no": "reject"}.get(i["names_owed_work"], ESCALATE),
    outcomes={"follow-up": REVERSIBLE, "reject": CONFIRM},
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


# ------------------------------------------------------------------ brain and lens uses (WO-087)
# `lens-match`: one (work, lens) pair. The lens's domain and when-to-apply sit in the STATE (the
# registry's wording is static). `escalate` (an unsure answer) displays as "maybe": never dropped.
register(
    "lens-match",
    questions=[question("applies", "noul",
                        "The lens described in the state applies to the work described in the state.",
                        {"true": "The work falls in the lens's domain and meets its when-to-apply "
                                 "condition.",
                         "false": "The work is about something else than the lens's domain, or its "
                                  "when-to-apply condition is not met."})],
    table=lambda i: {"yes": "applies", "no": "no"}.get(i["applies"], ESCALATE),
    outcomes={"applies": REVERSIBLE, "no": REVERSIBLE},
)

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

# `brain-fits`, then `brain-target`: where a new fact belongs. Split in two so an unsure page choice
# never hides a clear "no page fits". Candidates are chosen by code (at most BRAIN_SLOTS) and listed
# in the state as "Candidate 1".."Candidate 8"; the choice names a slot, code maps it to the page.
BRAIN_SLOTS = 8
register(
    "brain-fits",
    questions=[question("fits_an_existing_page", "noul",
                        "The new fact belongs on one of the candidate pages listed in the state.",
                        {"true": "A candidate page already covers the subject the fact is about.",
                         "false": "No candidate page covers that subject; the fact needs a page of "
                                  "its own."})],
    table=lambda i: {"yes": "fits", "no": "new-page"}.get(i["fits_an_existing_page"], ESCALATE),
    outcomes={"fits": REVERSIBLE, "new-page": REVERSIBLE},
)

register(
    "brain-target",
    questions=[question("page", "choice", "Which candidate page does the new fact belong on?",
                        {f"candidate-{n}": f"The fact is about the subject of Candidate {n}."
                         for n in range(1, BRAIN_SLOTS + 1)})],
    table=_name_or_escalate("page"),
    outcomes={f"candidate-{n}": REVERSIBLE for n in range(1, BRAIN_SLOTS + 1)},
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


# ------------------------------------------------------------------ scope and complexity uses (WO-089)
# `hunk-scope`: one hunk of an in-scope file against the work-order's scope text. `fits` is not a
# verdict: the digest still says every hunk has to be read. `escalate` displays as `unsure`.
register(
    "hunk-scope",
    questions=[question("serves_scope", "noul",
                        "The change in the hunk is part of what the scope text asks for.",
                        {"true": "The hunk edits what the scope text names, in the way it describes.",
                         "false": "The hunk changes something the scope text does not ask for, or "
                                  "changes it in a way the text does not describe."})],
    table=lambda i: {"yes": "fits", "no": "look"}.get(i["serves_scope"], ESCALATE),
    outcomes={"fits": REVERSIBLE, "look": REVERSIBLE},
)

# `wo-complexity-level`, `wo-touches-shared-tooling`, `wo-needs-design-choice`: three one-question
# uses (as WO-086 did for screening) so a settled level prints even when a noul is unsure. One input
# to the orchestrator's reading; it never picks a model or an effort.
COMPLEXITY_LEVELS = {
    "level-1": "One file is edited and the edit is mechanical: a rename, a wording change, a constant.",
    "level-2": "Several files are edited, or one design choice has to be made inside one module.",
    "level-3": "The change crosses modules, adds a new mechanism, or touches safety-relevant code.",
}
register(
    "wo-complexity-level",
    questions=[question("level", "choice", "Which situation does the work-order describe?",
                        COMPLEXITY_LEVELS)],
    table=_name_or_escalate("level"),
    outcomes={n: REVERSIBLE for n in COMPLEXITY_LEVELS},
)
register(
    "wo-touches-shared-tooling",
    questions=[question("touches_shared_tooling", "noul",
                        "The work-order edits a script or a test harness that other work-orders also edit.",
                        {"true": "Its scope names a shared script, a shared test file or a shared "
                                 "reference text.",
                         "false": "Its scope names only files of its own."})],
    table=lambda i: {"yes": "yes", "no": "no"}.get(i["touches_shared_tooling"], ESCALATE),
    outcomes={"yes": REVERSIBLE, "no": REVERSIBLE},
)
register(
    "wo-needs-design-choice",
    questions=[question("needs_design_choice", "noul",
                        "The work-order leaves a design decision to the implementer.",
                        {"true": "The scope text offers options or describes a goal without the exact edit.",
                         "false": "The scope text states the exact edit."})],
    table=lambda i: {"yes": "yes", "no": "no"}.get(i["needs_design_choice"], ESCALATE),
    outcomes={"yes": REVERSIBLE, "no": REVERSIBLE},
)


# ------------------------------------------------------------------ loose-ends uses (WO-093)
# Candidates are chosen by code (`loose_ends.py candidates`); the model only confirms a pair. `join`
# and `bundle` are reversible: the orchestrator still writes the order (or the new one) itself.
register(
    "loose-end-join",
    questions=[question("joins", "noul",
                        "Doing work-order A as scoped would also need, or naturally include, item B.",
                        {"true": "Item B is part of what order A changes, or order A cannot be done "
                                 "properly without it.",
                         "false": "Item B is a separate matter that order A does not need or include."})],
    table=lambda i: {"yes": "join", "no": "separate"}.get(i["joins"], ESCALATE),
    outcomes={"join": REVERSIBLE, "separate": REVERSIBLE},
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
