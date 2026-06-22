# Anomaly families — the nine prioritized categories

These are the nine families to scan systematically in Phase 2. They're ordered
roughly by blast radius (1 highest, 9 lowest), but a system's domain may
reorder them. The structure is universal; the specifics adapt.

Adapt the examples to the project's domain when scanning. For each family,
look for log evidence first — anomalies you can't prove from logs become
`unconfirmed` work-orders with the gap documented.

---

## 1. Math / formula / sizing correctness

**Highest blast radius for any system with computed outputs.**

What to look for:
- Critical formulas should be derivable from logged inputs. Find a log line
  that shows inputs and the computed output. Recompute by hand. Compare.
- Multipliers printed in logs that don't actually propagate — e.g., a
  `dd_throttle=0.5` log followed by a `contracts=14` calculation that didn't
  apply the throttle.
- Sign errors, off-by-one, integer-vs-float drift in places where the
  intermediate value is logged but not the final.
- Commission, fee, or rake calculations where the count of "sides" or "legs"
  could be wrong.

**Domain adaptations:**
- IoT/telemetry: batch sizing (`records = floor(buffer_bytes / record_size)`), throughput accounting (`samples × bytes_per_sample × devices − 2 × header_bytes × packets`), quota/rate-budget math.
- Billing: per-unit pricing, tax, discounts, currency conversion.
- ML: loss-function components, weighted aggregates, normalization.
- Data pipeline: aggregations, joins (cardinality bugs), windowed stats.

**Evidence pattern:** quote the input log line, quote the output log line,
show the recomputation, show the drift.

---

## 2. State machine / lifecycle / init ordering

What to look for:
- Fields set in one lifecycle phase used in an earlier phase (or set later
  than first use).
- Daily/session/lifetime reset boundaries: what resets when, what doesn't.
- Reset on restart vs reset on date change vs reset never — these are
  different invariants, often confused.
- Transitions that should be paired (open/close, start/stop, lock/release)
  but aren't, observable as orphaned log lines.

**Domain adaptations:**
- IoT/telemetry: peak-reading (high-water mark) lifecycle, session-peak tracking, reconnect-backoff/cooloff state, daily-quota reset.
- Web service: session init order, auth-context-vs-request lifecycle, request-scoped vs app-scoped state.
- Background jobs: idempotency keys set on which phase, retry state, cron-vs-realtime initialization.
- Game state: scene init, save/load, cross-frame mutations.

**Common bug shape:** "X is initialized in phase A but first used in phase B
which runs before A on cold start" — e.g., a streak-state loader that fires at
data-ready time before the account/user context is resolved, freezing the file
path to a placeholder. Analogous in web services to auth-context populated after
the first middleware that reads it.

---

## 3. Config / contract drift between producer and consumer

What to look for:
- Schema fields the writer emits vs the reader expects. A silent default
  fallback when a key is missing (`get("foo", 0)`) hides the drift.
- Field name capitalization, snake_case-vs-camelCase, plural-vs-singular.
- Required-vs-optional drift across versions.
- Serialization formats: JSON vs JSONL, BOM vs no-BOM, UTF-8 vs UTF-16,
  trailing comma tolerance.

**Domain adaptations:**
- IoT/telemetry: a device config JSON written by one language (e.g., a Python provisioner) and consumed by another (e.g., a C# firmware bridge) — field-name and type mismatches are silent.
- Microservices: API contract drift between client and server across independent deploy cycles.
- ML: feature-name drift between training-time schema and inference-time schema.
- Data pipeline: column-name drift between extractor and loader.

**Verification:** walk the writer-side field-by-field against the reader-side.
Quote both. If they match, document it as a DISPROOF in INDEX.md so the next
agent doesn't re-investigate.

---

## 4. Conditional gates / filters not firing when they should

What to look for:
- Guards documented as `if X then skip` that don't show their skip log line
  even when X is logged as true.
- Filter thresholds that pass-through trivially (e.g., `magnitude >= 0.0` is
  always true).
- Rate-limit or cooldown logic that resets too aggressively.
- "First N items" filters that count wrong elements (e.g., counts rows
  including header).

**Domain adaptations:**
- IoT/telemetry: tiered sampling filters (L1/L2/L3/L4), throttle activation thresholds, maintenance-window blocks.
- Web service: rate limiters, allowlist/denylist checks, feature flags.
- Validators: input sanitization, schema validators, range checks.
- Permissions: ACL evaluation, role checks.

**Pattern:** if a guard exists in code but never appears in logs even under
conditions you'd expect it to fire, file an `unconfirmed` work-order — the
absence of evidence is itself evidence.

---

## 5. Persistence / restart safety / multi-instance isolation

What to look for:
- State that should survive restart but resets to a placeholder.
- State that should be per-instance/per-account/per-tenant but writes to a
  shared file.
- File paths constructed with placeholder fallbacks (`?? "UNKNOWN"`) that
  freeze the path with the placeholder.
- Cross-restart drift: behavior depends on chart/process being open vs
  freshly started.

**Domain adaptations:**
- IoT/telemetry: peak-reading and backoff-state persistence — a placeholder device token in the file path means state silently resets every restart.
- Web service: session store, cache invalidation, sticky-routing.
- ML: model checkpoint loading, hyperparameter state across training runs.
- CLI tools: rc-file lookup, working-directory assumptions, env-var defaults.

**Test pattern:** read multi-day logs and look for whether observably-derived
state (like a high-water mark, a streak counter, a session token, a trained
checkpoint path) survives the restart boundary. If a `loaded from <X>` log line
never appears after restart, the state isn't persisting.

---

## 6. Diagnostics gaps (wrong log sink, silent fallback)

What to look for:
- Log lines emitted to one sink (Console/stdout/syslog) when they should
  reach another (per-instance file, structured log aggregator).
- Silent guards that fail open without logging — e.g., `try { X } catch { /* swallow */ }`
  in production code paths.
- Default-fallback returns (e.g., `return 1.0` on schema mismatch) without a
  warning emission.

**Domain adaptations:**
- IoT/telemetry: boot-phase log lines going to a global console instead of the per-device file logger — invisible once the console buffer wraps.
- Web service: error responses without server-side log entries (client sees 500, server log is silent).
- CLI tools: `2>/dev/null` patterns, or swallowed exceptions in shell wrappers, that hide real errors.
- ML: training-loop exceptions caught and logged only at DEBUG level while the job reports "complete".

**Why this family matters:** future diagnostic agents (including you) depend
on these logs. Closing the loop matters even when current behavior is
"correct".

---

## 7. Edge cases (sentinel handling, timezone, integer truncation)

What to look for:
- `None`/`null`/empty-string handling. Sentinel collisions (e.g., -1 as
  both "not found" and a legit value).
- Timezone boundaries: UTC-vs-local-vs-exchange. Midnight rollover behavior.
  Daylight Saving Time transitions.
- Integer truncation of floats where precision matters (e.g., `T=34.7` stored
  as `int` → 34, or rounded to 35).
- Empty-collection handling: divisions by zero, "max of empty" returning
  sentinel.
- Off-by-one in window definitions: `>= start AND < end` vs `>= start AND <= end`.

**Domain adaptations:**
- IoT/telemetry: device-local-vs-UTC boundary for daily reset, sensor-scale precision (5.0 vs 5).
- ML: NaN propagation through aggregations, masked values in feature pipelines.
- Web service: locale handling, encoding detection, max-int overflow.

---

## 8. Calibration / research-vs-deployment drift

What to look for:
- Values produced by an offline pipeline shipped to a live consumer where the
  consumer applies the value differently than the producer assumed.
- Threshold selectors that pick boundary values (e.g., T=0 as PF-maximum)
  that the live consumer's downstream logic depends on being non-zero.
- Hyperparameters tuned on one slice and deployed against a different one.

**Domain adaptations:**
- IoT/telemetry: alert threshold sweeps where the winning value (e.g., 0.0) degenerates the live gate — the optimizer picked a boundary that removes the filter entirely.
- ML: train-vs-serve skew; a preprocessing parameter tuned on training data applied differently at inference.
- Web service / A/B testing: stat-significance threshold used to select a variant, but the deployment activation condition uses a different comparison.
- Data pipeline: aggregation window tuned on historical cadence, deployed against a streaming feed with different timing.

**Pattern:** find a deployed value, find where it was selected, recompute
how the live consumer applies it. Differences are often hidden by the writer
and reader living in different code paths or even different languages.

---

## 9. Negative-EV / "shouldn't trigger" paths

What to look for:
- Guards that protect against bad behavior — verify they actually block what
  they're supposed to.
- "This branch should never run" code that occasionally runs.
- Dormant-mode logic for entities that should be inactive (e.g., disabled
  feature flags, suspended users).

**Domain adaptations:**
- IoT/telemetry: `enabled=false` devices should skip sampling entirely;
  a zeroed rate-budget should not emit telemetry.
- Web service: deactivated accounts must not be able to authenticate; deleted
  resources must not be returned by list endpoints.
- ML: out-of-distribution detector must trigger when expected, not silently
  return predictions.

**Critical insight:** for this family, **the absence of log evidence IS
evidence**. If a guard exists in code but never produces its expected log line
in the conditions where it should fire, that's either (a) the condition has
never occurred or (b) the guard isn't actually firing. File as `unconfirmed`
with the test condition that would distinguish (a) from (b).

---

## Cross-cutting heuristics

These apply across all nine families:

**Reproducibility check.** Before filing a work-order, count how many times
the anomaly appears in logs. Once = note it but treat with care. Multiple
times across different sessions = confident filing.

**Pair every assertion with quoted evidence.** "The log shows X" must be
followed by the actual log line, with file path and line number. Future
readers (including future you) will trust the work-order only as far as the
evidence supports.

**Severity is about consequence, not certainty.** A high-confidence
cosmetic bug is `low`. A low-confidence safety bug is `critical-unconfirmed`.
Don't conflate.

**Look for what's NOT in the log too.** If a log file is much shorter than
you expected, ask why. If a guard's "skip" branch never logs, ask why. If a
periodic job's heartbeat is missing, that's data.
