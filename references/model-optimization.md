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

## Mapping + ceiling

Start workers at **standard**. Choose **light** for bounded judgment with reliable
checks; choose **deep** for unresolved ambiguity, consequential decisions, or
evidence the lower route is inadequate. Use deterministic tools when sufficient.
Classify at dispatch/checkpoints, not per tool call. These are task tiers, not
three mandatory distinct models.

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

Establish the **actual lead pair** from the harness/operator, then configure it as
the ceiling. Workers can match it. Unknown or changed lead → revalidate before
routing. Fable or any other supported lead is permitted, never required. If more
capability is needed, propose a lead change to the operator; never switch the main
model automatically. No advisor, gateway, billing/fast/service-tier changes, or
deliberately weak-model experiments are part of this feature.

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
python <skill>/scripts/model_optimization.py select <repo> --harness codex --tier standard --lead lead-model --lead-effort high --runtime runtime.json --require text --require tools
```

Use `--harness claude` identically with that harness's mapping. `select` is read-only;
temporary inputs need not be retained. Exit 0: disabled or dispatch-ready; exit 2:
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
