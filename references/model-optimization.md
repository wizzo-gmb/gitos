# Model optimization — optional, repo-local

This is the policy's single home. Read it for `/gitos optimization`, an enabled
dispatch, or its normal closeout. It chooses **model + effort**, within the
operator-selected orchestrator's ceiling. Existing roles, WO scope, permissions,
and acceptance remain the contract. Native harness tools execute the dispatch.

## Preference + commands

At first inception, offer one optional question using the harness's question UI
where available: **Model optimization? Disabled (default) / Enabled.** Explain that
enabled routes workers and can retain repo-local model-selection lessons. A plain
text question is the fallback. Never treat silence as opt-in. After scaffolding,
persist the answer using `enable` or `disable`; an unanswered/skipped question uses
`skip`. Any recorded preference ends this interview; do not repeat it on resume.
Scaffolding itself creates no optimization setting or memory.

`/gitos optimization` is a skill intent, not a new executable slash command. Show
the current setting, then obtain the requested change. Explicit `enable`, `disable`,
or `configure` requests already authorize that named local change. Enabling also
establishes the current harness mapping below. Enabled without a usable mapping
means **setup incomplete**, not permission for a guessed route.

Run the helper from the active installed skill (`<skill>`), not a hard-coded
provider home. Commands work without a question UI:

```text
python <skill>/scripts/model_optimization.py status <repo>
python <skill>/scripts/model_optimization.py enable <repo>
python <skill>/scripts/model_optimization.py configure <repo> --harness codex --file mapping.json
python <skill>/scripts/model_optimization.py configure <repo> --harness claude --file mapping.json
python <skill>/scripts/model_optimization.py disable <repo>
```

The setting is `<home>/model-optimization.json`. Auto-detection follows scaffold:
`.gitos` → `outputs/debug` → `.pipeline` → `docs/agents`; `--home` selects an
existing home explicitly. No migration. Both harness maps coexist. `configure`
replaces that harness's routing fields, preserves unrelated fields, and does not
enable the feature. Serialize changes through the orchestrator, not concurrent
workers. Writes are atomic. Malformed/unsupported state is an error: inspect and
correct the local setting with the operator's intent; never silently overwrite it.

**Off means no optimization work.** Missing configuration is off. At session state
read, inspect the file only if present; only literal `enabled: true` with a valid
setting activates this policy. Invalid state never activates it. Disabled routine
sessions run no helper, discovery, optimization reporting, or learning. Explicit
status/configuration commands remain available. Disable preserves mappings, WO
evidence, and learned guidance. Re-enable refreshes discovery before using them.

## Session observation

When enabled, initialize one session baseline before the first optimized dispatch.
Use the active harness session/thread identity when exposed, or assign one stable
opaque identity for this GitOs session and carry it through resumes. Do not reuse
an identity for a different session or take the shared record's identity as proof
that it belongs to this session. If identity cannot be established after resume,
explicitly initialize a distinct new baseline and label it as such. Record model and effort independently, each
from an active **harness** observation or an **operator** report:

```text
python <skill>/scripts/model_optimization.py session-init <repo> --harness codex --session session-a --lead lead-model --model-source harness --lead-effort high --effort-source operator
```

Replace example values with evidence for this session. Omit an unavailable value
and its source; it becomes JSON `null` (unknown), not the string `unknown`. Omit
both pairs when neither is observable. `default` retains only the fixed/default
meaning described below; it does not stand in for an unknown active effort.
The helper validates provenance labels, not the truth of the supplied observation.

The baseline means **GitOs initialization / first observation**, not the harness
process's launch setting. Starting GitOs late cannot reconstruct earlier settings.
Repeating `session-init` with the same identity and harness preserves both original
baseline and latest current observation; it never fills unknown initial values
from later evidence. Resume with that same identity. A deliberate new session uses
a distinct identity and `--new-session` to replace the record:

```text
python <skill>/scripts/model_optimization.py session-init <repo> --harness codex --session session-b --new-session
```

One transient, untracked `<home>/model-optimization-session.json` stores only the
identity, harness, initial/current component values and provenance. Keep it out of
commits; no history, brain page, raw runtime document or additional ledger is
created. Commands must be serialized through the orchestrator: one active
optimization session per checkout. Atomic writes prevent partial files, not
concurrent lost updates. A displaced session must not dispatch against the new
owner's baseline. Use separate checkouts for simultaneous sessions; when taking
over this checkout deliberately, initialize a distinct new identity. Malformed
state fails without overwrite, even with `--new-session`: inspect/correct it or
explicitly remove the damaged transient record, then initialize a new baseline
whose collection time is understood. Never claim a discarded baseline was restored.

Before **each** optimized dispatch, refresh the current pair and supply it to
`select` with the same identity and component sources. Missing fresh values become
unknown even if the previous current observation was known. `select` reports
`changes.model`, `changes.effort`, and overall `change`: any known difference means
`changed`; both known equal components mean `unchanged`; otherwise `unknown`.
Unknown initial values can coexist with a valid known current pair. Missing or
mismatched session state, or an unknown current pair, cannot be dispatch-ready.
Every selection checks current evidence against the configured ceiling. If it
changed, revalidate the mapping; once it matches, selection can proceed while the
original baseline remains unchanged. Baseline drift alone is not a permanent block.

**Observation limits.** GitOs does not introspect hidden reasoning settings. In
Codex, use session/turn metadata only when the active client exposes the actual
pair for this session. `config/read` resolves on-disk settings; model catalogs,
saved defaults and a separately spawned app-server do not reveal the current
session's effort. Per-turn overrides can differ from those defaults. In Claude,
use exposed active-session metadata or an operator report of the active effort
display (for example after `/effort`). Saved settings and agent frontmatter alone
do not prove the lead's current effort. Neither path infers effort from behavior
or scans private session histories. If the agent cannot observe a field, retain
unknown or request an operator report; do not claim automatic change detection.

**Read effort yourself before asking anyone.** In Claude the client exports the
session's effort as `$CLAUDE_EFFORT` (documented, hooks reference: *"`$CLAUDE_EFFORT`
holds the same level"* as the hook payload's `effort.level`). Run
`python <skill>/scripts/model_optimization.py observe` or `echo $CLAUDE_EFFORT` in a
shell tool. `observe` is read-only and prints the effort and its source (`harness-env`),
or `unknown`. Only `low`, `medium`, `high`, `xhigh` and `max` count; any other value, or
none, is absent and never a guess. `session-init` and `reaffirm` use it when no
`--lead-effort` is given and record the source `harness-env`, distinct from an operator
report and from a hook payload; so does the hook when it re-verifies a stale effort from a payload with no `effort` key
(a malformed `effort` stays ambiguous and is not overruled).
The variable is re-read at each check, so an `/effort` change is picked up at the next
check, not instantly. There is no `$CLAUDE_MODEL`: take the model from the system
prompt's exact model ID as a self-report, or from a `PostModelSwitch` the hook recorded.

**Fallback.** When effort is unavailable (a model without effort, or another harness),
ask with the interactive question UI (`AskUserQuestion` in Claude Code), offering the
levels as options. Never ask in prose, where the question goes unnoticed; on a harness
without that UI, use a numbered list.
[Codex app-server](https://learn.chatgpt.com/docs/app-server),
[Claude model and effort settings](https://code.claude.com/docs/en/model-config).

**A value the client announces is harness evidence; an unannounced change leaves
the baseline unknown.** The limits above are about what an agent may *read*. They
do not forbid the client from *telling* the engine something, and the two cases
divide cleanly:

- **The announcement carries the value.** Record it with provenance `harness` — it
  came from the client, not from an agent's reading of a file.
- **The announcement carries only the fact of a change.** **Invalidate** the
  affected component to explicit unknown. `select` then refuses, so the next
  dispatch asks the operator for one value instead of proceeding on a stale one.

The second branch is the common one, and it is why the baseline needs no
inference. Keeping up means knowing when you no longer know: a mechanism that
cannot produce the new value is still correct, while one that keeps serving the
old value is not. A refresh that writes a *wrong* pair is worse than the
staleness it replaces, so wherever the evidence is thin, invalidate.

**Currency, in Claude.** The engine registers a hook on the client's
configuration-change, model-switch and dispatch events in the repo's committed
`.claude/settings.json`; `scaffold` lays it and `enable` back-fills it for a repo
that predates the seam. It is inert while optimization is off. On an announced
change the affected component drops to explicit unknown and `select` refuses with
a reason naming it. Re-establish from evidence, never from memory:

```text
python <skill>/scripts/model_optimization.py reaffirm <repo> --harness claude --session session-a --lead lead-model --model-source operator
python <skill>/scripts/model_optimization.py reaffirm <repo> --harness claude --session session-a --lead-effort high --effort-source operator
```

`reaffirm` touches only the components it is given and never the original
baseline, so re-establishing one component does not bless the other. An
invalidated component cannot hold a value: the record is rejected if it does.

Three properties of this are worth stating, because each one bounds a claim:

- **Precision.** A configuration announcement names the file that moved. Only a
  file that could carry a routing pin is considered, and only the part of it that
  could move each component. Reading that file to decide *whether* to invalidate
  is not the banned shortcut — the ban is on treating a saved setting as evidence
  of the active pair, and an invalidation claims nothing about any value. The
  comparison is over digests, which can answer "did this move?" and cannot answer
  "to what?". When a baseline is established (`session-init`) or re-established
  (`reaffirm`), the digests of every file that can carry a route are recorded:
  user `settings.json` (under `CLAUDE_CONFIG_DIR` when set), project
  `.claude/settings.json` and `.claude/settings.local.json`. So the **first** edit
  to each is judged on what moved, like every later one: an edit that touches only
  permissions, hooks or skill toggles costs nothing. A file absent at the baseline
  is recorded as having no routing keys, so creating it without any is not a
  change and creating it with one is. A file unreadable at the baseline is not
  recorded, and any file with no recorded digest still invalidates on its first
  announcement, as does a file unreadable when announced.
- **Effort can close the loop; model cannot.** A dispatch announcement carries the
  **session's own effort** at the top level, distinct from the effort the caller
  requested for that dispatch, so an invalidated effort is re-verified on the next
  dispatch as `harness` evidence with no operator question. **No announcement
  carries the session's model.** That component is invalidate-only and comes back
  solely from an operator report. Do not describe the pair as symmetric.
- **Granularity, and what is still unproven.** The dispatch alias set is coarser
  than a versioned operator control surface, where two versions of one alias can
  carry different effort pins; a switch between them can leave the mapped alias
  unchanged while changing the effort the lead runs at. Invalidation covers that
  because it compares nothing against the mapping. Model-change detection through
  a dedicated switch event is **registered but unproven** — a model change need
  not write a settings file, so until that event is observed, treat an
  unannounced model change as undetected rather than covered, and say so rather
  than claiming either way.

**The announcement is evidence of a change, never of a value.** Nothing in this
path infers a pair from behaviour, reads a session transcript, or promotes a saved
setting to evidence of the active pair. A hook that does not run leaves the
baseline exactly as stale as it was before the hook existed; `select` refuses on
what the hook *wrote*, not on whether it ran, so a silent hook is a missed
invalidation rather than a false green.

## Mapping + ceiling

Start workers at **standard**. Choose **light** for bounded judgment with reliable
checks; choose **deep** for **execution ambiguity** — the question only the work
itself answers, with no operator in the loop to ask — for consequential decisions,
or for evidence the lower route is inadequate. **Spec ambiguity caps the tier; it
does not raise it.** An unpinned Option, an unrun Part-0 probe, or a scope naming no
files is orchestrator-side work: pin the Option, run the probe, name the files, then
route. Effort against an unsettled spec buys a more confident reading, not a better
one. Use deterministic tools when sufficient. Classify at dispatch/checkpoints, not
per tool call. These are task tiers, not three mandatory distinct models.

Read the tier off countable work-order properties, so two orchestrators on one order
reach the same answer:

- `## Verification` demands a negative control, an adversarial wave, a fuzzer, or
  mutation testing → **deep**; that is the edge-case signal, where measured gains
  concentrate.
- `## Proposed scope` carries a diff sketch → **standard**; the judgment is spent.
- Read-only work, or one named file with no Options → **light**.

Where rules conflict, the highest tier among the matching rules wins: effort buys
verification, so a verification demand is the dominant signal, and a settled approach
does not cancel a hidden edge-case burden. Where no rule matches, **standard** stands
as the opening default. The ceiling binds after the rule resolves.

Treat this mapping as a **prior pending local data**, re-derivable once enough
dispatches carry a recorded tier and effort. Its support is one community-sourced
benchmark whose failure categories a model judge assigned and which are therefore
approximate; the published runs used internal settings with safety interventions off
and no internet for security tasks, so the source states the figures will not line
up with the public leaderboard; and **Software** — this engine's own category —
gained least of the technical categories (43% → 56%, against Hardware 34% → 75%).
That is a limit on the mapping, not a guarantee behind it.
Source: [Using Claude Code: Spending your effort](https://claude.dev/blog/spending-your-effort/),
Thariq Shihipar, claude.dev Engineering, 2026-09-25.

Discover choices from the active dispatch-tool schema first, a supported local
catalog second, or an explicitly supplied model-picker/mapping. Keep one preferred
pair per tier. No universal ranking by model name, version, price, or effort label.
Refresh on enable, mapping/lead/harness change, native override change, or an
unavailable-model failure; no per-WO roster sweep or web research.

This complete **illustrative** harness mapping is the shape accepted by `configure`.
Replace its names and capabilities with actual harness evidence. The operator's
configured ranks are policy, not measured provider facts:

```json
{
  "catalog": {
    "source": "native dispatch metadata; reviewed for this harness version",
    "models": {
      "worker-model": {"efforts": ["medium"], "capabilities": ["text", "tools"]},
      "lead-model": {"efforts": ["medium", "high"], "capabilities": ["text", "tools", "image"]}
    }
  },
  "choices": {
    "worker": {"model": "worker-model", "effort": "medium", "rank": 1},
    "lead-medium": {"model": "lead-model", "effort": "medium", "rank": 2},
    "lead-high": {"model": "lead-model", "effort": "high", "rank": 3}
  },
  "ceiling": "lead-high",
  "tiers": {"light": "worker", "standard": "lead-medium", "deep": "lead-high"}
}
```

Ranks order **model/effort pairs**; equal ranks are permitted. The same pair cannot
have contradictory ranks. Different efforts on the same model can share a rank or
have explicitly configured ranks; effort words themselves establish no ordering.
Tier ranks must be nondecreasing and no tier may exceed the ceiling. Capabilities
are evidence-backed labels for task requirements (inputs, tools, context capacity
where known), not an invented provider taxonomy. Unknown required support blocks
that route. `default` effort means no adjustable effort has been established;
omit the effort parameter. Use a named effort whenever supported. A default route
requires native evidence of its fixed/default behavior (`override.effort: default`),
not merely an absent parameter; it makes no claim about economy.

**A model with no effort levels is the exception.** The Claude model configuration
page lists the models that take an effort level and states that *"Models not
listed here do not support effort."* For such a model there is no effort to choose,
control or evidence, so a catalog records it as `"efforts": ["default"]` and
nothing else, and its route is `default`. `select` returns that route
`dispatch-ready` without effort evidence, and the dispatch passes the model only.
A catalog that lists `default` beside named levels is not this case; there the rule
above applies. Catalogs go stale: an alias can move to a newer model that does take
effort, so refresh discovery when the alias target changes.

Establish the **actual lead pair** from the harness/operator, then configure it as
the ceiling. Workers can match it. Unknown or changed lead → revalidate before
routing. Fable or any other supported lead is permitted, never required. If more
capability is needed, propose a lead change to the operator; never switch the main
model automatically. No advisor, gateway, billing/fast/service-tier changes, or
deliberately weak-model experiments are part of this feature.

## The dispatch requirement

The mapping above chooses a tier. For four days it was **advice addressed to a
reader**: nothing ran at the moment a dispatch was composed, so dispatches went out
at the ceiling by default and nothing could disagree afterwards. A sound rule with
no mechanism at the boundary where it must hold is a wish. This section is the
mechanism, and it binds the **dispatch tool** rather than any role — so it reaches
the orchestrator, a dispatched worker, and an agent three levels down, identically.
A requirement keyed to "the orchestrator dispatches" misses every sub-dispatch by
construction, which is not a hypothetical: a worker executing a work-order about
unverifiable assertions spawned a read-only sweep with neither component set.

**Two halves, because neither covers the other's ground.**

- **Declarative — the tier rides on the agent type.** A subagent definition in
  `.claude/agents/` carries `model` and `effort` of its own, so a type whose tier is
  derivable needs no cooperation from whatever spawns it. `scaffold` lays `Explore`
  at **light** (a read-only sweep is exactly what the mapping sends there) and `Plan`
  at **standard** (the opening default; no rule matches a design pass cleanly). It
  lays **no** `general-purpose` definition — that type's tier depends on the task it
  is handed, so a pair written there would be invented rather than derived. Existing
  files are never overwritten.
- **Refusing — the gate at the tool call.** `scripts/dispatch_guard.py` registers on
  the client's tool-call event, matched to the dispatch tool, in the repo's
  **committed** `.claude/settings.json`. It travels in git, so a fresh clone arrives
  with the gate on and there is no per-system step. A dispatch that sets no `model`,
  or no `effort`, or neither, is **denied with a reason**. One exception: a dispatch
  that names a model with **no effort levels** and no effort passes, but only where
  the repo's Claude mapping routes that model with effort `default` and its catalog
  lists no other effort (see *Mapping + ceiling*). Any other missing effort is still
  refused, and an unrouted dispatch always is.

**Precedence is honoured, not fought.** A per-invocation `model`/`effort` argument
beats a definition's frontmatter, and `CLAUDE_CODE_EFFORT_LEVEL` beats it too. That
is the right shape: the definition is the **floor** for a type, and an explicit route
on one dispatch is the **override**.

**The silent-typo hazard, and why presence is not the test.** Claude Code ignores an
unrecognized frontmatter field without reporting an error, and the field names are
case-sensitive. So a misspelled `effort` leaves the agent at the session's tier,
which is **indistinguishable from no routing at all**. A check that the field is
*present* therefore cannot go red on the failure that actually happens. Two things
close the gap, and neither is "look at the file":

- The selftest asserts the scaffolded definitions' frontmatter keys fall inside the
  documented field vocabulary and their values inside the documented enums, compared
  against a list written independently of the writer. That catches the typo.
- Effect itself is read from the client, not from the file: run with `--debug` and
  search `~/.claude/debug/<session-id>.txt` for `does not recognize or apply`
  (requires a recent client). **Frontmatter alone never proves an effective pair** —
  the same observation limit this policy already states for the lead.

**Binding the tier, not merely a typed pair — a separate opt-in.** A `model`/`effort`
pair proves a route was *written down*, not that it matches the tier the work-order
derives. An operator who wants that enforced can switch on the **tier binding**: the
gate then additionally requires a **routing receipt** that `select` authorized, and
compares the dispatched pair against it. The binding is **off unless asked for**, and
`enabled: true` is **not** the ask — `enabled` means *route dispatches by tier*, never
*refuse a dispatch that lacks a receipt*. The opt-in is its own top-level key in
`model-optimization.json`, honoured only as exactly JSON `true` and only while
optimization is enabled (there must be a tier to bind to):

```json
{"schema_version": 1, "enabled": true, "preference": "enabled", "dispatch_binding": true, "harnesses": {}}
```

Nothing writes `dispatch_binding`; it is set by hand. **Absent means off**, and so does
`false` or any non-boolean value — every repo that installed the gate before this key
existed carries no such key, so absence read as on would refuse every one of their
correctly routed dispatches. With the binding on, every dispatch needs a fresh receipt:

```text
python <skill>/scripts/model_optimization.py select <repo> --harness claude --tier deep ... > decision.json
python <skill>/scripts/dispatch_guard.py record <repo> --select decision.json
python <skill>/scripts/dispatch_guard.py show <repo>
```

The repo may come before or after the options (`record --select decision.json <repo>`
works too).

Only a `dispatch-ready` decision writes a receipt; `blocked` and
`recommendation-only` are refusals and authorize nothing. A receipt is **single-use
and short-lived**, and both properties are load-bearing rather than hygiene: a
receipt that outlived its dispatch would sit on disk approving every later one,
including the mis-tiered dispatch the gate exists to refuse — an assertion that
cannot go red. It is spent on the dispatch it authorized and expires on a clock, and
a receipt dated in the future is treated as a moved clock rather than as fresher
evidence. It lives outside the repo, in the per-user temp area, because a
single-use token for one dispatch is not repo content and must never travel in a
commit. With optimization **off**, or on without `dispatch_binding: true`, the receipt
layer does not apply at all; the floor still refuses an unrouted or half-routed
dispatch, because off has never meant *spend the ceiling by default*.

**The gate never blocks by accident.** On this event a nonzero exit is itself a
refused tool call, so the gate speaks **only** through its decision on stdout and
always exits 0. A crash, an absent engine, an unreadable configuration, an
unparseable announcement, or a call to any other tool all print nothing and the
dispatch proceeds. It is registered **without** `async` and **without**
`onFailure: "block"`: an async hook's decision fields are documented as having no
effect, so an async gate silently stops being a gate, while `onFailure: "block"`
would turn the gate's own breakage into a refusal. It also never answers `allow` —
that would bypass the rest of the permission system, and "no opinion" is the honest
answer to every question this gate was not built to answer. A **full-context fork**
is exempt: it inherits the lead's pair and `select` refuses to route one, so
demanding a route for a fork would redden on correct behaviour.

**Layer 2 — machine-wide, documented and optional.** The repo-scoped layer above is
the enforced default. An operator who wants every session covered installs the same
gate into their own `~/.claude/settings.json`, once, by hand:

```text
python <skill>/scripts/dispatch_guard.py install-user
```

This runs only on that explicit name — it edits the operator's own settings, which is
never a side effect of another command.

**Three limits. Each one is stated because the mechanism would otherwise read as
covering ground it does not.**

- **LIMIT 1 — repo scope does not reach sessions outside this repo.** A committed
  gate is invisible to any session in another checkout or another project. The
  reported failures are sessions *in general*, so **layer 2 is the only layer that
  covers that population** — not a nice-to-have on top of layer 1. Do not let the
  repo-scoped default imply coverage it does not have.
- **LIMIT 2 — the gate is Claude-only; the Codex half is UNENFORCED.** Both harnesses
  are supported, and a tool-call hook is a Claude Code surface that a Codex session
  never runs. So the requirement is **mechanical in Claude and prose in Codex**: in a
  Codex session nothing refuses an unrouted dispatch, and the `## Codex path` below
  carries the obligation as text only. Describing this as "the dispatch requirement"
  without that sentence would make the Codex half look covered when it is not.
- **LIMIT 3 — a hook is defeatable by configuration.** `disableAllHooks` in any
  settings file switches hooks off, and `allowManagedHooksOnly` in a managed
  organization blocks user, project, local and plugin hooks. An operator report names
  `--bare` as a third; the published hooks page does not confirm that, so treat it as
  reported rather than established. This is a strong guardrail, not a proof.

A scaffolded repo that has lost the gate is a **canary finding**, the same shape as a
repo-root `CLAUDE.md` that has lost its managed block — so the guardrail stops
depending on anyone remembering it is there.

## Codex path

Read the actual tool contract. If it offers model and reasoning overrides, use those
parameters. A full-history fork inherits its parent in harnesses that disallow
overrides on forks; choose a fresh context for a different route. Give that worker
the WO, Implementer brief, approved plan, and relevant pointers explicitly. Use only
delegation authorized by the current task and harness.

Inspect applicable agent/config layers read-only. A Codex custom-agent file's
`model` and `model_reasoning_effort` override dispatch settings; explicit spawn
settings otherwise precede `[agents]` defaults, then inheritance. Resolve both
fields: changing model does not prove effort changed. A tool exposing a smaller
contract wins over generic documentation. Do not write `.codex` settings to force
the optimization. [Native subagent contract](https://learn.chatgpt.com/docs/agent-configuration/subagents).

**Catalog when needed.** An existing app-server client can send `model/list` after
its connection's initialize handshake. The following standalone Python recipe is
also usable with a CLI whose `codex app-server --help` advertises stdio. Run it only
when native metadata is insufficient. It opens a short-lived foreground connection,
requests metadata, prints complete pages, and closes; no inference or thread is
started. Save stdout as `catalog-pages.json` outside the ledger. A client error or
unavailable CLI means use the manual mapping path, not an inference probe.

```python
import json, shutil, subprocess
executable = shutil.which("codex")
if executable is None:
    raise RuntimeError("Codex CLI unavailable; use native metadata or a manual mapping")
p = subprocess.Popen([executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, text=True, encoding="utf-8")
def send(value):
    p.stdin.write(json.dumps(value) + "\n")
    p.stdin.flush()
def reply(request_id):
    for line in p.stdout:
        value = json.loads(line)
        if value.get("id") == request_id:
            if "error" in value:
                raise RuntimeError(value["error"])
            return value
    raise RuntimeError("Catalog connection closed")
try:
    send({"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "gitos_catalog", "version": "1"}}})
    reply(1)
    send({"method": "initialized", "params": {}})
    pages, cursor, request_id = [], None, 2
    while True:
        send({"id": request_id, "method": "model/list", "params": {
            "limit": 100, "includeHidden": False, "cursor": cursor}})
        page = reply(request_id)
        pages.append(page)
        cursor = page["result"].get("nextCursor")
        if not cursor:
            break
        request_id += 1
    print(json.dumps(pages))
finally:
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
```

```text
python <skill>/scripts/model_optimization.py catalog --file catalog-pages.json
```

Use the normalized output as the mapping's `catalog`, adding only task capabilities
independently established by the tool contract. Missing modality metadata stays
unknown here. Catalog entries advertise choices; they do not prove entitlement or
actual execution. Capture rerouting/model and usage events only if this client
exposes them. [App-server protocol](https://learn.chatgpt.com/docs/app-server).

## Claude path

Use the native `Agent` tool's supported `model` parameter for a fresh worker and its
`effort` parameter where exposed; otherwise use an existing authorized agent
definition with the intended settings. Query `claude --version`, inspect `/model`
or available tool metadata, and resolve alias targets for this provider. `/model`
is a picker/inspection path, not permission to change the lead. Populate the same
mapping shape from these observations; `source` records the harness version and
alias resolution. Full model IDs avoid ambiguous alias changes. No roster of
current model names is shipped with GitOs.

Read only relevant model settings: selected agent frontmatter, applicable managed/
user/project/local settings, installed spawn overrides, and model-specific
environment variables. Do not dump credentials or the entire environment. Check
`availableModels`, alias/provider substitutions, `modelOverrides`,
`CLAUDE_CODE_SUBAGENT_MODEL`, force-subagent settings, `ANTHROPIC_DEFAULT_*_MODEL`,
and `CLAUDE_CODE_EFFORT_LEVEL` where applicable. At v2.1.251+, per-invocation model
normally precedes frontmatter, then subagent environment, then the lead; older
versions give that environment override precedence. Force/mod controls and
restrictions can alter this. Resolve the actual installed version's contract.

Per-invocation effort requires v2.1.292+ and the exposed parameter. On an older
client, an existing agent definition's `effort` may establish the route; the effort
environment variable takes precedence. If no supported way can apply the requested
pair, mark recommendation-only. Do not silently create agent definitions or alter
global/project harness settings. A full-context fork inherits the lead. Fresh
workers must read the WO and role; invoked skills/history are not assumed inherited.
[Claude subagents](https://code.claude.com/docs/en/sub-agents),
[model settings and restrictions](https://code.claude.com/docs/en/model-config).

## Dispatch + evidence

When enabled, consult applicable guidance in the repo's existing brain concept
`model-routing` (or its existing canonical equivalent), then select the task tier.
Honor pins and required capabilities before economy. A useful lesson can change
model/effort selection; it cannot broaden the WO or weaken acceptance.

The helper accepts a temporary **runtime evidence** JSON object, prepared from the
active tool/config inspection. It does not crawl settings or execute agents:

```json
{"context":"fresh", "overrides_checked":true,
 "model_control":true, "effort_control":true}
```

Set booleans true only when established. Optional `allowed_models` and
`unavailable_models` are lists; `override` is the resolved `{ "model": "...",
"effort": "..." }` or either field alone, including an operator pin. A conflict
blocks this route: honor the pin and revalidate rather than overriding it. A fixed
override matching the route can supply a control absent from the invocation tool.
Omitted evidence remains unknown; the example is not a blanket attestation.

```text
python <skill>/scripts/model_optimization.py select <repo> --harness codex --session session-a --tier standard --lead lead-model --model-source harness --lead-effort high --effort-source operator --runtime runtime.json --require text --require tools
```

Use `--harness claude` identically with that harness's mapping and initialized
session. `select` replaces the session record's current observation, including on
a valid blocked/recommendation-only decision; it never changes the baseline or
routing configuration. Temporary inputs need not be retained. Exit 0: disabled,
session-ready or dispatch-ready; exit 2:
invalid input; exit 3: blocked or recommendation-only. **Dispatch-ready is a checked
request, never confirmed execution.** Recommendation-only means no certified
optimized dispatch: disclose the limitation and use the established lead/inherited
workflow only if its pair is known within the ceiling; otherwise pause routing for
configuration. Missing/unsupported choices never trigger an automatic higher route.

Apply the checked pair through the native dispatcher and record one compact WO note:

> Model: standard; requested worker-model / medium; effective unknown (not exposed).
> Outcome: accepted after one revision; no model-selection adjustment supported.

Replace unknown with observed settings only when runtime evidence supports them.
Capture native reroutes if exposed, revalidate their ceiling, and report conflicts;
GitOs policy cannot prevent an opaque provider substitution. A repeated same failure
prompts reassessment: worker returns attempts and failure evidence to the orchestrator.
Distinguish reasoning difficulty from context, tool, credential, or environment gaps.
Escalate only for a useful reason within the ceiling. New tasks reset to their suitable
tier. Tokens/time/cost are optional observed evidence, never invented savings.

## Normal closeout → next selection

The orchestrator MAY retain a lesson about how **model selection** affected the WO:
adequacy, revisions/escalation, or avoidable model effort. No lesson is required.
Success does not prove a cheaper route would work; absent context does not establish
a weak model. Label uncertainty and model/version scope. No extra reviewer, stage,
benchmark, report, follow-up WO, or general handoff-improvement requirement.

Use the existing brain upsert protocol: search for the canonical routing concept;
update/replace its compact current guidance rather than append an event history.
Create `wiki/concepts/model-routing.md` only for a reusable, evidenced lesson, with
normal concept frontmatter/index/log handling. Link supporting WOs with relative
Markdown links resolved from the concept page (including the resolved directory
after a WO moves); the ledger keeps the details. No separate history or memory store.
If this repo has no brain, keep evidence in the WO and skip learning; do not create a
brain as a side effect. Legacy split homes use the already resolved brain location.

Later enabled dispatch reads applicable guidance before choosing. A mapping/model
upgrade weakens old lessons: reconsider their applicability and replace superseded
guidance in normal maintenance. Disable suspends both routing and this optional
learning while preserving everything for a later opt-in.
