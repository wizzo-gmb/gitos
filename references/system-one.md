# System One: an optional local decision model

The engine makes many small, repeated judgments (loose-end state and joins, parked triggers,
duplicates, proposal screening). **System One** lets a script ask a small local model a typed question instead of spending a
pass of the reasoning model. Implemented by `scripts/system_one.py` (client, cascade, log, CLI) and
`scripts/system_one_questions.py` (the single registry of question wording and decision tables).
**Opt-in per repo, invisible when off:** with no machine config (or a repo that has not chosen) every function reports off, no file is created, no
network call is made and the canary prints nothing new.

## The cascade

code rules -> **local decision model** -> the reasoning model -> the operator. The model answers small
typed questions (`noul` yes/no, `choice`, `score`); a **table in code** decides. `decide(use, item, state,
second_state=None)` asks the use's questions, settles each probability (`yes` above 0.7, `no` below 0.3,
otherwise `unsure`), applies the table, and on any `unsure` runs **one** second pass (the caller's
enriched `second_state`, and/or the configured `second` model; two models disagreeing is `unsure`).
Still unsure: outcome `escalate`. Never more than two passes. A failed call raises `Unavailable`; it is
never read as a "no".

## The action rule

Each table outcome is declared `reversible` or `confirm`. A `confirm` outcome is only ever **reported**:
no engine script applies it. Writing callers guard with `require_reversible(result)`, which raises on a
`confirm` outcome. The orchestrator reads the item and confirms it itself.

## What System One is for

System One is for decisions made **out of pass**: the loose-ends drain, the Parked sweep, intake screening,
the log scan and brain duplicate pairs. These run between orders on many small items that no pass is
holding, and a cheap local model reads them well. **In-pass decisions stay with the reasoning model**: reading
implementer notes, scoring a work-order, deciding which lens applies and judging a hunk happen while the
orchestrator is already reading the order or the diff, and a second read by another model adds work instead of
saving it, so no use makes them. `lenses` only lists the active set, and `scope` is a code rule on the paths a
work-order names.

## Config

Two levels. **The machine config** says a server exists; **the repo's choice** says this repo uses it. A
repo is on only with both: the machine config and a literal `{"enabled": true}` in `<home>/system-one.json`
(tracked, like `lenses.json`). `{"enabled": false}`, a missing file, or a malformed file means off, and the
reason is said: "not configured on this machine", "this repo has not chosen (run upgrade or `system_one.py
repo on`)", "this repo turned System One off", "this repo's system-one.json is malformed". Inception and
upgrade ask the question; `system_one.py repo on|off|status [ROOT]` writes and shows it (atomically, keeping
unrelated keys). `system_one.py status --brief` prints one line (`system-one: on (<model>)`, `off in this
repo`, `not chosen here`, `down (<reason class>)`), and nothing with no machine config.

Machine file `~/.claude/gitos-system-one/config.json` (`GITOS_SYSTEM_ONE_HOME` overrides the directory):

| field | meaning |
|---|---|
| `endpoint` | URL of the server (a bare origin gets `/v1/systemone`) |
| `model` | label sent as `model` |
| `second` | optional `{endpoint, model}` for a second opinion |
| `timeout_s` | default 20 |
| `thresholds` | `{yes: 0.7, no: 0.3}` |
| `workers` | the most concurrent requests, default 4 (never more than the use's questions) |
| `keep_examples` | default true: the log keeps the state text |
| `key_env` | the NAME of an environment variable holding a key; the key is never written or printed |
| `trusted_hosts` | exact hosts or CIDR ranges treated as local (see Other machines) |
| `allow_remote` | permit a non-local endpoint (state is scrubbed) |

Every question of a use is its own request with the same state, sent concurrently (at most `workers`
threads); the decision's call row records `requests: N`, and any one failed request makes the decision an
error and nothing is applied.

**Retired keys.** The readers know only the current keys. A machine config or `<home>/system-one.json` that still
carries a retired key (`RETIRED_KEYS` in `system_one.py`: `group`, `questions_per_request`, `assists`) makes System
One unavailable, with no request and no traceback: `status --brief` prints `system-one: down (config has retired
keys: <names>; run /gitos upgrade)`. `system_one.py migrate [ROOT] [--write]` lists the retired keys of both files;
`--write` removes them atomically and keeps every other key (a key on a line of its own is cut out and the other
lines stay byte for byte). With nothing to do it prints nothing and exits 0. `upgrade` runs `migrate --write`.
The next cleanup adds its keys to `RETIRED_KEYS`.

Retries: 429 and 5xx, 3 tries.

## Privacy

Local by default. An endpoint is `loopback`, `trusted-lan` or `remote` (`status` shows which). A remote
host is refused unless `allow_remote: true`; when allowed, `scrub()` replaces e-mail addresses and digit
runs of 7 or more in every state, and callers that pass `local_only=True` are refused outright.

## Other machines

The serving machine binds the network and demands a token. A client lists the server in `trusted_hosts`
(exact host or CIDR; matched on the literal host in the URL, a hostname only by exact string, no DNS
lookup decides trust) and sets the variable named by `key_env`; the key is sent as
`Authorization: Bearer <key>`. A trusted non-loopback endpoint without a key is refused with a message
naming the variable. Trusted endpoints are local: no scrubbing, `local_only` callers allowed. Traffic on
a plain LAN is unencrypted HTTP: state text and the token are visible to anyone on that network, which
the operator accepted for a private LAN. Where that is not acceptable, use a VPN or TLS.

## Answer shapes

Both are normalized to `{id: {"type", "value", "probabilities", "p"}}`, `p` being P(true) for a noul and
P(top) otherwise: the TypeSafe shape (typed per-answer objects: `{"type": "noul", "noul": 0.98}`,
`{"type": "choice", "choice", "confidence", "probabilities"}`) and the pplx shape (the answer carries a
`noul` / `choice` / `score` key plus `probabilities`; `type` may be absent). Anything else raises.

## The call log

Append-only JSONL at `~/.claude/gitos-system-one/log/<repo-key>.jsonl` (repo key: the federation id when
`<home>/federation.json` has one, else a sha1 of the resolved repo root). A call row has time, use, item,
registry version, pass, per-question `p`, outcome, settled `inputs`, model, latency, input tokens, `sha`
(sha256 of the exact state text), and the state only when `keep_examples`. **Safe to write from several
processes:** each row is one `os.write` to an `O_APPEND` descriptor taken under an exclusive lock on
`<log>.lock` (`msvcrt.locking` on Windows, else `fcntl.flock`); a lock not taken within 2 seconds skips
the write, so the log never breaks a decision.
`log --summary` prints how many lines were skipped as not valid JSON.

**The cache.** Before a request, `decide` looks in this repo's log for an earlier `call` row with the same
`use`, `registry`, model and `sha`; a hit returns that row's outcome and inputs (`cached: true`), makes no
request and writes no row. An `escalate` or `error` row, and a row without `sha` or `inputs`, is never
reused. `triage --fresh` and `decide(..., fresh=True)` skip it; the digest marks cached lines `[cache]`. CLI: `status [--json]`, `ask --state F --questions F`,
`log --summary [--use U]`, `uses-check [--endpoint URL] [--json]` (every use against a server; see *Machine setup*).

## Canary

Optional category `system-one`, absent when off: `endpoint-down`, `registry-invalid`. Report-only.

## The ledger uses and `triage`

`system_one.py triage <home> [--json] [--fresh]` gathers items in code, asks the uses below,
and prints a **digest**: one line per settled item (`ok  <ref>  <suggestion>  [pass N]`), full
text plus the answers for every `READ` item (a `confirm` outcome, or an `escalate` that
names its cause: `unsure: <question ids>` or `conflict: <the answers that clash>`), then counts. It
reads the home and writes nothing in it. Off or down: one line, exit 0, no partial output. Suggestions
are never written under an `Adjudication` heading (every digest line starts with a marker, and text is
printed behind `  | `); the orchestrator reads the digest and writes the block. The groups are the open Parked rows
(`parked-trigger`), candidate duplicate pairs (`duplicate`) and the loose ends (below); implementer notes are never
judged.

| use | item | outcomes (`confirm` marked) |
|---|---|---|
| `loose-end-join` | a (loose end, open work-order) pair chosen by `loose_ends.py candidates`: "the item is about the same part of the product as the order" (a relatedness check, not a need) | `join`, `separate` |
| `loose-end-pick` | an item and the open orders' titles (named by WO id), built per call by `system_one.pick_orders`; proposes join candidates only | a WO id (a choice; the registry carries a sample for `uses-check`) |
| `loose-end-bundle` | a pair of loose ends chosen by code: "one order could do both together" | `bundle`, `apart` |
| `parked-trigger` | an open Parked row, with commit subjects since `Parked on`, WO titles, the version | `fired`, `waiting` |
| `loose-end-state` | an item of `<home>/loose-ends.md`: its text, Source and age in days; three questions read in order (`says_done`, `needs_operator`, `waits_on_event`) | `closable`*, `ask-operator`, `park`, `open`, `escalate` |
| `duplicate` | a candidate pair chosen by code (shared WO/P ids or paths, word overlap) | `fold`*, `distinct` |
| `probe` | a text (status check and gate only; judges nothing real) | `greeting`, `other` |
| `proposal-area` | a pending intake proposal | one of nine area names (`canary`, `ledger`, `federation`, `model-optimization`, `harness`, `brain`, `roles-and-docs`, `operator-pages`, `other`) |
| `proposal-severity` | a pending intake proposal | `low`, `medium`, `high`, `critical` |
| `proposal-engine-change` | a pending intake proposal | `engine-change`, `no-engine-change` |
| `proposal-duplicate` | a (proposal, work-order) pair chosen by code | `likely-duplicate`, `distinct` |
| `card-group` | a board card (title, why, option labels) | `close-or-keep-open`, `decisions`, `your-actions`, `parked-work` |
| `brain-duplicate` | a brain page pair chosen by code (title tokens, shared tags, shared links) | `merge-candidate`*, `distinct` |
| `line-anomaly` | a log-line template: the template, one example line, the vocabulary's description of normal output | `abnormal`, `normal` |
| `line-family` | the same state, for a template judged abnormal or unsure: a choice over the anomaly family names parsed from `references/anomaly-families.md` at run time, plus the noul `fits_a_family` | a family name, `no-family` |

The proposal and card uses annotate only. Commands that print them (all write nothing; off or down: one line, exit 0):
`system_one.py screen <home> [--registry R] [--json]` (the federation intake listing plus proposal-* annotations; proposal-* uses, `local_only`, annotations are registry names and work-order ids
only), `system_one.py cards --items FILE [--home H] [--json]` (a group per card, never an option),
`system_one.py lenses <home> (--wo NNN | --text FILE) [--global-dir D] [--json]` (no model call: it lists the active set of `<home>/lenses.json` with each lens's domain and when-to-apply, and prints one line when lenses are
off; the repo wins a name collision; global layer `<skill>/agents`, or `--global-dir`, or `GITOS_GLOBAL_LENS_DIR`; verdicts `applies` /
`maybe` / `no`; a lens that cannot be judged is listed as a problem, never dropped),
`system_one.py brain-dupes <home> [--json]` (candidate pairs from a code prefilter; `merge-candidate` is reported,
never merged). `escalate` on a lens or a page pair never drops the item.

**System One never routes into the brain.** Whether a fact is plain from the code cannot be judged from a note
(measured on hand-labelled points: both models sent the same behaviour rules, about a third of them right), so no use
reads implementer notes or returns `brain`. `brain-dupes` says only that two pages look alike; the orchestrator
alone decides and writes brain pages.

**The `loose-ends` group.** `triage` reads `<home>/loose-ends.md` with no flag (no file: no group). Each
`new` item is asked `loose-end-state`: the item says it is
done -> `closable` (confirm); else it asks the owner -> `ask-operator`; else it waits on a named event -> `park`;
all three no -> `open`; an unsure answer that the table reads escalates (an unsure `waits_on_event` does not
escalate an item that says it is done). `superseded` is not an outcome here: an item another order already covers
is found by `loose-end-join` or `duplicate`, which see the other order. Then each (item, open order) join
candidate and each (item, item) bundle candidate is asked, all chosen by code. An item's join candidates are chosen in three steps, none of them a model's decision. (1) A shared reference or path
ranks first. (2) **BM25** over each open order (its title counted twice, read up to `## Implementer notes`, or the
first 4,000 characters; a Proposed fix scope heading is not needed; k1 1.2, b 0.75) gives the item's best three, in
progress or not (the drain only proposes; the orchestrator decides); a long order gains nothing from its length.
(3) **The title pick** (`loose-end-pick`) finds what words cannot: one `choice` question, "Which of these work orders
is about the same part of the product as this item?", with the open orders' titles as options (named by WO id, the
best 26 by BM25 when there are more), asked once per item and again with the options reversed, the probabilities
averaged (a choice leans to the first option); its top two orders join the candidates, unique. There is **no minimum
score**, then `loose-end-join` (the noul) decides, up to 60 pairs a run, taken best first across the items, each pair
once; `loose_ends.py join_candidates(home,
[(ref, text)])` serves any item text, on the list or not, to `drain` and `eval-drain`. An item waiting on the operator is
asked nothing. The digest lists each item's state, then its best join, then the bundles as groups (pairs joined by
code into connected groups), then **one `plan` line per item** naming the suggested next step, built by code:
`close (confirm)`, `ask the operator`, `park (trigger: ...)` come from the state; otherwise `related open order: consider adding WO-NNN` (kind `join`) beats
`bundle with L<a>, L<b> -> new order`, which beats `open` alone (`read it`). Nothing is applied. `closable` and
`fold` stay `confirm` outcomes; `join` and `bundle` are reversible because the orchestrator still writes the
order.

**`system_one.py drain <home> [--json] [--fresh]`** is the one command that writes in the home. It runs the
loose-ends group (state, joins, bundles) and writes one file per proposal, `<home>/drain/pending/<id>.md`, in the
shape of the federation intake: the id is the first 12 hex characters of a sha256 over the proposal's kind, its sorted
item ids and (for a join) the target order, so a re-run updates the same file (and leaves it alone when the body is
unchanged). Kinds: `join` (items to one open order), `new-order` (a bundle group, or one open item with no join),
`read` (an unsure item), `park` (with the trigger words found in the item), `ask` (the item as the question), `close` (confirm). An item the model
could not settle (`escalate`) becomes its own `read` proposal (one item, with the answers that were unsure), so it never vanishes; `accept` takes the same `--work-order` / `--parked` / `--reason` forms once the orchestrator has decided what it is. Each file has a header (id, kind, items, target, created, updated, model)
and the items in full with Source and age, plus context gathered by code: the Source orders and their titles, paths and
backticked names found, open orders that share those paths, the oldest item's age. No sentence is model-written. A
fingerprint declined before (`drain/declined/<id>.md`) is not proposed again; a pending file the run no longer produces
(its items left the list, or the answers regrouped them) is removed. A join proposal means "related to this open order": the orchestrator decides whether the items belong in that order, its next slice, or elsewhere. A join proposal whose target is in progress (a worktree exists, or its Implementer notes are started) says so in its header and body: `target in progress: <why>`; it is the same kind, and the orchestrator decides whether the item waits for the next slice, without changing a running slice's scope. `drain accept ID --work-order NNN [ROOT]` refuses
unless `work-orders/` holds an open WO-NNN (a resolved order, or a join whose target is resolved, is refused
with one line before anything changes), drops the items still on the list with `loose_ends.py drop --to WO-NNN`, and
moves the file to `drain/accepted/` with `accepted: WO-NNN, <date>` (a `park` takes `--parked P<n>`, a `close` takes
`--reason`, an `ask` only moves). `drain decline ID --reason R` refuses without a reason, moves the file to
`drain/declined/` and leaves the items. `drain defer ID` changes nothing. `drain status [ROOT]` prints
`drain: N pending (J join, B new-order, Q ask, P park, C close, R read)`, or nothing with no pending folder. Bodies are
shown in full: they are built from the repo's own list and code, so none of the federation intake's foreign-text
handling applies. The orchestrator reports the status line at first action and authors every order itself.

**`system_one.py eval-drain --home HOME FILE [--json]`** measures the drain against labels. FILE is JSONL, one item
per line: `{"id": "L<n>", "text": "...", "source": "...", "age_days": N, "expect_state":
"closable|ask-operator|park|open", "expect_join": "WO-NNN" | null}`. It asks `loose-end-state` for each item and
`loose-end-join` for each (item, open order of HOME) candidate chosen as triage does, cache off, and
prints the hand-back rate (items that escalate), the state accuracy on the settled items, and the join precision
and recall (an item's join is its first `join` pair). It writes nothing in the home; calls are logged.

## The diagnostic scan

`system_one.py scan <home> FILE... [--max-templates N] [--json]` is a reading order for the diagnostic role's scan phase; it writes nothing. **Code first:** lines are grouped by template (strings, uuids, timestamps, hex ids and numbers masked); each template keeps its count, the `file:line` of its first and last occurrence and up to 3 raw examples. Templates that `<home>/log_vocabulary.md` marks normal are counted and set aside, never sent: mark one with a bullet `normal: <line>` (`expected:` also works; a trailing `*` makes it a prefix; a leading timestamp is ignored); the entries also form the description of normal output in each state. **Then the model:** `line-anomaly` per remaining template, `line-family` for each one judged abnormal or unsure. `--max-templates` (default 40) caps the model calls (each of the two decisions counts as one), so a huge log costs a bounded amount; templates ranked first are those with an error-like word, then the rarest; the rest are counted as not judged. **Digest:** per family (the names come from the reference file) the template count, line count and top templates with the `file:line` of the first occurrence and one example, then `abnormal, no family` and `unsure`. It is a reading order, not a finding. Logs may hold secrets, so every call is `local_only`: a remote endpoint is refused and nothing is sent. Off or down: one line, exit 0.

## Scope check

`system_one.py scope <home> NNN [--range A..B] [--json]` is an advisory read-order for a work-order's diff; it writes nothing and asks no model. **By rule:** a changed file matching no path or glob named in the order's `## Proposed fix scope` is `outside-scope`; one matching the paragraph that starts `**Not in scope` is `forbidden`. The order's own file (`work-orders/WO-NNN-*.md`) is never `outside-scope`. The digest lists the two classes and its last line always says that every changed file still has to be read. Default range: merge-base to the branch `wo-NNN`.

## How to add a use

1. Add one `register(...)` entry to `system_one_questions.py` (questions, a table covering every
   combination of settled inputs, each outcome flagged `reversible` or `confirm`); bump
   `REGISTRY_VERSION`. Wording: one judgment per question, concrete and observable, a true answer means
   yes, no case-specific clauses.
2. In the calling script add a subcommand that builds the state, calls `decide`, applies only reversible
   outcomes. Catch `system_one.Unavailable` and fall through to today's path.
3. Add a gate case against `FakeSystemOne` in `.gitos/tools/selftest.py`.

## Machine setup

**Choosing a model.** Any server that answers `POST /v1/systemone` works (see *Answer shapes*). The reference
server is `assets/system-one/serve_general.py MODEL_DIR` with Qwen3.5-9B, loaded BF16 (about 20 GB, alone on the
card). Any instruction model can serve all three question types; any other question type is a 400 `RequestError`.
Every number is raw and uncalibrated, read from the next-token logits with thinking off in the chat template.
`noul`: p(true) is the softmax over the yes and no answer tokens. `choice`: the options are listed as lettered lines
(`A. <name>: <its criteria text>`, at most 26; more is a 400), the model is asked for one letter, and the
probabilities are the softmax over the option letters' tokens; the answer is `{"type": "choice", "choice",
"confidence", "probabilities"}` by option name. A choice leans toward the option listed first: `--choice-passes 2`
(default 1) asks a second time with the options reversed and averages the two sets per option name, **at twice the
requests** (the model call, not the HTTP request count). `score`: the same over levels numbered `1.` to `N.` (at most
9, so a level is one digit token); the answer carries `score` (the level of highest probability, taken from the
level's name when that is a number, else its place), `confidence` and `probabilities` by level; no registered use
asks a score today. `--8bit` loads with bitsandbytes 8-bit when that package is installed in the model environment
and refuses with a message when not. The first request after start is slow; `--warmup` pays it at start. Measure
latency on your own card.
**A test model runs alone on the card:** stop the production service first (`systemctl --user stop system-one`),
or two models share the card and time and memory numbers mean nothing. To compare two models, serve each in turn
and run `python scripts/system_one.py eval-drain --home HOME FILE` on the same labelled set (see *The
`loose-ends` group*); compare the hand-back rate, the state accuracy and the join precision and recall, and for BF16 against 8-bit compare the same
numbers on the same file.

**After any model change, run `system_one.py uses-check [--endpoint URL] [--json]`.** It builds one request per
registered use from that use's own questions and a short neutral text (`A short test text for checking the
connection.`, or the use's `sample` entry when the registry gives one), sends it to the configured server (or to
`--endpoint`, so it can run in *Machine setup* before the config is written), and checks that each answer parses
through `normalize_answer` **as the declared type** (a choice names one of its options with a probability for each; a
noul answered to a choice question fails). It prints `ok <use> (<n> questions)` or `FAIL <use>: <reason>` per use and
a count, and exits 1 when any use fails (2 when there is no endpoint or it is not loopback or trusted). It decides
nothing. With a machine config it logs one `kind: "check"` row per use (`ok`, `reason`,
`model`, `latency_ms`); `check` rows are never `call` rows, so the cache and `log --summary` ignore them.
Without a config it writes nothing.

**A dead GPU is not hidden.** The server exits non-zero after a CUDA or accelerator error (the exception type or
message names CUDA, `AcceleratorError` or `cudaError`; **not** an out-of-memory error, which is per request: it answers 500, releases cached memory and keeps serving), after answering that request with 500, so `Restart=on-failure`
restarts it; other errors keep returning 500 and the server stays up. `GET /health` runs one tiny real decision
(kept for 30 seconds) and answers 503 with `"status": "model-failed"` when it fails, so `setup`, `status` (which probes `/health`; `status --brief` prints
`system-one: down (model-failed)`) and an operator's `curl` see the truth. `GET /v1/models` only lists the model and does not run one.

**Keep each state small.** Time grows with tokens. The engine already caps what it
sends per item; write new uses so the state is the few facts the question needs, not a whole document.

**WSL2 or Linux steps.**

1. Install `uv` and a C compiler: `sudo apt install build-essential`, then `curl -LsSf https://astral.sh/uv/install.sh | sh`.
2. Make the environment: `uv venv --python 3.12 ~/system-one/venv`, then `source ~/system-one/venv/bin/activate`.
3. Download the checkpoint (`hf download Qwen/Qwen3.5-9B --local-dir models/qwen3.5-9b`, run in `~/system-one`;
   BF16, about 20 GB).
4. Install into the venv what the server imports, with `uv pip install torch transformers` (a transformers
   release that loads Qwen3.5; `bitsandbytes` only for `--8bit`).
5. Copy `assets/system-one/serve_general.py` into `~/system-one` and test it by hand:
   `python serve_general.py models/qwen3.5-9b --warmup`, then
   `curl http://127.0.0.1:8765/health`.

The server answers `POST /v1/systemone`, `GET /health` and `GET /v1/models`. One request runs on the model at a
time. Request bodies are never logged. A non-loopback `--host` is refused unless `--token-env NAME` names an
environment variable that holds a token; the token is compared in constant time and never printed.

**Machine config.** Last step: `python scripts/system_one.py setup`. It looks only at
`http://127.0.0.1:8765/v1/systemone` (or the `--endpoint` you give; it never scans other ports or hosts) and
checks, in order, that `/health` answers `status: ok` with a model name, that `/v1/models` lists it, and that
one `probe` decision comes back with probabilities, printing each step. Something that answers but fails a
check is reported as not a System One server and nothing is written. Without `--write` it prints what it
would write; `setup --write` writes `~/.claude/gitos-system-one/config.json` (`endpoint`, `model`,
`timeout_s`) atomically, never over an existing one without `--force`, and refuses a non-loopback endpoint
whose host is not in `trusted_hosts`. `setup --detect` is the quiet form for inception and upgrade (one
line if a server answers, else nothing, 2-second timeout). Then `system_one.py status`, and in each repo
`system_one.py repo on`. You can still write the file by hand (see *Config*), for example
`{"endpoint": "http://127.0.0.1:8765", "model": "qwen3.5-9b"}`. When the engine runs on
Windows and the server in WSL2, WSL2 forwards `localhost`, so the loopback URL works unchanged.

**Auto-start.**

- *Linux, or WSL2 with systemd enabled* (`systemd=true` under `[boot]` in `/etc/wsl.conf`): a user unit
  `~/.config/systemd/user/system-one.service` with `ExecStart=%h/system-one/venv/bin/python
  %h/system-one/serve_general.py models/qwen3.5-9b --host 0.0.0.0 --port 8765 --token-env SYSTEM_ONE_TOKEN --warmup`
  (with `WorkingDirectory=%h/system-one`; drop `--host 0.0.0.0` and `--token-env` to serve loopback only), `Restart=on-failure`, and
  `WantedBy=default.target`; then `systemctl --user enable --now system-one` and, on a plain Linux machine,
  `loginctl enable-linger $USER` so it runs without a login. Put a token in the unit with
  `EnvironmentFile=` pointing at a file only you can read, never in the unit text.
- *WSL2 on Windows:* the distro stops when nothing uses it. Add a Task Scheduler task that runs at logon:
  `wsl.exe -d <distro> -- sleep infinity`, which starts the distro (and with it the user unit) and keeps it up.

**Serving other machines.** On the serving machine start with `--host 0.0.0.0 --token-env SYSTEM_ONE_TOKEN`
(or the address of one interface) and the variable set. In WSL2 the distro sits behind a virtual network, so
forward the port from Windows: `netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8765
connectaddress=<WSL2 address> connectport=8765` (the WSL2 address changes on restart; re-run the command from
the logon task), and add a firewall rule for inbound TCP 8765 whose remote address is limited to the local
subnet. On each client list the server in `trusted_hosts` (exact host or CIDR), set `endpoint` to its URL, and
set `key_env` to the NAME of a variable that holds the token on that client. Plain HTTP on a LAN is
unencrypted: the token and the state text are visible to anyone on that network (see *Other machines*).

**Windows settings when the GPU also drives a display.** A long job on the card can make Windows reset the
driver and the server die with a CUDA error. Raise the timeout: registry `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers`,
DWORD `TdrDelay` (for example 30 seconds), then reboot. In the NVIDIA control panel set *CUDA - Sysmem Fallback
Policy* to *Prefer No Sysmem Fallback*, so a model that does not fit fails fast instead of spilling into
system memory and crawling.
