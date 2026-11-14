# System One: an optional local decision model

The engine makes many small, repeated judgments (note routing, parked triggers, duplicates, proposal
screening). **System One** lets a script ask a small local model a typed question instead of spending a
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
| `group` | `single` (one request per question, concurrent) or `joint` (one request) |
| `workers` | concurrency for `single`, default 4 |
| `keep_examples` | default true: the log keeps the state text |
| `key_env` | the NAME of an environment variable holding a key; the key is never written or printed |
| `trusted_hosts` | exact hosts or CIDR ranges treated as local (see Other machines) |
| `allow_remote` | permit a non-local endpoint (state is scrubbed) |

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
registry version, pass, per-question `p`, outcome, model, latency, input tokens, and the state only when
`keep_examples`. `record_final(use, item, final, by)` (`accepted` or `overridden`) makes each row a
labelled example. CLI: `status [--json]`, `ask --state F --questions F`, `log --summary [--use U]`,
`replay --use U [--endpoint URL]` (agreement of another model on logged examples).

## Canary

Optional category `system-one`, absent when off: `endpoint-down`, `registry-invalid`, `high-override`
(last 50 finalized rows of a use overridden more than 30 %). Report-only.

## The ledger uses and `triage`

`system_one.py triage <home> [--register FILE] [--json]` gathers items in code, asks the uses below,
and prints a **digest**: one line per settled item (`ok  <ref>  <suggestion>  [pass N | rule]`), full
text plus the answers for every `READ` item (a `confirm` outcome, a deviation, or an `escalate` that
names its cause: `unsure: <question ids>` or `conflict: <the answers that clash>`), then counts. It
reads the home and writes nothing in it. Off or down: one line, exit 0, no partial output. Suggestions
are never written under an `Adjudication` heading (every digest line starts with a marker, and text is
printed behind `  | `); the orchestrator reads the digest and writes the block. `system_one.py final <use>
<item> accepted|overridden [--outcome O]` records what was done with a suggestion (`accepted` without
`--outcome` takes the latest logged outcome).

| use | item | outcomes (`confirm` marked) |
|---|---|---|
| `note-route` | a point of an implementer note with no routing label | `follow-up`, `brain`, `reject`*, `escalate` |
| `note-trigger` | a point routed `follow-up`: a Parked row or a work-order | `parked`, `work-order` |
| `followup-point` | a point under a *Follow-ups* heading | `parked`, `work-order`, `reject`* |
| `process-point` | a point under a *Process notes* heading | `follow-up`, `reject`* |
| `parked-trigger` | an open Parked row, with commit subjects since `Parked on`, WO titles, the version | `fired`, `waiting` |
| `row-state` | a row of a register (`--register`; id in the first column) | `needs-work`, `in-progress`, `waiting-proof`, `waiting-owner`, `waiting-external`, `closable`*, `superseded`*, `note-only`, `unsettled` |
| `duplicate` | a candidate pair chosen by code (shared WO/P ids or paths, word overlap) | `fold`*, `distinct` |
| `probe` | a text (status check and gate only; judges nothing real) | `greeting`, `other` |
| `proposal-area` | a pending intake proposal | one of nine area names (`canary`, `ledger`, `federation`, `model-optimization`, `harness`, `brain`, `roles-and-docs`, `operator-pages`, `other`) |
| `proposal-severity` | a pending intake proposal | `low`, `medium`, `high`, `critical` |
| `proposal-engine-change` | a pending intake proposal | `engine-change`, `no-engine-change` |
| `proposal-duplicate` | a (proposal, work-order) pair chosen by code | `likely-duplicate`, `distinct` |
| `card-group` | a board card (title, why, option labels) | `close-or-keep-open`, `decisions`, `your-actions`, `parked-work` |
| `lens-match` | a (work text, lens) pair: the lens's domain and when-to-apply plus the work-order's title, severity and scope | `applies`, `no`, `escalate` (shown as `maybe`) |
| `brain-duplicate` | a brain page pair chosen by code (title tokens, shared tags, shared links) | `merge-candidate`*, `distinct` |
| `brain-fits` | a new fact and up to 8 candidate pages chosen by code | `fits`, `new-page` |
| `brain-target` | the same state, asked only when `brain-fits` says `fits`: a choice among `candidate-1`..`candidate-8` | `candidate-N` (code maps N to the page) |
| `line-anomaly` | a log-line template: the template, one example line, the vocabulary's description of normal output | `abnormal`, `normal` |
| `line-family` | the same state, for a template judged abnormal or unsure: a choice over the anomaly family names parsed from `references/anomaly-families.md` at run time, plus the noul `fits_a_family` | a family name, `no-family` |
| `hunk-scope` | one hunk of an in-scope file with the work-order's scope text | `fits`, `look`, `escalate` (shown as `unsure`) |
| `wo-complexity-level` | a work-order's title, severity and scope text | `level-1`, `level-2`, `level-3`, `escalate` |
| `wo-touches-shared-tooling` | the same state | `yes`, `no`, `escalate` (shown as `unsure`) |
| `wo-needs-design-choice` | the same state | `yes`, `no`, `escalate` (shown as `unsure`) |

The proposal and card uses annotate only. Commands that print them (all write nothing; off or down: one line, exit 0):
`system_one.py screen <home> [--registry R] [--json]` (the federation intake listing plus proposal-* annotations; proposal-* uses, `local_only`, annotations are registry names and work-order ids
only), `system_one.py cards --items FILE [--home H] [--json]` (a group per card, never an option),
`system_one.py lenses <home> (--wo NNN | --text FILE) [--global-dir D] [--json]` (reads only the active set of `<home>/lenses.json`, and prints one line without a model call when lenses are
off; the repo wins a name collision; global layer `<skill>/agents`, or `--global-dir`, or `GITOS_GLOBAL_LENS_DIR`; verdicts `applies` /
`maybe` / `no`; a lens that cannot be judged is listed as a problem, never dropped),
`system_one.py brain-dupes <home> [--json]` (candidate pairs from a code prefilter; `merge-candidate` is reported,
never merged), `system_one.py brain-target <home> --fact FILE [--json]` (`update <page>`, `new page`, or `undecided`;
no candidate page means `new page` with no model call). `escalate` on a lens or a page choice never drops the item.

**Notes are split before they are asked.** A labelled bullet holds several points, so each bullet is
split at enumerators (`(1)`, `(a)`, `1.` at a sentence start) or, with none, at sentence ends, keeping
code spans and parentheses whole; a point under 4 words joins its neighbour. Refs are
`WO-NNN#<bullet>.<point>`. The heading is carried in each point's state as a fact. **The heading routes
by rule, with no model call, where it is unambiguous:** *Deviations* -> always `READ` (`deviation:
accept or revert`); *Durable facts* -> `brain`. *Follow-ups* asks only `already_done` and
`has_trigger`; *Process notes* asks only `names_owed_work`; any other heading, or none, gets the full
`note-route` questions. Headings are matched case-insensitively, with or without bold, colon, dash or
full stop. Notes triaged: every open work-order's, and resolved ones only when the canary's
`notes-unadjudicated` check covers them.

## The diagnostic scan

`system_one.py scan <home> FILE... [--max-templates N] [--json]` is a reading order for the diagnostic role's scan phase; it writes nothing. **Code first:** lines are grouped by template (strings, uuids, timestamps, hex ids and numbers masked); each template keeps its count, the `file:line` of its first and last occurrence and up to 3 raw examples. Templates that `<home>/log_vocabulary.md` marks normal are counted and set aside, never sent: mark one with a bullet `normal: <line>` (`expected:` also works; a trailing `*` makes it a prefix; a leading timestamp is ignored); the entries also form the description of normal output in each state. **Then the model:** `line-anomaly` per remaining template, `line-family` for each one judged abnormal or unsure. `--max-templates` (default 40) caps the model calls (each of the two decisions counts as one), so a huge log costs a bounded amount; templates ranked first are those with an error-like word, then the rarest; the rest are counted as not judged. **Digest:** per family (the names come from the reference file) the template count, line count and top templates with the `file:line` of the first occurrence and one example, then `abnormal, no family` and `unsure`. It is a reading order, not a finding. Logs may hold secrets, so every call is `local_only`: a remote endpoint is refused and nothing is sent. Off or down: one line, exit 0.

## Scope check and complexity

`system_one.py scope <home> NNN [--range A..B] [--json]` is an advisory read-order for a work-order's diff; it writes nothing. **By rule, no model:** a changed file matching no path or glob named in the order's `## Proposed fix scope` is `outside-scope`; one matching the paragraph that starts `**Not in scope` is `forbidden`. The order's own file (`work-orders/WO-NNN-*.md`) is never `outside-scope`. **By model:** each hunk of an in-scope file is judged by `hunk-scope` (`fits` / `look` / `unsure`; a hunk over 6,000 tokens is split). The digest lists `forbidden`, `outside-scope`, then `look` and `unsure` hunks with `file:line`, then a count of `fits`, and its last line always says that every hunk still has to be read. There is no "pass". Off or down, the rule half still prints and the hunks are stated as not judged. Default range: merge-base to the branch `wo-NNN`.

`system_one.py complexity <home> NNN [--json]` scores a work-order with three one-question uses (`wo-complexity-level`, `wo-touches-shared-tooling`, `wo-needs-design-choice`). It prints the level and the two inputs, an unsure input shown as `unsure` beside a settled level; `no input` appears only when the level itself is unsure. It never selects a model tier and is not passed to `model_optimization.py`: the orchestrator reads it as one input.

## How to add a use

1. Add one `register(...)` entry to `system_one_questions.py` (questions, a table covering every
   combination of settled inputs, each outcome flagged `reversible` or `confirm`); bump
   `REGISTRY_VERSION`. Wording: one judgment per question, concrete and observable, a true answer means
   yes, no case-specific clauses.
2. In the calling script add a subcommand that builds the state, calls `decide`, applies only reversible
   outcomes, and calls `record_final`. Catch `system_one.Unavailable` and fall through to today's path.
3. Add a gate case against `FakeSystemOne` in `.gitos/tools/selftest.py`.

## Machine setup

**Choosing a model.** Any server that answers `POST /v1/systemone` works (see *Answer shapes*). The tested
one is `perplexity-ai/pplx-decider-flash-v1.2`, a Python library with no server of its own; the repo ships a
small wrapper, `assets/system-one/serve_decider.py`, that serves it. Measured on one machine on 2026-11-14
(an RTX 3090 in a Thunderbolt enclosure that also drove the display; WSL2 Ubuntu 22.04; Python 3.12 venv made
by `uv`; `build-essential` needed for Triton's C compiler): load 13 s; about 9.1 GB of GPU memory; 80 ms for a
~130-token item, 235 ms at ~760 tokens, 0.8 s at ~2,800, 1.7 s at ~5,500, 8.3 s at ~20,000; 15 to 19 small
decisions a second with 4 to 16 concurrent clients. The model's `fast=True` path (`--fast`) was slower there
(about 450 ms floor) and used about 7 GB more, so the default path is the reference. The first request after
start compiles kernels (about 30 s); `--warmup` pays it at start. Measure on your own card.

**Keep each state small.** Time grows with tokens (see the numbers above). The engine already caps what it
sends per item; write new uses so the state is the few facts the question needs, not a whole document.

**WSL2 or Linux steps.**

1. Install `uv` and a C compiler: `sudo apt install build-essential`, then `curl -LsSf https://astral.sh/uv/install.sh | sh`.
2. Make the environment: `uv venv --python 3.12 ~/system-one/venv`, then `source ~/system-one/venv/bin/activate`.
3. Download the checkpoint into `~/system-one/pplx-decider-flash-v1.2` (for example `hf download perplexity-ai/pplx-decider-flash-v1.2 --local-dir ~/system-one/pplx-decider-flash-v1.2`;
   accept the model's licence on its page first).
4. Install the checkpoint's own `requirements` file into the venv with `uv pip install -r <file>`. The server
   imports the library from `<checkpoint>/source/src` at run time; torch comes from those requirements.
5. Copy `assets/system-one/serve_decider.py` next to the checkpoint and test it by hand:
   `python serve_decider.py ~/system-one/pplx-decider-flash-v1.2 --warmup`, then
   `curl http://127.0.0.1:8765/health`.

The server answers `POST /v1/systemone`, `GET /health` and `GET /v1/models`. One worker thread answers queued
requests in micro-batches (`--max-batch`, default 16) and falls back to one request at a time when a batch
raises, so one bad request cannot fail its neighbours. Request bodies are never logged; the log is one line
per batch. A non-loopback `--host` is refused unless `--token-env NAME` names an environment variable that
holds a token; the token is compared in constant time and never printed.

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
`{"endpoint": "http://127.0.0.1:8765", "model": "pplx-decider-flash-v1.2"}`. When the engine runs on
Windows and the server in WSL2, WSL2 forwards `localhost`, so the loopback URL works unchanged.

**Auto-start.**

- *Linux, or WSL2 with systemd enabled* (`systemd=true` under `[boot]` in `/etc/wsl.conf`): a user unit
  `~/.config/systemd/user/system-one.service` with `ExecStart=%h/system-one/venv/bin/python
  %h/system-one/serve_decider.py %h/system-one/pplx-decider-flash-v1.2 --warmup`, `Restart=on-failure`, and
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
