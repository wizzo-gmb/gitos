# Domain profiles — layering domain content on the engine

GitOS ships a **generic engine**: the roles (three operator-entry + the dispatched implementer), the brain schema, the work-order
template, the nine anomaly families, the acceptance-criteria and production-handoff
skeletons. The engine knows nothing about any specific product.

A **domain profile** is how a downstream product makes that engine concrete. It is the
delta a real project layers on top — the gates, the contract values, the extra failure
modes, and (optionally) a starter scaffold — without ever touching the engine itself.

## The one rule

> **A profile adds content on top of the engine; it never edits the engine.**

This is what makes "improve the engine fearlessly" true. Because a profile only *adds*,
the engine can be re-synced into a downstream product at any time and the profile content
survives untouched (see [the bridge pattern](#the-bridge-pattern) below). The moment a
profile *edits* an engine file instead of layering beside it, that file can no longer be
re-synced without a merge conflict — and the fork is back.

## What a profile contains

A profile is four kinds of additive content:

1. **Concrete acceptance criteria** — instantiate `acceptance-criteria.md`'s generic,
   four-property gate skeleton with the actual thresholds and hold-out surface this product
   uses. The engine says "a gate is precommitted, measurable, evaluated on a locked
   hold-out, and compared to a null"; the profile says *which* gates, at *what* numbers.

2. **A filled production-handoff contract** — instantiate `production-handoff-contract.md`'s
   section skeleton with this product's real IO contract, environment, provenance, failure
   modes, and — most importantly — the known prod-vs-dev deltas.

3. **Extra anomaly families** — append product-specific failure modes to the diagnostic
   brief's canonical nine. The nine generic families stay; the profile *adds* the ones a
   given domain carries (a hardware integration, a third-party API boundary, a GPU
   inference path) under the diagnostic brief's "project-specific families" placeholder.

4. **An optional starter scaffold** — a blank source tree, config, and test layout the
   product's inception step lays down alongside the agent home. Optional, and always
   additive: the engine's `scaffold.py` lays the agent home; the profile's scaffold (if
   any) lays the application skeleton.

Everything else — the role briefs, the brain schema, the work-order format, the maintenance
loop — is engine, shared verbatim, never copied-and-edited.

## Three worked illustrations

**Web / API service.**
- *Acceptance:* p95 latency < 200 ms on a reserved traffic-replay profile; error rate
  < 0.1% over a 24-hour canary; must beat a hard-coded most-common-response stub.
- *Handoff contract:* names the load balancer, the rollback runbook, the error-budget
  burn-rate alert, and the dev-vs-prod delta in connection-pool sizing.
- *Extra anomaly family:* "retry-storm amplification" — a client retry policy that turns a
  brief upstream blip into a self-sustained load spike.

**Data pipeline / ETL.**
- *Acceptance:* output row count within ±0.01% of source after joins, on a locked
  validation snapshot; zero nulls in the required columns; the reconciliation tolerance
  check is known-answer unit-tested.
- *Handoff contract:* names the upstream schema owner, the late-arriving-data policy, and
  the dev-vs-prod delta between the batch backfill and the streaming feed's timing.
- *Extra anomaly family:* "watermark / windowing drift" — an aggregation window tuned on
  historical cadence that mis-buckets events under a live feed's jitter.

**ML / model.**
- *Acceptance:* held-out metric (e.g. F1) beats the majority-class baseline by a
  precommitted margin, set before training and never peeked at during tuning; calibration
  error below a fixed threshold on the same split.
- *Handoff contract:* names the feature store, the model-registry version pin, and the
  train-vs-serve delta in feature freshness.
- *Extra anomaly family:* "train-serve skew" — a preprocessing parameter fit on training
  data applied differently at inference time.

In each case the *shape* came from the engine (`acceptance-criteria.md`,
`production-handoff-contract.md`, `anomaly-families.md`); only the *content* is the profile.

## The bridge pattern

A downstream product keeps its profile in its own repo and pulls the engine in via an
**upgrade flow** (see `references/upgrade.md`): the upgrade re-reads the current engine and
adopts the latest directives, while the product's profile content (its gates, its filled
contract, its extra anomaly families, its project state) is **preserved** — never synced
over, because the profile only ever lived *beside* the engine, not inside it. One engine,
many products, no fork.

The mechanics of that wrapper — the required SYNC / PRESERVE / MERGE sections, the version-compat
metadata, and the `_meta.bridge` pointer the upgrade resolves — are specified in
[the BRIDGE contract](bridge.md) (`references/bridge.md`).
