"""Repo-local model routing support; no inference, agent runner, or settings discovery.

See references/model-optimization.md. Configured ranks express operator policy,
not provider capability claims. Runtime evidence is supplied by the active harness.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

TIERS = ("light", "standard", "deep")
HARNESSES = ("codex", "claude")
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")
FILENAME = "model-optimization.json"
SESSION_FILENAME = "model-optimization-session.json"


class Invalid(ValueError):
    """Invalid input; no write or routing is permitted."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def strings(value):
    return isinstance(value, list) and all(isinstance(x, str) and x for x in value)


def read_json(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    except (OSError, ValueError) as exc:
        raise Invalid(f"Cannot read JSON {path}: {exc}") from exc


def home_path(root, requested="auto"):
    root = Path(root).resolve()
    require(root.is_dir(), "Repo root must be an existing directory")
    if requested != "auto":
        return root / requested
    return next((root / p for p in HOMES if (root / p).is_dir()), root / ".gitos")


def empty_config():
    return {"schema_version": 1, "enabled": False, "preference": "unasked", "harnesses": {}}


def validate_catalog(catalog):
    require(isinstance(catalog, dict), "catalog must be an object")
    require(isinstance(catalog.get("source"), str) and catalog["source"], "catalog.source required")
    models = catalog.get("models")
    require(isinstance(models, dict) and models, "catalog.models must be nonempty")
    for model, spec in models.items():
        require(isinstance(model, str) and model and isinstance(spec, dict), "Invalid catalog model")
        require(strings(spec.get("efforts")) and spec["efforts"], f"{model}: efforts required")
        require(strings(spec.get("capabilities")), f"{model}: capabilities must be a list")
    return catalog


def codex_catalog(payload):
    """Normalize complete model/list response page(s); never interpret as entitlement."""
    pages = payload if isinstance(payload, list) else [payload]
    require(bool(pages), "No catalog pages")
    models = {}
    for i, page in enumerate(pages):
        require(isinstance(page, dict), "Invalid catalog page")
        result = page.get("result", page)
        require(isinstance(result, dict) and isinstance(result.get("data"), list), "Expected model/list data")
        require(not result.get("nextCursor") or i < len(pages) - 1,
                "Incomplete catalog: fetch nextCursor before importing")
        for item in result["data"]:
            require(isinstance(item, dict), "Invalid model/list entry")
            if item.get("hidden") is True:
                continue
            model = item.get("model") or item.get("id")
            require(isinstance(model, str) and model, "Invalid catalog model ID")
            efforts = item.get("supportedReasoningEfforts", [])
            require(isinstance(efforts, list), "Invalid supportedReasoningEfforts")
            require(all(isinstance(e, dict) and isinstance(e.get("reasoningEffort"), str)
                        for e in efforts), "Invalid reasoning effort entry")
            # 'default' means omit the effort override, not an inferred effort level.
            spec = {"efforts": [e["reasoningEffort"] for e in efforts] or ["default"],
                    "capabilities": item.get("inputModalities", [])}
            require(model not in models or models[model] == spec, "Conflicting catalog model entries")
            models[model] = spec
    return validate_catalog({"source": "codex model/list; advertised, entitlement unverified", "models": models})


def validate_mapping(mapping):
    require(isinstance(mapping, dict), "Harness mapping must be an object")
    validate_catalog(mapping.get("catalog"))
    choices = mapping.get("choices")
    require(isinstance(choices, dict) and choices, "choices must be nonempty")
    pairs = {}
    for name, choice in choices.items():
        require(isinstance(name, str) and name and isinstance(choice, dict), "Invalid choice")
        model, effort, rank = choice.get("model"), choice.get("effort"), choice.get("rank")
        require(isinstance(model, str) and isinstance(effort, str), f"{name}: model and effort required")
        require(type(rank) is int and rank >= 0, f"{name}: rank must be a nonnegative integer")
        spec = mapping["catalog"]["models"].get(model)
        require(spec is not None, f"{name}: model absent from catalog; refresh discovery")
        require(effort in spec["efforts"], f"{name}: unsupported effort {effort}")
        pair = (model, effort)
        require(pair not in pairs or pairs[pair] == rank, "Same model/effort has contradictory ranks")
        pairs[pair] = rank
    ceiling = mapping.get("ceiling")
    require(isinstance(ceiling, str) and ceiling in choices, "ceiling must name a choice")
    tiers = mapping.get("tiers")
    require(isinstance(tiers, dict) and set(tiers) == set(TIERS), "tiers must contain light, standard, deep")
    for tier, name in tiers.items():
        require(isinstance(name, str) and name in choices, f"{tier}: unknown choice")
        require(choices[name]["rank"] <= choices[ceiling]["rank"], f"{tier}: choice exceeds ceiling")
    ranks = [choices[tiers[t]]["rank"] for t in TIERS]
    require(ranks == sorted(ranks), "Tier ranks must be nondecreasing; equal ranks are allowed")
    return mapping


def validate_config(config):
    require(isinstance(config, dict), "Configuration must be an object")
    require(type(config.get("schema_version")) is int and config["schema_version"] == 1,
            "Unsupported schema_version")
    require(type(config.get("enabled")) is bool, "enabled must be a JSON boolean")
    require(config.get("preference") in ("unasked", "enabled", "disabled", "skipped"), "Invalid preference")
    require(config["enabled"] == (config["preference"] == "enabled"), "enabled and preference disagree")
    require(isinstance(config.get("harnesses"), dict), "harnesses must be an object")
    for name, mapping in config["harnesses"].items():
        require(name in HARNESSES, f"Unsupported harness: {name}")
        validate_mapping(mapping)
    return config


def load_config(home):
    path = home / FILENAME
    return validate_config(read_json(path)) if path.exists() else empty_config()


def save_config(home, config):
    validate_config(config)
    save_json(home, FILENAME, config)


def save_json(home, filename, value):
    # Explicit configuration requires an existing pipeline; never scaffold by accident.
    require(home.is_dir(), "Pipeline home missing; initialize GitOs first")
    write_json_atomic(home / filename, value)


def write_json_atomic(path, value):
    """Replace `path` with `value` as JSON, atomically, and only when the bytes would change.

    Separated from `save_json` because the hook registration below writes a file OUTSIDE the
    pipeline home, and an operator's settings file deserves the same no-partial-write
    guarantee as the engine's own state. -> True when bytes changed.
    """
    path = Path(path)
    data = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8-sig") == data:
        return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=f".{path.name}-",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return True


# --------------------------------------------------------------------------- .gitignore
# The enable-time half of the per-session guarantee. `scaffold.py` lays the line for a repo
# scaffolded from this version on; a repo scaffolded earlier has none, so enabling optimization
# ensures it. This mirrors the per-checkout seam in `scripts/federation.py` (`ignore_pattern` /
# `ensure_gitignore`) deliberately and line for line: same status vocabulary, same append-only
# idempotence, same one-path precision, same named skip. It is a local sibling rather than a
# shared helper because that helper hard-codes its own filename and header, so reuse would mean
# reshaping federation — out of scope here. The pair is held in step by the selftest gate
# `optimization session baseline untracked`, which drives BOTH writers over the same fixtures
# and refuses any divergence in status, idempotence or precision.
def ignore_pattern(root, home):
    """The one `.gitignore` line that ignores this repo's session record, or None when the home
    is not inside the repo root (nothing to write in that case)."""
    try:
        parts = Path(home).resolve().relative_to(Path(root).resolve()).parts
    except ValueError:
        return None
    if not parts:
        return None
    return "/".join((*parts, SESSION_FILENAME))


def ensure_gitignore(root, home):
    """Make sure `<root>/.gitignore` ignores exactly `<home>/model-optimization-session.json`.

    The baseline is per session, so the transient record must not travel in git - and a repo
    with optimization on must not show a permanently untracked file either. Exactly ONE path is
    ignored: the pipeline home itself stays tracked, because the ledger and the brain are the
    repo's audit trail. Append-only and idempotent; it never removes or rewrites an existing
    line.

    -> (status, pattern) with status in {'present', 'appended', 'created', 'skipped'}.
    """
    pattern = ignore_pattern(root, home)
    if pattern is None:
        return "skipped", None
    gitignore = Path(root) / ".gitignore"
    header = ("# The optimization baseline is PER SESSION: this one transient file is ignored "
              "so a clone\n"
              "# arrives with no baseline to dispatch against. Everything else in the pipeline "
              "home stays TRACKED.\n")
    if not gitignore.exists():
        gitignore.write_text(header + pattern + "\n", encoding="utf-8")
        return "created", pattern
    text = gitignore.read_text(encoding="utf-8")
    existing = {ln.strip().lstrip("/") for ln in text.splitlines()}
    if pattern in existing:
        return "present", pattern
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    with gitignore.open("a", encoding="utf-8") as fh:
        fh.write(sep + header + pattern + "\n")
    return "appended", pattern


def report_gitignore(root, status, pattern):
    """Name the enable-time ignore outcome on stderr; stdout stays the machine-readable record.

    A skip is reported with the pattern to lay by hand, so an unignorable home is visible
    rather than silent.
    """
    if status == "skipped":
        print(f"model optimization: .gitignore skipped - the home is not inside the repo root; "
              f"ignore '{SESSION_FILENAME}' by hand so the baseline stays per session",
              file=sys.stderr)
        return
    print(f"model optimization: .gitignore {status} '{pattern}' in {Path(root) / '.gitignore'} "
          f"(the baseline is per session, so the record stays out of commits)", file=sys.stderr)


# The levels the client documents for `effort.level` and `$CLAUDE_EFFORT`. Anything else is absent.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# `harness-env` is evidence the ENGINE read from `$CLAUDE_EFFORT` itself: distinct from the
# operator's report and from a hook payload, and valid for effort only (there is no CLAUDE_MODEL).
ENV_SOURCE = "harness-env"


def harness_env_effort(environ=None):
    """The session effort the client exports as `$CLAUDE_EFFORT`, or None.

    Documented levels only. An unset, empty, unknown or garbled value is ABSENT, never a guess,
    and the variable is re-read on every call, so an `/effort` change shows at the next check
    rather than instantly.
    """
    value = (os.environ if environ is None else environ).get("CLAUDE_EFFORT")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in EFFORT_LEVELS else None


def observation(model=None, effort=None, model_source=None, effort_source=None):
    result = {}
    for key, value, source in (("model", model, model_source), ("effort", effort, effort_source)):
        require(value is None or isinstance(value, str) and bool(value.strip()), f"Invalid observed {key}")
        require(value is None or value.strip().lower() != "unknown", f"Omit unknown {key}; do not supply a sentinel")
        allowed = ("harness", "operator") + ((ENV_SOURCE,) if key == "effort" else ())
        require((value is None and source is None) or
                (value is not None and source in allowed),
                f"Known {key} requires harness/operator source; unknown requires no source")
        result[key] = {"value": value, "source": source}
    return result


def validate_observation(value):
    require(isinstance(value, dict) and set(value) == {"model", "effort"}, "Invalid observation")
    for component in value.values():
        require(isinstance(component, dict) and set(component) == {"value", "source"},
                "Invalid observation component")
    observation(value["model"]["value"], value["effort"]["value"],
                value["model"]["source"], value["effort"]["source"])


SESSION_REQUIRED = frozenset({"schema_version", "session_id", "harness", "initial", "current"})
# Written only by the currency mechanism below, and absent from a record that never needed it:
# `stale` names the components an announced operator change invalidated and why; the digests
# say whether a later announcement about the same file actually moved anything.
SESSION_OPTIONAL = frozenset({"stale", "config_fingerprints"})


def validate_session(state):
    require(isinstance(state, dict) and SESSION_REQUIRED <= set(state) <=
            SESSION_REQUIRED | SESSION_OPTIONAL, "Invalid session state")
    require(type(state["schema_version"]) is int and state["schema_version"] == 1,
            "Unsupported session schema_version")
    require(isinstance(state["session_id"], str) and bool(state["session_id"].strip()),
            "Session identity required")
    require(state["harness"] in HARNESSES, "Invalid session harness")
    validate_observation(state["initial"])
    validate_observation(state["current"])
    stale = state.get("stale")
    if stale is not None:
        require(isinstance(stale, dict) and bool(stale) and set(stale) <= {"model", "effort"},
                "stale must name model and/or effort")
        for component, reason in stale.items():
            require(isinstance(reason, str) and bool(reason.strip()),
                    f"{component}: an invalidation must say why")
            # THE INVARIANT THAT MAKES THIS SAFE BY CONSTRUCTION: a component the engine can no
            # longer vouch for must not still be holding the value it can no longer vouch for.
            require(state["current"][component]["value"] is None,
                    f"{component}: an invalidated component must be explicit unknown, "
                    f"never a held value")
    fingerprints = state.get("config_fingerprints")
    if fingerprints is not None:
        require(isinstance(fingerprints, dict), "config_fingerprints must be an object")
        for path, digests in fingerprints.items():
            require(isinstance(path, str) and bool(path.strip()), "Invalid fingerprint path")
            require(isinstance(digests, dict) and set(digests) <= {"model", "effort"} and
                    all(isinstance(v, str) and bool(v.strip()) for v in digests.values()),
                    "Invalid routing fingerprint")
    return state


def load_session(home):
    path = home / SESSION_FILENAME
    return validate_session(read_json(path)) if path.exists() else None


# --------------------------------------------------------------------------- currency
# WHY THIS SECTION EXISTS. The baseline is a record of an OBSERVED model/effort pair. It was
# true when it was written and nothing made it expire. An operator who changes model or effort
# mid-session has no reason to think the engine cares, so the record keeps serving a pair that
# no longer exists and `select` signs off a route derived from it - a GREEN answer rather than
# no answer, on the approving path.
#
# WHAT THIS SECTION DELIBERATELY DOES NOT DO: it never produces the new pair by inferring from
# behaviour, by scanning session histories, or by promoting a saved setting to evidence of the
# active pair. Those prohibitions (references/model-optimization.md, *Observation limits*) are
# load-bearing, and a refresh that writes a WRONG pair is worse than the staleness it replaces.
#
# SO THE MECHANISM IS INVALIDATION. On an observed change the affected component drops to
# explicit unknown and `select` refuses until it is re-established from evidence. That reuses
# the refusal this module already has instead of adding a second gate: keeping up means knowing
# when you no longer know, not producing a value you cannot vouch for.
#
# ONE VALUE IS AN EXCEPTION, and it is not an exception to that rule: a value the CLIENT HANDS
# a hook is harness evidence, the same class as any other active-session metadata the policy
# already admits. An announced change is evidence that something moved; an unannounced one
# leaves the baseline unknown.
#
# PRECISION IS AS LOAD-BEARING AS DETECTION. Invalidating on every settings change would ask
# the operator to re-report after an unrelated edit, and an alarm that cries wolf gets
# silenced. The announcement names WHICH FILE moved, so the decision narrows to files that
# could carry the routing pair, and then to the part of such a file that could move each
# component. Reading that file to decide WHETHER to invalidate is not the banned shortcut: the
# ban is on treating a saved setting as evidence of the active pair, and an invalidation makes
# no claim about any value.
# Only these filenames can carry a routing pin, whatever scope announced them.
ROUTING_SETTINGS_FILENAMES = ("settings.json", "settings.local.json")
# Settings keys that could move a component's value, split by the component each one reaches.
# A per-model effort map reaches BOTH: it is keyed by model id and holds that model's own pin.
ROUTING_KEYS = {
    "model": ("model",),
    "effort": ("effort", "effortLevel", "reasoningEffort", "thinking", "alwaysThinkingEnabled"),
}
ROUTING_KEYS_SHARED = ("modelSettings",)


def routing_subset(settings, component):
    """The part of a settings document that could move `component`, or None if not an object.

    Environment entries are included by NAME pattern rather than from an exhaustive list: an
    unlisted variable that pins a model or an effort should still count as something that
    moved. Over-inclusion here costs one extra invalidation; under-inclusion costs a missed
    change, which is the failure this whole section exists to end.
    """
    if not isinstance(settings, dict):
        return None
    subset = {key: settings[key]
              for key in (*ROUTING_KEYS[component], *ROUTING_KEYS_SHARED) if key in settings}
    env = settings.get("env")
    if isinstance(env, dict):
        picked = {k: v for k, v in env.items()
                  if isinstance(k, str) and ("MODEL" in k.upper() or "EFFORT" in k.upper())}
        if picked:
            subset["env"] = picked
    return subset


def routing_fingerprints(path):
    """Per-component digests of the routing-relevant part of a settings file.

    A DIGEST, NOT A VALUE - and that is the line this draws against the policy's ban. A hash
    can answer "did this move?" and is incapable of answering "to what?", so nothing here can
    promote a saved setting to evidence of the active pair even by accident. Nothing in this
    module reads a fingerprint for anything but equality.

    -> {'model': <hex>, 'effort': <hex>}, or None when the file cannot be read as an object,
    which means "cannot rule a change out" rather than "unchanged".
    """
    try:
        settings = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    return routing_digests(settings)


def routing_digests(settings):
    """Per-component digests of a settings document already parsed; None if not an object."""
    if not isinstance(settings, dict):
        return None
    digests = {}
    for component in ("model", "effort"):
        blob = json.dumps(routing_subset(settings, component), sort_keys=True, ensure_ascii=False)
        digests[component] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return digests


def settings_may_carry_routing(file_path):
    """Whether an announced file could hold a routing pin at all. The precision lever: an edit
    to anything else is not a reason to ask the operator to re-report."""
    if not isinstance(file_path, str) or not file_path.strip():
        return False
    return Path(file_path).name.lower() in ROUTING_SETTINGS_FILENAMES


def fingerprint_key(path):
    """One spelling per settings file, so an announced path and a seeded path meet. Absolute
    and case-normalized, never symlink-resolved: the client names the file it watched."""
    return os.path.normcase(os.path.abspath(str(path)))


def user_settings_dir():
    """The operator's own settings directory: the client's config-dir override, else home."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured and configured.strip():
        return Path(configured)
    return Path.home() / ".claude"


def baseline_settings_paths(root):
    """Every settings file that can carry a route for a session in `root`: user, project, local."""
    root = Path(root)
    return (user_settings_dir() / "settings.json",
            root / ".claude" / "settings.json",
            root / ".claude" / "settings.local.json")


def seed_fingerprints(session, root):
    """Record the routing digests of every route-carrying settings file at baseline time.

    WHY. Without a digest taken when the baseline was established, the first announced edit to
    each file has nothing to be compared against and has to invalidate whatever moved - so an
    edit that only touched permissions, hooks or skill toggles cost the operator a re-report.
    With one, the first edit is judged like every later one: on what actually moved.

    Three cases, each chosen so a miss is impossible rather than merely unlikely:
      * ABSENT now - recorded as a document with no routing keys. A file created later with
        none is then not a change; one created WITH routing keys is.
      * UNREADABLE now - recorded as nothing, so the first announcement about it still
        invalidates. A baseline cannot vouch for a file it could not read.
      * READABLE - its digests, overwriting any earlier ones: the baseline is being
        (re-)established now, so now is the reference.
    Digests only, as everywhere in this section: nothing here can say what a value is.
    """
    updated = copy.deepcopy(session)
    prints = dict(updated.get("config_fingerprints") or {})
    for path in baseline_settings_paths(root):
        key = fingerprint_key(path)
        digests = routing_digests({}) if not path.exists() else routing_fingerprints(path)
        if digests is None:
            prints.pop(key, None)
        else:
            prints[key] = digests
    updated["config_fingerprints"] = prints
    return validate_session(updated)


def has_no_effort_levels(spec):
    """Whether a catalog entry records a model with no effort levels at all.

    `default` alone is how a catalog says it: discovery fills `["default"]` for a model that
    lists no efforts. Per the client's model configuration page, models outside its effort
    table "do not support effort", so for such a model there is no effort to choose, control
    or evidence - and a route that names none is complete, not half-routed. A catalog that
    lists `default` BESIDE named levels is a different case: there an effort exists and
    leaving it at default still needs native evidence.
    """
    return isinstance(spec, dict) and spec.get("efforts") == ["default"]


def announced_session_effort(payload):
    """The SESSION's own effort as the client hands it to a hook, or None.

    Measured, not assumed: on a dispatch announcement the session's effort sits at the TOP
    LEVEL as an object with a `level` field, while the effort the caller REQUESTED for that
    dispatch sits inside the tool input as a bare string. The two were separated by driving a
    dispatch whose requested effort differed from the session's - the top-level field did not
    follow the request, so it is not the request.

    Read defensively on purpose. ONE shape was observed, from one client version. An absent
    key, a null, a bare string, a different inner key or an empty level are all AMBIGUOUS, and
    the rule applies to the good path too: ambiguous means invalidate, never guess. So anything
    but the one accepted shape returns None and the component stays unknown.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get("effort")
    if not isinstance(value, dict):
        return None
    level = value.get("level")
    if not isinstance(level, str) or not level.strip() or level.strip().lower() == "unknown":
        return None
    return level.strip()


def invalidate(session, components, reason):
    """Drop the named components to explicit unknown and record why. Never writes a value."""
    require(bool(components), "Invalidation must name at least one component")
    updated = copy.deepcopy(session)
    stale = dict(updated.get("stale") or {})
    for component in components:
        require(component in ("model", "effort"), f"Unknown component: {component}")
        updated["current"][component] = {"value": None, "source": None}
        stale[component] = reason
    updated["stale"] = stale
    return validate_session(updated)


def reestablish(session, model=None, effort=None, model_source=None, effort_source=None):
    """Record a freshly evidenced value for the components supplied and clear their staleness.

    Components not supplied are left exactly as they are: re-establishing effort from harness
    evidence must not quietly bless a model that nothing has re-observed. `initial` is never
    touched - the baseline keeps meaning first observation, and this is a current one.
    """
    require(model is not None or effort is not None, "Name at least one component to re-establish")
    observed = observation(model, effort, model_source, effort_source)
    updated = copy.deepcopy(session)
    stale = dict(updated.get("stale") or {})
    for component, supplied in (("model", model), ("effort", effort)):
        if supplied is None:
            continue
        updated["current"][component] = observed[component]
        stale.pop(component, None)
    if stale:
        updated["stale"] = stale
    else:
        updated.pop("stale", None)
    return validate_session(updated)


def apply_event(home, payload):
    """Decide what one announced client event means for this home's baseline.

    -> (action, detail) with action in {'invalidated', 're-verified', 'ignored', 'no-baseline'}.
    """
    if not isinstance(payload, dict):
        return "ignored", "the announcement is not an object"
    event = payload.get("hook_event_name")
    session = load_session(home)
    if session is None:
        return "no-baseline", "no session baseline in this home; nothing to keep current"

    if event == "PreToolUse":
        # The CLOSING half: a client that hands over the session's own effort re-verifies that
        # component with no operator question at all. It only ever CLEARS staleness, so it is
        # not a second source of truth competing with the operator's report.
        level, source = announced_session_effort(payload), "harness"
        if level is None and "effort" not in payload:
            # No effort key at all: the hook process's own `$CLAUDE_EFFORT` is the same level.
            # A key that IS present but malformed stays ambiguous, so it is never overruled here.
            level, source = harness_env_effort(), ENV_SOURCE
        if level is None:
            return "ignored", "no session effort in the one accepted shape; the component stands"
        if not (session.get("stale") or {}).get("effort"):
            return "ignored", f"effort is not stale; the client reports {level}"
        save_json(home, SESSION_FILENAME,
                  reestablish(session, effort=level, effort_source=source))
        return "re-verified", f"effort={level}, from {source} evidence the client supplied"

    if event == "PostModelSwitch":
        # Switching model can also change the effort the lead runs at, because an effort pin is
        # held PER MODEL ID - so both components go unknown, not only the one that was named.
        save_json(home, SESSION_FILENAME,
                  invalidate(session, ("model", "effort"),
                             "the operator switched model; the active id and its own effort pin "
                             "are both unobserved"))
        return "invalidated", "model, effort"

    if event == "ConfigChange":
        file_path = payload.get("file_path")
        if not settings_may_carry_routing(file_path):
            return "ignored", f"{file_path!r} cannot carry a routing pin"
        digests = routing_fingerprints(file_path)
        key = fingerprint_key(file_path)
        known = session.get("config_fingerprints") or {}
        # A record written before keys were normalized holds the announced spelling.
        previous = known.get(key, known.get(str(file_path)))
        if digests is None:
            # Unreadable: a change was announced and cannot be ruled out. Refuse to guess.
            moved = ("model", "effort")
        elif not isinstance(previous, dict):
            # No digest for this file: it was not one the baseline seeds (user, project and
            # local settings are seeded when the baseline is established - see
            # `seed_fingerprints`), or it was unreadable then. Nothing rules the change out,
            # so this costs one invalidation; every later edit is judged on what moved.
            moved = ("model", "effort")
        else:
            moved = tuple(c for c in ("model", "effort") if previous.get(c) != digests.get(c))
        updated = copy.deepcopy(session)
        if digests is not None:
            prints = dict(updated.get("config_fingerprints") or {})
            prints.pop(str(file_path), None)
            prints[key] = digests
            updated["config_fingerprints"] = prints
        name = Path(str(file_path)).name
        if not moved:
            save_json(home, SESSION_FILENAME, validate_session(updated))
            return "ignored", f"the routing-relevant part of {name} did not move"
        scope = payload.get("source")
        reason = (f"{scope if isinstance(scope, str) and scope else 'an unnamed'}-scope {name} "
                  f"changed; the engine cannot read the active pair out of a saved file")
        save_json(home, SESSION_FILENAME, invalidate(updated, moved, reason))
        return "invalidated", ", ".join(moved)

    return "ignored", f"unhandled event {event!r}"


# --------------------------------------------------------------------------- hook registration
# The delivery seam, laid by `scripts/scaffold.py` for a repo scaffolded from this version on
# and back-filled by `enable` for one that predates it - the same two-writer shape as the
# `.gitignore` seam above, and the same status vocabulary.
#
# The command is a SELF-LOCATING bootstrap rather than a path resolved at write time, because
# the file it lands in is COMMITTED: an absolute path would be one machine's truth travelling
# to every clone. It resolves the installed engine from the operator's own home, needs no
# shell, and so one committed string behaves the same on every platform and in every checkout.
#
# IT IS FAIL-OPEN BY CONSTRUCTION, and that is the whole reason for its shape. This string
# outlives the engine version that wrote it: it is committed into repos, and the installed
# engine beside it can be older, newer, or absent. On the tool-call event a nonzero exit is a
# REFUSAL of the operator's tool call, so a bootstrap that let an unrecognized argument, an
# absent install or any other failure escape would start blocking tool calls in every
# scaffolded repo the moment the two versions differed. So it calls the entry point DIRECTLY
# rather than through the argument parser - an engine that has no such entry point raises and
# is swallowed, instead of a parser exiting nonzero - and it swallows BaseException, which
# includes the SystemExit an older parser would raise. A hook that cannot invalidate must
# degrade to the staleness that preceded it, never to a refused tool call.
HOOK_BOOTSTRAP = (
    "import importlib.util, pathlib, sys\n"
    "try:\n"
    "    p = pathlib.Path.home() / '.claude/skills/gitos/scripts/model_optimization.py'\n"
    "    spec = importlib.util.spec_from_file_location('gitos_model_optimization', p)\n"
    "    engine = importlib.util.module_from_spec(spec)\n"
    "    spec.loader.exec_module(engine)\n"
    "    engine.hook_command(sys.stdin)\n"
    "except BaseException:\n"
    "    pass\n"
)
# A dispatch boundary is where a stale baseline does its damage, so the dispatch tool is the
# only matcher the tool-call event needs. Leaving the other tools alone also keeps the hook
# off every file read.
HOOK_MATCHERS = {"ConfigChange": None, "PostModelSwitch": None, "PreToolUse": "Agent"}


def hook_entry():
    """The one hook entry the engine owns, identical on every event it registers."""
    return {"type": "command", "command": "python", "args": ["-I", "-c", HOOK_BOOTSTRAP],
            "async": True,
            "statusMessage": "gitos: keep the model/effort baseline current"}


def ensure_settings_hook(root, entry=None, matchers=None):
    """Make sure `<root>/.claude/settings.json` registers a hook entry on each event named.

    Defaults to THIS module's currency hook. `entry` and `matchers` are parameters rather than
    constants so a sibling change that needs its own hook on its own events passes two
    arguments instead of copying fifty lines - the extend-never-replace rule applied to this
    writer itself, not only to the file it writes.

    EXTEND, NEVER REPLACE. The engine owns one entry per event and nothing else in the file.
    Other top-level keys, other events, other matcher groups, and other commands inside an
    event this one also uses are all preserved - a sibling change that wants another event or
    another hook beside this one APPENDS its own group and rewrites none of this. Append-only
    and idempotent; it never removes or rewrites an entry it finds.

    A file that is unreadable, not an object, or shaped unexpectedly is LEFT UNTOUCHED and
    reported, because clobbering an operator's hook configuration in order to install a safety
    check is not a safety improvement.

    -> (status, detail) with status in {'present', 'appended', 'created', 'skipped'}.
    """
    path = Path(root) / ".claude" / "settings.json"
    entry = hook_entry() if entry is None else entry
    matchers = HOOK_MATCHERS if matchers is None else matchers
    require(bool(matchers), "Name at least one event to register the hook on")
    require(isinstance(entry.get("args"), list) and bool(entry["args"]),
            "A registered entry needs `args`; that list is how a repeat recognizes it")
    created = not path.exists()
    if created:
        settings = {}
    else:
        try:
            settings = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return "skipped", f"{path} could not be read as JSON ({exc}); left untouched"
        if not isinstance(settings, dict):
            return "skipped", f"{path} is not a JSON object; left untouched"
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return "skipped", f"{path} has a non-object `hooks`; left untouched"
    added = []
    for event, matcher in matchers.items():
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            return "skipped", f"{path} has a non-list `hooks.{event}`; left untouched"
        # Identity is the ARGS, not the whole entry: an operator who retitled the status
        # message or made the hook synchronous still has it registered, and a second run must
        # not install a duplicate beside their edit.
        if any(isinstance(group, dict) and isinstance(group.get("hooks"), list) and
               any(isinstance(h, dict) and h.get("args") == entry["args"] for h in group["hooks"])
               for group in groups):
            continue
        group = {"hooks": [copy.deepcopy(entry)]}
        if matcher is not None:
            group = {"matcher": matcher, **group}
        hooks[event] = [*groups, group]
        added.append(event)
    if not added:
        return "present", f"the hook is registered on {', '.join(matchers)}"
    settings["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, settings)
    return ("created" if created else "appended"), ", ".join(added)


def report_settings_hook(root, status, detail):
    """Name the registration outcome on stderr; stdout stays the machine-readable record."""
    path = Path(root) / ".claude" / "settings.json"
    if status == "skipped":
        print(f"model optimization: currency hook NOT registered - {detail}. Register it by hand, "
              f"or an operator model/effort change leaves the baseline stale instead of unknown",
              file=sys.stderr)
        return
    print(f"model optimization: currency hook {status} in {path} ({detail}); an announced "
          f"operator change now invalidates the baseline rather than leaving it stale",
          file=sys.stderr)


def hook_command(stream):
    """The client-event entry point. ALWAYS returns 0 and NEVER writes to stdout.

    This runs on a tool-call boundary where stdout is a decision channel and a nonzero exit is
    a refusal, so a hook that can block a tool call or take a session down is a hook the
    operator switches off - and a switched-off hook is exactly the staleness this exists to
    end. The broad guard is therefore deliberate and is NOT a gate: refusing a dispatch is
    `select`'s job, and `select` refuses on what this hook wrote, never on whether it ran.
    """
    try:
        payload = json.loads(stream.read() or "null")
        root = payload.get("cwd") if isinstance(payload, dict) else None
        if not isinstance(root, str) or not Path(root).is_dir():
            print("model optimization hook: inert - the announcement names no usable cwd",
                  file=sys.stderr)
            return 0
        home = home_path(root)
        if not home.is_dir():
            return 0
        if not load_config(home)["enabled"]:
            return 0
        action, detail = apply_event(home, payload)
        print(f"model optimization hook: {action} - {detail}", file=sys.stderr)
    except Exception as exc:  # a hook must never be the thing that breaks a session
        print(f"model optimization hook: inert - {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


def initialize_session(home, config, harness, session_id, initial, new_session=False, root=None):
    validate_config(config)
    if not config["enabled"]:
        return {"status": "disabled", "reason": "Optimization is off; no session state accessed"}
    proposed = validate_session({"schema_version": 1, "session_id": session_id, "harness": harness,
                                 "initial": initial, "current": copy.deepcopy(initial)})
    if root is not None:
        proposed = seed_fingerprints(proposed, root)
    previous = load_session(home)  # Even explicit replacement must not hide corrupt state.
    if previous is not None:
        same = (previous["session_id"], previous["harness"]) == (session_id, harness)
        if same:
            require(not new_session, "Use a distinct identity for a new session; baseline preserved")
            return {"status": "session-ready", "session": previous}
        require(new_session and previous["session_id"] != session_id,
                "Session identity/harness mismatch; deliberately initialize a distinct --new-session")
    save_json(home, SESSION_FILENAME, proposed)
    return {"status": "session-ready", "session": proposed}


def compare_observations(initial, current):
    changes = {}
    for key in ("model", "effort"):
        before, after = initial[key]["value"], current[key]["value"]
        changes[key] = ("unknown" if before is None or after is None else
                        "unchanged" if before == after else "changed")
    overall = ("changed" if "changed" in changes.values() else
               "unchanged" if all(v == "unchanged" for v in changes.values()) else "unknown")
    return {"change": overall, "changes": changes}


def select(config, harness, tier="standard", lead=None, lead_effort=None, runtime=None, required=(),
           session=None, session_id=None, model_source=None, effort_source=None):
    """Validate a proposed dispatch. Does not observe execution or select task tier."""
    validate_config(config)
    result = {"status": "disabled", "reason": "Optimization is off; use existing dispatch behavior"}
    if not config["enabled"]:
        return result
    result = {"status": "blocked", "tier": tier, "effective": "unknown"}

    def stop(reason, status="blocked"):
        return {**result, "status": status, "reason": reason}

    require(harness in HARNESSES and tier in TIERS, "Unknown harness or tier")
    if session is None:
        return stop("Session baseline missing; run session-init before optimized dispatch")
    validate_session(session)
    if not session_id or (session["session_id"], session["harness"]) != (session_id, harness):
        return stop("Session identity/harness mismatch; resume its identity or explicitly initialize a new session")
    # STALENESS, not absence. A missing baseline was already refused above; this refuses a
    # baseline that is PRESENT and was true when written, and whose value an announced operator
    # change has since expired. The caller cannot talk its way past it by re-reporting the
    # pre-change pair in good faith, which is exactly how the stale pair kept being approved.
    # Returned before `result["session"]` is set, so a refusal writes nothing: the record keeps
    # its explicit unknown instead of being handed back the value it just invalidated.
    stale = session.get("stale") or {}
    if stale:
        named = "; ".join(f"{k}: {v}" for k, v in sorted(stale.items()))
        return stop(f"Session baseline invalidated by an announced operator change - {named}. "
                    f"Re-establish the affected component(s) with `reaffirm` from harness or "
                    f"operator evidence; do not re-report the pre-change pair")
    current = observation(lead, lead_effort, model_source, effort_source)
    result["session"] = {**session, "current": current}
    result.update(compare_observations(session["initial"], current))
    mapping = config["harnesses"].get(harness)
    if mapping is None:
        return stop("Configure this harness after discovery; no cross-harness fallback")
    ceiling = mapping["choices"][mapping["ceiling"]]
    if lead is None or lead_effort is None:
        return stop("Actual lead model/effort unknown; establish the ceiling before routing")
    if (lead, lead_effort) != (ceiling["model"], ceiling["effort"]):
        return stop("Lead changed; revalidate the mapping and ceiling")
    choice = mapping["choices"][mapping["tiers"][tier]]
    result["requested"] = {"model": choice["model"], "effort": choice["effort"]}
    capabilities = mapping["catalog"]["models"][choice["model"]]["capabilities"]
    if not set(required).issubset(capabilities):
        return stop("Required capabilities are absent or unverified; refresh discovery or choose another route")
    runtime = {} if runtime is None else runtime
    require(isinstance(runtime, dict), "runtime must be an object")
    for key in ("overrides_checked", "model_control", "effort_control"):
        require(key not in runtime or type(runtime[key]) is bool, f"runtime.{key} must be boolean")
    unavailable = runtime.get("unavailable_models", [])
    require(strings(unavailable), "unavailable_models must be a list")
    if choice["model"] in unavailable:
        return stop("Requested model unavailable; refresh discovery, no automatic fallback")
    allowed = runtime.get("allowed_models")
    require(allowed is None or strings(allowed), "allowed_models must be a list")
    if allowed is not None and choice["model"] not in allowed:
        return stop("Requested model conflicts with native restrictions")
    override = runtime.get("override")
    if override is not None:
        require(isinstance(override, dict) and bool(override) and
                set(override).issubset({"model", "effort"}) and
                all(isinstance(v, str) and v for v in override.values()), "Invalid resolved override")
        if any(result["requested"][key] != value for key, value in override.items()):
            return stop("Native override/operator pin conflicts with route; honor pin and revalidate")
    context = runtime.get("context")
    require(context in (None, "fresh", "fork"), "context must be fresh or fork")
    if context == "fork" and (choice["model"], choice["effort"]) != (lead, lead_effort):
        return stop("Full-context fork inherits the lead; use a fresh worker for this route")
    if runtime.get("overrides_checked") is not True or context is None:
        return stop("Native precedence/context not established; recommendation only", "recommendation-only")
    # A model with no effort levels has no effort to control or evidence: the route is the
    # model alone, and demanding effort evidence for it would bump every such light route up a
    # tier. Only a catalog that lists `default` and nothing else qualifies.
    effortless = has_no_effort_levels(mapping["catalog"]["models"][choice["model"]])
    if context != "fork":
        model_fixed = override and override.get("model") == choice["model"]
        effort_fixed = override and override.get("effort") == choice["effort"]
        if not (runtime.get("model_control") is True or model_fixed):
            return stop("Model control unavailable or unverified; recommendation only", "recommendation-only")
        if not effortless:
            if choice["effort"] == "default" and not effort_fixed:
                return stop("Default effort is not established by native evidence; recommendation only", "recommendation-only")
            if not (runtime.get("effort_control") is True or effort_fixed):
                return stop("Effort control unavailable or unverified; recommendation only", "recommendation-only")
    if effortless:
        return stop("Use the native dispatcher with the model only; this model has no effort "
                    "levels, so pass no effort. Confirm actual execution separately", "dispatch-ready")
    return stop("Use the native dispatcher; confirm actual execution separately", "dispatch-ready")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "enable", "disable", "skip", "configure",
                                            "session-init", "reaffirm", "select", "catalog", "hook",
                                            "observe"))
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--home", choices=("auto",) + HOMES, default="auto")
    parser.add_argument("--harness", choices=HARNESSES)
    parser.add_argument("--file", help="Harness mapping JSON, or Codex model/list pages for catalog")
    parser.add_argument("--tier", choices=TIERS, default="standard")
    parser.add_argument("--lead")
    parser.add_argument("--lead-effort")
    parser.add_argument("--session", help="Explicit identity of this active GitOs session")
    parser.add_argument("--new-session", action="store_true", help="Deliberately replace a different session baseline")
    parser.add_argument("--model-source", choices=("harness", "operator"))
    parser.add_argument("--effort-source", choices=("harness", "operator"))
    parser.add_argument("--runtime", help="JSON evidence from current native harness, never settings to apply")
    parser.add_argument("--require", action="append", default=[], dest="required")
    args = parser.parse_args(argv)
    # The hook takes its repo from the announcement rather than from argv, so one committed
    # command string serves every repo and every checkout.
    if args.command == "hook":
        return hook_command(sys.stdin)
    # Read-only and needs no repo, config or baseline: what the client itself says right now.
    if args.command == "observe":
        level = harness_env_effort()
        print(json.dumps({"effort": level or "unknown", "source": ENV_SOURCE if level else None}))
        return 0
    try:
        if args.command == "catalog":
            require(args.file, "catalog requires --file with complete Codex model/list response page(s)")
            output = codex_catalog(read_json(args.file))
        else:
            root = Path(args.root).resolve()
            home = home_path(root, args.home)
            config = load_config(home)
            if args.command in ("enable", "disable", "skip"):
                if args.command != "skip" or config["preference"] == "unasked":
                    config["enabled"] = args.command == "enable"
                    config["preference"] = {"enable": "enabled", "disable": "disabled", "skip": "skipped"}[args.command]
                    save_config(home, config)
                if config["enabled"] and args.command == "enable":
                    # A repo scaffolded before these seams existed carries neither; enable lays
                    # both. Same reasoning for both: a repo that enables optimization later
                    # should not need a line or a hook back-filled by hand.
                    report_gitignore(root, *ensure_gitignore(root, home))
                    report_settings_hook(root, *ensure_settings_hook(root))
                output = config
            elif args.command == "configure":
                require(args.harness and args.file, "configure requires --harness and --file")
                mapping = validate_mapping(read_json(args.file))
                # Replace routing fields while preserving unrelated per-harness settings.
                merged = copy.deepcopy(config["harnesses"].get(args.harness, {}))
                merged.update(mapping)
                config["harnesses"][args.harness] = merged
                save_config(home, config)
                output = config
            elif args.command == "session-init":
                lead_effort, effort_source = args.lead_effort, args.effort_source
                if lead_effort is None and harness_env_effort():
                    lead_effort, effort_source = harness_env_effort(), ENV_SOURCE
                initial = (observation(args.lead, lead_effort, args.model_source, effort_source)
                           if config["enabled"] else None)
                output = initialize_session(home, config, args.harness, args.session, initial,
                                            args.new_session, root=root)
            elif args.command == "reaffirm":
                require(args.harness, "reaffirm requires --harness")
                lead_effort, effort_source = args.lead_effort, args.effort_source
                if lead_effort is None and harness_env_effort():
                    lead_effort, effort_source = harness_env_effort(), ENV_SOURCE
                require(args.lead is not None or lead_effort is not None,
                        "reaffirm requires --lead and/or --lead-effort with its source "
                        "(or a CLAUDE_EFFORT the client exports)")
                session = load_session(home) if config["enabled"] else None
                if not config["enabled"]:
                    output = {"status": "disabled",
                              "reason": "Optimization is off; no session state accessed"}
                elif session is None:
                    output = {"status": "blocked",
                              "reason": "No session baseline to re-establish; run session-init"}
                elif (not args.session or (session["session_id"], session["harness"]) !=
                      (args.session, args.harness)):
                    output = {"status": "blocked",
                              "reason": "Session identity/harness mismatch; resume its identity "
                                        "or explicitly initialize a new session"}
                else:
                    session = seed_fingerprints(
                        reestablish(session, args.lead, lead_effort,
                                    args.model_source, effort_source), root)
                    save_json(home, SESSION_FILENAME, session)
                    output = {"status": "session-ready", "session": session}
            elif args.command == "select":
                require(args.harness, "select requires --harness")
                require(not args.new_session, "--new-session is only valid with session-init")
                # A disabled invocation reads no runtime/discovery input, even if supplied.
                runtime = read_json(args.runtime) if config["enabled"] and args.runtime else None
                session = load_session(home) if config["enabled"] else None
                output = select(config, args.harness, args.tier, args.lead, args.lead_effort, runtime, args.required,
                                session, args.session, args.model_source, args.effort_source)
                if "session" in output:
                    save_json(home, SESSION_FILENAME, output["session"])
            else:
                output = config
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 3 if output.get("status") in ("blocked", "recommendation-only") else 0
    except (Invalid, OSError) as exc:
        print(f"model optimization: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
