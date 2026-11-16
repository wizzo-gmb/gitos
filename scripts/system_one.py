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
                and r.get("outcome") not in (None, "escalate", "error")
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


_USE_OF = {"parked": "parked-trigger", "duplicates": "duplicate", "loose-ends": "loose-end-state"}


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


def _loose_end_items(home: Path) -> tuple:
    """-> (items, new rows, open orders). Read from `<home>/loose-ends.md` with no flag. Each `new` item is
    asked `loose-end-state`; the (item, open order) join pairs (the item's best three open orders by BM25, in progress or not, plus the model's title pick)
    and the (item, item) bundle pairs are chosen by code (`loose_ends.candidates`). An item waiting on the
    operator is asked nothing."""
    le = _loose_ends()
    if not le.list_path(home).is_file():
        return [], [], []
    rows = [r for r in le.rows_of(home) if r["state"].strip() == le.STATE_NEW and le.ID_RE.fullmatch(r["id"])]
    if not rows:
        return [], [], []
    cand = le.candidates(home, sm=sys.modules[__name__],
                         pick=lambda ref, text, opts: pick_orders(home, ref, text, opts))
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
    """Connected groups of items joined by `bundle` pairs, joined by code: [[L1, L2, L5], ...]."""
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in results:
        if r["use"] == "loose-end-bundle" and r["outcome"] == "bundle":
            a, b = r["ref"].split("~")
            parent[find(a)] = find(b)
    groups: dict = {}
    for x in list(parent):
        groups.setdefault(find(x), []).append(x)
    return sorted((sorted(g, key=lambda t: int(t[1:])) for g in groups.values()), key=lambda g: int(g[0][1:]))


_TRIGGER = re.compile(r"\b(?:after|once|until|when|waits? (?:for|on)|following)\b[^.;]{3,70}", re.I)


def _drain_plan(results: list, bundles: list) -> list:
    """One suggested next step per loose end, built by code from the answers: [{ref, step}]. A step the
    item's own state settles (`close`, `ask`, `park`) comes first; otherwise a `join` answer beats a
    bundle group, and a bundle beats `open` alone (an item still unsettled is `read it`). Nothing is
    applied."""
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
        if out == "closable":
            step, kind = "close (confirm)", "close"
        elif out == "ask-operator":
            step, kind = "ask the operator", "ask"
        elif out == "park":
            m = _TRIGGER.search(r["text"])
            trig = _squash(m.group(0)) if m else "name the event"
            step, kind = f"park (trigger: {trig})", "park"
        elif ref in best:
            step, kind, wo = f"related open order: consider adding {best[ref]}", "join", best[ref]
        elif group:
            step, kind = "bundle with " + ", ".join(x for x in group if x != ref) + " -> new order", "bundle"
        else:
            step, kind = "read it", ("open" if out == "open" else "read")
        plan.append({"ref": ref, "step": step, "kind": kind, "wo": wo})
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


def triage(home, fresh: bool = False) -> dict:
    """Gather, judge, return the digest data. Reads the home, writes nothing in it. Raises
    `Unavailable` (so the caller prints one line and no partial output) when System One is off or a
    call fails."""
    home = Path(home)
    _active_config(home)                                  # Off -> raises before any gathering
    c = _canary()
    parked = _parked_items(home, c)
    loose, loose_rows, _orders = _loose_end_items(home)
    as_dup = [{"ref": r["id"], "text": r["item"]} for r in loose_rows]
    items = parked + _duplicate_items(home, c, parked + as_dup) + loose
    results = []
    for it in items:
        use = it.get("use") or _USE_OF[it["group"]]
        r = decide(use, it["ref"], it["state"], home=home, fresh=fresh)
        results.append({"group": it["group"], "use": use, "ref": it["ref"], "outcome": r["outcome"],
                        "label": r["outcome"], "confirm": r["confirm"], "pass": r["pass"],
                        "inputs": r["inputs"], "text": it["text"], "cause": _cause(r, use),
                        "cached": bool(r.get("cached"))})
    counts = {"settled": 0, "confirm": 0, "escalate": 0}
    for r in results:
        r["review"] = r["confirm"] or r["outcome"] == "escalate"
        counts["confirm" if r["confirm"] else "escalate" if r["review"] else "settled"] += 1
    seen: set = set()
    for r in results:                     # the best join of an item: its first `join` pair (best score first)
        r["best"] = False
        if r["use"] == "loose-end-join" and r["outcome"] == "join":
            item = r["ref"].split("~")[0]
            if item not in seen:
                seen.add(item)
                r["best"] = True
    bundles = _bundle_groups(results)
    return {"registry": _registry().REGISTRY_VERSION, "items": results, "counts": counts,
            "bundles": bundles, "plan": _drain_plan(results, bundles)}


def format_digest(d: dict) -> str:
    """One line per settled item; full text only for `escalate` and `confirm` items. Every line
    starts with a marker (`ok`, `READ`, `|`, `==`, `counts`), never with a markdown heading."""
    out = [f"== system-one triage (registry v{d['registry']}): {len(d['items'])} items =="]
    order = {"fired": 0, "waiting": 1}
    for group in ("parked", "duplicates", "loose-ends"):
        rows = [r for r in d["items"] if r["group"] == group]
        if not rows:
            continue
        rows.sort(key=lambda r: (r["review"], order.get(r["outcome"], 2)))
        if group == "loose-ends":
            # each item's loose-end-state, then its best join; a bundle pair is rolled into a group below
            rank = {"loose-end-state": 0, "loose-end-join": 1, "loose-end-bundle": 2}
            rows = [r for r in rows if r["use"] == "loose-end-state" or r["review"]
                    or (r["use"] == "loose-end-join" and r.get("best"))]
            rows.sort(key=lambda r: (rank[r["use"]], r["ref"]))
        out.append(f"== {group}: {len(rows)} ==")
        for r in rows:
            mark = "READ" if r["review"] else "ok  "
            tag = " (confirm: report only, never applied)" if r["confirm"] else \
                  f" ({r['cause']})" if r["cause"] else ""
            how = f"pass {r['pass']}"
            if r.get("cached"):
                how += "] [cache"
            out.append(f"{mark} {r['ref']}  {r['label']}{tag}  [{how}]")
            if r["review"]:
                for ln in r["text"].splitlines() or [""]:
                    out.append(f"  | {ln}")
                if r["inputs"]:
                    out.append("  | answers: " + ", ".join(f"{k}={v}" for k, v in r["inputs"].items()))
        if group == "loose-ends":
            for g in d.get("bundles", []):
                out.append(f"ok   bundle {' '.join(g)}  (one order could do these together)")
            for p in d.get("plan", []):                 # WO-098: one suggested step per item; nothing applied
                out.append(f"ok   plan {p['ref']}  {p['step']}")
    c = d["counts"]
    out.append(f"counts: settled {c['settled']}, confirm {c['confirm']}, escalate {c['escalate']}")
    return "\n".join(out)


# ------------------------------------------------------------------ the drain proposals (WO-098)
# `drain` is the one System One command that writes in the home: one file per proposal under
# `<home>/drain/pending/`, with a federation-shaped lifecycle (accept by authoring a native order, decline
# with a reason, defer). The proposals are built from our own list and code, so each body is shown in full.
# No sentence is model-written: each is an item's own text or built by code from the answers.
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
        out.append(f"- {ref} (Source: {r['source']}; {age}): {r['text']}")
    if p["kind"] == "join":
        out += ["", "## Target", "", "- related open order: consider adding",
                f"- {p['wo']}: {titles.get(p['wo'], '')}"]
        if p.get("in_progress"):
            out.append(f"- target in progress: {p['in_progress']}")
    if p["kind"] == "park":
        out += ["", "## Trigger words found", "", f"- {p['trigger']}"]
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
    head += [f"- created: {created}", f"- updated: {updated}", f"- model: {model}"]
    return "\n".join(head + _proposal_body(p, rows, ctx, titles)) + "\n"


def _read_proposal(path: Path) -> "dict | None":
    text = _read_text(path)
    if text is None:
        return None
    meta = {}
    for ln in text.splitlines():
        m = re.match(r"- (id|kind|items|target|created|updated|model): (.*)$", ln)
        if m and m.group(1) not in meta:
            meta[m.group(1)] = m.group(2).strip()
    if not meta.get("id") or not meta.get("kind"):
        return None
    meta["item_list"] = [x.strip() for x in meta.get("items", "").split(",") if x.strip()]
    meta["text"] = text
    return meta


def _drain_dirs(home: Path) -> dict:
    return {k: Path(home) / DRAIN_DIR / k for k in ("pending", "accepted", "declined")}


def drain(home, fresh: bool = False) -> dict:
    """Ask the loose-ends group (state, joins, bundles) and write one file per proposal under
    `<home>/drain/pending/`. A proposal declined before (same fingerprint) is not proposed again; a
    pending file this run no longer produces (its items left the list, or the answers regrouped them) is
    removed. Raises `Unavailable` (nothing written) when System One is off or a call fails.
    -> {"counts", "written", "removed", "skipped"}."""
    home = Path(home)
    cfg = _active_config(home)
    c = _canary()
    le = _loose_ends()
    items, loose_rows, orders = _loose_end_items(home)
    results = []
    for it in items:
        r = decide(it["use"], it["ref"], it["state"], home=home, fresh=fresh)
        results.append({"group": it["group"], "use": it["use"], "ref": it["ref"], "outcome": r["outcome"],
                        "text": it["text"], "cause": _cause(r, it["use"])})
    bundles = _bundle_groups(results)
    plan = _drain_plan(results, bundles)
    cause = {r["ref"]: r["cause"] for r in results if r["use"] == "loose-end-state"}
    rows = {r["id"]: {"text": _squash(r["item"]), "source": r["source"], "age": le.age_days(r["added"])}
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
                          "trigger": (p["step"][len("park (trigger: "):-1] if p["kind"] == "park" else "")})
    dirs = _drain_dirs(home)
    now = _now()
    written, skipped, keep = [], [], set()
    for p in props:
        p["items"] = sorted(p["items"], key=lambda t: int(t[1:]))
        p["id"] = drain_id(p["kind"], p["items"], p.get("wo"))
        if (dirs["declined"] / f"{p['id']}.md").is_file():
            skipped.append(p["id"])
            continue
        keep.add(p["id"])
        path = dirs["pending"] / f"{p['id']}.md"
        old = _read_proposal(path) if path.is_file() else None
        ctx = _group_context(home, c, p["items"], rows, orders)
        created = old["created"] if old and old.get("created") else now
        text = _proposal_file(p, created, now, cfg.get("model", ""), rows, ctx, titles)
        if old and re.sub(r"- updated: .*", "", old["text"]) == re.sub(r"- updated: .*", "", text):
            continue                                   # same proposal, same body: leave the file alone
        _write_text_atomic(path, text)
        written.append(p["id"])
    removed = []
    if dirs["pending"].is_dir():
        for f in sorted(dirs["pending"].glob("*.md")):
            if f.stem not in keep and _DRAIN_ID.fullmatch(f.stem):
                f.unlink()
                removed.append(f.stem)
    counts = {k: sum(1 for p in props if p["kind"] == k and p["id"] in keep) for k in DRAIN_KINDS}
    counts["pending"] = sum(counts.values())
    return {"counts": counts, "written": written, "removed": removed, "skipped": skipped}


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
    return (f"drain: {sum(n.values())} pending ({n['join']} join, {n['new-order']} new-order, "
            f"{n['ask']} ask, {n['park']} park, {n['close']} close, {n['read']} read)")


def _drain_dispose(home, pid: str, state: str, note: str, drop_to: "str | None" = None) -> str:
    """Move a pending proposal to `accepted/` or `declined/`, appending the disposition line. `drop_to`:
    drop the proposal's items still on the list to that destination first (`loose_ends.py drop`)."""
    le = _loose_ends()
    dirs = _drain_dirs(home)
    if not _DRAIN_ID.fullmatch(pid or ""):
        raise ValueError(f"{pid!r} is not a proposal id (12 hex characters)")
    src = dirs["pending"] / f"{pid}.md"
    m = _read_proposal(src) if src.is_file() else None
    if m is None:
        raise ValueError(f"no pending proposal {pid} under {dirs['pending']}")
    if drop_to:
        live = {r["id"] for r in le.rows_of(home)}
        try:
            for x in m["item_list"]:
                if x in live:
                    le.drop(home, x, drop_to)
        except le.LooseEndsError as e:
            raise ValueError(str(e))
    dest = dirs[state] / f"{pid}.md"
    _write_text_atomic(dest, m["text"].rstrip("\n") + f"\n\n{state}: {note}, {_now()[:10]}\n")
    src.unlink()
    return str(dest)


def drain_accept(home, pid: str, work_order: "str | None" = None, parked: "str | None" = None,
                 reason: "str | None" = None) -> str:
    """Accept a proposal by the act that carries it out: a `join` or `new-order` needs the native order
    (`work-orders/` holds it, and it must be open: a resolved order, or a join whose target is resolved, is
    refused before anything changes), a `park` needs the
    P<n> row, a `close` needs a reason; an `ask` needs nothing (the items stay on the list)."""
    home = Path(home)
    src = _drain_dirs(home)["pending"] / f"{pid}.md"
    m = _read_proposal(src) if src.is_file() else None
    if m is None:
        raise ValueError(f"no pending proposal {pid}")
    kind = m["kind"]
    listing = {n: r for n, _p, r in _wo_listing(home, _canary())}

    def require_open(nnn: str) -> None:
        if listing.get(nnn):
            raise ValueError(f"WO-{nnn} is resolved: a proposal is accepted into an open order, so nothing "
                             f"was changed (decline it, or author a new order)")
    if kind == "join" and m.get("target"):
        require_open(str(m["target"]).strip().lstrip("WwOo-").zfill(3))
    if work_order and kind in ("join", "new-order", "read"):
        require_open(str(work_order).strip().lstrip("WwOo-").zfill(3))
    if kind in ("join", "new-order"):
        if not work_order:
            raise ValueError(f"a {kind} proposal is accepted with --work-order NNN (author the order first)")
        nnn = str(work_order).strip().lstrip("WwOo-").zfill(3)
        if nnn not in listing:
            raise ValueError(f"no work-order {nnn} under {home / 'work-orders'}: author it first")
        return _drain_dispose(home, pid, "accepted", f"WO-{nnn}", f"WO-{nnn}")
    if kind == "read":                  # the orchestrator decided what the item is: the same three forms
        if work_order:
            kind = "new-order"
        elif parked:
            kind = "park"
        elif reason:
            kind = "close"
        else:
            raise ValueError("a read proposal is accepted with --work-order NNN, --parked P<n> or --reason R")
    if kind == "park":
        if not (parked and re.fullmatch(r"P\d+", parked)):
            raise ValueError("a park proposal is accepted with --parked P<n> (park it in the INDEX first)")
        return _drain_dispose(home, pid, "accepted", parked, parked)
    if kind == "close":
        if not (reason and len(reason.split()) >= 3):
            raise ValueError("a close proposal is accepted with --reason (a few words: what makes it done)")
        return _drain_dispose(home, pid, "accepted", f"closed: {_squash(reason)}", f"closed:{_squash(reason)}")
    return _drain_dispose(home, pid, "accepted", "asked the operator")


def drain_decline(home, pid: str, reason: "str | None") -> str:
    if not reason or not reason.strip():
        raise ValueError("decline needs --reason")
    return _drain_dispose(Path(home), pid, "declined", _squash(reason))


def _drain_cli(args) -> int:
    priv = argparse.ArgumentParser(prog="system_one.py drain", add_help=False)
    priv.add_argument("rest", nargs="*")
    priv.add_argument("--work-order")
    priv.add_argument("--parked")
    priv.add_argument("--reason")
    priv.add_argument("--json", action="store_true")
    priv.add_argument("--fresh", action="store_true")
    try:
        ns = priv.parse_intermixed_args(list(args.rest))
    except SystemExit:
        return 2
    for k in ("json", "fresh"):
        setattr(args, k, getattr(args, k) or getattr(ns, k))
    args.work_order, args.parked, args.reason = ns.work_order, ns.parked, ns.reason
    rest = list(ns.rest)
    act = rest[0] if rest and rest[0] in ("accept", "decline", "defer", "status") else None
    try:
        if act is None:
            if len(rest) != 1:
                print("drain: usage: drain <home> | accept ID --work-order NNN [ROOT] | decline ID --reason R "
                      "[ROOT] | defer ID [ROOT] | status [ROOT]", file=sys.stderr)
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
                  f"{c['park']} park, {c['close']} close, {c['read']} read); {len(d['written'])} written, {len(d['removed'])} removed")
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
        if act == "accept":
            dest = drain_accept(home, rest[1], args.work_order, args.parked, args.reason)
        else:
            dest = drain_decline(home, rest[1], args.reason)
        print(f"{'accepted' if act == 'accept' else 'declined'}: {rest[1]} -> {dest}")
        return 0
    except (OSError, ValueError) as e:
        print(f"drain: {e}", file=sys.stderr)
        return 2


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
# `lenses` and `brain-dupes` read and print: nothing is written in the repo or the
# global lens library. Code gathers and prefilters; the model answers one small question per
# candidate; an unsure answer degrades to "maybe" / "READ", never to a silent drop.
GLOBAL_LENS_ENV = "GITOS_GLOBAL_LENS_DIR"
MAX_BRAIN_PAIRS = 30
TAG_HUB = 8                       # a tag on more pages than this is no signal
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
        d = brain_dupes(home)
        print(json.dumps(d) if args.json else format_brain_dupes(d))
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


def scope_check(home, wo: str, rng: "str | None" = None) -> dict:
    """A code rule on the paths a work-order's scope names: a changed file the scope's Not in scope names
    is `forbidden`, one no scope path names is `outside-scope`. No model; writes nothing."""
    home = Path(home)
    nnn, text, c = _wo_text(home, wo)
    _scope, inside, forbidden = _scope_patterns(text, c)
    root = Path((_git(home, "rev-parse", "--show-toplevel") or str(home.parent)).strip())
    rng = rng or _default_range(root, nnn)
    if not rng:
        raise ValueError(f"no range for WO-{nnn}: no branch wo-{nnn} and no main/master; pass --range A..B")
    names = _git(root, "diff", "--no-renames", "--name-only", rng)
    if names is None:
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
        d = scope_check(home, args.wo, args.range)
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
    """The retired keys found in the machine config and the repo's `system-one.json`: [(path, [names])].
    With `write`, the keys are removed atomically and every other key stays. A file that is missing,
    unreadable or not an object is skipped."""
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


def eval_drain(path: str, home) -> dict:
    """Ask `loose-end-state` for each labelled item and `loose-end-join` for each (item, open order)
    candidate, cache off, and compare with the labels. Hand-back is an `escalate` (a `closable` is
    settled: its confirm is a separate step). Writes nothing in the home; raises `Unavailable` when off or
    a call fails."""
    pts = _drain_points(path)
    home = Path(home)
    _active_config(home)
    rows = []
    for p in pts:
        r = decide("loose-end-state", p["id"], _loose_state(p["id"], _squash(p["text"]), p.get("source") or "unknown",
                                                           p.get("age_days")), home=home, fresh=True)
        rows.append({"id": p["id"], "expect_state": p["expect_state"], "outcome": r["outcome"],
                     "handed_back": r["outcome"] == "escalate", "expect_join": p.get("expect_join"),
                     "join": None})
    by = {r["id"]: r for r in rows}
    asked: set = set()
    for j in _loose_ends().join_candidates(home, [(p["id"], p["text"]) for p in pts], sm=sys.modules[__name__],
                                           pick=lambda ref, text, opts: pick_orders(home, ref, text, opts))["join"]:
        j2 = _join_item(j)
        if j2["ref"] in asked:
            continue                                     # each pair is asked once per run
        asked.add(j2["ref"])
        r = decide("loose-end-join", j2["ref"], j2["state"], home=home, fresh=True)
        if r["outcome"] == "join" and by[j["item"]]["join"] is None:
            by[j["item"]]["join"] = j["wo"]              # the best join of an item: its first `join` pair
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
        d = eval_drain(args.file, _resolve_home(args.home))
    except ValueError as e:
        print(f"eval-drain: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"eval-drain: cannot read {args.file}: {e}", file=sys.stderr)
        return 2
    print(json.dumps(d) if args.json else format_drain_eval(d))
    return 0


def _triage_cli(args) -> int:
    home = Path(args.home)
    if (home / ".gitos").is_dir():
        home = home / ".gitos"
    try:
        d = triage(home, fresh=args.fresh)
    except Off:
        print("system-one: off")
        return 0
    except Unavailable as e:
        print(f"system-one: unavailable ({e})")
        return 0
    print(json.dumps(d) if args.json else format_digest(d))
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
    tg = sub.add_parser("triage", help="digest of ledger judgments (writes nothing in the home)")
    tg.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    tg.add_argument("--json", action="store_true")
    tg.add_argument("--fresh", action="store_true", help="ask every item again; skip the cache")
    dr = sub.add_parser("drain", help="ask the loose-ends group and write one proposal file each under "
                                      "<home>/drain/pending/ (the one command that writes in the home); "
                                      "also: accept ID | decline ID | defer ID | status")
    dr.add_argument("rest", nargs=argparse.REMAINDER,
                    help="<home>; or accept ID --work-order NNN | --parked P<n> | --reason R [ROOT]; "
                         "decline ID --reason R [ROOT]; defer ID [ROOT]; status [ROOT]")
    dr.add_argument("--json", action="store_true")
    dr.add_argument("--fresh", action="store_true", help="ask every item again; skip the cache")
    ed = sub.add_parser("eval-drain", help="ask the drain's uses on labelled loose ends and compare with the labels")
    ed.add_argument("file", help="JSONL: id, text, source, age_days, expect_state "
                                 "(closable|ask-operator|park|open), expect_join (WO-NNN or null)")
    ed.add_argument("--home", required=True, help="the .gitos directory or repo root whose open orders are the join candidates")
    ed.add_argument("--json", action="store_true")
    cd = sub.add_parser("cards", help="suggest a board group per card (picks no option)")
    cd.add_argument("--items", required=True, help="JSON list of cards: id, title, why, options")
    cd.add_argument("--home", default=".", help="the .gitos directory or the repo root")
    cd.add_argument("--json", action="store_true")
    sc = sub.add_parser("screen", help="the intake listing plus a local model's annotation per proposal")
    sc.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    sc.add_argument("--registry", default=None, help="the federation registry directory")
    sc.add_argument("--json", action="store_true")
    ln = sub.add_parser("lenses", help="list the active lenses with their domain and when-to-apply (no model call, writes nothing)")
    ln.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    ln.add_argument("--wo", help="a work-order number")
    ln.add_argument("--text", help="a text file describing the work")
    ln.add_argument("--global-dir", help=f"the global lens library (default: ${GLOBAL_LENS_ENV}, "
                                         f"else <skill>/agents)")
    ln.add_argument("--json", action="store_true")
    bd = sub.add_parser("brain-dupes", help="near-duplicate brain page pairs with a verdict (writes nothing)")
    bd.add_argument("home", help="the .gitos directory (or the repo root that holds it)")
    bd.add_argument("--json", action="store_true")
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
        if args.cmd == "migrate":
            found = migrate(args.root, args.write)
            if found:
                print(("removed retired keys: " if args.write else "retired keys: ")
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
        if args.cmd == "triage":
            return _triage_cli(args)
        if args.cmd == "drain":
            return _drain_cli(args)
        if args.cmd == "eval-drain":
            return _eval_drain_cli(args)
        if args.cmd == "scan":
            return _scan_cli(args)
        if args.cmd == "cards":
            return _cards_cli(args)
        if args.cmd == "screen":
            return _screen_cli(args)
        if args.cmd in ("lenses", "brain-dupes"):
            return _brain_cli(args)
        return _scope_cli(args)
    except Unavailable as e:
        print(f"unavailable: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
