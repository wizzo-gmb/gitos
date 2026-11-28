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

  * `questions`: a list of `question(...)` dicts. `type` is `noul` (a yes/no) or `choice`
    (`criteria` maps each choice name to when it applies).
  * `table(inputs)`: a pure function from the answers `{question_id: value}` to an outcome
    name. A noul answer is `"yes"`, `"no"` or `"unsure"`. A choice answer is the chosen name or
    `"unsure"`. An answer that is missing or not one of those words counts as `"unsure"`.
  * `outcomes`: every outcome the table can return, flagged `REVERSIBLE` (a script may apply it)
    or `CONFIRM` (it is only ever REPORTED; a person or the reasoning model confirms it by reading
    the item). `escalate` is reserved: always reversible, meaning "hand it to the reasoning model".
  * EVERY combination of inputs is enumerated at load time (including `unsure`). A combination the
    table raises on, or maps to an unlisted outcome, is a load-time error (`RegistryError`), and
    a combination with an `unsure` input the decision reads must map to `escalate` (`reads(inputs)`
    names the answers a decision uses; the default is all of them, `loose-end-state` narrows it).
  * Bump `REGISTRY_VERSION` when a question's wording or a table changes: the export records it,
    so an answers file is comparable only to the registry version it was exported under.

WORDING RULES (the vendor's, kept here because they are the part that rots):
  * ONE judgment per question. Two ideas in one question is two questions.
  * Concrete and observable: say what is on the page, not what the author meant.
  * A true (yes) answer means yes: phrase every noul as a statement that is true or false.
  * No case-specific clauses. An unsure answer is fixed with better state or a smaller question,
    never with wording tuned to the one item that went wrong.
"""

from __future__ import annotations

import itertools

REGISTRY_VERSION = 16

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
    only an unsure answer among them must map to `escalate`."""
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
# ------------------------------------------------------------------ loose-ends uses (WO-093)
# Candidates are chosen by code (`loose_ends.py candidates`); the helper only confirms a pair. `join`
# and `bundle` are reversible: the orchestrator still writes the order (or the new one) itself.
register(
    "loose-end-join",
    questions=[question("joins", "noul",
                        "Item B is about the same part of the product as work-order A, so whoever does or "
                        "plans order A should look at it.",
                        {"true": "B concerns the same feature, screen, data, component or rule that order A "
                                 "works on, even if order A does not mention it.",
                         "false": "B concerns a different feature or area; order A's work would not touch it."})],
    table=lambda i: {"yes": "join", "no": "separate"}.get(i["joins"], ESCALATE),
    outcomes={"join": REVERSIBLE, "separate": REVERSIBLE},
)

register(
    "loose-end-bundle",
    questions=[question("bundles", "noul",
                        "One work-order could do item A and item B together, because they change "
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
# an item another order covers is found by `loose-end-join`, which sees the other order.
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
