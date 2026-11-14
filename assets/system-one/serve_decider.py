"""Serve a pplx-decider checkpoint as POST /v1/systemone on loopback (reference server for gitos System One).

Usage: python serve_decider.py CHECKPOINT_DIR [--port 8765] [--host 127.0.0.1] [--fast] [--max-batch 16]
                               [--max-length 32768] [--token-env NAME] [--warmup]

Binding anything but loopback requires --token-env: the named environment variable holds a shared token,
and every POST must carry "Authorization: Bearer <token>". The token is never printed.

One model, one GPU: requests are queued and answered in micro-batches by a single worker thread, so
concurrent clients share forward passes instead of contending for the device. GET /health answers once the
model is loaded. Nothing is logged but one line per batch (count, milliseconds); request bodies are never
written anywhere.

--warmup sends one tiny request through the model before the server starts listening, so the first real
call does not pay the one-off kernel compile. The model library is imported from the checkpoint
directory at run time, so everything up to argument parsing works without torch installed.
"""
import argparse, hmac, json, os, queue, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--fast", action="store_true")
ap.add_argument("--max-batch", type=int, default=16)
ap.add_argument("--max-length", type=int, default=32768)
ap.add_argument("--token-env", default=None)
ap.add_argument("--warmup", action="store_true")
args = ap.parse_args()

TOKEN = os.environ.get(args.token_env) if args.token_env else None
if args.host not in ("127.0.0.1", "localhost", "::1") and not TOKEN:
    # checked before anything heavy is imported; the message never carries a token value
    sys.exit("refusing to bind a non-loopback address without a token: pass --token-env NAME and set it")

ckpt = Path(args.checkpoint).resolve()
sys.path.insert(0, str(ckpt / "source" / "src"))
from pplx_decider import Decider  # noqa: E402

t0 = time.time()
decider = Decider.from_pretrained(ckpt, device="cuda", fast=args.fast, max_length=args.max_length)
MODEL = ckpt.name
print(f"loaded {MODEL} in {time.time() - t0:.1f}s (fast={args.fast})", flush=True)
if args.warmup:
    t0 = time.time()
    decider.decide({"state": "hello", "questions": {"w": {"type": "noul", "instructions": "Is this a greeting?"}}})
    print(f"warmup {time.time() - t0:.1f}s", flush=True)

jobs: "queue.Queue[tuple[dict, threading.Event, dict]]" = queue.Queue()


def worker():
    while True:
        batch = [jobs.get()]
        while len(batch) < args.max_batch:
            try:
                batch.append(jobs.get_nowait())
            except queue.Empty:
                break
        t = time.time()
        try:
            outs = decider.decide([b[0] for b in batch])
            for (_, ev, box), out in zip(batch, outs):
                box["ok"] = out
        except Exception:
            # one bad request must not fail its neighbours: answer each alone
            for req, ev, box in batch:
                try:
                    box["ok"] = decider.decide(req)
                except Exception as e:  # RequestError, LengthError, CUDA OOM
                    box["err"] = (type(e).__name__, str(e)[:300])
        ms = (time.time() - t) * 1000
        for _, ev, box in batch:
            box["ms"] = ms
            ev.set()
        print(f"batch {len(batch)} {ms:.0f}ms", flush=True)


threading.Thread(target=worker, daemon=True).start()


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
        if self.path in ("/health", "/v1/models"):
            self._send(200, {"status": "ok", "model": MODEL, "data": [{"id": MODEL}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/systemone":
            return self._send(404, {"error": "not found"})
        if TOKEN and not hmac.compare_digest((self.headers.get("Authorization") or "").encode("utf-8"),
                                                          ("Bearer " + TOKEN).encode("utf-8")):
            return self._send(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n))
            body = {"state": req["state"], "questions": req["questions"]}
            if req.get("images"):
                body["images"] = req["images"]
        except Exception as e:
            return self._send(400, {"error": "bad request", "detail": type(e).__name__})
        ev, box = threading.Event(), {}
        jobs.put((body, ev, box))
        ev.wait()
        if "err" in box:
            name, detail = box["err"]
            code = 400 if name in ("RequestError", "LengthError") else 500
            return self._send(code, {"error": name, "detail": detail})
        out = dict(box["ok"])
        out["model"] = MODEL
        out["model_ms"] = round(box["ms"], 1)
        self._send(200, out)


srv = ThreadingHTTPServer((args.host, args.port), H)
print(f"serving on http://{args.host}:{args.port}/v1/systemone", flush=True)
srv.serve_forever()
