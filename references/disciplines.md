# Engineering Disciplines

These are the transferable rules that emerged from real failures — not abstract best practices, but lessons extracted from things that actually went wrong. Each has a name so it can be cited precisely in work-orders, code review, and orchestrator decisions.

For each: what the rule is, the failure it prevents, and where it tends to bite hardest.

---

## (a) Gate-math-is-code — regression-test your checks

**The rule:** Every check, gate, filter, or audit that produces a pass/fail verdict is code. Its arithmetic must be unit-tested with known-answer inputs that assert the exact verdict — both a case that should PASS and a case that should BLOCK. "The system ran without crashing" is not a test of the gate's correctness.

**The failure it prevents:** A metric gate consumed the wrong statistic (excess kurtosis where the formula expected full kurtosis, so Normal≈0 instead of Normal=3). The gate silently inverted promote/kill verdicts on high-scoring configurations. The test suite was green the entire time because no test had ever pinned the gate's arithmetic to a hand-computed expected answer. The inversion shipped and was caught only when a human checked a result that looked wrong.

**Where it bites:** Anywhere a formula is translated from math notation to code — statistical gates (FDR, calibration error, AUC), latency percentile checks, reconciliation tolerance checks, threshold comparisons. Also common: a gate that works correctly at implementation but drifts when a dependency updates its output format. The regression test is what catches the drift.

**How to apply it:** For every gate, write at least two tests before the gate is considered wired: one with a hand-computed input that should pass, one that should fail. If the gate depends on a statistical function (e.g. a percentile computation, a BH-FDR p-value), write a known-answer test for that function too — don't assume the function is correct because it came from a library.

---

## (b) Precondition-guards — prove the change bit

**The rule:** When a filter, transform, or selection step runs, assert that it actually changed something before counting its verdict. A pass/fail from a step that silently changed nothing is not a result — it's a no-op masquerading as a result.

**The failure it prevents:** A filter "passed" cleanly in the evaluation pipeline, but the filtered item count was identical to the unfiltered baseline. The filter was mis-wired and did nothing. Because the pipeline didn't assert a count change, the "pass" propagated as if the filter had genuinely validated the hypothesis. The silent no-op was indistinguishable from a working filter.

**Where it bites:** Filter hypotheses (a new entry filter that should reduce trade count), data preprocessing steps (a deduplication step that should reduce row count), transformation pipelines (a normalization step that should change value ranges), any step that claims to select or exclude items. Also bites in configuration changes: "the feature flag was set" is not evidence the flag was read — check the behavior changed.

**How to apply it:** Before a filtered result counts, assert: `assert filtered_count != baseline_count`. If the count is equal, the precondition guard fails loudly and the downstream verdict is discarded. Write the guard as part of the gate, not as a debug print — it should block, not warn.

---

## (c) Cheap-probe-before-expensive-sweep

**The rule:** Before launching a costly parameter sweep, grid search, or multi-dimensional scan, run a cheap read-only probe over the candidate space. Only a GO verdict from the probe authorizes the expensive sweep. A probe that surfaces a contradiction (e.g. the idea that won on input A loses on input B) is itself a NO-GO and saves the sweep cost.

**The failure it prevents — two failure modes:**
1. A read-only probe over ~9,500 candidate arms returned NO-GO before a 13-cell parameter sweep was ever launched, saving the entire sweep cost. The probe found the signal absent at every tested point; the sweep would have confirmed the same thing at 100× the cost.
2. A feature re-encoding that looked promising on one instrument turned out strictly worse on a second instrument. A two-instrument probe surfaced the contradiction cheaply; without it the sweep would have run on one instrument, declared a win, and deployed a context-specific edge as a general one.

**Where it bites:** ML hyperparameter sweeps, A/B test variant selection, multi-instrument or multi-segment analysis, any task where the expensive job is justified only if a preliminary signal exists. Also bites in infrastructure work: verify the new dependency is available on the target machine before triggering the full deployment pipeline.

**How to apply it:** The probe should be read-only and fast — it checks GO/NO-GO, it does not optimize. Document the probe result as a work-order or a brain decision page before authorizing the sweep. A contradiction discovered in the probe (the idea works here but not there) is a finding, not a failure — record it.

---

## (d) Check-the-path-not-the-schedule

**The rule:** When investigating whether a bug or leak is possible, trace the actual execution path — what code actually runs, in what order, with what data — rather than reasoning from structure alone. A structurally plausible bug may be a no-op because the code path that would trigger it is never reached.

**The failure it prevents:** A structurally plausible data leak was flagged as a likely bug based on how the code was organized. When the actual execution path was traced (following the call chain, checking which branches were taken for the relevant input), the leak was unreachable — the concerning code path was never executed in the scenario under investigation. Reporting it as a bug without tracing the path would have triggered unnecessary rework.

**Where it bites:** Security and correctness audits ("this could leak data if..."), refactoring ("this change might break..."), performance investigations ("this code might be slow because..."). Also bites in distributed systems: "the retry loop could cause a duplicate write" may be false if the upstream component is idempotent — trace the path before filing the bug.

**How to apply it:** Before writing a bug work-order for a suspected path, read the code, follow the call chain, and identify at least one concrete input that reaches the concerning code. If you can't construct the input, mark the finding as "unconfirmed — path may be unreachable" and list what would need to be true for it to be reachable.

---

## (e) Copy-without-rename leak

**The rule:** When copying a file, module, or document from one project/context to another, rename every identifier that names the source before the copy counts as done. A copied file that still carries the source's name is not ported — it is a leak. Copy and rename are one atomic operation, not two separate steps.

**The failure it prevents:** A project copied files from a reference scaffold "as a baseline" and never renamed them. The original project's config class, entire feature modules, environment variable prefixes, test fixtures, and docstrings stayed wired in — approximately 500 references across 50 files. The test suite was green throughout because renaming was never a test condition. The leak was caught only by `grep`, weeks later, when something behaved unexpectedly and the investigation revealed the stale references. The fix was a major cleanup that could have been avoided by a per-file rename rule applied at copy time.

**The same failure in prose/brain pages:** A concept page copied from one project's brain and pasted into another retains the first project's framing, constraints, and examples. The reader assumes the page describes the current project. A rename/reframe is as mandatory for prose as for code.

**Where it bites:** Any port from a reference implementation, any "use this as a starting point" copy, any template instantiation. Also bites in documentation: "let's use the old project's runbook as a base" — the old project's service names, ports, and commands stay in, and the operator follows the wrong runbook under pressure.

**How to apply it:** Per-file, immediately after copying: `grep -i '<source_name>' <copied_file>` must return nothing except a single explicit attribution comment (`# ported from <source>:<path>`). Run the grep as you go — not just at the end. The handoff gate re-runs the same grep across the whole tree as a final check.

---

## (f) Disproofs-are-deliverables

**The rule:** A hypothesis that was tested and ruled out is a deliverable. Record it — what was tested, what the result was, and why it was ruled out — so it is not re-investigated by a future session, a different team member, or a different agent.

**The failure it prevents:** An idea that failed evaluation was not recorded. Six months later, a new team member (or a compacted AI session with no memory) independently re-investigated the same idea, ran the same tests, and reached the same negative conclusion — wasting the same time twice. In a more acute form: a disproved idea was re-proposed during a planning session because there was no record it had been tried; the "new" proposal was approved and a work-order was opened before anyone recalled the prior negative result.

**Where it bites:** Research-heavy projects (ML, product experiments, architectural spikes), long-running codebases with high turnover, any project using an AI agent whose context compacts between sessions. Especially bites in hypothesis-driven work where the space of ideas is large and each test is expensive.

**How to apply it:** When a hypothesis, approach, or design option is ruled out, write a one-paragraph finding: what was tried, what was observed, and why it doesn't work (or doesn't work well enough). File it in the INDEX under "Findings DISPROVED" and, if the brain exists, add a decision page (ADR-style) for any non-trivial choice made. Link it from anywhere the idea might re-surface (the work-order that tested it, the relevant concept page). "We tried this" is as valuable as "we found this works."

---

## (g) Trust-but-verify-the-landing

**The rule:** When an agent (AI or human) reports that a task is done, verify with direct evidence before marking it complete. An agent's "done" is a claim about intent, not a record of what was actually written to disk, committed, or deployed. Read the diff. Run the grep. Check the output file. The verification is not distrust — it is how the loop closes.

**The failure it prevents:** An implementing agent reported that a rename was complete. The orchestrator marked the work-order resolved. A subsequent investigation (triggered by an unrelated anomaly) found that several files had not been updated — the agent had renamed the ones it drafted but missed files it hadn't opened. The "done" was accurate for the files the agent had explicitly touched and incomplete for the ones it hadn't considered. The gap was only surfaced when a grep ran across the full tree.

**Where it bites:** Any multi-file change where the agent touched some files but may have missed others. Any change where the success condition is "no occurrences of X remain" rather than "this specific line was changed." Any deployment where the expected artifact (a binary, a config file, a database row) must actually exist for the deployment to be live. Also bites in code review: "the comment says it does X" is not the same as "the code does X."

**How to apply it:** After a work-order is reported done, run at least one of: `git diff` (inspect what actually changed), a targeted grep (confirm the old pattern is gone and the new one is present), or a read of the specific output file (confirm the artifact exists and has the expected content). Move the work-order to `resolved/` only after the verification step, not on the agent's report alone. Document what you verified in the work-order's closing comment.
