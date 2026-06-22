# Acceptance Criteria

**What goes here:** the project's promotion gates — the explicit, precommitted tests a deliverable must pass before it advances to the next lifecycle stage. This reference explains what makes a gate system rigorous and gives cross-domain examples; for worked end-to-end instantiations see `references/profiles.md`.

---

## What makes acceptance criteria rigorous?

Four properties separate real gates from wishful thinking.

**1. Precommitted — decided before you see the results.**
Write the gates before you run anything. The most common way acceptance criteria fail is that they're set (or quietly adjusted) after a run looks promising. A gate you set after seeing a result is a post-hoc rationalization, not a filter. Record your criteria in the handoff or a work-order, with a commit-hash or timestamp, before the first evaluation run.

**2. Measurable — a clear pass/fail, not a vague judgment.**
"Performance is acceptable" is not a gate. "p95 response time < 200 ms on the baseline load profile" is. Each gate should produce a boolean verdict you could check by script without asking anyone's opinion. If you can't write `assert measured_value >= threshold`, the gate isn't finished.

**3. Evaluated on a locked hold-out — not the data you built on.**
Whatever you optimized, tuned, or trained against is compromised for honest evaluation. A held-out test set (or a frozen validation slice, or a canary deployment cohort, or a sample the labeler never saw) must be designated at project start and never touched during development. If you peek at it — to check a threshold, to debug an anomaly — it's no longer a hold-out. Reserve it. The final verdict runs exactly once, or under strict attestation if it runs more than once.

**4. Compared to a null/baseline — "is it actually better than nothing?"**
Every project should answer: what does the simplest imaginable alternative score? Random guess, majority-class classifier, mean prediction, a sleep-1-second stub, a `git blame` of the previous version — pick one and make the candidate beat it. A system that beats nothing is not ready. Gate 0 is always: does it outperform the null?

**5. Gate math is code — regression-test your checks.**
The arithmetic inside a gate is itself software, and software has bugs. A gate that consumes the wrong statistic (e.g. excess kurtosis where the formula expected full kurtosis, or a rate where a count was expected) will silently invert pass/fail verdicts with no test suite error. Write at least one known-answer regression test per gate: feed a hand-computed input, assert the exact verdict. Test that it BLOCKS a bad input AND PASSES a good one. A gate with no regression test is a claim, not a check.

---

## Example gate shapes across domains

These are illustrative shapes. Your project defines the thresholds.

**Web / API service**
- p95 latency on the baseline synthetic load profile < 200 ms (evaluated on the reserved traffic replay, not synthetic load you tuned against)
- Error rate < 0.1% over a 24-hour canary window
- Null baseline: a hard-coded stub returning the most-common response in under 1 ms — the new system must beat the stub on every non-latency metric
- Gate math: a percentile-computation function is unit-tested against a hand-crafted sorted array with a known p95 value

**ML / model**
- Held-out test-set F1 >= 0.72 (set before training, never peeked at during tuning)
- Beats majority-class baseline on held-out F1 by at least 0.10 absolute
- Calibration error (ECE) < 0.05 on the same held-out split
- Gate math: the ECE computation is unit-tested with a hand-crafted probability-vector/label pair whose exact ECE is known

**Data pipeline / ETL**
- Row count reconciliation: output row count within ±0.01% of source row count after joins (evaluated on a locked validation snapshot)
- No null values in the five required columns on the full output table
- Processing time < 15 minutes on the reference dataset size
- Null baseline: the previous pipeline version's output used as the expected reference — the new run must match within tolerance
- Gate math: the reconciliation tolerance check is unit-tested with a constructed count pair that should barely pass and one that should barely fail

**Library / SDK**
- Public API surface is backward-compatible with the previous minor version (checked by a programmatic diff of the exported symbol set)
- No regression on the existing benchmark suite (p50 latency within 5% of baseline, measured on the frozen benchmark dataset)
- Zero new linter errors on files changed in this release
- Gate math: the API-compat diff tool is tested with a known-breaking change to confirm it flags the right symbols

---

## Filling your gates

In the project handoff (`handoff.md`, §Acceptance), fill in:

```
gate_1: <what is measured> | <threshold> | <hold-out or evaluation surface>
gate_2: ...
null_baseline: <what the simplest alternative scores on each gate>
gate_math_tests: <pointer to the regression test file(s)>
precommitment_timestamp: <commit hash or date when gates were written>
```

You don't need eight gates or four. You need enough to prevent the failure modes your domain carries. Two rigorous gates beat ten vague ones.
