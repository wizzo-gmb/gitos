# Production Handoff Contract

**What goes here:** before a piece of software is handed from the environment where it was built (dev/research/staging) to the environment where it runs for real (production/live), a set of questions must be answered in writing. This reference defines the sections and explains what belongs in each; for a worked end-to-end instantiation see `references/profiles.md`.

The contract is not bureaucracy — it's a forcing function for discovering the gaps between how the system behaves in development and how it will behave live. The highest-value section is the last one: **known prod-vs-dev deltas**, the things you already know will behave differently. Surprises after deployment are expensive; writing them down before deployment is cheap.

---

## When to fill this

Fill it before the first production run, not after. It is a blocking deliverable at the point of promotion, not a retrospective document. If you can't fill a section, that gap is itself important to name — a blank section means "we haven't decided this yet", which is a different state from "this is not applicable".

Store it at `.gitos/production-contract.md` (scaffolded by `scaffold.py` when the handoff declares a production target). It is immutable once the system goes live — changes after the fact become a new version with a changelog entry.

---

## Contract sections

### 1. Interface / IO contract

*What to document here:* The exact shape of what goes in and what comes out. For a service: request schema, response schema, error codes. For a model: input feature vector spec (names, types, ranges), output format (score, label, confidence). For a library: public API surface, function signatures, return types. For a pipeline: input table/file schema, output table/file schema, null-handling policy.

Why this matters: if the caller and the callee disagree about the contract, the system fails silently at the boundary — wrong column names, wrong types, unexpected nulls. Document the contract so both sides can be tested against it independently.

```
interface:
  inputs: <FILL — schema, types, required vs optional, null policy>
  outputs: <FILL — schema, types, units, what a missing value means>
  errors: <FILL — error codes/exceptions and their semantics>
  versioning: <FILL — how the interface version is communicated to callers>
```

### 2. Environment and configuration

*What to document here:* Every environment variable, config file, secret reference, and runtime flag the system reads. Where config is loaded from. What happens if a required variable is missing (crash-fast is better than a silent default). Which settings differ between dev and prod, and which must not.

```
environment:
  required_vars: <FILL — var name, purpose, where it's set in prod>
  config_files: <FILL — paths, how they're loaded, which env overrides which>
  secrets: <FILL — how secrets are injected (vault reference, env, etc.) — never literal values here>
  dev_vs_prod_differences: <FILL — the vars that are different in prod; flag anything that could cause a silent behavioral difference>
```

### 3. Data provenance and migration

*What to document here:* Where the data the system consumes comes from, how old it is allowed to be, and what happens if it's missing or stale. If a schema migration is needed to move from dev to prod, describe it. If the system reads from a live feed, document the feed's reliability SLA and what the system does when it misses an update.

```
data:
  sources: <FILL — each input data source, its owner, its update cadence>
  staleness_policy: <FILL — how old is too old? what happens if stale data is detected?>
  migration: <FILL — any schema changes, backfill steps, or data format conversions needed at deployment>
  provenance_check: <FILL — how the system asserts it's reading the right data (checksum, row count, schema version)>
```

### 4. Failure modes and rollback

*What to document here:* The ways the system can fail, ranked by likelihood and impact. For each failure mode: how it's detected, what the blast radius is, and what the recovery action is. Document the rollback procedure explicitly — who does it, what commands run, how long it takes, and how you confirm the rollback succeeded.

```
failures:
  - mode: <FILL — describe the failure>
    detection: <FILL — how you know it happened>
    blast_radius: <FILL — who/what is affected>
    recovery: <FILL — steps to restore service>
rollback:
  procedure: <FILL — exact steps>
  estimated_time: <FILL>
  confirmation: <FILL — how you know rollback succeeded>
```

### 5. Observability — logs, metrics, alerts

*What to document here:* What the system emits, where it goes, and what you watch. For logs: format (structured JSON is better than free text), path or stream, rotation policy, what a healthy log looks like vs. an unhealthy one. For metrics: which counters/gauges/histograms are emitted, what their normal ranges are, and what's a warning vs. a page. For alerts: who gets paged for what, and what the on-call response should be.

```
observability:
  logs:
    format: <FILL — structured JSON / plain text / etc.>
    location: <FILL — file path, log stream, aggregator>
    what_healthy_looks_like: <FILL>
  metrics:
    emitted: <FILL — metric names, types, normal ranges>
    dashboards: <FILL — where to look>
  alerts:
    - condition: <FILL>
      severity: <FILL>
      responder: <FILL>
      runbook_pointer: <FILL — link to the runbook section>
```

### 6. Performance budget

*What to document here:* The latency, throughput, and resource ceilings the system is expected to operate within. These should match (or be derived from) the acceptance criteria in `handoff.md §Acceptance`. Include both the steady-state expectation and the degraded-mode floor: how slow is too slow, how much memory is too much, and what triggers a scale-up vs. an incident.

```
performance:
  latency: <FILL — p50, p95, p99 targets; measurement surface>
  throughput: <FILL — requests/sec, rows/min, etc.>
  resource_ceilings: <FILL — CPU, memory, disk, network>
  degraded_mode: <FILL — what the system does when it's overloaded>
```

### 7. Security and permissions

*What to document here:* What the system is allowed to access and what it isn't. Which credentials it uses. Least-privilege principle: does it read only what it needs? If it writes to a production store, who authorized that permission and is it scoped correctly? Any data classification concerns (PII, financial data, access controls).

```
security:
  credentials_used: <FILL — service account names, credential stores>
  permissions: <FILL — what the system can read/write/call>
  least_privilege_audit: <FILL — confirm the system cannot access more than it needs>
  data_classification: <FILL — sensitivity of the data it touches>
```

### 8. Dependency pinning

*What to document here:* Every external dependency the system relies on — language runtime version, library versions, OS packages, external services, infrastructure components — and how they're pinned. "Latest" is not a pin. Document what happens if a dependency is unavailable: does the system degrade gracefully or fail hard?

```
dependencies:
  runtime: <FILL — language/runtime version, pinned exactly>
  libraries: <FILL — version-pinned list or pointer to lockfile>
  external_services: <FILL — APIs, databases, queues — their SLAs and your fallback>
  unavailability_behavior: <FILL — what happens if each dependency is down>
```

### 9. Runbook

*What to document here:* The step-by-step operating procedures for the things that will definitely need doing: starting, stopping, restarting, checking health, clearing a stuck job, rotating a credential. Written for the person who will be on call at 2am who may not be the person who built this. Commands are literal; flags are explained.

```
runbook:
  start: <FILL — exact command, expected output>
  stop: <FILL — exact command, graceful vs. forced>
  health_check: <FILL — how to confirm the system is running correctly>
  common_ops:
    - situation: <FILL>
      steps: <FILL>
```

### 10. Known prod-vs-dev deltas (the highest-value section)

*What to document here:* The behavioral differences between the environment where this was built and the environment where it will run. These are the things you already know are different — document them here rather than discovering them in production. Each delta has: what the dev behavior is, what the prod behavior will be, the expected impact on the system's metrics, and how you'll monitor whether the impact is within tolerance.

This is the highest-value section because it converts known surprises into managed risks. Every delta not written here is a surprise waiting to happen at the worst time.

```
prod_vs_dev_deltas:
  - delta_id: D1
    name: <FILL — short name>
    dev_behavior: <FILL — what happens in dev/research/staging>
    prod_behavior: <FILL — what will actually happen live>
    expected_impact: <FILL — how this changes the measured performance metrics>
    monitoring: <FILL — how you'll confirm the impact is within tolerance>
    within_tolerance_if: <FILL — the quantitative threshold for "acceptable">
```

---

## Filling the contract

The contract is filled at the point of promotion. In plan mode, the inception orchestrator adds a "fill production-handoff contract" step to the plan before any deployment work begins. The `<FILL>` placeholders are replaced with project-specific answers; none are left blank — a blank means "unknown", which must be named explicitly as a risk.
