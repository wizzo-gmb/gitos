#!/usr/bin/env python3
"""System One client: an optional LOCAL decision model the engine's scripts can ask.

Stdlib only. Library plus CLI. Detail, config reference and the "how to add a use" recipe:
`references/system-one.md`. Question wording and decision tables live ONLY in
`system_one_questions.py` (the registry).

THE CASCADE:  code rules -> this local model -> the reasoning model -> the operator.
Judgments come from the model, decisions come from a table in code. A failed call is an error
(`Unavailable`), never a "no".

INVISIBLE WHEN OFF. With no machine config every function reports off, no file is created and no
network call is made. A repo is on only with `<home>/system-one.json` `{"enabled": true}`; no file
means it has not chosen, which is off.

PUBLIC API (everything a use needs; later work-orders extend the registry, not this file)

    available(home=None) -> bool                 config present, repo not opted out, health ok
    is_configured(home=None) -> bool             config present and repo not opted out (no network)
    ask(state, questions, *, home=None, local_only=False) -> {id: {type, value, probabilities, p}}
    settle(p, thresholds=None) -> "yes" | "no" | "unsure"
    decide(use, item, state, second_state=None, *, home=None, local_only=False) -> result
        result = {"outcome", "confirm", "pass": 1|2, "inputs": {...}}   (outcome may be "escalate")
    require_reversible(result)                   raises ConfirmRequired on a `confirm` outcome
    log_summary(use=None, *, home=None) -> {use: stats}
    registry_problems() -> [str]
    scrub(state) -> state

Exceptions: `Unavailable` (any failed call, or off), `Off`, `Refused` (remote endpoint not
allowed, or `local_only`), `ConfirmRequired`. All but `ConfirmRequired` are `Unavailable`s, so
one `except system_one.Unavailable` is the whole fall-through.

ADDING A USE = one `register(...)` entry in the registry plus a CLI subcommand in the calling
script that builds the state, calls `decide` and applies only `reversible` outcomes (guard with
`require_reversible`).

ANSWER SHAPES, both normalized by `normalize_answer`:
  * typed (OpenAPI `SystemOneResponse`): `{"model", "answers": {id: {"type": "noul", "noul": 0.98}
    | {"type": "choice", "choice": "x", "confidence": .9, "probabilities": {...}}
    | {"type": "score", "score": 1.7, "confidence": .9, "probabilities": {...}}}, "usage": {...}}`
  * keyed: `{"answers": {id: {"choice"|"noul"|"score": ..., "probabilities": ..., ...}}, "usage": {...}}`
    (the answer's type is the key it carries; `type` may be absent).
  A noul's `p` is P(true); a choice's or score's `p` is P(top). A shape that is neither raises.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import ipaddress
import contextlib
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

RETIRED_KEYS = ("group", "questions_per_request", "assists")   # config keys no longer read; `migrate` removes them
CONFIG_NAME = "config.json"
OPTOUT_NAME = "system-one.json"
FEDERATION_NAME = "federation.json"
HEALTH_TIMEOUT_S = 2.0
RETRIES = 3
BACKOFF_S = 0.25                  # doubled per retry; a test sets it to 0
DEFAULTS = {"timeout_s": 20, "thresholds": {"yes": 0.7, "no": 0.3}, "workers": 4, "keep_examples": True, "allow_remote": False, "trusted_hosts": []}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DIGITS = re.compile(r"\d{7,}")


class Unavailable(Exception):
    """A call could not be made or did not return a usable answer. Never defaulted to an answer."""


class Off(Unavailable):
    """System One is not configured here (or this repo opted out)."""


class Refused(Unavailable):
    """The endpoint is not allowed for this call (remote without `allow_remote`, or `local_only`)."""


class RetiredKeys(Unavailable):
    """The machine config or the repo's system-one.json carries a key this engine no longer reads."""


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
    retired = [k for k in RETIRED_KEYS if k in raw]
    if retired:
        raise RetiredKeys(retired_line(retired))
    cfg = {**DEFAULTS, **raw}
    cfg["thresholds"] = {**DEFAULTS["thresholds"],
                         **(raw.get("thresholds") if isinstance(raw.get("thresholds"), dict) else {})}
    sec = cfg.get("second")
    if sec is not None and not (isinstance(sec, dict) and isinstance(sec.get("endpoint"), str)):
        raise Unavailable("config `second` needs an `endpoint` string")
    return cfg


def retired_line(names) -> str:
    return f"config has retired keys: {', '.join(names)}; run /gitos upgrade"


REPO_REASONS = {
    "retired": "this repo's system-one.json has retired keys; run /gitos upgrade",
    "missing": "this repo has not chosen (run upgrade or `system_one.py repo on`)",
    "off": "this repo turned System One off",
    "malformed": "this repo's system-one.json is malformed",
}


def repo_choice(home: "Path | None") -> "tuple[str, str]":
    """This repo's own choice, `<home>/system-one.json`: (`on` | `off` | `missing` | `malformed` | `retired`, detail).
    Only a literal `enabled: true` is on; a missing file is `missing` (not chosen, so off)."""
    if home is None:
        return "on", ""
    path = Path(home) / OPTOUT_NAME
    if not path.is_file():
        return "missing", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return "malformed", f"unreadable ({type(e).__name__})"
    if not isinstance(data, dict):
        return "malformed", "not a JSON object"
    retired = [k for k in RETIRED_KEYS if k in data]
    if retired:
        return "retired", ", ".join(retired)
    if "enabled" not in data:
        return "missing", "no `enabled` key"
    en = data.get("enabled")
    if en is True:
        return "on", ""
    if en is False:
        return "off", ""
    return "malformed", "`enabled` must be true or false"


def _active_config(home) -> dict:
    """The config for a call. Raises Off when there is none or this repo is not on."""
    cfg = load_config()
    if cfg is None:
        raise Off("System One is not configured on this machine")
    state, detail = repo_choice(_home(home))
    if state == "retired":
        raise RetiredKeys(retired_line(detail.split(", ")))
    if state != "on":
        raise Off(REPO_REASONS[state])
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
    """Probe `<origin>/health` within 2 s (WO-096: a server runs a real decision there, so a dead GPU is
    seen). A 503 or a `model-failed` status is down with the reason `model-failed`; another 5xx is down.
    A server with no `/health` (404) falls back to `/v1/models`: any answer below 500 means it is up."""
    sp = urllib.parse.urlsplit(endpoint)
    origin = f"{sp.scheme}://{sp.netloc}"
    try:
        req = urllib.request.Request(origin + "/health", headers=_headers(cfg), method="GET")
        with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT_S) as resp:
            try:
                body = json.loads(resp.read(1 << 16).decode("utf-8"))
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("status") == "model-failed":
                return False, "model-failed"
            return True, "ok"
    except urllib.error.HTTPError as e:
        if e.code == 503:
            return False, "model-failed"
        if e.code != 404:
            return (e.code < 500), f"HTTP {e.code}"
    except Exception as e:
        return False, _clean(type(e).__name__, cfg)
    req = urllib.request.Request(origin + "/v1/models", headers=_headers(cfg), method="GET")
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
               local_only: bool, meta: "dict | None" = None) -> "tuple[dict, int]":
    """Ask one model all `questions`: each question is its own request with the same state, sent
    concurrently (at most one thread per question). `meta["requests"]` counts the requests made.
    -> (normalized answers, tokens). Any one failed request raises `Unavailable`."""
    state = _prepare(endpoint, cfg, state, local_only)
    ids = list(questions)
    if len(ids) == 1:
        if meta is not None:
            meta["requests"] = meta.get("requests", 0) + 1
        data, tok = _post(endpoint, cfg, model, state, questions)
        return normalize_response(data, ids), tok
    if meta is not None:
        meta["requests"] = meta.get("requests", 0) + len(ids)
    workers = max(1, min(int(cfg["workers"]), len(ids)))
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


def decide(use: str, item, state, second_state=None, *, home=None, local_only: bool = False,
           fresh: bool = False) -> dict:
    """Run a use's questions, apply its table, and on any unsure input run ONE second pass.

    Pass 2 re-asks only the unsure questions: the primary model with `second_state` (when given)
    and the configured `second` model (with `second_state`, else `state`). When two answers settle
    differently the input stays unsure. Anything still unsure escalates. Never more than two passes.

    WO-094: before a request, an earlier settled `call` row of this repo's log with the same use,
    registry, model and state text (its `sha`) is returned as it was logged, with `cached: True`; no
    request is made and no row is written. `fresh=True` skips that. An earlier `escalate` or `error`
    row is never reused.
    """
    reg = _registry()
    u = reg.USES[use]
    cfg = _active_config(home)
    th = cfg["thresholds"]
    qs = reg.request_questions(use)
    if not fresh:
        hit = _cache_lookup(_home(home), cfg, use, reg.REGISTRY_VERSION, state)
        if hit is not None:
            res = _result(reg, u, hit["outcome"], hit["inputs"], hit["pass"])
            res["cached"] = True
            return res
    t0 = time.monotonic()
    meta = {"p": {}, "tokens": 0, "models": [cfg.get("model", "")]}
    h = _home(home)

    def finish(result: dict) -> dict:
        _log_call(h, cfg, use, item, result, meta, state, int((time.monotonic() - t0) * 1000))
        return result

    try:
        answers, tok = _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, state, qs, local_only,
                                  meta)
        meta["tokens"] += tok
        meta["p"] = {i: a["p"] for i, a in answers.items()}
        inputs = _inputs(u, answers, th)
        unsure = [i for i in u["reads"](dict(inputs)) if inputs[i] == "unsure"]
        if not unsure:
            return finish(_result(reg, u, u["table"](dict(inputs)), inputs, 1))
        sec = cfg.get("second")
        if second_state is None and sec is None:
            return finish(_result(reg, u, reg.ESCALATE, inputs, 1))
        sub = {i: qs[i] for i in unsure}
        asked = []                      # list of (answers) from the second pass
        if second_state is not None:
            a, tok = _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, second_state, sub,
                                local_only, meta)
            asked.append(a)
            meta["tokens"] += tok
        if sec is not None:
            scfg = {**cfg, "model": sec.get("model", "")}
            a, tok = _model_ask(sec["endpoint"], sec.get("model", ""), scfg,
                                second_state if second_state is not None else state, sub, local_only,
                                meta)
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
        if any(merged[i] == "unsure" for i in u["reads"](dict(merged))):
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
LOCK_WAIT_S = 2.0


@contextlib.contextmanager
def _log_lock(path: Path):
    """An exclusive lock on `<log>.lock` (msvcrt on Windows, else fcntl), waited for at most
    LOCK_WAIT_S. Yields True when held, False when it could not be taken in time."""
    lock = path.with_name(path.name + ".lock")
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    held = False
    try:
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.005)
        yield held
    finally:
        if held:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def _append(home: "Path | None", row: dict) -> bool:
    """Append one JSON line. One process at a time (`_log_lock`), the whole line in one `os.write`
    to an `O_APPEND` descriptor. -> False when the lock could not be taken in time (not written)."""
    path = log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    with _log_lock(path) as held:
        if not held:
            return False
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0),
                     0o644)
        try:
            view = memoryview(line)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
    return True


HELPER_MODEL = "helper"           # the call-log model of an answer that came from a dispatched helper (WO-101)
_CACHE: dict = {}                 # log path -> {"pos", "head", "map"}: an incremental read of the log


def _cache_map(path: Path) -> dict:
    """{(use, registry, model, sha): latest settled call row} of the log at `path`, read
    incrementally (only complete lines past the last position)."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(64)
            ent = _CACHE.get(str(path))
            if ent is None or size < ent["pos"] or ent["head"] != head:
                ent = _CACHE[str(path)] = {"pos": 0, "head": head, "map": {}}
            f.seek(ent["pos"])
            data = f.read()
    except OSError:
        return {}
    end = data.rfind(b"\n") + 1
    for raw in data[:end].splitlines():
        try:
            r = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        if (isinstance(r, dict) and r.get("kind") == "call" and r.get("sha")
                and r.get("outcome") not in (None, "escalate", "error") and r.get("model") != HELPER_MODEL
                and isinstance(r.get("inputs"), dict) and r.get("pass") in (1, 2)):
            ent["map"][(r.get("use"), r.get("registry"), r.get("model"), r["sha"])] = r
    ent["pos"] += end
    return ent["map"]


def _state_sha(state) -> str:
    text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_lookup(h, cfg: dict, use: str, registry, state) -> "dict | None":
    path = log_path(h)
    if not path.is_file():
        return None
    sha = _state_sha(state)
    primary, sec = cfg.get("model", ""), cfg.get("second")
    models = [primary] + ([primary + "+" + sec.get("model", "")] if sec else [])
    table = _cache_map(path)
    for m in models:
        row = table.get((use, registry, m, sha))
        if row is not None:
            return row
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_call(home, cfg, use, item, result, meta, state, latency_ms) -> None:
    row = {"kind": "call", "t": _now(), "use": use, "item": str(item),
           "registry": _registry().REGISTRY_VERSION, "pass": result["pass"],
           "p": meta["p"], "outcome": result["outcome"], "model": "+".join(meta["models"]),
           "latency_ms": latency_ms, "input_tokens": meta["tokens"], "sha": _state_sha(state)}
    if result.get("inputs"):
        row["inputs"] = result["inputs"]
    if meta.get("requests"):
        row["requests"] = meta["requests"]
    if "p2" in meta:
        row["p2"] = meta["p2"]
    if "error" in meta:
        row["error"] = _clean(meta["error"], cfg)
    if cfg.get("keep_examples"):
        row["state"] = state
    try:
        _append(home, row)
    except OSError:
        pass                    # the log never breaks a decision (a busy lock skips the write too)


def log_rows(home=None, skipped: "list | None" = None) -> list:
    """Every valid row. Lines that are not valid JSON are skipped; `skipped`, a list, gets one entry
    per skipped line."""
    path = log_path(_home(home))
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if isinstance(row, dict):
                rows.append(row)
            elif skipped is not None:
                skipped.append(line)
    return rows


def log_summary(use: "str | None" = None, *, home=None) -> dict:
    stats: dict = {}
    lat: dict = {}
    for r in log_rows(home):
        u = r.get("use")
        if r.get("kind") != "call" or (use and u != use):
            continue                # only decisions count; `check` rows (uses-check) are not
        s = stats.setdefault(u, {"calls": 0, "settled_pass1": 0, "settled_pass2": 0,
                                 "escalated": 0, "errors": 0, "median_latency_ms": None})
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


# ------------------------------------------------------------------------------------- loose-ends items
# Code gathers the loose-ends items and the candidate pairs; the registry's `loose-end-*` uses judge them.
# The drain below is the only reader of the answers.
MAX_STATE = 1500                  # characters per item sent to the model: small items are fast
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


def pick_orders(home, item_ref: str, item_text: str, options: list) -> list:
    """The model's title pick: which open orders are about the same part of the product as the item. One `choice`
    question over the orders' titles (named by WO id, at most 26); asked twice, the second time with the options
    in reverse order, and the probabilities per order averaged (a choice leans to the option listed first).
    -> [(order ref, probability)], best first. A server that does not answer a choice gives []."""
    reg = _registry()
    cfg = _active_config(home)
    q = reg.USES["loose-end-pick"]["questions"][0]
    state = _cap(f"Item {item_ref}: {item_text}", 500)
    names = [r for r, _t in options]
    sums = {n: 0.0 for n in names}
    meta = {"p": {}, "tokens": 0, "models": [cfg.get("model", "")]}
    t0 = time.monotonic()
    passes = 0
    for opts in (options, list(reversed(options))):
        qs = {"order": {"type": "choice", "instructions": q["instructions"],
                        "criteria": {r: _cap(t, 200) for r, t in opts}}}
        answers, tok = _model_ask(cfg["endpoint"], cfg.get("model", ""), cfg, state, qs, False, meta)
        meta["tokens"] += tok
        a = answers["order"]
        if a["type"] != "choice":
            return []
        probs = a["probabilities"] or {a["value"]: a["p"]}
        for n in names:
            sums[n] += float(probs.get(n, 0.0))
        passes += 1
    ranked = sorted(((n, v / passes) for n, v in sums.items()), key=lambda x: (-x[1], x[0]))
    meta["p"] = {"order": ranked[0][1]} if ranked else {}
    _log_call(_home(home), cfg, "loose-end-pick", item_ref,
              {"outcome": ranked[0][0] if ranked else "escalate", "pass": 2, "inputs": {"order": ranked[0][0]} if ranked else {}},
              meta, state, int((time.monotonic() - t0) * 1000))
    return ranked


def _loose_end_items(home: Path, pick: bool = True) -> tuple:
    """-> (items, new rows, open orders). Read from `<home>/loose-ends.md` with no flag. Each `new` item is
    asked `loose-end-state` (a row in any other state, or one whose State cannot be read, is asked nothing); the (item, open order) join pairs (the item's best three open orders by BM25, in progress or not, plus the model's title pick)
    and the (item, item) bundle pairs are chosen by code (`loose_ends.candidates`). A `new` row a pile file already
    holds (a crash between the pile write and the row write) is asked nothing: the next write marks it `proposed:`. `pick=False` skips the title pick (it needs a model): the candidates then come
    from references, paths and BM25 only."""
    le = _loose_ends()
    if not le.list_path(home).is_file():
        return [], [], []
    piled = _pile_ids(home)
    rows = [r for r in le.rows_of(home)
            if r["state"].strip() == le.STATE_NEW and le.ID_RE.fullmatch(r["id"]) and r["id"] not in piled]
    if not rows:
        return [], [], []
    cand = le.candidates(home, sm=sys.modules[__name__],
                         pick=(lambda ref, text, opts: pick_orders(home, ref, text, opts)) if pick else None)
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
# `drain` is the one System One command that writes in the home. The list row is the authority: a proposed item's
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


def drain(home, fresh: bool = False) -> dict:
    """Ask the loose-end uses (state, joins, bundles) of the `new` rows, write one file per proposal under
    `<home>/drain/pending/`, then mark each proposed row `proposed: <kind>`. A run never deletes a pending file:
    only `accept`, `decline` and `withdraw` do. Raises `Unavailable` (nothing written) when System One is off or a
    call fails. -> {"counts", "written", "proposed"}."""
    home = Path(home)
    cfg = _active_config(home)
    items, loose_rows, orders = _loose_end_items(home)
    results = []
    for it in items:
        r = decide(it["use"], it["ref"], it["state"], home=home, fresh=fresh)
        results.append({"group": it["group"], "use": it["use"], "ref": it["ref"], "outcome": r["outcome"],
                        "text": it["text"], "cause": _cause(r, it["use"])})
    return _drain_write(home, cfg.get("model", ""), loose_rows, orders, results)


def _drain_write(home: Path, model: str, loose_rows: list, orders: list, results: list) -> dict:
    """The proposals of the answered items: the same path for a server's answers and a helper's."""
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


# ------------------------------------------------------------------ the drain by a helper, the default (WO-101)
# The same questions and tables, with the answers read from a file a dispatched helper wrote. Nothing here
# calls a model or handles a key: `--export` writes the questions, `--answers` reads the words and applies
# each use's table. The export and the answers belong to one list state, tied by a fingerprint.
EXPORT_FORMAT = "gitos-drain-export"
ANSWERS_FORMAT = "gitos-drain-answers"
TITLE_PICK_NOTE = ("skipped: the title pick needs a model; join candidates come from references, paths and "
                   "BM25 only")


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
            "fingerprint": fp, "title_pick": TITLE_PICK_NOTE,
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
    -> {"outcomes": {ref: {"outcome", "inputs"}}, "defaulted": n, "unknown": [refs not in the list]}."""
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
        out[it["ref"]] = {"outcome": u["table"](dict(inputs)), "inputs": inputs}
    known = {it["ref"] for it in items}
    return {"outcomes": out, "defaulted": defaulted, "unknown": sorted(k for k in doc["answers"] if k not in known)}


def _helper_log(home: Path, items: list, applied: dict) -> None:
    """One call-log row per applied item, model `helper`."""
    reg = _registry()
    for it in items:
        o = applied["outcomes"][it["ref"]]
        try:
            _append(home, {"kind": "call", "t": _now(), "use": it["use"], "item": it["ref"],
                           "registry": reg.REGISTRY_VERSION, "pass": 1, "p": {}, "outcome": o["outcome"],
                           "model": HELPER_MODEL, "latency_ms": 0, "input_tokens": 0,
                           "sha": _state_sha(it["state"]), "inputs": o["inputs"]})
        except OSError:
            pass                    # the log never breaks a decision


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
    """Write the export file for the loose-ends items the drain would ask. No model call; works with System
    One off, unconfigured or down. -> {"items": n, "fingerprint": F}."""
    items = _loose_end_items(Path(home), pick=False)[0]
    doc = helper_export(items)
    _write_export(path, doc)
    return {"items": len(items), "fingerprint": doc["fingerprint"]}


def drain_answers(home, doc) -> dict:
    """The drain from a helper's answers: the proposals are written through `_drain_write`, as for a server.
    -> `drain`'s result plus {"defaulted", "unknown"}. A stale or unreadable document raises ValueError
    with nothing written."""
    home = Path(home)
    items, loose_rows, orders = _loose_end_items(home, pick=False)
    applied = helper_apply(items, doc)
    results = [{"group": it["group"], "use": it["use"], "ref": it["ref"],
                "outcome": applied["outcomes"][it["ref"]]["outcome"], "text": it["text"],
                "cause": _cause(applied["outcomes"][it["ref"]], it["use"])} for it in items]
    d = _drain_write(home, HELPER_MODEL, loose_rows, orders, results)
    _helper_log(home, items, applied)
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
    priv.add_argument("--fresh", action="store_true")
    priv.add_argument("--export")
    priv.add_argument("--answers")
    try:
        ns = priv.parse_intermixed_args(list(args.rest))
    except SystemExit:
        return 2
    for k in ("json", "fresh"):
        setattr(args, k, getattr(args, k) or getattr(ns, k))
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
            if len(rest) != 1:
                print("drain: usage: drain <home> | accept ID (--work-order NNN [--slice NAME] | --question Q "
                      "| --reason R) [ROOT] | decline ID --reason R [--route DEST] [ROOT] | withdraw ID [ROOT] | defer ID [ROOT] "
                      "| status [ROOT]", file=sys.stderr)
                return 2
            try:
                d = drain(_resolve_home(rest[0]), fresh=args.fresh)
            except Off:
                print("system-one: off")
                return 0
            except Unavailable as e:
                print(f"system-one: unavailable ({e})")
                return 0
            c = d["counts"]
            print(json.dumps(d) if args.json else
                  f"drain: {c['pending']} pending ({c['join']} join, {c['new-order']} new-order, {c['ask']} ask, "
                  f"{c['park']} park, {c['close']} close, {c['read']} read); {len(d['written'])} written, "
                  f"{len(d['proposed'])} rows marked proposed")
            return 0
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
    reasoning model, which reads the list). Raises Off when System One is not on in this repo."""
    home = Path(home)
    _active_config(home)
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
    try:
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
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
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
    pat = re.compile(rf"wo-{re.escape(nnn)}(-s\d+)?$", re.I)
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


# ------------------------------------------------------------------------------------- repo choice
def _write_json_atomic(path: Path, obj) -> None:
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".s1-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(obj, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_repo_choice(home, enabled: bool) -> None:
    """Write `<home>/system-one.json` `enabled`, atomically, keeping unrelated keys. Refuses a malformed
    file (fix or delete it first)."""
    home = Path(home)
    state, detail = repo_choice(home)
    if state == "malformed":
        raise ValueError(f"system-one.json is malformed ({detail}): fix or delete it first")
    if state == "retired":
        raise ValueError(retired_line(detail.split(", ")))
    raw: dict = {}
    if (home / OPTOUT_NAME).is_file():
        raw = json.loads((home / OPTOUT_NAME).read_text(encoding="utf-8"))
    raw["enabled"] = enabled
    _write_json_atomic(home / OPTOUT_NAME, raw)


def _strip_keys(text: str, names: list) -> str:
    """`text` (a JSON object) without the top-level `names`. A key that sits alone on its own line is cut
    out of the text and every other line stays byte for byte; any other layout is rewritten whole."""
    want = {k: v for k, v in json.loads(text).items() if k not in names}
    lines = text.splitlines(keepends=True)
    keep = [ln for ln in lines if not any(re.match(r'\s*"' + re.escape(k) + r'"\s*:', ln) for k in names)]
    for i, ln in enumerate(keep[:-1]):
        if ln.rstrip().endswith(",") and keep[i + 1].strip().startswith("}"):
            keep[i] = ln.rstrip()[:-1] + ln[len(ln.rstrip()):]
    try:
        if len(keep) < len(lines) and json.loads("".join(keep)) == want:
            return "".join(keep)
    except ValueError:
        pass
    return json.dumps(want, indent=2) + "\n"


def migrate(root=".", write: bool = False) -> list:
    """What `/gitos upgrade` converts: [(path, [names])]. The retired keys of the machine config and the repo's
    `system-one.json` (with `write`, removed atomically, every other key stays; a file that is missing,
    unreadable or not an object is skipped). The not-now stores move with `ledger_migrate.py`."""
    found = []
    for path in (system_home() / CONFIG_NAME, _repo_home(root) / OPTOUT_NAME):
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, ValueError):
            continue
        names = [k for k in RETIRED_KEYS if isinstance(data, dict) and k in data]
        if not names:
            continue
        found.append((path, names))
        if write:
            _write_text_atomic(path, _strip_keys(text, names))
    return found


def _repo_home(root) -> Path:
    root = Path(root)
    return root / ".gitos" if (root / ".gitos").is_dir() else root


def _repo_cli(args) -> int:
    rest = list(args.rest)
    if len(rest) > 1:
        print("repo: takes at most one ROOT", file=sys.stderr)
        return 2
    args.root = rest[0] if rest else "."
    home = _repo_home(args.root)
    try:
        if args.action in ("on", "off"):
            if not home.is_dir():
                print(f"repo: no home under {args.root}", file=sys.stderr)
                return 2
            set_repo_choice(home, args.action == "on")
        state, detail = repo_choice(home)
    except (OSError, ValueError) as e:
        print(f"repo: {e}", file=sys.stderr)
        return 2
    words = {"on": "on", "off": "off", "missing": "not chosen (off)", "malformed": "malformed (off)",
             "retired": "retired keys (off)"}
    print(f"system-one repo: {words[state]}" + (f" - {detail}" if detail else ""))
    return 0


# ------------------------------------------------------------------------------------- helper model
HELPER_DEFAULTS = {"claude": "haiku", "codex": "gpt-5.1-codex-mini"}   # the only place either name appears in code
HELPER_SOURCES = ("optimization", "recorded", "default")               # first match wins
HELPER_KEY = "helper"             # `{"<harness>": "<model>"}` in <home>/system-one.json


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


def _helper_recorded(home: Path, harness: str) -> "str | None":
    try:
        data = json.loads((home / OPTOUT_NAME).read_text(encoding="utf-8"))
        model = data[HELPER_KEY][harness]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return model if isinstance(model, str) and model.strip() else None


def helper_model(home, harness: "str | None") -> "tuple[str, str] | None":
    """(model, source) for this repo's helper on `harness`, or None. Sources, first match wins:
    the model-optimization light choice, the recorded pick, the shipped default."""
    if not harness:
        return None
    home = Path(home)
    finders = {"optimization": lambda: _helper_optimization(home, harness),
               "recorded": lambda: _helper_recorded(home, harness),
               "default": lambda: HELPER_DEFAULTS.get(harness)}
    for src in HELPER_SOURCES:
        model = finders[src]()
        if model:
            return model, {"optimization": "model-optimization light choice", "recorded": f"recorded in {OPTOUT_NAME}",
                           "default": "shipped default"}[src]
    return None


def set_helper(home, harness: str, model: str) -> None:
    """Record the helper model for `harness` in `<home>/system-one.json`, atomically, keeping every other key."""
    home = Path(home)
    state, detail = repo_choice(home)
    if state == "malformed":
        raise ValueError(f"system-one.json is malformed ({detail}): fix or delete it first")
    if state == "retired":
        raise ValueError(retired_line(detail.split(", ")))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", harness or "") or not re.fullmatch(r"\S{1,100}", model or ""):
        raise ValueError("helper --set takes a harness name and a model name without spaces")
    raw: dict = {}
    if (home / OPTOUT_NAME).is_file():
        raw = json.loads((home / OPTOUT_NAME).read_text(encoding="utf-8"))
    picks = raw.get(HELPER_KEY)
    raw[HELPER_KEY] = {**(picks if isinstance(picks, dict) else {}), harness: model}
    _write_json_atomic(home / OPTOUT_NAME, raw)


def _helper_cli(args) -> int:
    home = _repo_home(args.root)
    if not home.is_dir():
        print(f"helper: no home under {args.root}", file=sys.stderr)
        return 2
    if args.set:
        try:
            set_helper(home, args.set[0], args.set[1])
        except (OSError, ValueError) as e:
            print(f"helper: {e}", file=sys.stderr)
            return 2
        print(f"helper: recorded {args.set[1]} for {args.set[0]}")
        return 0
    harness = args.harness or detect_harness()
    found = helper_model(home, harness)
    if found is None:
        print(f"helper: no model for harness '{harness or 'unknown'}'; ask the operator to pick one of their "
              f"available models, then run helper --set {harness or '<harness>'} MODEL", file=sys.stderr)
        return 3
    print(f"helper: {found[0]} ({harness}; {found[1]})")
    return 0


# ------------------------------------------------------------------------------------- setup
SETUP_ENDPOINT = "http://127.0.0.1:8765/v1/systemone"
SETUP_TIMEOUT_S = 10.0
DETECT_TIMEOUT_S = 2.0


def _get_json(url: str, timeout: float, headers: dict) -> "tuple[str, object, str]":
    """GET -> (`down` | `answers`, parsed JSON or None, detail). `down` is no HTTP answer at all."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1 << 20)
    except urllib.error.HTTPError as e:
        return "answers", None, f"HTTP {e.code}"
    except Exception as e:
        return "down", None, type(e).__name__
    try:
        return "answers", json.loads(raw.decode("utf-8")), ""
    except ValueError:
        return "answers", None, "not JSON"


def _listed_models(data) -> list:
    rows = data.get("data") if isinstance(data, dict) and "data" in data else \
        data.get("models") if isinstance(data, dict) else data
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, dict):
            out += [r[k] for k in ("id", "name", "model") if isinstance(r.get(k), str)]
    return out


def check_server(endpoint: str, base_cfg: "dict | None" = None, timeout: float = SETUP_TIMEOUT_S) -> dict:
    """Is `endpoint` a System One server? Three checks, in order, stopping at the first that fails:
    `/health` says `status: ok` with a model name; `/v1/models` lists that model; one `probe` decision
    comes back in a valid answer shape with probabilities. -> {state: ok|down|not-system-one, steps,
    model, failed}. Contacts only the one endpoint."""
    cfg = {**DEFAULTS, **(base_cfg or {}), "endpoint": endpoint, "timeout_s": timeout}
    sp = urllib.parse.urlsplit(endpoint)
    origin = f"{sp.scheme}://{sp.netloc}"
    hdr = _headers(cfg)
    res: dict = {"endpoint": endpoint, "state": "not-system-one", "steps": [], "model": "", "failed": ""}

    def step(name, ok, detail):
        res["steps"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            res["failed"] = name
        return ok

    kind, data, why = _get_json(origin + "/health", timeout, hdr)
    if kind == "down":
        res["state"] = "down"
        step("health", False, why)
        return res
    model = data.get("model") if isinstance(data, dict) else None
    if not (isinstance(data, dict) and data.get("status") == "ok" and isinstance(model, str) and model):
        step("health", False, why or "no `status: ok` with a model name")
        return res
    res["model"] = model
    step("health", True, f"status ok, model {model}")
    kind, data, why = _get_json(origin + "/v1/models", timeout, hdr)
    if model not in _listed_models(data):
        step("models", False, why or f"`/v1/models` does not list {model}")
        return res
    step("models", True, f"lists {model}")
    try:
        reg = _registry()
        qs = reg.request_questions("probe")
        ans = normalize_response(_post(endpoint, cfg, model, "hello there", qs)[0], list(qs))
        if not all(a["probabilities"] for a in ans.values()):
            raise Unavailable("the answer carries no probabilities")
    except Unavailable as e:
        step("probe", False, _clean(str(e), cfg))
        return res
    step("probe", True, "a decision came back with probabilities")
    res["state"] = "ok"
    return res


def _setup_cli(args) -> int:
    endpoint = args.endpoint or SETUP_ENDPOINT
    try:
        existing = load_config()
    except Unavailable:
        existing = None
    base = existing or {}
    cls = endpoint_class(endpoint, base)
    if args.detect:
        if cls == "remote":
            return 0
        r = check_server(endpoint, base, DETECT_TIMEOUT_S)
        if r["state"] == "ok":
            print(f"system-one: a server answers at {endpoint} (model {r['model']}); "
                  f"`system_one.py setup --write` sets it up")
        return 0
    if cls == "remote":
        print(f"setup: refused: {endpoint} is not loopback and its host is not in `trusted_hosts` "
              f"of the machine config; nothing was contacted", file=sys.stderr)
        return 2
    print(f"checking {endpoint}")
    r = check_server(endpoint, base)
    for s in r["steps"]:
        print(f"  {s['name']:<7} {'ok' if s['ok'] else 'FAILED'}  {s['detail']}")
    if r["state"] == "down":
        print(f"nothing answers at {endpoint} ({r['steps'][0]['detail']}); nothing was written")
        return 1
    if r["state"] != "ok":
        print(f"something answers at {endpoint} but it is not a System One server ({r['failed']}); "
              f"nothing was written")
        return 1
    new = {**(existing or {}), "endpoint": endpoint, "model": r["model"],
           "timeout_s": (existing or {}).get("timeout_s", DEFAULTS["timeout_s"])}
    path = system_home() / CONFIG_NAME
    if not args.write:
        print(f"would write {path}:\n{json.dumps(new, indent=2)}")
        if path.is_file():
            print("a machine config already exists; writing it needs --write --force")
        else:
            print("to write it: system_one.py setup --write"
                  + (f" --endpoint {endpoint}" if args.endpoint else ""))
        return 0
    if path.is_file() and not args.force:
        print(f"setup: {path} already exists and is not overwritten without --force", file=sys.stderr)
        return 2
    _write_json_atomic(path, new)
    print(f"wrote {path}")
    return 0


# ------------------------------------------------------------------ every use against a server (WO-097)
USES_CHECK_STATE = "A short test text for checking the connection."


def _check_answer(q: dict, a: dict) -> None:
    """Raise Unavailable unless the normalized answer `a` is the right shape for the question `q`."""
    if a["type"] != q["type"]:
        raise Unavailable(f"answered type {a['type']!r} for a {q['type']!r} question")
    if q["type"] == "choice":
        names = list(q["criteria"])
        if a["value"] not in names:
            raise Unavailable(f"the choice {a['value']!r} is not one of the options")
        if not a["probabilities"] or any(n not in a["probabilities"] for n in names):
            raise Unavailable("the choice answer lacks a probability for every option")
    elif q["type"] == "score":
        if not a["probabilities"]:
            raise Unavailable("the score answer carries no probabilities")


def uses_check(endpoint: str, base_cfg: "dict | None" = None, model: str = "", home=None,
               log: bool = True) -> list:
    """Send one request per registered use, built from that use's own questions and a short neutral text
    (`sample` of the use when the registry gives one), and check each answer parses through
    `normalize_answer` for the declared type. -> [{use, questions, ok, reason, latency_ms}]. Decides
    nothing and writes no `final`; each result is a `check` row in the log (never a `call` row, so the
    cache never reads it) when `log` is true."""
    cfg = {**DEFAULTS, **(base_cfg or {}), "endpoint": endpoint}
    reg = _registry()
    out = []
    for use in reg.USES:
        qs = reg.request_questions(use)
        t = time.time()
        reason = ""
        try:
            data = _post(endpoint, cfg, model, reg.USES[use].get("sample", USES_CHECK_STATE), qs)[0]
            ans = normalize_response(data, list(qs))
            for qid, a in ans.items():
                _check_answer(qs[qid], a)
        except Unavailable as e:
            reason = _clean(str(e), cfg)
        row = {"use": use, "questions": len(qs), "ok": not reason, "reason": reason,
               "latency_ms": round((time.time() - t) * 1000, 1)}
        out.append(row)
        if log:
            try:
                _append(_home(home), {"kind": "check", "t": _now(), "model": model, **row})
            except OSError:
                pass
    return out


def _uses_check_cli(args) -> int:
    try:
        base = load_config()
    except Unavailable as e:
        print(f"unavailable: {e}", file=sys.stderr)
        return 3
    endpoint = args.endpoint or (base or {}).get("endpoint")
    if not endpoint:
        print("uses-check: no endpoint: pass --endpoint, or configure the machine first", file=sys.stderr)
        return 2
    if endpoint_class(endpoint, base or {}) == "remote":
        print(f"uses-check: refused: {endpoint} is not loopback and its host is not in `trusted_hosts` "
              f"of the machine config; nothing was contacted", file=sys.stderr)
        return 2
    cfg = {**DEFAULTS, **(base or {}), "endpoint": endpoint}
    model = (base or {}).get("model", "") if endpoint == (base or {}).get("endpoint") else ""
    if not model:
        origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(endpoint))
        _, data, _ = _get_json(origin + "/health", SETUP_TIMEOUT_S, _headers(cfg))
        model = data.get("model", "") if isinstance(data, dict) and isinstance(data.get("model"), str) else ""
    results = uses_check(endpoint, base, model, log=base is not None)
    bad = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps({"endpoint": endpoint, "model": model, "uses": results, "failed": len(bad)}))
    else:
        for r in results:
            print(f"ok {r['use']} ({r['questions']} questions)" if r["ok"] else f"FAIL {r['use']}: {r['reason']}")
        print(f"{len(results) - len(bad)} of {len(results)} uses ok" + (f", {len(bad)} failed" if bad else ""))
    return 1 if bad else 0


# ------------------------------------------------------------------------------------- CLI
def _brief() -> int:
    """One line, or nothing when there is no machine config."""
    try:
        cfg = load_config()
    except RetiredKeys as e:
        print(f"system-one: down ({e})")
        return 0
    except Unavailable:
        print("system-one: down (config)")
        return 0
    if cfg is None:
        return 0
    state, detail = repo_choice(find_home())
    if state == "retired":
        print(f"system-one: down ({retired_line(detail.split(', '))})")
    elif state in ("off", "malformed"):
        print("system-one: off in this repo")
    elif state == "missing":
        print("system-one: not chosen here")
    else:
        ok, detail = health(cfg["endpoint"], cfg)
        print(f"system-one: on ({cfg.get('model') or 'model unnamed'})" if ok
              else f"system-one: down ({detail})")
    return 0


def _status(as_json: bool, brief: bool = False) -> int:
    if brief:
        return _brief()
    home = find_home()
    info: dict = {"state": "off"}
    try:
        cfg = load_config()
    except Unavailable as e:
        cfg = None
        info["reason"] = str(e)
    if cfg is not None and repo_choice(home)[0] != "on":
        info["reason"] = REPO_REASONS[repo_choice(home)[0]]
    elif cfg is not None:
        ok, detail = health(cfg["endpoint"], cfg)
        info.update({"state": "on", "endpoint": cfg["endpoint"], "model": cfg.get("model", ""),
                     "class": endpoint_class(cfg["endpoint"], cfg), "health": detail if not ok else "ok",
                     "key": ("set" if _key(cfg) else "unset") if cfg.get("key_env") else "none"})
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
        for k in ("endpoint", "model", "class", "health", "key", "registry_version"):
            print(f"  {k}: {info[k]}")
    return 0


def _load_json_or_text(path: str):
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        return text


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


def _eval_join_items(pts: list, home, pick: bool) -> list:
    """Each (item, open order) pair once, as the drain chooses them: `_join_item` plus its `item` and `wo`."""
    out, asked = [], set()
    cand = _loose_ends().join_candidates(
        home, [(p["id"], p["text"]) for p in pts], sm=sys.modules[__name__],
        pick=(lambda ref, text, opts: pick_orders(home, ref, text, opts)) if pick else None)["join"]
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


def eval_drain(path: str, home) -> dict:
    """Ask `loose-end-state` for each labelled item and `loose-end-join` for each (item, open order)
    candidate, cache off, and compare with the labels. Hand-back is an `escalate` (a `closable` is
    settled: its confirm is a separate step). Writes nothing in the home; raises `Unavailable` when off or
    a call fails."""
    pts = _drain_points(path)
    home = Path(home)
    _active_config(home)
    state_out = {it["ref"]: decide("loose-end-state", it["ref"], it["state"], home=home, fresh=True)["outcome"]
                 for it in _eval_state_items(pts)}
    join_out = [(j2, decide("loose-end-join", j2["ref"], j2["state"], home=home, fresh=True)["outcome"])
                for j2 in _eval_join_items(pts, home, True)]
    return _eval_report(pts, state_out, join_out)


def eval_export(path: str, home, out_path) -> dict:
    """The labelled set as an export file (see `helper_export`); the labels are not in it. No model call."""
    pts = _drain_points(path)
    items = _eval_state_items(pts) + _eval_join_items(pts, Path(home), False)
    doc = helper_export(items)
    _write_export(out_path, doc)
    return {"items": len(items), "fingerprint": doc["fingerprint"]}


def eval_answers(path: str, home, doc) -> dict:
    """Score a helper's answers to `eval_export`'s file, exactly as `eval_drain` scores a server's. A stale
    document raises ValueError. Calls are logged with model `helper`."""
    pts = _drain_points(path)
    home = Path(home)
    states = _eval_state_items(pts)
    joins = _eval_join_items(pts, home, False)
    applied = helper_apply(states + joins, doc)
    _helper_log(home, states + joins, applied)
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
        d = eval_drain(args.file, _resolve_home(args.home))
    except ValueError as e:
        print(f"eval-drain: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"eval-drain: cannot read {args.file}: {e}", file=sys.stderr)
        return 2
    print(json.dumps(d) if args.json else format_drain_eval(d))
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
    s.add_argument("--brief", action="store_true", help="one line, or nothing with no machine config")
    rg = sub.add_parser("repo", help="this repo's choice: on, off or status (<home>/system-one.json)")
    rg.add_argument("action", choices=("on", "off", "status"))
    rg.add_argument("rest", nargs="*", metavar="ROOT")
    hp = sub.add_parser("helper", help="the drain helper's model for this repo and where it came from; "
                                       "--set HARNESS MODEL records a pick (no model call)")
    hp.add_argument("root", nargs="?", default=".", metavar="ROOT")
    hp.add_argument("--harness", help="claude or codex (default: detected from the environment)")
    hp.add_argument("--set", nargs=2, metavar=("HARNESS", "MODEL"), help="record the operator's pick")
    mg = sub.add_parser("migrate", help="list (or, with --write, remove) the retired keys of the machine "
                                        "config and the repo's system-one.json")
    mg.add_argument("root", nargs="?", default=".", metavar="ROOT")
    mg.add_argument("--write", action="store_true", help="remove the keys; every other key stays")
    su = sub.add_parser("setup", help="find and check a local server, then write the machine config")
    su.add_argument("--endpoint", help=f"default {SETUP_ENDPOINT}")
    su.add_argument("--write", action="store_true", help="write the machine config")
    su.add_argument("--force", action="store_true", help="overwrite an existing machine config")
    su.add_argument("--detect", action="store_true", help="quiet: one line if a server answers, else nothing")
    uc = sub.add_parser("uses-check", help="send every registered use to the server and check each answer "
                                           "parses for its declared type (decides nothing)")
    uc.add_argument("--endpoint", help="a server to check (default: the machine config's)")
    uc.add_argument("--json", action="store_true")
    a = sub.add_parser("ask", help="ask the configured model")
    a.add_argument("--state", required=True)
    a.add_argument("--questions", required=True)
    a.add_argument("--json", action="store_true")
    lg = sub.add_parser("log", help="call log")
    lg.add_argument("--summary", action="store_true")
    lg.add_argument("--use")
    lg.add_argument("--json", action="store_true")
    dr = sub.add_parser("drain", help="ask the loose-end questions and write one proposal file each under "
                                      "<home>/drain/pending/ (the one command that writes in the home); "
                                      "also: accept ID | decline ID | withdraw ID | defer ID | status")
    dr.add_argument("rest", nargs=argparse.REMAINDER,
                    help="<home>; or accept ID --work-order NNN [--slice NAME] | --question Q | --reason R [ROOT]; "
                         "decline ID --reason R [--route DEST] [ROOT]; withdraw ID [ROOT]; defer ID [ROOT]; status [ROOT]")
    dr.add_argument("--json", action="store_true")
    dr.add_argument("--fresh", action="store_true", help="ask every item again; skip the cache")
    ed = sub.add_parser("eval-drain", help="ask the drain's uses on labelled loose ends and compare with the labels")
    ed.add_argument("file", help="JSONL: id, text, source, age_days, expect_state "
                                 "(closable|ask-operator|park|open), expect_join (WO-NNN or null)")
    ed.add_argument("--home", required=True, help="the home directory (or the repo root that holds it) whose open orders are the join candidates")
    ed.add_argument("--export", metavar="OUT", help="write the questions of the labelled set to OUT for a helper "
                                                    "(no model call; the title pick is skipped)")
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
    given = sys.argv[1:] if argv is None else list(argv)
    if given and not given[0].startswith("-") and given[0] not in sub.choices:
        print(f"system_one.py: unknown command {given[0]!r}; run system_one.py --help", file=sys.stderr)
        return 2
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            return _status(args.json, args.brief)
        if args.cmd == "repo":
            return _repo_cli(args)
        if args.cmd == "helper":
            return _helper_cli(args)
        if args.cmd == "migrate":
            found = migrate(args.root, args.write)
            if found:
                print(("migrated: " if args.write else "to migrate: ")
                      + "; ".join(f"{', '.join(n)} in {p}" for p, n in found))
            return 0
        if args.cmd == "setup":
            return _setup_cli(args)
        if args.cmd == "uses-check":
            return _uses_check_cli(args)
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
            skipped: list = []
            log_rows(skipped=skipped)
            if args.json:
                print(json.dumps(stats))
            else:
                for u, st in stats.items():
                    print(u + ": " + ", ".join(f"{k}={v}" for k, v in st.items()))
                if not stats:
                    print("no log rows")
                if args.summary:
                    print(f"skipped lines (not valid JSON): {len(skipped)}")
            return 0
        if args.cmd == "drain":
            return _drain_cli(args)
        if args.cmd == "eval-drain":
            return _eval_drain_cli(args)
        if args.cmd == "lenses":
            return _lenses_cli(args)
        return _scope_cli(args)
    except Unavailable as e:
        print(f"unavailable: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
