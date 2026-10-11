"""Repo-local model routing support; no inference, agent runner, or settings discovery.

See references/model-optimization.md. Configured ranks express operator policy,
not provider capability claims. Runtime evidence is supplied by the active harness.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

TIERS = ("light", "standard", "deep")
HARNESSES = ("codex", "claude")
HOMES = (".gitos", "outputs/debug", ".pipeline", "docs/agents")
FILENAME = "model-optimization.json"


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
    # Explicit configuration requires an existing pipeline; never scaffold by accident.
    require(home.is_dir(), "Pipeline home missing; initialize GitOs first")
    path = home / FILENAME
    data = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8-sig") == data:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=home, prefix=".model-optimization-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def select(config, harness, tier="standard", lead=None, lead_effort=None, runtime=None, required=()):
    """Validate a proposed dispatch. Does not observe execution or select task tier."""
    validate_config(config)
    result = {"status": "disabled", "reason": "Optimization is off; use existing dispatch behavior"}
    if not config["enabled"]:
        return result
    result = {"status": "blocked", "tier": tier, "effective": "unknown"}

    def stop(reason, status="blocked"):
        return {**result, "status": status, "reason": reason}

    require(harness in HARNESSES and tier in TIERS, "Unknown harness or tier")
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
    if context != "fork":
        model_fixed = override and override.get("model") == choice["model"]
        effort_fixed = override and override.get("effort") == choice["effort"]
        if not (runtime.get("model_control") is True or model_fixed):
            return stop("Model control unavailable or unverified; recommendation only", "recommendation-only")
        if choice["effort"] == "default" and not effort_fixed:
            return stop("Default effort is not established by native evidence; recommendation only", "recommendation-only")
        if not (runtime.get("effort_control") is True or effort_fixed):
            return stop("Effort control unavailable or unverified; recommendation only", "recommendation-only")
    return stop("Use the native dispatcher; confirm actual execution separately", "dispatch-ready")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "enable", "disable", "skip", "configure", "select", "catalog"))
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--home", choices=("auto",) + HOMES, default="auto")
    parser.add_argument("--harness", choices=HARNESSES)
    parser.add_argument("--file", help="Harness mapping JSON, or Codex model/list pages for catalog")
    parser.add_argument("--tier", choices=TIERS, default="standard")
    parser.add_argument("--lead")
    parser.add_argument("--lead-effort")
    parser.add_argument("--runtime", help="JSON evidence from current native harness, never settings to apply")
    parser.add_argument("--require", action="append", default=[], dest="required")
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            require(args.file, "catalog requires --file with complete Codex model/list response page(s)")
            output = codex_catalog(read_json(args.file))
        else:
            home = home_path(args.root, args.home)
            config = load_config(home)
            if args.command in ("enable", "disable", "skip"):
                if args.command != "skip" or config["preference"] == "unasked":
                    config["enabled"] = args.command == "enable"
                    config["preference"] = {"enable": "enabled", "disable": "disabled", "skip": "skipped"}[args.command]
                    save_config(home, config)
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
            elif args.command == "select":
                require(args.harness, "select requires --harness")
                # A disabled invocation reads no runtime/discovery input, even if supplied.
                runtime = read_json(args.runtime) if config["enabled"] and args.runtime else None
                output = select(config, args.harness, args.tier, args.lead, args.lead_effort, runtime, args.required)
            else:
                output = config
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 3 if output.get("status") in ("blocked", "recommendation-only") else 0
    except (Invalid, OSError) as exc:
        print(f"model optimization: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
