#!/usr/bin/env python3
"""System One client: an optional LOCAL decision model the engine's scripts can ask.

Stdlib only. Library plus CLI. Detail, config reference and the "how to add a use" recipe:
`references/system-one.md`. Question wording and decision tables live ONLY in
`system_one_questions.py` (the registry).

THE CASCADE:  code rules -> this local model -> the reasoning model -> the operator.
Judgments come from the model, decisions come from a table in code. A failed call is an error
(`Unavailable`), never a "no".

INVISIBLE WHEN OFF. With no machine config every function reports off, no file is created and no
network call is made. A repo opts out with `<home>/system-one.json` `{"enabled": false}`.

PUBLIC API (everything a use needs; later work-orders extend the registry, not this file)

    available(home=None) -> bool                 config present, repo not opted out, health ok
    is_configured(home=None) -> bool             config present and repo not opted out (no network)
    ask(state, questions, *, home=None, local_only=False) -> {id: {type, value, probabilities, p}}
    settle(p, thresholds=None) -> "yes" | "no" | "unsure"
    decide(use, item, state, second_state=None, *, home=None, local_only=False) -> result
        result = {"outcome", "confirm", "pass": 1|2, "inputs": {...}}   (outcome may be "escalate")
    require_reversible(result)                   raises ConfirmRequired on a `confirm` outcome
    record_final(use, item, final, by, *, home=None)    by = "accepted" | "overridden"
    log_summary(use=None, *, home=None) -> {use: stats}
    high_override(home=None, last=50, limit=0.30) -> [(use, rate)]
    registry_problems() -> [str]
    scrub(state) -> state

Exceptions: `Unavailable` (any failed call, or off), `Off`, `Refused` (remote endpoint not
allowed, or `local_only`), `ConfirmRequired`. All but `ConfirmRequired` are `Unavailable`s, so
one `except system_one.Unavailable` is the whole fall-through.

ADDING A USE = one `register(...)` entry in the registry plus a CLI subcommand in the calling
script that builds the state, calls `decide`, applies only `reversible` outcomes (guard with
`require_reversible`), and calls `record_final` once the outcome is accepted or overridden.

ANSWER SHAPES, both normalized by `normalize_answer`:
  * TypeSafe (OpenAPI `SystemOneResponse`): `{"model", "answers": {id: {"type": "noul", "noul": 0.98}
    | {"type": "choice", "choice": "x", "confidence": .9, "probabilities": {...}}
    | {"type": "score", "score": 1.7, "confidence": .9, "probabilities": {...}}}, "usage": {...}}`
  * pplx: `{"answers": {id: {"choice"|"noul"|"score": ..., "probabilities": ..., ...}}, "usage": {...}}`
    (the answer's type is the key it carries; `type` may be absent).
  A noul's `p` is P(true); a choice's or score's `p` is P(top). A shape that is neither raises.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from importlib import util as importlib_util
from pathlib import Path

CONFIG_NAME = "config.json"
OPTOUT_NAME = "system-one.json"
FEDERATION_NAME = "federation.json"
HEALTH_TIMEOUT_S = 2.0
RETRIES = 3
BACKOFF_S = 0.25                  # doubled per retry; a test sets it to 0
DEFAULTS = {"timeout_s": 20, "thresholds": {"yes": 0.7, "no": 0.3}, "group": "single",
            "workers": 4, "keep_examples": True, "allow_remote": False, "trusted_hosts": []}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DIGITS = re.compile(r"\d{7,}")


class Unavailable(Exception):
    """A call could not be made or did not return a usable answer. Never defaulted to an answer."""


class Off(Unavailable):
    """System One is not configured here (or this repo opted out)."""


class Refused(Unavailable):
    """The endpoint is not allowed for this call (remote without `allow_remote`, or `local_only`)."""


class ConfirmRequired(Exception):
    """A `confirm` outcome reached a caller that writes."""


# ------------------------------------------------------------------------------------- locations
def system_home() -> Path:
    """The machine dir `~/.claude/gitos-system-one` (HOME-relative; `GITOS_SYSTEM_ONE_HOME` wins)."""
    env = os.environ.get("GITOS_SYSTEM_ONE_HOME")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / ".claude" / "gitos-system-one"


def find_home(start: "str | os.PathLike | None" = None) -> "Path | None":
    """The nearest `.gitos` directory at or above `start` (default: the cwd), or None."""
    p = Path(start or os.getcwd()).resolve()
    for d in (p, *p.parents):
        if (d / ".gitos").is_dir():
            return d / ".gitos"
    return None


def _home(home) -> "Path | None":
    return Path(home) if home is not None else find_home()


def repo_key(home: "Path | None") -> str:
    """The federation id when `<home>/federation.json` carries one, else a sha1 of the repo root."""
    if home is not None:
        try:
            fid = json.loads((Path(home) / FEDERATION_NAME).read_text(encoding="utf-8")).get("id")
            if isinstance(fid, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", fid):
                return fid
        except (OSError, ValueError, AttributeError):
            pass
    root = Path(home).resolve().parent if home is not None else Path(os.getcwd()).resolve()
    return hashlib.sha1(str(root).encode("utf-8")).hexdigest()


def log_path(home: "Path | None") -> Path:
    return system_home() / "log" / f"{repo_key(home)}.jsonl"


# ------------------------------------------------------------------------------------- config
def load_config() -> "dict | None":
    """The machine config with defaults applied, or None when there is none. Raises Unavailable
    when the file exists but cannot be used."""
    path = system_home() / CONFIG_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unavailable(f"config unreadable ({type(e).__name__})")
    if not isinstance(raw, dict) or not isinstance(raw.get("endpoint"), str) or not raw["endpoint"]:
        raise Unavailable("config needs an `endpoint` string")
    cfg = {**DEFAULTS, **raw}
    cfg["thresholds"] = {**DEFAULTS["thresholds"],
                         **(raw.get("thresholds") if isinstance(raw.get("thresholds"), dict) else {})}
    if cfg["group"] not in ("single", "joint"):
        raise Unavailable("config `group` must be `single` or `joint`")
    sec = cfg.get("second")
    if sec is not None and not (isinstance(sec, dict) and isinstance(sec.get("endpoint"), str)):
        raise Unavailable("config `second` needs an `endpoint` string")
    return cfg


def opted_out(home: "Path | None") -> bool:
    if home is None:
        return False
    try:
        data = json.loads((Path(home) / OPTOUT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("enabled") is False


def _active_config(home) -> dict:
    """The config for a call. Raises Off when there is none or the repo opted out."""
    if opted_out(_home(home)):
        raise Off("this repo opted out of System One")
    cfg = load_config()
    if cfg is None:
        raise Off("System One is not configured on this machine")
    return cfg


def is_configured(home=None) -> bool:
    try:
        _active_config(home)
        return True
    except Unavailable:
        return False


def _key(cfg: dict) -> "str | None":
    name = cfg.get("key_env")
    return os.environ.get(name) if isinstance(name, str) and name else None


def _clean(text: str, cfg: dict) -> str:
    """A message safe to show: the key never appears."""
    k = _key(cfg)
    return text.replace(k, "[key]") if k else text


# ------------------------------------------------------------------------------------- privacy
def is_loopback(endpoint: str) -> bool:
    host = (urllib.parse.urlsplit(endpoint).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def scrub(state):
    """E-mail addresses and digit runs of 7 or more replaced, in every string of a state."""
    if isinstance(state, str):
        return _DIGITS.sub("[number]", _EMAIL.sub("[email]", state))
    if isinstance(state, dict):
        return {k: scrub(v) for k, v in state.items()}
    if isinstance(state, list):
        return [scrub(v) for v in state]
    return state


def is_trusted(endpoint: str, cfg: dict) -> bool:
    """The literal host of the URL matches `trusted_hosts` (exact hosts or CIDR ranges). An IP host is
    matched with `ipaddress`; a hostname only by exact string. No DNS lookup ever decides trust."""
    host = urllib.parse.urlsplit(endpoint).hostname or ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    for entry in cfg.get("trusted_hosts") or []:
        if not isinstance(entry, str):
            continue
        if ip is None:
            if entry == host:
                return True
            continue
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def endpoint_class(endpoint: str, cfg: dict) -> str:
    """`loopback`, `trusted-lan` or `remote`. The first two are *local*."""
    if is_loopback(endpoint):
        return "loopback"
    return "trusted-lan" if is_trusted(endpoint, cfg) else "remote"


def _prepare(endpoint: str, cfg: dict, state, local_only: bool):
    """Gate one endpoint. Loopback: as is. Trusted LAN: as is, but only with a key (never printed).
    Remote: refused unless `allow_remote` (and always under `local_only`); scrubbed when allowed."""
    cls = endpoint_class(endpoint, cfg)
    if cls == "loopback":
        return state
    if cls == "trusted-lan":
        if not _key(cfg):
            name = cfg.get("key_env") or "key_env"
            raise Refused(f"a trusted non-loopback endpoint requires a key: set the environment "
                          f"variable named by `key_env` ({name})")
        return state
    if local_only:
        raise Refused("this call is local-only and the endpoint is not loopback or trusted")
    if not cfg.get("allow_remote"):
        raise Refused("the endpoint is not loopback or trusted and `allow_remote` is not set")
    return scrub(state)


# ------------------------------------------------------------------------------------- transport
def _endpoint_url(endpoint: str) -> str:
    sp = urllib.parse.urlsplit(endpoint)
    return endpoint if sp.path not in ("", "/") else endpoint.rstrip("/") + "/v1/systemone"


def _headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    k = _key(cfg)
    if k:
        h["Authorization"] = f"Bearer {k}"
    return h


def health(endpoint: str, cfg: dict) -> "tuple[bool, str]":
    """Probe `<origin>/v1/models` within 2 s. Any HTTP answer below 500 means the server is up."""
    sp = urllib.parse.urlsplit(endpoint)
    url = f"{sp.scheme}://{sp.netloc}/v1/models"
    req = urllib.request.Request(url, headers=_headers(cfg), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S):
            return True, "ok"
    except urllib.error.HTTPError as e:
        return (e.code < 500), f"HTTP {e.code}"
    except Exception as e:
        return False, _clean(type(e).__name__, cfg)


def available(home=None) -> bool:
    try:
        cfg = _active_config(home)
    except Unavailable:
        return False
    return health(cfg["endpoint"], cfg)[0]


def _post(endpoint: str, cfg: dict, model: str, state, questions: dict) -> "tuple[dict, int]":
    """One request, with 3 tries on 429/5xx. -> (response json, input tokens)."""
    body = json.dumps({"model": model, "state": state, "questions": questions}).encode("utf-8")
    last = "no attempt"
    for attempt in range(RETRIES):
        req = urllib.request.Request(_endpoint_url(endpoint), data=body, headers=_headers(cfg),
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout_s"])) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429 or e.code >= 500:
                if attempt < RETRIES - 1:
                    time.sleep(BACKOFF_S * (2 ** attempt))
                continue
            raise Unavailable(_clean(f"the model refused the request ({last})", cfg))
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise Unavailable(_clean(f"the model is unreachable ({type(e).__name__})", cfg))
        except ValueError:
            raise Unavailable("the model answered with something that is not JSON")
        usage = data.get("usage") if isinstance(data, dict) else None
        tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        return data, tokens if isinstance(tokens, int) else 0
    raise Unavailable(_clean(f"the model kept failing ({last}, {RETRIES} tries)", cfg))


# ------------------------------------------------------------------------------------- answers
def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
        raise Unavailable(f"unreadable answer: {what} is not a probability")
    return float(v)


def normalize_answer(qid: str, raw) -> dict:
    """One per-answer object of either shape -> {type, value, probabilities, p}."""
    if not isinstance(raw, dict):
        raise Unavailable(f"unreadable answer for {qid!r}: not an object")
    kind = raw.get("type")
    if kind not in ("noul", "choice", "score"):
        kind = next((k for k in ("noul", "choice", "score") if k in raw), None)
    if kind is None:
        raise Unavailable(f"unreadable answer for {qid!r}: no noul, choice or score")
    probs = raw.get("probabilities")
    probs = {str(k): float(v) for k, v in probs.items()
             if isinstance(v, (int, float)) and not isinstance(v, bool)} \
        if isinstance(probs, dict) else {}
    if kind == "noul":
        v = raw.get("noul")
        if isinstance(v, dict):
            v = next((v[k] for k in ("p", "probability", "true", "yes") if k in v), None)
        if v is None:
            v = next((probs[k] for k in ("true", "yes", "True", "Yes") if k in probs), None)
        if isinstance(v, bool):
            v = 1.0 if v else 0.0
        p = _num(v, f"noul of {qid!r}")
        return {"type": "noul", "value": p > 0.5, "probabilities": probs or {"true": p, "false": 1 - p},
                "p": p}
    if kind == "choice":
        choice = raw.get("choice")
        if not isinstance(choice, str):
            raise Unavailable(f"unreadable answer for {qid!r}: choice is not a name")
        p = probs.get(choice, raw.get("confidence"))
        return {"type": "choice", "value": choice, "probabilities": probs,
                "p": _num(p, f"probability of {choice!r} for {qid!r}")}
    value = raw.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Unavailable(f"unreadable answer for {qid!r}: score is not a number")
    p = max(probs.values()) if probs else raw.get("confidence")
    return {"type": "score", "value": float(value), "probabilities": probs,
            "p": _num(p, f"top probability for {qid!r}")}


def normalize_response(data, ids: list) -> dict:
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise Unavailable("unknown response shape: no `answers` object")
    missing = [i for i in ids if i not in answers]
    if missing:
        raise Unavailable(f"the response lacks an answer for {missing[0]!r}")
    return {i: normalize_answer(i, answers[i]) for i in ids}


def _model_ask(endpoint: str, model: str, cfg: dict, state, questions: dict,
               local_only: bool) -> "tuple[dict, int]":
    """Ask one model all `questions` per the group setting. -> (normalized answers, tokens)."""
    state = _prepare(endpoint, cfg, state, local_only)
    ids = list(questions)
    if cfg["group"] == "joint" or len(ids) == 1:
        data, tok = _post(endpoint, cfg, model, state, questions)
        return normalize_response(data, ids), tok
    workers = max(1, int(cfg["workers"]))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {i: ex.submit(_post, endpoint, cfg, model, state, {i: questions[i]}) for i in ids}
        out, total = {}, 0
        for i, f in futs.items():
            data, tok = f.result()          # re-raises Unavailable
            out.update(normalize_response(data, [i]))
            total += tok
    return out, total


def ask(state, questions: dict, *, home=None, local_only: bool = False) -> dict:
    """Ask the configured model. -> {id: {type, value, probabilities, p}}. Raises Unavailable."""
    cfg = _active_config(home)
    return _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, state, questions, local_only)[0]


# ------------------------------------------------------------------------------------- cascade
def settle(p: float, thresholds: "dict | None" = None) -> str:
    """Above `yes` reads yes, below `no` reads no, between is `unsure`."""
    th = {**DEFAULTS["thresholds"], **(thresholds or {})}
    return "yes" if p > th["yes"] else "no" if p < th["no"] else "unsure"


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


def _inputs(use: dict, answers: dict, th: dict) -> dict:
    """Settled input per question: yes/no/unsure for a noul; the choice or unsure for a choice."""
    out = {}
    for q in use["questions"]:
        a = answers[q["id"]]
        if q["type"] == "noul":
            out[q["id"]] = settle(a["p"], th)
        else:
            out[q["id"]] = a["value"] if a["p"] > th["yes"] else "unsure"
    return out


def _result(reg, use: dict, outcome: str, inputs: dict, n: int) -> dict:
    return {"outcome": outcome, "confirm": use["outcomes"][outcome] == reg.CONFIRM,
            "pass": n, "inputs": inputs}


def decide(use: str, item, state, second_state=None, *, home=None, local_only: bool = False) -> dict:
    """Run a use's questions, apply its table, and on any unsure input run ONE second pass.

    Pass 2 re-asks only the unsure questions: the primary model with `second_state` (when given)
    and the configured `second` model (with `second_state`, else `state`). When two answers settle
    differently the input stays unsure. Anything still unsure escalates. Never more than two passes.
    """
    reg = _registry()
    u = reg.USES[use]
    cfg = _active_config(home)
    th = cfg["thresholds"]
    qs = reg.request_questions(use)
    t0 = time.monotonic()
    meta = {"p": {}, "tokens": 0, "models": [cfg.get("model", "")]}
    h = _home(home)

    def finish(result: dict) -> dict:
        _log_call(h, cfg, use, item, result, meta, state, int((time.monotonic() - t0) * 1000))
        return result

    try:
        answers, tok = _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, state, qs, local_only)
        meta["tokens"] += tok
        meta["p"] = {i: a["p"] for i, a in answers.items()}
        inputs = _inputs(u, answers, th)
        unsure = [i for i, v in inputs.items() if v == "unsure"]
        if not unsure:
            return finish(_result(reg, u, u["table"](dict(inputs)), inputs, 1))
        sec = cfg.get("second")
        if second_state is None and sec is None:
            return finish(_result(reg, u, reg.ESCALATE, inputs, 1))
        sub = {i: qs[i] for i in unsure}
        asked = []                      # list of (answers) from the second pass
        if second_state is not None:
            a, tok = _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, second_state, sub,
                                local_only)
            asked.append(a)
            meta["tokens"] += tok
        if sec is not None:
            scfg = {**cfg, "model": sec.get("model", "")}
            a, tok = _model_ask(sec["endpoint"], sec.get("model", ""), scfg,
                                second_state if second_state is not None else state, sub, local_only)
            asked.append(a)
            meta["tokens"] += tok
            meta["models"].append(sec.get("model", ""))
        meta["p2"] = {i: [a[i]["p"] for a in asked] for i in unsure}
        merged = dict(inputs)
        sub_use = {"questions": [q for q in u["questions"] if q["id"] in sub]}
        settled = [_inputs(sub_use, a, th) for a in asked]
        for i in unsure:
            vals = {s[i] for s in settled}
            merged[i] = vals.pop() if len(vals) == 1 else "unsure"
        if "unsure" in merged.values():
            return finish(_result(reg, u, reg.ESCALATE, merged, 2))
        return finish(_result(reg, u, u["table"](dict(merged)), merged, 2))
    except Unavailable as e:
        meta["error"] = str(e)
        _log_call(h, cfg, use, item, {"outcome": "error", "pass": 0}, meta, state,
                  int((time.monotonic() - t0) * 1000))
        raise


def require_reversible(result: dict) -> None:
    """For callers that write: a `confirm` outcome is only ever reported, never applied."""
    if result.get("confirm"):
        raise ConfirmRequired(f"outcome {result.get('outcome')!r} needs confirmation; report it, "
                              f"do not apply it")


# ------------------------------------------------------------------------------------- the log
def _append(home: "Path | None", row: dict) -> None:
    path = log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_call(home, cfg, use, item, result, meta, state, latency_ms) -> None:
    row = {"kind": "call", "t": _now(), "use": use, "item": str(item),
           "registry": _registry().REGISTRY_VERSION, "pass": result["pass"],
           "p": meta["p"], "outcome": result["outcome"], "model": "+".join(meta["models"]),
           "latency_ms": latency_ms, "input_tokens": meta["tokens"]}
    if "p2" in meta:
        row["p2"] = meta["p2"]
    if "error" in meta:
        row["error"] = _clean(meta["error"], cfg)
    if cfg.get("keep_examples"):
        row["state"] = state
    try:
        _append(home, row)
    except OSError:
        pass                    # the log never breaks a decision


def record_final(use: str, item, final: str, by: str, *, home=None) -> None:
    """Record what was finally done with an item: `by` is `accepted` or `overridden`. Together
    with the call row it is a labelled example. Writes nothing when System One is off."""
    if by not in ("accepted", "overridden"):
        raise ValueError("`by` must be `accepted` or `overridden`")
    _active_config(home)
    _append(_home(home), {"kind": "final", "t": _now(), "use": use, "item": str(item),
                          "final": final, "by": by})


def log_rows(home=None) -> list:
    path = log_path(_home(home))
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def log_summary(use: "str | None" = None, *, home=None) -> dict:
    stats: dict = {}
    lat: dict = {}
    for r in log_rows(home):
        u = r.get("use")
        if use and u != use:
            continue
        s = stats.setdefault(u, {"calls": 0, "settled_pass1": 0, "settled_pass2": 0,
                                 "escalated": 0, "errors": 0, "accepted": 0, "overridden": 0,
                                 "median_latency_ms": None})
        if r.get("kind") == "final":
            if r.get("by") in ("accepted", "overridden"):
                s[r["by"]] += 1
            continue
        s["calls"] += 1
        if r.get("outcome") == "error":
            s["errors"] += 1
        elif r.get("outcome") == "escalate":
            s["escalated"] += 1
        elif r.get("pass") == 1:
            s["settled_pass1"] += 1
        else:
            s["settled_pass2"] += 1
        if isinstance(r.get("latency_ms"), (int, float)):
            lat.setdefault(u, []).append(r["latency_ms"])
    for u, vals in lat.items():
        stats[u]["median_latency_ms"] = statistics.median(vals)
    return stats


def high_override(home=None, last: int = 50, limit: float = 0.30) -> list:
    """Uses whose last `last` finalized rows are overridden more than `limit`: [(use, rate)].
    A use with fewer than `last` finals is not judged."""
    finals: dict = {}
    for r in log_rows(home):
        if r.get("kind") == "final" and r.get("by") in ("accepted", "overridden"):
            finals.setdefault(r.get("use"), []).append(r["by"])
    out = []
    for u, bys in finals.items():
        if len(bys) >= last:
            window = bys[-last:]
            rate = window.count("overridden") / last
            if rate > limit:
                out.append((u, rate))
    return out


def replay(use: str, endpoint: "str | None" = None, *, home=None) -> dict:
    """Re-ask logged examples that have a final outcome (pass 1 only) and count agreement."""
    reg = _registry()
    u = reg.USES[use]
    cfg = _active_config(home)
    if endpoint:
        cfg = {**cfg, "endpoint": endpoint, "second": None}
    calls, finals = {}, {}
    for r in log_rows(home):
        if r.get("use") != use:
            continue
        if r.get("kind") == "call" and "state" in r and r.get("outcome") != "error":
            calls[r["item"]] = r
        elif r.get("kind") == "final":
            finals[r["item"]] = r
    qs = reg.request_questions(use)
    n = agree = errors = 0
    for item, fin in finals.items():
        if item not in calls:
            continue
        n += 1
        try:
            ans, _ = _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, calls[item]["state"], qs,
                                False)
        except Unavailable:
            errors += 1
            continue
        inputs = _inputs(u, ans, cfg["thresholds"])
        out = reg.ESCALATE if "unsure" in inputs.values() else u["table"](dict(inputs))
        agree += out == fin["final"]
    return {"use": use, "examples": n, "agree": agree, "errors": errors}


# ------------------------------------------------------------------------------------- ledger triage
# WO-085. Code gathers the items and their facts, the registry's uses judge them, and a DIGEST is
# printed. Nothing is written in the repo's home, and no output line can read as an `Adjudication`
# heading: the orchestrator reads the digest and writes the block itself.
MAX_STATE = 1500                  # characters per item sent to the model: small items are fast
MAX_PAIRS = 40
HUB_LIMIT = 4                     # a reference or path shared by more items than this is no signal
OVERLAP = 0.5                     # word-overlap (Jaccard) above which a pair becomes a candidate
_REF = re.compile(r"\b(?:WO-\d{3}|P\d+)\b")
_PATH = re.compile(r"[\w.-]+(?:/[\w.-]+)+|\b[\w-]+\.(?:py|md|json|js|html|sh|toml|ya?ml)\b")
_WORD = re.compile(r"[a-z][a-z0-9_-]{3,}")
_STOP = frozenset("that this with from have been will they them then than when which what where "
                  "would could should about into only also each every their there these those "
                  "work order note notes item items file files".split())
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


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


def _in_scope_resolved(home: Path, c) -> set:
    """Resolved work-orders the canary's `notes-unadjudicated` check covers: those whose INDEX
    row names an engine version at or past the habit (older ones are exempt, so are not triaged)."""
    idx = _read_text(home / "INDEX.md")
    block = c.section_lines(idx, c.RESOLVED_HEADING) if idx else None
    out = set()
    for row in (c._table_rows(block) or []) if block is not None else []:
        nnn = c.clean_cell(row[0]) if row else ""
        vers = [int(v) for v in c.VERSION_IN_CELL_RE.findall(row[2])] if len(row) > 2 else []
        if c.NNN_RE.fullmatch(nnn) and vers and max(vers) >= c.LOOSE_ENDS_FROM_VERSION:
            out.add(nnn)
    return out


def _note_items(home: Path, c) -> list:
    """One item per bullet of an Implementer notes section that has no Adjudication block, for
    every open work-order and every resolved one the canary's adjudication check covers."""
    items = []
    covered = _in_scope_resolved(home, c)
    for nnn, path, res in _wo_listing(home, c):
        if res and nnn not in covered:
            continue
        text = _read_text(path)
        notes = c.section_lines(text, c.NOTES_HEADING) if text else None
        if not notes or any(c.ADJUDICATION_HEADING_RE.match(ln.strip()) for ln in notes):
            continue
        title, cur, bullets = _title(text, path.stem), None, []
        for ln in notes:
            s = ln.strip()
            if not s or s.startswith(("#", "<!--")) or c.NOTE_PLACEHOLDER_RE.match(s):
                cur = None if not s else cur
                continue
            if _BULLET.match(s):
                cur = [_BULLET.sub("", s)]
                bullets.append(cur)
            elif cur is not None:
                cur.append(s)
            else:
                cur = [s]
                bullets.append(cur)
        bullets = [_squash(" ".join(b)) for b in bullets]
        bullets = [b for b in bullets if len(b) > 11 and not c.NOTE_NONE_RE.match(b)]
        for k, b in enumerate(bullets, 1):
            label, body = _split_label(b)
            kind = _label_kind(label)
            for j, point in enumerate(_split_points(body), 1):
                head = f"This point was written under the heading: {label}\n" if label else ""
                items.append({"group": "notes", "ref": f"WO-{nnn}#{k}.{j}", "text": point,
                              "label": label, "kind": kind,
                              "state": _cap(f"Work-order: WO-{nnn} {title}\n{head}Point: {point}")})
    return items


_BOLD_LABEL = re.compile(r"^(?:\*\*|__)\s*([^*_]{2,40}?)\s*[.:\-–—]*\s*(?:\*\*|__)\s*"
                         r"[.:\-–—]*\s*")
_PLAIN_LABEL = re.compile(r"^(deviations?|surprises?|durable facts?|process notes?|follow-?ups?|"
                          r"follow ups?)\s*[.:\-–—]+\s*", re.IGNORECASE)
_LABEL_KINDS = (("deviation", "deviation"), ("durable fact", "durable"), ("follow", "followup"),
                ("process", "process"))
_ENUM = re.compile(r"(?:(?<=\s)|^)(?:\(\d+\)|\([a-z]\))(?=\s)|(?<=[.!?;]\s)\d+[.)](?=\s)")
_SENT_END = re.compile(r"[.!?][\"')\]]*\s+(?=[A-Z0-9\[*\0])")
MIN_POINT_WORDS = 4


def _split_label(text: str) -> tuple:
    """(label, rest): a leading bold label, or a known label word followed by punctuation."""
    m = _BOLD_LABEL.match(text) or _PLAIN_LABEL.match(text)
    if not m:
        return "", text
    return _squash(m.group(1)).rstrip(".:"), text[m.end():].strip()


def _label_kind(label: str) -> str:
    low = label.lower()
    for key, kind in _LABEL_KINDS:
        if key in low:
            return kind
    return "other"


def _mask(s: str, parens: bool) -> str:
    """`s` with code spans (and, when `parens`, parenthesised text) blanked to NULs, same length."""
    out, depth, code = list(s), 0, False
    for i, ch in enumerate(s):
        if ch == "`":
            code = not code
            out[i] = "\0"
            continue
        if code:
            out[i] = "\0"
            continue
        if parens:
            if ch == "(":
                depth += 1
            if depth > 0:
                out[i] = "\0"
            if ch == ")" and depth > 0:
                depth -= 1
    return "".join(out)


def _split_points(text: str) -> list:
    """A labelled bullet is several points. Split at enumerators ((1), (a), `1.` at a sentence
    start; two or more of them), else at sentence ends, keeping code spans and parentheses whole.
    A point under MIN_POINT_WORDS words joins its neighbour."""
    text = _squash(text)
    enums = list(_ENUM.finditer(_mask(text, False)))
    if len(enums) >= 2:
        cuts = [(0, 0)] + [(m.start(), m.end()) for m in enums]
        ends = [m.start() for m in enums] + [len(text)]
        pieces = [text[cuts[i][1]:ends[i]] for i in range(len(cuts))]
    else:
        masked, pieces, last = _mask(text, True), [], 0
        for m in _SENT_END.finditer(masked):
            pieces.append(text[last:m.start() + 1])
            last = m.end()
        pieces.append(text[last:])
    pieces = [p.strip(" ;") for p in pieces if p.strip(" ;")]
    out: list = []
    carry = ""
    for p in pieces:
        p = (carry + " " + p).strip()
        carry = ""
        if len(p.split()) < MIN_POINT_WORDS:
            if out:
                out[-1] += " " + p
            else:
                carry = p
        else:
            out.append(p)
    if carry:
        out.append(carry)
    return out or [text]


def _parked_rows(home: Path, c) -> list:
    """Open Parked rows: [{id, item, trigger, source, on}]. Closed rows (`-> WO-NNN`, `-> dropped`)
    are skipped."""
    idx = _read_text(home / "INDEX.md")
    block = c.section_lines(idx, c.PARKED_HEADING) if idx else None
    rows = []
    for row in (c._table_rows(block) or []) if block is not None else []:
        cells = [c.clean_cell(x) for x in row] + [""] * 5
        if not c.PARKED_ID_RE.fullmatch(cells[0]):
            continue
        if re.search(r"(?:→|->)\s*(?:WO-\d{3}|dropped)", " ".join(row), re.IGNORECASE):
            continue
        rows.append({"id": cells[0], "item": cells[1], "trigger": cells[2], "source": cells[3],
                     "on": cells[4]})
    return rows


def _git_subjects(root: Path, since: str) -> list:
    import subprocess
    cmd = ["git", "-C", str(root), "log", "--format=%s", "-n", "30"]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since or ""):
        cmd.append(f"--since={since}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    return [_cap(s, 140) for s in r.stdout.splitlines() if s.strip()] if r.returncode == 0 else []


def _parked_items(home: Path, c) -> list:
    rows = _parked_rows(home, c)
    if not rows:
        return []
    root = home.parent
    ver = (_read_text(root / "VERSION") or "").strip()
    titles = {True: [], False: []}
    for nnn, path, resolved in _wo_listing(home, c):
        text = _read_text(path) or ""
        titles[resolved].append(f"WO-{nnn} {_cap(_title(text, path.stem), 110)}")
    items = []
    for r in rows:
        lines = [f"Parked row: {r['item']}", f"Restart trigger: {r['trigger']}",
                 f"Parked on: {r['on']}", f"Current version: {ver or 'unknown'}"]
        lines += ["Commits since then:"] + [f"- {s}" for s in _git_subjects(root, r["on"])[:15]]
        lines += ["Open work-orders:"] + [f"- {t}" for t in titles[False][:20]]
        lines += ["Recently resolved work-orders:"] + [f"- {t}" for t in titles[True][-12:]]
        items.append({"group": "parked", "ref": r["id"], "text": f"{r['item']} (trigger: {r['trigger']})",
                      "state": "\n".join(lines)})
    return items


def _register_items(path: str, c) -> list:
    text = _read_text(Path(path))
    if text is None:
        raise OSError(f"cannot read register file {path}")
    items = []
    for row in c._table_rows(text.splitlines()) or []:
        cells = [c.clean_cell(x) for x in row]
        if not cells or not cells[0]:
            continue
        body = _cap(" | ".join(cells[1:]) if len(cells) > 1 else cells[0])
        items.append({"group": "register", "ref": cells[0], "text": body,
                      "state": _cap(f"Register row {cells[0]}: {body}")})
    return items


def _signals(text: str, own: str) -> tuple:
    refs = set(_REF.findall(text)) | {own}
    paths = set(_PATH.findall(text))
    words = {w for w in _WORD.findall(text.lower()) if w not in _STOP}
    return refs, paths, words


def _duplicate_items(home: Path, c, parked: list) -> list:
    """Candidate pairs among open Parked rows and open work-orders, chosen by code: a shared
    reference (an item's own id counts) or path (one shared by more than HUB_LIMIT items is
    skipped) or word overlap."""
    pool = []
    for r in parked:
        pool.append((r["ref"], r["text"]))
    for nnn, path, resolved in _wo_listing(home, c):
        if resolved:
            continue
        text = _read_text(path) or ""
        scope = c.section_lines(text, "## Proposed fix scope") or []
        pool.append((f"WO-{nnn}", _squash(_title(text, path.stem) + ". " + " ".join(scope))[:1200]))
    sig = {ref: _signals(t, ref) for ref, t in pool}
    count: dict = {}
    for refs, paths, _w in sig.values():
        for k in refs | paths:
            count[k] = count.get(k, 0) + 1
    scored = []
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            (ra, ta), (rb, tb) = pool[i], pool[j]
            fa, fb = sig[ra], sig[rb]
            shared = {k for k in (fa[0] | fa[1]) & (fb[0] | fb[1]) if count[k] <= HUB_LIMIT}
            wa, wb = fa[2], fb[2]
            jac = len(wa & wb) / len(wa | wb) if len(wa) >= 5 and len(wb) >= 5 else 0.0
            if shared or jac >= OVERLAP:
                scored.append((len(shared), jac, ra, rb, ta, tb))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2], s[3]))
    items = []
    for _n, _j, ra, rb, ta, tb in scored[:MAX_PAIRS]:
        items.append({"group": "duplicates", "ref": f"{ra}~{rb}", "text": f"A {ra}: {_cap(ta, 500)}\n"
                      f"B {rb}: {_cap(tb, 500)}",
                      "state": f"Item A ({ra}): {_cap(ta, 700)}\nItem B ({rb}): {_cap(tb, 700)}"})
    return items


_USE_OF = {"notes": "note-route", "parked": "parked-trigger", "duplicates": "duplicate",
           "register": "row-state"}


_REJECT_DONE = "reject: done in this order"


def _refine_follow_up(r: dict, it: dict, home) -> tuple:
    """A `follow-up` outcome: ask `note-trigger` for a Parked row or a work-order."""
    t = decide("note-trigger", it["ref"], it["state"], home=home)
    r = {**r, "inputs": {**r["inputs"], **t["inputs"]}, "pass": max(r["pass"], t["pass"])}
    return r, {"parked": "follow-up (Parked row)", "work-order": "follow-up (work-order)"
               }.get(t["outcome"], "follow-up (Parked or work-order: read it)")


def _judge_note(it: dict, home) -> tuple:
    """-> (use, result, digest label). The point's heading routes by rule where it is unambiguous
    (no model request); otherwise the questions the heading leaves open are asked."""
    kind, ref, state = it["kind"], it["ref"], it["state"]
    if kind == "deviation":
        return "label-rule", {"outcome": "deviation", "confirm": False, "pass": 0, "inputs": {},
                              "rule": True}, "deviation: accept or revert (label rule)"
    if kind == "durable":
        return "label-rule", {"outcome": "brain", "confirm": False, "pass": 0, "inputs": {},
                              "rule": True}, "brain (label rule)"
    if kind == "followup":
        r = decide("followup-point", ref, state, home=home)
        return "followup-point", r, {"parked": "follow-up (Parked row)",
                                     "work-order": "follow-up (work-order)",
                                     "reject": _REJECT_DONE}.get(r["outcome"], r["outcome"])
    if kind == "process":
        r = decide("process-point", ref, state, home=home)
        if r["outcome"] == "follow-up":
            r, label = _refine_follow_up(r, it, home)
            return "process-point", r, label
        return "process-point", r, ("reject: process note, no action" if r["outcome"] == "reject"
                                    else r["outcome"])
    r = decide("note-route", ref, state, home=home)
    if r["outcome"] == "follow-up":
        r, label = _refine_follow_up(r, it, home)
        return "note-route", r, label
    return "note-route", r, _REJECT_DONE if r["outcome"] == "reject" else r["outcome"]


def _cause(r: dict) -> str:
    """Why an item escalated: the unsure questions, or the answers that conflict."""
    if r["outcome"] != "escalate":
        return ""
    unsure = [k for k, v in r["inputs"].items() if v == "unsure"]
    if unsure:
        return "unsure: " + ", ".join(unsure)
    yes = [f"{k}={v}" for k, v in r["inputs"].items() if v == "yes"]
    return "conflict: " + (", ".join(yes) if yes else "no answer is yes")


def triage(home, register: "str | None" = None) -> dict:
    """Gather, judge, return the digest data. Reads the home, writes nothing in it. Raises
    `Unavailable` (so the caller prints one line and no partial output) when System One is off or a
    call fails."""
    home = Path(home)
    _active_config(home)                                  # Off -> raises before any gathering
    c = _canary()
    items = _note_items(home, c)
    parked = _parked_items(home, c)
    items += parked + _duplicate_items(home, c, parked)
    if register:
        items += _register_items(register, c)
    results = []
    for it in items:
        if it["group"] == "notes":
            use, r, label = _judge_note(it, home)
        else:
            use = _USE_OF[it["group"]]
            r = decide(use, it["ref"], it["state"], home=home)
            label = r["outcome"]
        results.append({"group": it["group"], "use": use, "ref": it["ref"], "outcome": r["outcome"],
                        "label": label, "confirm": r["confirm"], "pass": r["pass"],
                        "inputs": r["inputs"], "text": it["text"],
                        "rule": bool(r.get("rule")), "cause": _cause(r)})
    counts = {"settled": 0, "confirm": 0, "escalate": 0}
    for r in results:
        r["review"] = r["confirm"] or r["outcome"] in ("escalate", "deviation")
        counts["confirm" if r["confirm"] else "escalate" if r["review"] else "settled"] += 1
    return {"registry": _registry().REGISTRY_VERSION, "items": results, "counts": counts}


def _flags(r: dict) -> str:
    names = {"money_or_safety": "safety", "user_visible": "user-visible", "severe": "severe",
             "several_items": "several"}
    on = [n for k, n in names.items() if r["inputs"].get(k) == "yes"]
    return f" [{', '.join(on)}]" if on else ""


def format_digest(d: dict) -> str:
    """One line per settled item; full text only for `escalate` and `confirm` items. Every line
    starts with a marker (`ok`, `READ`, `|`, `==`, `counts`), never with a markdown heading."""
    out = [f"== system-one triage (registry v{d['registry']}): {len(d['items'])} items =="]
    order = {"fired": 0, "waiting": 1}
    for group in ("notes", "parked", "duplicates", "register"):
        rows = [r for r in d["items"] if r["group"] == group]
        if not rows:
            continue
        rows.sort(key=lambda r: (r["review"], order.get(r["outcome"], 2)))
        out.append(f"== {group}: {len(rows)} ==")
        for r in rows:
            mark = "READ" if r["review"] else "ok  "
            tag = " (confirm: report only, never applied)" if r["confirm"] else \
                  f" ({r['cause']})" if r["cause"] else ""
            how = "rule" if r.get("rule") else f"pass {r['pass']}"
            out.append(f"{mark} {r['ref']}  {r['label']}{tag}{_flags(r)}  [{how}]")
            if r["review"]:
                for ln in r["text"].splitlines() or [""]:
                    out.append(f"  | {ln}")
                if r["inputs"]:
                    out.append("  | answers: " + ", ".join(f"{k}={v}" for k, v in r["inputs"].items()))
    c = d["counts"]
    out.append(f"counts: settled {c['settled']}, confirm {c['confirm']}, escalate {c['escalate']}")
    return "\n".join(out)


# ------------------------------------------------------------------ intake and board (WO-086)
# `screen_proposals` annotates pending proposals; `cards` groups board cards. Both only ANNOTATE:
# the result carries registry option names and work-order numbers (from file names), never model
# text, and nothing is written. A proposal body is foreign text: it goes to the model only as state
# for a `local_only` call, and not into any value this function returns.
RECENT_RESOLVED = 15              # resolved work-orders (newest first) that a proposal is compared to
DUP_MIN_SHARED = 4                # shared meaningful words for a (proposal, work-order) candidate
DUP_OVERLAP = 0.15
DUP_PER_PROPOSAL = 3
BODY_LINES = 12


def _dup_pool(home: Path) -> list:
    """[(nnn, text)] for open and recently resolved work-orders: title plus the first lines."""
    c = _canary()
    listing = _wo_listing(home, c)
    resolved = [w for w in listing if w[2]][-RECENT_RESOLVED:]
    pool = []
    for nnn, path, _res in [w for w in listing if not w[2]] + resolved:
        text = _read_text(path) or ""
        lines = [ln for ln in text.splitlines()[1:] if ln.strip() and not ln.startswith(">")]
        pool.append((nnn, _squash(_title(text, path.stem) + ". " + " ".join(lines[:BODY_LINES]))[:900]))
    return pool


def _dup_candidates(text: str, pool: list) -> list:
    _r, _p, words = _signals(text, "")
    scored = []
    for nnn, wt in pool:
        _r2, _p2, w2 = _signals(wt, "")
        shared = words & w2
        jac = len(shared) / len(words | w2) if words and w2 else 0.0
        if len(shared) >= DUP_MIN_SHARED and jac >= DUP_OVERLAP:
            scored.append((-jac, nnn, wt))
    scored.sort()
    return [(n, t) for _j, n, t in scored[:DUP_PER_PROPOSAL]]


def screen_proposals(home, proposals: list) -> dict:
    """proposals: [{"id", "title", "body"}] -> {id: {"area", "severity", "engine_change",
    "duplicate_of"}}; each value is a registry option name or None (an unsure judgment stays None).
    Every call is `local_only`: a non-local endpoint raises `Refused` before any request. Raises
    `Unavailable` (Off, down, Refused) for the caller to fall back to the plain listing."""
    home = Path(home)
    _active_config(home)
    pool = _dup_pool(home)
    out = {}
    for pr in proposals:
        pid = pr["id"]
        text = _cap(f"Proposal title: {pr['title']}\nProposal body: {pr['body']}", 1400)
        def one(use):
            r = decide(use, pid, text, home=home, local_only=True)
            return None if r["outcome"] == "escalate" else r["outcome"]
        dup = None
        for nnn, wt in _dup_candidates(f"{pr['title']} {pr['body'][:1500]}", pool):
            state = f"Item A (proposal): {_cap(pr['title'] + '. ' + pr['body'], 700)}\n" \
                    f"Item B (WO-{nnn}): {_cap(wt, 700)}"
            if decide("proposal-duplicate", f"{pid}~WO-{nnn}", state, home=home,
                      local_only=True)["outcome"] == "likely-duplicate":
                dup = f"WO-{nnn}"
                break
        out[pid] = {"area": one("proposal-area"), "severity": one("proposal-severity"),
                    "engine_change": one("proposal-engine-change"), "duplicate_of": dup}
    return out


SCREEN_BODY_CHARS = 3000
SCREEN_NEEDS_LOCAL = "screening needs a local model: nothing was sent and nothing is annotated"
SCREEN_WO_REF = re.compile(r"WO-\d{3,}")


def _federation():
    """federation.py, imported by path. The dependency runs ONE WAY: this network-capable tool reads
    the authorizing tool; federation.py never imports this file (it must stay incapable of reaching
    a network)."""
    mod = sys.modules.get("_gitos_federation_s1")
    if mod is None:
        path = Path(__file__).resolve().with_name("federation.py")
        spec = importlib_util.spec_from_file_location("_gitos_federation_s1", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_federation_s1"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_federation_s1", None)
            raise
    return mod


def screen_intake(home: Path, view: dict) -> None:
    """**THE ONE PATH THAT READS A PROPOSAL BODY, AND ONLY TO SEND IT TO A LOCAL ENDPOINT.**

    Annotates each pending entry of `view` (federation.list_intake's result) in place with `screen`,
    a one-line annotation ASSEMBLED ONLY FROM THE REGISTRY'S OWN OPTION NAMES (an area, a severity
    word, `engine-change`, `likely-duplicate-of WO-NNN`): no body text, no header value and no model
    free text can reach it. An annotation is not a decision.

    Off or down: nothing is added. A non-local endpoint: no body is read and no request is made,
    and `screen_note` says so.
    """
    fed = _federation()
    Engine = fed.Engine
    pending = view.get("pending") or []
    if not pending:
        return
    try:
        cfg = _active_config(home)
    except Unavailable:
        return                                           # off or opted out
    if endpoint_class(cfg["endpoint"], cfg) == "remote":
        view[Engine("screen_note")] = Engine(SCREEN_NEEDS_LOCAL)
        return
    items = []
    for p in pending:
        pid = fed.emission_text(p["proposal_id"])
        try:
            body = fed.read_proposal_body(fed.proposal_path(fed.intake_dir(home), pid))
        except (fed.FederationError, OSError):
            continue
        items.append({"id": pid, "title": fed.emission_text(p["title"]),
                      "body": body[:SCREEN_BODY_CHARS]})
    try:
        got = screen_proposals(home, items)
    except Refused:
        view[Engine("screen_note")] = Engine(SCREEN_NEEDS_LOCAL)
        return
    except Unavailable:
        return
    for p in pending:
        r = got.get(fed.emission_text(p["proposal_id"]))
        if not r:
            continue
        parts = []
        if r["area"]:
            parts.append("area " + r["area"])
        if r["severity"]:
            parts.append("severity " + r["severity"])
        if r["engine_change"]:
            parts.append(r["engine_change"])
        if r["duplicate_of"] and SCREEN_WO_REF.fullmatch(r["duplicate_of"]):
            parts.append("likely-duplicate-of " + r["duplicate_of"])
        if parts:
            p[Engine("screen")] = Engine("; ".join(parts))


def _screen_cli(args) -> int:
    """The plain federation intake listing, then one `screen` line per annotated proposal."""
    fed = _federation()
    home = Path(args.home)
    if (home / ".gitos").is_dir():
        home = home / ".gitos"
    view = fed.list_intake(home, registry=args.registry)
    screen_intake(home, view)
    pending = view.get("pending") or []
    if args.json:
        print(fed.emit_json(view))
        return 0
    fed._print_intake(fed.emit_human(view))
    lines = [(fed.emission_text(p["proposal_id"])[:8], fed.emission_text(p["screen"]))
             for p in pending if "screen" in p]
    if "screen_note" in view:
        print(f"  screen    {fed.emission_text(view['screen_note'])}")
    if lines:
        print("  screen    a local model's suggestion, in this engine's own words only. It is not a "
              "decision: accept, decline and defer stay yours.")
        for pid8, text in lines:
            print(f"            screen  {pid8}  {text}")
    return 0


def _card_state(card: dict) -> str:
    opts = card.get("options") or []
    labels = [o if isinstance(o, str) else str(o.get("label") or o.get("title") or o.get("id") or "")
              for o in opts]
    return _cap(f"Card: {card.get('title', '')}. Why: {card.get('why', '')}. "
                f"Options: {'; '.join(l for l in labels if l)}")


def cards(home, items: list) -> dict:
    """Suggested board group per card. It picks no option: the recommendation stays the
    orchestrator's, and no option text is returned."""
    _active_config(home)
    rows = []
    for n, card in enumerate(items):
        cid = str(card.get("id") or f"card-{n + 1}") if isinstance(card, dict) else f"card-{n + 1}"
        r = decide("card-group", cid, _card_state(card if isinstance(card, dict) else {}), home=home)
        rows.append({"id": cid, "title": _squash(card.get("title", "")) if isinstance(card, dict) else "",
                     "group": None if r["outcome"] == "escalate" else r["outcome"],
                     "pass": r["pass"]})
    return {"registry": _registry().REGISTRY_VERSION, "cards": rows}


def format_cards(d: dict) -> str:
    out = [f"== system-one cards (registry v{d['registry']}): {len(d['cards'])} cards =="]
    for r in d["cards"]:
        mark, what = ("ok  ", r["group"]) if r["group"] else ("READ", "unsure: no group suggested")
        out.append(f"{mark} {r['id']}  {what}  [pass {r['pass']}]")
        if not r["group"]:
            out.append(f"  | {r['title']}")
    out.append("note: groups only. A card's recommended option stays the orchestrator's choice; "
               "this digest names none.")
    return "\n".join(out)


def _cards_cli(args) -> int:
    home = Path(args.home)
    if (home / ".gitos").is_dir():
        home = home / ".gitos"
    try:
        items = json.loads(Path(args.items).read_text(encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("cards", items.get("items"))
        if not isinstance(items, list):
            raise ValueError("expected a JSON list of cards")
    except (OSError, ValueError) as e:
        print(f"cards: cannot read --items ({type(e).__name__})", file=sys.stderr)
        return 2
    try:
        d = cards(home, items)
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
        return 0
    print(json.dumps(d) if args.json else format_cards(d))
    return 0


# ------------------------------------------------------------------ the brain and the lenses (WO-087)
# `lenses`, `brain-dupes` and `brain-target` read and print: nothing is written in the repo or the
# global lens library. Code gathers and prefilters; the model answers one small question per
# candidate; an unsure answer degrades to "maybe" / "READ", never to a silent drop.
GLOBAL_LENS_ENV = "GITOS_GLOBAL_LENS_DIR"
MAX_BRAIN_PAIRS = 30
TAG_HUB = 8                       # a tag on more pages than this is no signal
TARGET_MIN_SCORE = 2
_LENS_NEEDS = ("domain", "when-to-apply")


def _brain_lint():
    mod = sys.modules.get("_gitos_brain_lint_s1")
    if mod is None:
        path = Path(__file__).resolve().with_name("brain_lint.py")
        spec = importlib_util.spec_from_file_location("_gitos_brain_lint_s1", path)
        mod = importlib_util.module_from_spec(spec)
        sys.modules["_gitos_brain_lint_s1"] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop("_gitos_brain_lint_s1", None)
            raise
    return mod


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
            scope = _squash(" ".join(c.section_lines(text, "## Proposed fix scope") or []))
            return f"WO-{nnn}", (f"Work-order WO-{nnn}: {_title(text, path.stem)}\n"
                                 f"Severity: {_cap(sev, 200)}\nScope: {_cap(scope, 1000)}")
    raise ValueError(f"no work-order {nnn} under {home}")


def match_lenses(home, wo=None, text_file=None, global_dir=None) -> dict:
    """Judge every lens against the work. Raises Unavailable (off, down) before any partial output."""
    home = Path(home)
    _active_config(home)
    lm = _lenses_mod()
    cfg = lm.load(home)
    if cfg["state"] != "on":                          # lenses are opt-in per repo: no judging, no model call
        return {"registry": _registry().REGISTRY_VERSION, "work": "", "lenses": [], "off": True,
                "problems": [f"lenses.json: {cfg['error']}"] if cfg["error"] else []}
    label, work = _work_state(home, wo, text_file)
    act = {(a["layer"], a["name"]) for a in lm.active(home, global_dir)}
    g = gather_lenses(home, global_dir, act)
    rows = []
    for lens in g["lenses"]:
        state = (f"Lens {lens['name']}. Domain: {_cap(lens['domain'], 200)}. "
                 f"When to apply: {_cap(lens['when'], 400)}\n{work}")
        r = decide("lens-match", f"{label}~{lens['name']}", state, home=home)
        rows.append({**lens, "verdict": {"applies": "applies", "no": "no"}.get(r["outcome"], "maybe"),
                     "pass": r["pass"]})
    rows.sort(key=lambda r: ({"applies": 0, "maybe": 1, "no": 2}[r["verdict"]], r["name"]))
    return {"registry": _registry().REGISTRY_VERSION, "work": label, "lenses": rows,
            "problems": g["problems"]}


def format_lenses(d: dict) -> str:
    if d.get("off"):
        return "\n".join(["lenses are off for this repo"] + [f"problem: {p}" for p in d["problems"]])
    out = [f"== system-one lenses (registry v{d['registry']}): {len(d['lenses'])} lenses vs {d['work']} =="]
    for r in d["lenses"]:
        out.append(f"{r['verdict']:<8}{r['name']}  [{r['layer']}]  {_cap(r['domain'], 60)}  [pass {r['pass']}]")
    if not d["lenses"]:
        out.append("no lenses found in either layer")
    for p in d["problems"]:
        out.append(f"problem: {p}")
    out.append("note: `maybe` means the model was unsure: read that lens's when-to-apply yourself. "
               "The role still reads each matching lens; this is a suggestion.")
    return "\n".join(out)


def _brain_pages(home: Path) -> list:
    bl, c = _brain_lint(), _canary()
    pages = []
    for ptype in bl.PAGE_TYPES:
        d = home / "brain" / "wiki" / ptype
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            p = bl.parse_page(f, ptype)
            raw = _read_text(f) or ""
            tags = (c.parse_frontmatter(raw) or {}).get("tags", "")
            tagset = {t.strip().strip("\"'").lower() for t in tags.strip("[]").split(",") if t.strip()}
            body = _squash(re.sub(r"^\s*#\s+.+$", "", p.body, count=1, flags=re.M).replace("#", " "))
            pages.append({"ref": f"{ptype}/{p.slug}", "title": p.title, "tags": tagset,
                          "ttok": bl.title_tokens(p.title) | bl.title_tokens(p.slug.replace("-", " ")),
                          "links": p.wikilinks, "body": body})
    return pages


def _page_text(p: dict, n: int) -> str:
    return f"{p['title']}. {_cap(p['body'], n)}"


def brain_dupe_candidates(pages: list) -> list:
    """Page pairs worth asking about, chosen by code: a title-token overlap (Jaccard 0.3 or more), or
    two shared tags plus a shared title token, or three shared links. Tags on many pages are no signal."""
    bl = _brain_lint()
    count: dict = {}
    for p in pages:
        for t in p["tags"]:
            count[t] = count.get(t, 0) + 1
    out = []
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            a, b = pages[i], pages[j]
            tj = bl.jaccard(a["ttok"], b["ttok"])
            tags = {t for t in a["tags"] & b["tags"] if count[t] <= TAG_HUB}
            links = len(a["links"] & b["links"])
            if tj >= 0.3 or (len(tags) >= 2 and a["ttok"] & b["ttok"]) or links >= 3:
                out.append((-tj, -len(tags), -links, a["ref"], b["ref"], a, b))
    out.sort(key=lambda r: r[:5])
    return [(a, b) for *_k, a, b in out[:MAX_BRAIN_PAIRS]]


def brain_dupes(home) -> dict:
    home = Path(home)
    _active_config(home)
    rows = []
    for a, b in brain_dupe_candidates(_brain_pages(home)):
        state = f"Page A ({a['ref']}): {_page_text(a, 700)}\nPage B ({b['ref']}): {_page_text(b, 700)}"
        r = decide("brain-duplicate", f"{a['ref']}~{b['ref']}", state, home=home)
        rows.append({"a": a["ref"], "b": b["ref"], "outcome": r["outcome"], "confirm": r["confirm"],
                     "pass": r["pass"], "text": f"A {a['ref']}: {_cap(_page_text(a, 300), 340)}\n"
                                                f"B {b['ref']}: {_cap(_page_text(b, 300), 340)}"})
    return {"registry": _registry().REGISTRY_VERSION, "pairs": rows}


def format_brain_dupes(d: dict) -> str:
    out = [f"== system-one brain-dupes (registry v{d['registry']}): {len(d['pairs'])} candidate pairs =="]
    for r in d["pairs"]:
        read = r["confirm"] or r["outcome"] == "escalate"
        tag = " (confirm: report only, never merged)" if r["confirm"] else \
              " (unsure: read both pages)" if read else ""
        out.append(f"{'READ' if read else 'ok  '} {r['a']}~{r['b']}  {r['outcome']}{tag}  [pass {r['pass']}]")
        if read:
            out += [f"  | {ln}" for ln in r["text"].splitlines()]
    out.append("note: candidates come from a code prefilter; nothing was merged or edited.")
    return "\n".join(out)


def brain_target_candidates(pages: list, fact: str) -> list:
    """At most BRAIN_SLOTS pages that share tags or tokens with the fact, best first."""
    bl = _brain_lint()
    words = bl.title_tokens(fact)
    _r, _p, body_words = _signals(fact, "")
    scored = []
    for p in pages:
        pw = _signals(p["body"][:1500], "")[2]
        score = 2 * len(p["tags"] & words) + len(p["ttok"] & words) + (1 if len(body_words & pw) >= 5 else 0)
        if score >= TARGET_MIN_SCORE:
            scored.append((-score, p["ref"], p))
    scored.sort(key=lambda s: s[:2])
    return [p for _s, _r2, p in scored[:_registry().BRAIN_SLOTS]]


def brain_target(home, fact: str) -> dict:
    """-> {"suggestion": "update <ref>" | "new page" | "undecided", "candidates": [ref], ...}.
    With no candidate the answer is `new page` and no call is made."""
    home = Path(home)
    _active_config(home)
    cands = brain_target_candidates(_brain_pages(home), fact)
    res = {"registry": _registry().REGISTRY_VERSION, "candidates": [p["ref"] for p in cands],
           "suggestion": "new page", "pass": 0, "why": "no existing page shares tags or words with the fact"}
    if not cands:
        return res
    listing = "\n".join(f"Candidate {n}: {p['ref']}. Tags: {', '.join(sorted(p['tags'])) or 'none'}. "
                        f"{_page_text(p, 140)}" for n, p in enumerate(cands, 1))
    state = f"New fact: {_cap(fact, 500)}\n{listing}"
    f = decide("brain-fits", "fact", state, home=home)
    res["pass"] = f["pass"]
    if f["outcome"] == "new-page":
        res["why"] = "the model says no candidate covers the fact"
        return res
    if f["outcome"] == "escalate":
        res.update(suggestion="undecided", why="unsure whether any candidate fits: read them")
        return res
    t = decide("brain-target", "fact", state, home=home)
    res["pass"] = max(res["pass"], t["pass"])
    slot = t["outcome"].rsplit("-", 1)[-1] if t["outcome"] != "escalate" else ""
    if slot.isdigit() and 1 <= int(slot) <= len(cands):
        res.update(suggestion=f"update {cands[int(slot) - 1]['ref']}", why="the model chose this candidate")
    else:
        res.update(suggestion="undecided", why="a page fits but the model was unsure which: read the candidates")
    return res


def format_brain_target(d: dict) -> str:
    out = [f"== system-one brain-target (registry v{d['registry']}) ==",
           f"{'ok  ' if d['suggestion'] != 'undecided' else 'READ'} {d['suggestion']}  ({d['why']})  "
           f"[pass {d['pass']}]"]
    out += [f"  | candidate {n}: {r}" for n, r in enumerate(d["candidates"], 1)]
    out.append("note: a suggestion only; the orchestrator reads the page and writes the update.")
    return "\n".join(out)


def _brain_cli(args) -> int:
    home = _resolve_home(args.home)
    try:
        if args.cmd == "lenses":
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
        if not (home / "brain" / "wiki").is_dir():
            print(f"{args.cmd}: no brain/wiki under {home}", file=sys.stderr)
            return 2
        if args.cmd == "brain-dupes":
            d = brain_dupes(home)
            print(json.dumps(d) if args.json else format_brain_dupes(d))
        else:
            try:
                fact = Path(args.fact).read_text(encoding="utf-8")
            except OSError as e:
                print(f"brain-target: cannot read --fact ({type(e).__name__})", file=sys.stderr)
                return 2
            d = brain_target(home, fact)
            print(json.dumps(d) if args.json else format_brain_target(d))
        return 0
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
        return 0


# ------------------------------------------------------------------ diagnostic scan (WO-088)
# `scan` reduces log files in CODE first (lines -> templates with counts and positions), sets aside the
# templates the vocabulary file marks normal, then asks `line-anomaly` per remaining template and
# `line-family` for the abnormal or unsure ones. The digest is a READING ORDER, never a finding: logs may
# hold secrets, so every call is `local_only`. Writes nothing.
FAMILIES_FILE = Path(__file__).resolve().parent.parent / "references" / "anomaly-families.md"
DEFAULT_MAX_TEMPLATES = 40        # model calls (line-anomaly + line-family decisions) per scan
SCAN_EXAMPLES = 3
SCAN_TOP = 5
_MASKS = (
    (re.compile(r"\"[^\"\n]*\"|(?<!\w)'[^'\n]*'(?!\w)"), "<str>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<time>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "<date>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b"), "<hex>"),
    (re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)*"), "<n>"),
)
_ALERT = re.compile(r"\b(error|errors|fail|failed|failure|exception|traceback|fatal|critical|panic|"
                    r"timeout|refused|denied|warn|warning)\b", re.I)
_NORMAL_LINE = re.compile(r"^\s*(?:[-*+]\s*)?(?:normal|expected)(?:\s+line)?\s*:\s*(.+?)\s*$", re.I)


def line_template(line: str) -> str:
    """The line with strings, uuids, timestamps, hex ids and numbers masked, whitespace squashed."""
    for rx, repl in _MASKS:
        line = rx.sub(repl, line)
    return _squash(line)


_LEAD_TIME = re.compile(r"^(?:\[?(?:<ts>|<date>|<time>)\]?\s*)+")


def _core(tpl: str) -> str:
    """A template without its leading timestamp, so a vocabulary entry need not carry one."""
    return _LEAD_TIME.sub("", tpl)


def _vocab_normal(home: Path) -> tuple:
    """-> (exact templates, prefix templates, description). The vocabulary marks a normal line with a
    bullet `normal: <line>` (`expected:` also works); a trailing `*` makes it a prefix match. A
    leading timestamp is ignored on both sides."""
    text = _read_text(home / "log_vocabulary.md") or ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    exact, prefix, shown = set(), [], []
    for ln in text.splitlines():
        m = _NORMAL_LINE.match(ln)
        if not m:
            continue
        entry = m.group(1).strip().strip("`").strip()
        if not entry:
            continue
        shown.append(entry)
        if entry.endswith("*"):
            prefix.append(_core(line_template(entry[:-1])))
        else:
            exact.add(_core(line_template(entry)))
    desc = _cap("; ".join(shown), 600) if shown else "no normal output is recorded in the vocabulary"
    return exact, prefix, desc


def _is_normal(tpl: str, exact: set, prefix: list) -> bool:
    tpl = _core(tpl)
    return tpl in exact or any(tpl.startswith(p) for p in prefix)


def _reduce_logs(files: list) -> tuple:
    """-> ({template: record}, line count). Reads each file once; blank lines are skipped."""
    tpls: dict = {}
    total = 0
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for no, raw in enumerate(fh, 1):
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                total += 1
                t = line_template(line)
                rec = tpls.get(t)
                if rec is None:
                    rec = tpls[t] = {"template": t, "count": 0, "first": f"{f}:{no}", "last": "",
                                     "examples": [], "alert": bool(_ALERT.search(line)),
                                     "order": len(tpls)}
                rec["count"] += 1
                rec["last"] = f"{f}:{no}"
                if len(rec["examples"]) < SCAN_EXAMPLES:
                    rec["examples"].append(line[:300])
    return tpls, total


def _scan_state(rec: dict, desc: str) -> str:
    return (f"Log line template: {_cap(rec['template'], 300)}\nExample line: {_cap(rec['examples'][0], 300)}\n"
            f"Normal output for this system: {desc}")


def scan(home, files: list, max_templates: int = DEFAULT_MAX_TEMPLATES) -> dict:
    """Reduce, set the vocabulary-normal aside, judge what is left within `max_templates` model calls.
    Raises `Unavailable` (off, down, or a remote endpoint: nothing is sent) before any partial output."""
    home = Path(home)
    _active_config(home)
    reg = _registry()
    try:
        reg.set_line_families(reg.parse_families(FAMILIES_FILE))
    except OSError:
        pass                                              # the registry keeps its fallback family
    exact, prefix, desc = _vocab_normal(home)
    tpls, total = _reduce_logs(files)
    aside = [r for r in tpls.values() if _is_normal(r["template"], exact, prefix)]
    rest = [r for r in tpls.values() if not _is_normal(r["template"], exact, prefix)]
    rest.sort(key=lambda r: (not r["alert"], r["count"], r["order"]))
    budget = max(1, int(max_templates))
    calls = 0
    judged_normal, not_judged = [], []
    families: dict = {}
    no_family, unsure = [], []
    for r in rest:
        if budget < 1:
            not_judged.append(r)
            continue
        a = decide("line-anomaly", r["first"], _scan_state(r, desc), home=home, local_only=True)
        budget -= 1
        calls += 1
        r["anomaly"] = a["outcome"]
        if a["outcome"] == "normal":
            judged_normal.append(r)
            continue
        if budget < 1:
            r["note"] = "family not judged: --max-templates reached"
            unsure.append(r)
            continue
        f = decide("line-family", r["first"], _scan_state(r, desc), home=home, local_only=True)
        budget -= 1
        calls += 1
        if f["outcome"] == "escalate":
            r["note"] = "unsure which family: read it"
            unsure.append(r)
        elif f["outcome"] == reg.NO_FAMILY:
            if a["outcome"] == "abnormal":
                no_family.append(r)
            else:
                r["note"] = "unsure whether abnormal, and no family fits"
                unsure.append(r)
        else:
            if a["outcome"] == "escalate":
                r["note"] = "unsure whether abnormal"
            families.setdefault(f["outcome"], []).append(r)

    def lines(rows):
        return sum(r["count"] for r in rows)

    def out(rows):
        return [{k: r.get(k, "") for k in ("template", "count", "first", "last", "examples", "note")}
                for r in rows]
    return {"registry": reg.REGISTRY_VERSION, "files": [str(f) for f in files], "lines": total,
            "templates": len(tpls), "calls": calls, "max_templates": max(1, int(max_templates)),
            "vocabulary_normal": {"templates": len(aside), "lines": lines(aside)},
            "judged_normal": {"templates": len(judged_normal), "lines": lines(judged_normal)},
            "not_judged": {"templates": len(not_judged), "lines": lines(not_judged)},
            "families": {n: {"templates": len(rs), "lines": lines(rs), "top": out(rs[:SCAN_TOP])}
                         for n, rs in sorted(families.items())},
            "no_family": {"templates": len(no_family), "lines": lines(no_family),
                          "top": out(no_family[:SCAN_TOP])},
            "unsure": {"templates": len(unsure), "lines": lines(unsure), "top": out(unsure[:SCAN_TOP])}}


def format_scan(d: dict) -> str:
    out = [f"== system-one scan (registry v{d['registry']}): {d['lines']} lines, {d['templates']} templates, "
           f"{d['calls']} model calls ==",
           f"set aside: vocabulary-normal {d['vocabulary_normal']['templates']} templates / "
           f"{d['vocabulary_normal']['lines']} lines; judged normal {d['judged_normal']['templates']} / "
           f"{d['judged_normal']['lines']}; not judged (--max-templates {d['max_templates']}) "
           f"{d['not_judged']['templates']} / {d['not_judged']['lines']}"]

    def block(title, g):
        out.append(f"== {title}: {g['templates']} templates, {g['lines']} lines ==")
        for r in g["top"]:
            note = f"  ({r['note']})" if r.get("note") else ""
            out.append(f"  {r['count']}x  {r['first']}  {r['template']}{note}")
            out.append(f"  | e.g. {r['examples'][0]}")
    for name, g in d["families"].items():
        block(f"family {name}", g)
    block("abnormal, no family", d["no_family"])
    block("unsure", d["unsure"])
    out.append("note: a reading order, not a finding. Read the literal lines yourself before citing them.")
    return "\n".join(out)


def _scan_cli(args) -> int:
    home = Path(args.home)
    if (home / ".gitos").is_dir():
        home = home / ".gitos"
    if args.max_templates < 1:
        print("scan: --max-templates must be at least 1", file=sys.stderr)
        return 2
    try:
        d = scan(home, args.files, args.max_templates)
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
        return 0
    except OSError as e:
        print(f"scan: cannot read a log file ({type(e).__name__}: {e})", file=sys.stderr)
        return 2
    print(json.dumps(d) if args.json else format_scan(d))
    return 0


# ------------------------------------------------------------------------------------- scope and complexity (WO-089)
HUNK_TOKENS = 6000                # a hunk over this many tokens (4 characters each) is split
_SCOPE_END = "every hunk still has to be read: this digest orders the read, it is not a check of the diff"
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
    body = "\n".join(c.section_lines(text, "## Proposed fix scope") or [])
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


def _default_range(root: Path, nnn: str) -> "str | None":
    """The merge-base with the current branch to `wo-NNN`; when on `wo-NNN`, to HEAD from the
    merge-base with main or master."""
    branch = f"wo-{nnn}"
    cur = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    has = _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None
    if has and cur != branch:
        base = (_git(root, "merge-base", "HEAD", branch) or "").strip()
        return f"{base}..{branch}" if base else None
    for trunk in ("main", "master"):
        if trunk != cur and _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{trunk}") is not None:
            base = (_git(root, "merge-base", "HEAD", trunk) or "").strip()
            return f"{base}..HEAD" if base else None
    return None


def _diff_hunks(diff: str) -> list:
    """[{file, line, lines}] per hunk of a unified diff; `line` is the first line in the new file."""
    out, cur, fname = [], None, None
    for ln in diff.splitlines():
        if ln.startswith("diff --git "):
            fname, cur = None, None
            m = re.match(r"diff --git a/(.+) b/(.+)$", ln)
            if m:
                fname = m.group(2)
        elif ln.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", ln)
            cur = {"file": fname, "line": int(m.group(2)) if m else 0, "lines": [ln]}
            out.append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
    return [h for h in out if h["file"]]


def _split_hunk(h: dict, limit: int) -> list:
    """The hunk as one or more pieces of at most `limit` tokens; `line` follows each piece."""
    if sum(len(x) + 1 for x in h["lines"]) <= limit * 4:
        return [h]
    pieces, cur, size, line = [], [], 0, h["line"]
    start = line
    for ln in h["lines"]:
        if cur and size + len(ln) + 1 > limit * 4:
            pieces.append({"file": h["file"], "line": start, "lines": cur})
            cur, size, start = [], 0, line
        cur.append(ln)
        size += len(ln) + 1
        if not ln.startswith("-"):
            line += 1
    if cur:
        pieces.append({"file": h["file"], "line": start, "lines": cur})
    return pieces


def scope_check(home, wo: str, rng: "str | None" = None) -> dict:
    """The rule half (`forbidden`, `outside-scope`) never needs the model; the hunk half becomes a
    stated line when System One is off or down. Writes nothing."""
    home = Path(home)
    nnn, text, c = _wo_text(home, wo)
    scope, inside, forbidden = _scope_patterns(text, c)
    root = Path((_git(home, "rev-parse", "--show-toplevel") or str(home.parent)).strip())
    rng = rng or _default_range(root, nnn)
    if not rng:
        raise ValueError(f"no range for WO-{nnn}: no branch wo-{nnn} and no main/master; pass --range A..B")
    diff = _git(root, "diff", "--no-renames", "--unified=3", rng)
    names = _git(root, "diff", "--no-renames", "--name-only", rng)
    if diff is None or names is None:
        raise ValueError(f"git diff {rng} failed under {root}")
    files = [x for x in names.splitlines() if x.strip()]
    try:
        own = home.resolve().relative_to(root.resolve()).as_posix() + f"/work-orders/WO-{nnn}-*.md"
    except ValueError:
        own = f"work-orders/WO-{nnn}-*.md"
    facts = []
    for f in files:
        hit = next((p for p in forbidden if _matches(f, p)), None)
        if hit:
            facts.append({"file": f, "class": "forbidden", "why": f"Not in scope names `{hit}`"})
        elif not any(_matches(f, p) for p in inside + [own]):
            facts.append({"file": f, "class": "outside-scope", "why": "no path in the scope names it"})
    judged = {f["file"] for f in facts}
    rows, model = [], {"state": "checked"}
    try:
        _active_config(home)
    except Unavailable as e:
        model = {"state": "off" if isinstance(e, Off) else "unavailable", "why": str(e)}
    pieces = [p for h in _diff_hunks(diff) if h["file"] not in judged for p in _split_hunk(h, HUNK_TOKENS)]
    if model["state"] == "checked":
        for p in pieces:
            state = f"Scope text: {_cap(scope, 2500)}\nFile: {p['file']}\nHunk:\n" + "\n".join(p["lines"])
            try:
                r = decide("hunk-scope", f"WO-{nnn}:{p['file']}:{p['line']}", state, home=home)
            except Unavailable as e:
                model = {"state": "unavailable", "why": str(e)}
                rows = []
                break
            first = next((x[1:].strip() for x in p["lines"][1:] if x[:1] in "+-" and x[1:].strip()), "")
            rows.append({"file": p["file"], "line": p["line"], "first": first,
                         "verdict": {"fits": "fits", "look": "look"}.get(r["outcome"], "unsure")})
    return {"registry": _registry().REGISTRY_VERSION, "wo": f"WO-{nnn}", "range": rng,
            "files": len(files), "hunks": len(pieces), "facts": facts, "model": model, "hunk_rows": rows}


def format_scope(d: dict) -> str:
    out = [f"== system-one scope {d['wo']} (registry v{d['registry']}): {d['range']}, "
           f"{d['files']} files, {d['hunks']} hunks =="]
    for cls in ("forbidden", "outside-scope"):
        out += [f"{cls:<14}{f['file']}  ({f['why']})" for f in d["facts"] if f["class"] == cls]
    m = d["model"]
    if m["state"] != "checked":
        out.append(f"hunks: not judged, system-one {m['state']} ({m.get('why', '')})")
    for cls in ("look", "unsure"):
        out += [f"{cls:<14}{r['file']}:{r['line']}  | {_cap(r['first'], 80)}" for r in d["hunk_rows"]
                if r["verdict"] == cls]
    if m["state"] == "checked":
        out.append(f"fits: {sum(1 for r in d['hunk_rows'] if r['verdict'] == 'fits')} hunks")
    out.append(_SCOPE_END)
    return "\n".join(out)


def complexity(home, wo: str) -> dict:
    """Score a work-order in three one-question calls. Raises Unavailable before any output. Writes
    nothing; picks nothing. `level` is None when the level itself is unsure (the nouls are then not
    asked); an unsure noul is None beside a settled level."""
    home = Path(home)
    nnn, text, c = _wo_text(home, wo)
    _active_config(home)
    scope, inside, _ = _scope_patterns(text, c)
    sev = next((ln.strip() for ln in (c.section_lines(text, "## Severity") or []) if ln.strip()), "")
    state = (f"Work-order WO-{nnn}: {_title(text, nnn)}\nSeverity: {_cap(sev, 200)}\n"
             f"Files named: {len(inside)}\nScope: {_cap(scope, 2500)}")
    r = decide("wo-complexity-level", f"WO-{nnn}", state, home=home)
    lvl = r["outcome"][len("level-"):] if r["outcome"].startswith("level-") else None
    inputs = {"touches_shared_tooling": None, "needs_design_choice": None}
    if lvl is not None:
        for use, key in (("wo-touches-shared-tooling", "touches_shared_tooling"),
                         ("wo-needs-design-choice", "needs_design_choice")):
            v = decide(use, f"WO-{nnn}", state, home=home)["outcome"]
            inputs[key] = v if v in ("yes", "no") else None
    return {"registry": _registry().REGISTRY_VERSION, "wo": f"WO-{nnn}", "level": lvl,
            "inputs": inputs, "pass": r["pass"]}


def format_complexity(d: dict) -> str:
    head = f"== system-one complexity {d['wo']} (registry v{d['registry']}) =="
    if d["level"] is None:
        return head + "\nno input (the model was unsure)"
    i = d["inputs"]
    words = {"1": "one file, a mechanical edit", "2": "several files or one design choice",
             "3": "cross-module change, a new mechanism, or safety-relevant code"}
    return "\n".join([head, f"level: {d['level']} ({words[d['level']]})",
                      f"touches_shared_tooling: {i['touches_shared_tooling'] or 'unsure'}",
                      f"needs_design_choice: {i['needs_design_choice'] or 'unsure'}",
                      "note: one input to your own reading; the choice of model and effort stays yours."])


def _scope_cli(args) -> int:
    home = _resolve_home(args.home)
    try:
        if args.cmd == "scope":
            d = scope_check(home, args.wo, args.range)
            print(json.dumps(d) if args.json else format_scope(d))
        else:
            d = complexity(home, args.wo)
            print(json.dumps(d) if args.json else format_complexity(d))
        return 0
    except (OSError, ValueError) as e:
        print(f"{args.cmd}: {e}", file=sys.stderr)
        return 2
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
        return 0


# ------------------------------------------------------------------------------------- CLI
def _status(as_json: bool) -> int:
    home = find_home()
    info: dict = {"state": "off"}
    if home is not None and opted_out(home):
        info["reason"] = "this repo opted out"
    else:
        try:
            cfg = load_config()
        except Unavailable as e:
            cfg = None
            info["reason"] = str(e)
        if cfg is not None:
            ok, detail = health(cfg["endpoint"], cfg)
            info.update({"state": "on", "endpoint": cfg["endpoint"], "model": cfg.get("model", ""),
                         "class": endpoint_class(cfg["endpoint"], cfg), "health": detail if not ok else "ok",
                         "key": ("set" if _key(cfg) else "unset") if cfg.get("key_env") else "none",
                         "group": cfg["group"]})
            try:
                info["registry_version"] = _registry().REGISTRY_VERSION
            except Exception as e:
                info["registry_version"] = f"invalid ({type(e).__name__})"
    if as_json:
        print(json.dumps(info))
    elif info["state"] == "off":
        print("off" + (f" ({info['reason']})" if "reason" in info else ""))
    else:
        print("on")
        for k in ("endpoint", "model", "class", "health", "key", "group", "registry_version"):
            print(f"  {k}: {info[k]}")
    return 0


def _load_json_or_text(path: str):
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        return text


def _triage_cli(args) -> int:
    home = Path(args.home)
    if (home / ".gitos").is_dir():
        home = home / ".gitos"
    try:
        d = triage(home, args.register)
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
        return 0
    print(json.dumps(d) if args.json else format_digest(d))
    return 0


def _final_cli(args) -> int:
    outcome = args.outcome
    if outcome is None:
        if args.by == "overridden":
            print("final: `overridden` needs --outcome", file=sys.stderr)
            return 2
        calls = [r for r in log_rows() if r.get("kind") == "call" and r.get("use") == args.use
                 and r.get("item") == args.item and r.get("outcome") not in (None, "error")]
        if not calls:
            print(f"final: no logged call for {args.use} {args.item}; pass --outcome", file=sys.stderr)
            return 2
        outcome = calls[-1]["outcome"]
    record_final(args.use, args.item, outcome, args.by)
    print(f"recorded: {args.use} {args.item} {outcome} ({args.by})")
    return 0


def main(argv: "list | None" = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")        # Windows consoles default to cp1252
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="system_one.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="off / on, endpoint, model, health, registry version")
    s.add_argument("--json", action="store_true")
    a = sub.add_parser("ask", help="ask the configured model")
    a.add_argument("--state", required=True)
    a.add_argument("--questions", required=True)
    a.add_argument("--json", action="store_true")
    lg = sub.add_parser("log", help="call log")
    lg.add_argument("--summary", action="store_true")
    lg.add_argument("--use")
    lg.add_argument("--json", action="store_true")
    rp = sub.add_parser("replay", help="re-ask logged examples against another endpoint")
    rp.add_argument("--use", required=True)
    rp.add_argument("--endpoint")
    tg = sub.add_parser("triage", help="digest of ledger judgments (writes nothing in the home)")
    tg.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    tg.add_argument("--register", help="a markdown table whose first column is the row id")
    tg.add_argument("--json", action="store_true")
    cd = sub.add_parser("cards", help="suggest a board group per card (picks no option)")
    cd.add_argument("--items", required=True, help="JSON list of cards: id, title, why, options")
    cd.add_argument("--home", default=".", help="the .gitos directory or the repo root")
    cd.add_argument("--json", action="store_true")
    sc = sub.add_parser("screen", help="the intake listing plus a local model's annotation per proposal")
    sc.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    sc.add_argument("--registry", default=None, help="the federation registry directory")
    sc.add_argument("--json", action="store_true")
    ln = sub.add_parser("lenses", help="which lenses apply to a work-order or a text (writes nothing)")
    ln.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    ln.add_argument("--wo", help="a work-order number")
    ln.add_argument("--text", help="a text file describing the work")
    ln.add_argument("--global-dir", help=f"the global lens library (default: ${GLOBAL_LENS_ENV}, "
                                         f"else <skill>/agents)")
    ln.add_argument("--json", action="store_true")
    bd = sub.add_parser("brain-dupes", help="near-duplicate brain page pairs with a verdict (writes nothing)")
    bd.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    bd.add_argument("--json", action="store_true")
    bt = sub.add_parser("brain-target", help="the page a new fact belongs on, or a new page")
    bt.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    bt.add_argument("--fact", required=True, help="a text file holding the fact")
    bt.add_argument("--json", action="store_true")
    sc = sub.add_parser("scan", help="reading order for log files: templates grouped by anomaly family")
    sc.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    sc.add_argument("files", nargs="+", help="log files to scan")
    sc.add_argument("--max-templates", type=int, default=DEFAULT_MAX_TEMPLATES,
                    help="model calls to spend on templates (default %(default)s)")
    sc.add_argument("--json", action="store_true")
    sc = sub.add_parser("scope", help="advisory scope check of a work-order's diff (writes nothing)")
    sc.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    sc.add_argument("wo", help="a work-order number")
    sc.add_argument("--range", help="A..B (default: merge-base to the branch wo-NNN)")
    sc.add_argument("--json", action="store_true")
    cx = sub.add_parser("complexity", help="how complex a work-order reads; one input, never a choice")
    cx.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    cx.add_argument("wo", help="a work-order number")
    cx.add_argument("--json", action="store_true")
    fn = sub.add_parser("final", help="record what was done with a suggestion")
    fn.add_argument("use")
    fn.add_argument("item")
    fn.add_argument("by", choices=("accepted", "overridden"))
    fn.add_argument("--outcome", help="the final outcome (default for `accepted`: the logged one)")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            return _status(args.json)
        if args.cmd == "ask":
            out = ask(_load_json_or_text(args.state), _load_json_or_text(args.questions))
            if args.json:
                print(json.dumps(out))
            else:
                for i, v in out.items():
                    print(f"{i}: {v['value']} (p={v['p']:.3f})")
            return 0
        if args.cmd == "log":
            stats = log_summary(args.use)
            if args.json:
                print(json.dumps(stats))
            else:
                for u, st in stats.items():
                    print(u + ": " + ", ".join(f"{k}={v}" for k, v in st.items()))
                if not stats:
                    print("no log rows")
            return 0
        if args.cmd == "triage":
            return _triage_cli(args)
        if args.cmd == "scan":
            return _scan_cli(args)
        if args.cmd == "final":
            return _final_cli(args)
        if args.cmd == "cards":
            return _cards_cli(args)
        if args.cmd == "screen":
            return _screen_cli(args)
        if args.cmd in ("lenses", "brain-dupes", "brain-target"):
            return _brain_cli(args)
        if args.cmd in ("scope", "complexity"):
            return _scope_cli(args)
        res = replay(args.use, args.endpoint)
        print(json.dumps(res))
        return 0
    except Unavailable as e:
        print(f"unavailable: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
