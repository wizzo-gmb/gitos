# Glossary

Terminology used by the GitOS skill. Definitions are domain-agnostic.

---

## Core terms

**Pipeline home**
The directory where GitOS stores its working artifacts: the work-order ledger, the handoff, role briefs, and the brain. Default: `.gitos/` at the project root. Legacy projects may use `.pipeline/` or `outputs/debug/` as the home; the skill auto-detects and adopts it in place.

**Work-order**
The unit of tracked work in a GitOS pipeline. A work-order is a markdown file under `<home>/work-orders/` with a standard header (ID, severity, status, summary), a body that contains evidence-first findings or a scoped task description, and a lifecycle (open → resolved). Work-orders are the single task ledger — they are not knowledge pages (that's the brain) and not the birth record (that's the handoff).

**Forward work-order**
A work-order that describes planned or proposed work — a new hypothesis to test, a feature to build, a refactoring to attempt. Authored by the orchestrator when it identifies a next step. Contrasts with a bug work-order (below), which originates in the diagnostic role.

**Bug work-order**
A work-order that documents an anomaly or defect found by the diagnostic role. Written with evidence first: what was observed, where, what the expected behavior is, and what the severity is. Bug work-orders are written by the diagnostic finder and authorized for implementation by the orchestrator.

**Brain**
The orchestrator's long-term memory for a project. Stored at `.gitos/brain/` as a self-contained knowledge vault of typed, cross-linked pages. Page types: sources (factual summaries of ingested documents), entities (modules, services, components, dependencies, people), concepts (patterns, conventions, invariants, architectural understanding), decisions (ADR-style records of why things are the way they are). The brain holds knowledge; work-orders hold tasks; the handoff holds the birth record. Nothing is in two places.

**Handoff**
The birth record of a project — filled once at inception and never edited afterward. Records the project's identity, its acceptance criteria, its hold-out discipline, its outcome definition, its production target (if any), and any predecessor lessons. Anything that evolves over time moves into a brain page; the handoff is the immutable reference for what was decided at the start. Stored at `<home>/handoff.md`.

**Acceptance criteria**
The precommitted, measurable gates a deliverable must pass before it advances to the next lifecycle stage. Decided before evaluation runs. Evaluated on a locked hold-out set. Compared against a null/baseline. Gate arithmetic is unit-tested with known-answer cases. See `references/acceptance-criteria.md` for the full treatment.

**Hold-out** (also: locked hold-out, test set)
The portion of data, traffic, or evaluation surface that is designated at project start and never used during development, tuning, or optimization. The hold-out exists solely for the final, honest evaluation. Peeking at it — even to debug — compromises it. If the evaluation must run more than once, use attestation (a commit hash or timestamp gate) to record when and why.

**Production-handoff contract**
The written record of what was decided before the system was deployed: the IO contract, environment, data provenance, failure modes, rollback procedure, observability, performance budget, security/permissions, dependencies, runbook, and — most importantly — the known prod-vs-dev deltas. Filled as a blocking deliverable at the point of promotion. See `references/production-handoff-contract.md` for the skeleton.

**Null/baseline**
The simplest possible alternative the candidate system must beat. Random guess, majority-class classifier, mean prediction, the previous version, a hardcoded stub — the choice depends on the domain. A system that cannot beat its own null is not ready for promotion. Every set of acceptance criteria should include a null baseline result on the same evaluation surface.

**Lifecycle stages**
Project-declared labels for how far along a deliverable is: typically something like V0 (discovery/prototype), V1 (production candidate), live. The exact names are project-defined and recorded in the handoff. "V0→V1 promotion" means the deliverable passed acceptance criteria and is ready for production handoff. Stages are labels, not code — they don't imply specific tooling beyond what the project declares.

**Inception role**
The one-time bootstrapper. Runs an interview, lays the `.gitos/` directory tree, seeds the brain, fills the handoff, and hands control to the orchestrator. Does not write application source code.

**Orchestrator role**
The front-line builder and coordinator. Reads the handoff once, reads `INDEX.md` and the brain every session, owns the work-order lifecycle, builds with the user, stewards the brain via the maintenance loop (inline upsert → checkpoint reconcile → `brain_lint.py`), and invokes the diagnostic role for evidence. May authorize edits.

**Diagnostic role**
The read-only finder. Builds the output vocabulary, scans anomaly families, writes evidence-first work-orders. Does not edit code. The finding/fixing separation is the most important role boundary — it keeps the investigator's read-only posture intact under pressure.

**Implementer role**
The dispatched executor — an ephemeral agent the orchestrator spins up to land one work-order, then return. Not an operator-entry role (no session, no user phrasing). Edits only what its work-order's Proposed fix scope specifies; surfaces follow-ups and out-of-scope observations as *proposed* notes, never self-executed. Full brief: `references/roles/implementer.md`.
