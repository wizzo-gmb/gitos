"""Serve a general instruction model as POST /v1/systemone on loopback (noul, choice and score questions).

Usage: python serve_general.py MODEL_DIR [--port 8765] [--host 127.0.0.1] [--token-env NAME] [--warmup]
                               [--8bit] [--choice-passes 1|2]

HTTP surface: GET /health, GET /v1/models, POST /v1/systemone. Any other
question type is a 400 RequestError naming the type.

noul: p(true) is the softmax over the next-token logits of the yes and no answer tokens (every case and
leading-space form of the two words), read after the chat template with thinking off.
choice: the options are listed as lettered lines (`A. <name>: <criteria text>`, at most 26), the model is
asked for one letter, and the probabilities are the softmax over the next-token logits of the option
letters (upper case, lower case, with and without a leading space). Answer: {"type": "choice", "choice":
<name>, "confidence": <top p>, "probabilities": {<name>: p}}. A choice leans toward the option listed
first; --choice-passes 2 asks a second time with the options reversed and averages the two probability
sets per option name, at twice the requests (the default, 1, asks once).
score: the same method over numbered levels (`1. <level>: <text>`, at most 9, so a level is one digit
token); the value is the level of highest probability. Answer: {"type": "score", "score": <level>,
"confidence": <top p>, "probabilities": {<level name>: p}}.
All numbers are raw and uncalibrated. One request runs on the model at a time (a lock).

Default is BF16 on the first CUDA device. --8bit loads with bitsandbytes 8-bit when that package is
installed and refuses with a clear message when it is not. A test model runs alone on the card: stop any
other model service first.

Binding anything but loopback requires --token-env; the token is never printed.
Nothing heavy is imported before argument parsing, so --help and the token refusal work without torch.

A dead GPU is never hidden. A CUDA or accelerator error while answering (the exception type or message
names CUDA, AcceleratorError or cudaError; an out-of-memory error is per request and only
answers 500 after releasing cached memory) is answered with 500 and then the process exits non-zero, so a
service manager with a restart-on-failure policy brings it back. GET /health runs one tiny real decision
(the result is kept for 30 seconds) and answers 503 with "status": "model-failed" when it fails.
"""
import argparse, hmac, importlib.util, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HEALTH_TTL_S = 30.0
FATAL_EXIT_CODE = 3
_ACCEL_WORDS = ("CUDA", "cuda", "AcceleratorError", "cudaError")
SYSTEM = ("You judge one statement about a piece of text. Read the text, the statement and the two "
          "descriptions, then answer with exactly one word: yes or no.")
YES_WORDS = ["yes", "Yes", " yes", " Yes", "YES", " YES"]
NO_WORDS = ["no", "No", " no", " No", "NO", " NO"]
MAX_CHOICES = 26
MAX_LEVELS = 9
CHOICE_SYSTEM = ("You classify one text. Read the text, the question and the lettered options, then answer "
                 "with exactly one letter: the letter of the option that fits best.")
SCORE_SYSTEM = ("You rate one text. Read the text, the question and the numbered levels, then answer with "
                "exactly one digit: the number of the level that fits best.")
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "123456789"


class RequestError(Exception):
    """The request cannot be answered by this server (a client error, HTTP 400)."""


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token-env", default=None)
    ap.add_argument("--warmup", action="store_true")
    ap.add_argument("--8bit", dest="eight_bit", action="store_true",
                    help="load with bitsandbytes 8-bit (refused when the package is not installed)")
    ap.add_argument("--choice-passes", type=int, choices=(1, 2), default=1,
                    help="2 asks each choice a second time with the options reversed and averages "
                         "(twice the requests); default 1")
    return ap


def check_eight_bit(find_spec=importlib.util.find_spec):
    """Refuse --8bit clearly when bitsandbytes is not installed (without importing it)."""
    if find_spec("bitsandbytes") is None:
        sys.exit("--8bit needs the bitsandbytes package, which is not installed in this environment: "
                 "install it, or serve BF16 by leaving --8bit off")


def is_oom_error(e) -> bool:
    """CUDA out of memory: per request and not sticky, so the server keeps serving."""
    return "OutOfMemory" in type(e).__name__ or "out of memory" in str(e).lower()


def release_cached_memory():
    """After an out-of-memory error, hand the cached blocks back when torch is loaded."""
    torch = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def is_accelerator_error(e) -> bool:
    """True when the exception type or message names CUDA / the accelerator and is not an out-of-memory
    error: the device is not trustworthy and the process must restart."""
    if is_oom_error(e):
        return False
    text = f"{type(e).__name__} {e}"
    return any(w in text for w in _ACCEL_WORDS)


def exit_process(code=FATAL_EXIT_CODE):
    """Leave now, non-zero. A function so a test can replace it."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def validate_request(req):
    """-> (state text, {question id: question}); raises RequestError naming the problem."""
    if not isinstance(req, dict) or "state" not in req or not isinstance(req.get("questions"), dict):
        raise RequestError("a request needs state and questions")
    state = req["state"] if isinstance(req["state"], str) else json.dumps(req["state"])
    for qid, q in req["questions"].items():
        if not isinstance(q, dict):
            raise RequestError(f"question {qid} is not an object")
        kind = q.get("type")
        if kind not in ("noul", "choice", "score"):
            raise RequestError(f"question {qid} has type {kind!r}: this server answers noul, choice and "
                               f"score only")
        if kind != "noul":
            crit = q.get("criteria")
            what = "options" if kind == "choice" else "levels"
            if not isinstance(crit, dict) or not crit:
                raise RequestError(f"question {qid} has type {kind!r} and needs criteria naming its {what}")
            limit = MAX_CHOICES if kind == "choice" else MAX_LEVELS
            if len(crit) > limit:
                raise RequestError(f"question {qid} has {len(crit)} {what}: at most {limit} for type {kind!r}")
    return state, req["questions"]


def user_prompt(state, q):
    crit = q.get("criteria") or {}
    return (f"Text:\n{state}\n\nStatement: {q.get('instructions', '')}\n"
            f"Answer yes when: {crit.get('true', 'the statement is true.')}\n"
            f"Answer no when: {crit.get('false', 'the statement is false.')}\n\n"
            "Is the statement true of the text? Answer yes or no.")


def choice_prompt(state, q, names):
    """The user text of a choice, the options listed in the order of `names` as lettered lines."""
    crit = q.get("criteria") or {}
    lines = "\n".join(f"{LETTERS[i]}. {n}: {crit.get(n, '')}" for i, n in enumerate(names))
    return (f"Text:\n{state}\n\nQuestion: {q.get('instructions', '')}\n\nOptions:\n{lines}\n\n"
            "Which option fits the text best? Answer with the letter only.")


def score_prompt(state, q, names):
    crit = q.get("criteria") or {}
    lines = "\n".join(f"{i + 1}. {n}: {crit.get(n, '')}" for i, n in enumerate(names))
    return (f"Text:\n{state}\n\nQuestion: {q.get('instructions', '')}\n\nLevels:\n{lines}\n\n"
            "Which level fits the text best? Answer with the number only.")


def choice_probs(letter_probs, state, q, passes=1):
    """-> ({option name: probability}, input tokens). `letter_probs(system, user, symbols) -> (one
    probability per symbol, summing to 1, input tokens)` is the model call (replaceable). With two passes the
    second asks the options in reverse order and the two sets are averaged per option name."""
    names = list(q["criteria"])
    orders = [names] + ([names[::-1]] if passes >= 2 else [])
    total, toks = {n: 0.0 for n in names}, 0
    for order in orders:
        ps, n_tok = letter_probs(CHOICE_SYSTEM, choice_prompt(state, q, order), list(LETTERS[:len(order)]))
        toks += n_tok
        for name, p in zip(order, ps):
            total[name] += p / len(orders)
    return total, toks


def score_probs(letter_probs, state, q):
    """-> ({level name: probability}, input tokens), the levels numbered 1..N in the order given."""
    names = list(q["criteria"])
    ps, toks = letter_probs(SCORE_SYSTEM, score_prompt(state, q, names), list(DIGITS[:len(names)]))
    return dict(zip(names, ps)), toks


def _level_value(name, index):
    """The number a score answer carries for a level: its name when that is a number, else its place (1..N)."""
    try:
        return float(name)
    except (TypeError, ValueError):
        return float(index + 1)


def answer_one(q, state, p_true, letter_probs, choice_passes):
    """-> (answer object, input tokens) for one validated question."""
    kind = q["type"]
    if kind == "noul":
        p, n = p_true(state, q)
        return {"type": "noul", "noul": p}, n
    if kind == "choice":
        probs, n = choice_probs(letter_probs, state, q, choice_passes)
        top = max(probs, key=probs.get)
        return {"type": "choice", "choice": top, "confidence": probs[top], "probabilities": probs}, n
    probs, n = score_probs(letter_probs, state, q)
    names = list(probs)
    top = max(names, key=probs.get)
    return {"type": "score", "score": _level_value(top, names.index(top)), "confidence": probs[top],
            "probabilities": probs}, n


def answer_request(req, p_true, model_name, letter_probs=None, choice_passes=1):
    """-> (status code, body, fatal). `p_true(state, question) -> (probability, input tokens)`;
    `letter_probs` is the symbol-probability call of `choice_probs` (choice and score questions)."""
    try:
        state, questions = validate_request(req)
        t = time.time()
        answers, toks = {}, 0
        for qid, q in questions.items():
            answers[qid], n = answer_one(q, state, p_true, letter_probs, choice_passes)
            toks += n
        return 200, {"answers": answers, "model": model_name, "usage": {"input_tokens": toks},
                     "model_ms": round((time.time() - t) * 1000, 1)}, False
    except RequestError as e:
        return 400, {"error": "RequestError", "detail": str(e)[:300]}, False
    except Exception as e:
        if is_oom_error(e):
            release_cached_memory()
        return 500, {"error": type(e).__name__, "detail": str(e)[:300]}, is_accelerator_error(e)


class Health:
    """One tiny real decision, kept for HEALTH_TTL_S. `probe()` raises when the model cannot answer."""

    def __init__(self, probe, model, clock=time.monotonic):
        self.probe, self.model, self.clock = probe, model, clock
        self.at, self.last = None, None
        self.lock = threading.Lock()

    def check(self):
        """-> (status code, body, fatal)."""
        with self.lock:
            now = self.clock()
            if self.at is None or now - self.at >= HEALTH_TTL_S:
                try:
                    self.probe()
                    self.last = (200, {"status": "ok", "model": self.model, "data": [{"id": self.model}]}, False)
                except Exception as e:
                    self.last = (503, {"status": "model-failed", "model": self.model,
                                       "error": type(e).__name__, "detail": str(e)[:300]},
                                 is_accelerator_error(e))
                self.at = now
            return self.last


def load_model(path, eight_bit):
    """-> (tokenizer, model). The heavy imports happen here, after argument parsing."""
    import torch
    import transformers
    tok = transformers.AutoTokenizer.from_pretrained(path)
    kw = {"device_map": {"": 0}, "quantization_config": transformers.BitsAndBytesConfig(load_in_8bit=True)} \
        if eight_bit else {"dtype": torch.bfloat16}
    model, errs = None, []
    for cls in ("AutoModelForCausalLM", "AutoModelForImageTextToText"):
        try:
            model = getattr(transformers, cls).from_pretrained(path, **kw)
            break
        except Exception as e:  # noqa
            errs.append(f"{cls}: {type(e).__name__}: {str(e)[:200]}")
    if model is None:
        sys.exit("could not load the model: " + "; ".join(errs))
    if not eight_bit:
        model = model.to("cuda")
    return tok, model.eval()


def make_p_true(tok, model):
    import torch

    def ids_for(words):
        out = set()
        for w in words:
            t = tok.encode(w, add_special_tokens=False)
            if t:
                out.add(t[0])
        return sorted(out)

    yes, no = ids_for(YES_WORDS), ids_for(NO_WORDS)
    lock = threading.Lock()

    def p_true(state, q):
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(state, q)}]
        try:
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
        except TypeError:
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = tok(prompt, return_tensors="pt").to("cuda")
        with lock, torch.no_grad():
            logits = model(**enc).logits[0, -1].float()
        pair = torch.stack([torch.logsumexp(logits[yes], 0), torch.logsumexp(logits[no], 0)])
        return torch.softmax(pair, 0)[0].item(), int(enc["input_ids"].shape[1])

    return p_true


def make_letter_probs(tok, model):
    """-> `letter_probs(system, user, symbols) -> (probabilities, input tokens)`: the softmax over the
    next-token logits of each symbol (its bare and leading-space forms, upper and lower case)."""
    import torch

    cache = {}

    def ids_for(sym):
        if sym not in cache:
            ids = set()
            for w in {sym, sym.lower(), " " + sym, " " + sym.lower()}:
                t = tok.encode(w, add_special_tokens=False)
                if t:
                    ids.add(t[0])
            cache[sym] = sorted(ids)
        return cache[sym]

    lock = threading.Lock()

    def letter_probs(system, user, symbols):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
        except TypeError:
            prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = tok(prompt, return_tensors="pt").to("cuda")
        with lock, torch.no_grad():
            logits = model(**enc).logits[0, -1].float()
        scores = torch.stack([torch.logsumexp(logits[ids_for(s)], 0) for s in symbols])
        return torch.softmax(scores, 0).tolist(), int(enc["input_ids"].shape[1])

    return letter_probs


PROBE_QUESTION = {"type": "noul", "instructions": "The text is a greeting."}


def make_handler(token, p_true, name, health, letter_probs=None, choice_passes=1):
    """The request handler class. A fatal (CUDA or accelerator) failure is answered first, then the process exits."""

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                code, obj, fatal = health.check()
                self._send(code, obj)
                if fatal:
                    exit_process()
            elif self.path == "/v1/models":
                self._send(200, {"status": "ok", "model": name, "data": [{"id": name}]})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path.rstrip("/") != "/v1/systemone":
                return self._send(404, {"error": "not found"})
            if token and not hmac.compare_digest((self.headers.get("Authorization") or "").encode("utf-8"),
                                                 ("Bearer " + token).encode("utf-8")):
                return self._send(401, {"error": "unauthorized"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n))
            except Exception as e:
                return self._send(400, {"error": "bad request", "detail": type(e).__name__})
            code, obj, fatal = answer_request(req, p_true, name, letter_probs, choice_passes)
            self._send(code, obj)
            if fatal:
                exit_process()

    return H


def main(argv=None):
    args = build_parser().parse_args(argv)
    token = os.environ.get(args.token_env) if args.token_env else None
    if args.host not in ("127.0.0.1", "localhost", "::1") and not token:
        # checked before anything heavy is imported; the message never carries a token value
        sys.exit("refusing to bind a non-loopback address without a token: pass --token-env NAME and set it")
    if args.eight_bit:
        check_eight_bit()

    t0 = time.time()
    tok, model = load_model(args.model, args.eight_bit)
    name = os.path.basename(args.model.rstrip("/\\"))
    p_true = make_p_true(tok, model)
    letter_probs = make_letter_probs(tok, model)
    print(f"loaded {name} via {type(model).__name__} in {time.time() - t0:.1f}s "
          f"({'8-bit' if args.eight_bit else 'bf16'}, choice passes {args.choice_passes})", flush=True)
    if args.warmup:
        t0 = time.time()
        p_true("hello", PROBE_QUESTION)
        print(f"warmup {time.time() - t0:.1f}s", flush=True)

    health = Health(lambda: p_true("hello", PROBE_QUESTION), name)
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(token, p_true, name, health, letter_probs, args.choice_passes))
    print(f"serving on http://{args.host}:{args.port}/v1/systemone", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
