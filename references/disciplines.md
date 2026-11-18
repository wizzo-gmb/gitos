# Engineering Disciplines

These are the transferable rules that emerged from real failures — not abstract best practices, but lessons extracted from things that actually went wrong. Each has a letter and a name so it can be cited precisely in work-orders, code review, and orchestrator decisions.

A discipline holds in any domain. A lens is a domain technique pack that implements disciplines and says which ones; a profile packages a domain. The engine came out of quantitative research, so many of the war-stories are from there. They are labelled "(quant instance)", and the entries from (h) on carry one software instance and one quant instance each.

For each: what the rule is, the failure it prevents, where it tends to bite hardest, and how to apply it.

| | Discipline | In one line |
|---|---|---|
| (a) | Gate-math-is-code | A check's arithmetic is code: known-answer tests that pass a good input and block a bad one. |
| (b) | Precondition-guards | A step that changed nothing has no verdict; assert that the change bit. |
| (c) | Cheap-probe-before-expensive-sweep | A cheap read-only GO/NO-GO, including whether the data can decide at all, before the costly run. |
| (d) | Check-the-path-not-the-schedule | Trace what actually runs, and re-derive second-hand premises, before calling it a bug. |
| (e) | Copy-without-rename leak | Copy and rename are one step; a copy that still names its source is a leak. |
| (f) | Disproofs-are-deliverables | Record what was ruled out, and under what conditions, so nobody runs it again. |
| (g) | Trust-but-verify-the-landing | "Done" is a claim; check the disk, the running system, and what the evidence was made with. |
| (h) | A-check-must-be-able-to-fail | Show a check go red on a planted defect before its green counts. |
| (i) | No-answer-is-not-a-pass | Skipped, empty, missing or crashed is a state of its own that blocks, never a neutral value. |
| (j) | A-null-needs-a-positive-control | "No effect" counts only if the instrument could have seen one. |
| (k) | Attack-your-own-win | A positive result gets the adversary a negative one would get. |
| (l) | Name-the-clock | Every time value says which clock it is on. |
| (m) | Evidence-or-name-the-gap | Ship one field short with the gap named; never fill it with something plausible. |
| (n) | A-rule-needs-a-mechanism | A rule with no enforcement where it must hold is a wish. |
| (o) | Finish-what-you-find | Fix what you find within the order's scope; defer only what is out of it; drop nothing. |

---

## (a) Gate-math-is-code — regression-test your checks

**The rule:** Every check, gate, filter, or audit that produces a pass/fail verdict is code. Its arithmetic must be unit-tested with known-answer inputs that assert the exact verdict — both a case that should PASS and a case that should BLOCK. "The system ran without crashing" is not a test of the gate's correctness.

**The failure it prevents (quant instance):** A metric gate consumed the wrong statistic (excess kurtosis where the formula expected full kurtosis, so Normal≈0 instead of Normal=3). The gate silently inverted promote/kill verdicts on high-scoring configurations. The test suite was green the entire time because no test had ever pinned the gate's arithmetic to a hand-computed expected answer. The inversion shipped and was caught only when a human checked a result that looked wrong.

**Where it bites:** Anywhere a formula is translated from math notation to code — statistical gates (FDR, calibration error, AUC), latency percentile checks, reconciliation tolerance checks, threshold comparisons. Also common: a gate that works correctly at implementation but drifts when a dependency updates its output format. The regression test is what catches the drift.

**How to apply it:** For every gate, write at least two tests before the gate is considered wired: one with a hand-computed input that should pass, one that should fail. If the gate depends on a statistical function (e.g. a percentile computation, a BH-FDR p-value), write a known-answer test for that function too — don't assume the function is correct because it came from a library. Known-answer tests prove the arithmetic on inputs you chose; whether the gate, as wired, can go red at all is (h).

---

## (b) Precondition-guards — prove the change bit

**The rule:** When a filter, transform, or selection step runs, assert that it actually changed something before counting its verdict. A pass/fail from a step that silently changed nothing is not a result — it's a no-op masquerading as a result.

**The failure it prevents (quant instance):** A filter "passed" cleanly in the evaluation pipeline, but the filtered item count was identical to the unfiltered baseline. The filter was mis-wired and did nothing. Because the pipeline didn't assert a count change, the "pass" propagated as if the filter had genuinely validated the hypothesis. The silent no-op was indistinguishable from a working filter.

**Where it bites:** Filter hypotheses (a new filter that should reduce the item count), data preprocessing steps (a deduplication step that should reduce row count), transformation pipelines (a normalization step that should change value ranges), any step that claims to select or exclude items. Also bites in configuration changes: "the feature flag was set" is not evidence the flag was read — check the behavior changed.

**How to apply it:** Before a filtered result counts, assert: `assert filtered_count != baseline_count`. If the count is equal, the precondition guard fails loudly and the downstream verdict is discarded. Write the guard as part of the gate, not as a debug print — it should block, not warn.

---

## (c) Cheap-probe-before-expensive-sweep

**The rule:** Before launching a costly parameter sweep, grid search, or multi-dimensional scan, run a cheap read-only probe over the candidate space. Only a GO verdict from the probe authorizes the expensive sweep. A probe that surfaces a contradiction (e.g. the idea that won on input A loses on input B) is itself a NO-GO and saves the sweep cost.

**The failure it prevents — two failure modes (quant instances):**
1. A read-only probe over ~9,500 candidate arms returned NO-GO before a 13-cell parameter sweep was ever launched, saving the entire sweep cost. The probe found the signal absent at every tested point; the sweep would have confirmed the same thing at 100× the cost.
2. A feature re-encoding that looked promising on one instrument turned out strictly worse on a second instrument. A two-instrument probe surfaced the contradiction cheaply; without it the sweep would have run on one instrument, declared a win, and deployed a context-specific edge as a general one.

**Where it bites:** ML hyperparameter sweeps, A/B test variant selection, multi-segment or multi-population analysis, any task where the expensive job is justified only if a preliminary signal exists. Also bites in infrastructure work: verify the new dependency is available on the target machine before triggering the full deployment pipeline.

**How to apply it:** The probe should be read-only and fast — it checks GO/NO-GO, it does not optimize. Document the probe result as a work-order or a brain decision page before authorizing the sweep. A contradiction discovered in the probe (the idea works here but not there) is a finding, not a failure — record it.

**Decidability is part of the probe.** Before the spend, work out what the data can settle: units per cell, and the smallest effect the run could detect against the effect you care about. If the run cannot decide, change the design or stop; running it anyway produces noise that gets over-read. Software: an A/B test whose traffic over the planned duration cannot show the lift it is meant to detect. (Quant instance: a 768-cell parameter grid against roughly 435 usable trades left half the cells unable to reach 30 trades before any gate ran.)

---

## (d) Check-the-path-not-the-schedule

**The rule:** When investigating whether a bug or leak is possible, trace the actual execution path — what code actually runs, in what order, with what data — rather than reasoning from structure alone. A structurally plausible bug may be a no-op because the code path that would trigger it is never reached.

**The failure it prevents:** A structurally plausible data leak was flagged as a likely bug based on how the code was organized. When the actual execution path was traced (following the call chain, checking which branches were taken for the relevant input), the leak was unreachable — the concerning code path was never executed in the scenario under investigation. Reporting it as a bug without tracing the path would have triggered unnecessary rework.

**Where it bites:** Security and correctness audits ("this could leak data if..."), refactoring ("this change might break..."), performance investigations ("this code might be slow because..."). Also bites in distributed systems: "the retry loop could cause a duplicate write" may be false if the upstream component is idempotent — trace the path before filing the bug.

**How to apply it:** Before writing a bug work-order for a suspected path, read the code, follow the call chain, and identify at least one concrete input that reaches the concerning code. If you can't construct the input, mark the finding as "unconfirmed — path may be unreachable" and list what would need to be true for it to be reachable.

**Premises expire.** The same applies to second-hand claims. A flag, a comment, a doc, a backlog row, a handoff figure or an earlier session's diagnosis records someone's decision or an old measurement, not current fact. Re-derive it from the source before acting on it, or cite it as "not re-checked". Software: an orchestrator's diagnosis in a brief was wrong, and was caught only because the implementer re-read the source instead of trusting the brief. (Quant instance: a disabled data flag, with a comment saying the module sourced no calendar, was cited three times as proof that a hypothesis could not be tested; the calendar was already in the database.)

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

**How to apply it:** When a hypothesis, approach, or design option is ruled out, write a one-paragraph finding: what was tried, what was observed, and why it doesn't work (or doesn't work well enough). File it on a brain decision page (ADR-style) when the brain exists, else in the work-order that tested it. Link it from anywhere the idea might re-surface (the work-order that tested it, the relevant concept page). "We tried this" is as valuable as "we found this works."

A disproof records the conditions it was tested under (data, versions, environment), so that a negative about the environment can be re-tested when those change rather than inherited forever. A disproof also counts only if the instrument could have seen the effect; see (j). The project's own retracted claims are deliverables too: mark the claim retracted where it stands, keep the old text, and say why it was wrong.

---

## (g) Trust-but-verify-the-landing

**The rule:** When an agent (AI or human) reports that a task is done, verify with direct evidence before marking it complete. An agent's "done" is a claim about intent, not a record of what was actually written to disk, committed, or deployed. Read the diff. Run the grep. Check the output file. The verification is not distrust — it is how the loop closes.

**The failure it prevents:** An implementing agent reported that a rename was complete. The orchestrator marked the work-order resolved. A subsequent investigation (triggered by an unrelated anomaly) found that several files had not been updated — the agent had renamed the ones it drafted but missed files it hadn't opened. The "done" was accurate for the files the agent had explicitly touched and incomplete for the ones it hadn't considered. The gap was only surfaced when a grep ran across the full tree.

**Where it bites:** Any multi-file change where the agent touched some files but may have missed others. Any change where the success condition is "no occurrences of X remain" rather than "this specific line was changed." Any deployment where the expected artifact (a binary, a config file, a database row) must actually exist for the deployment to be live. Also bites in code review: "the comment says it does X" is not the same as "the code does X."

**How to apply it:** After a work-order is reported done, run at least one of: `git diff` (inspect what actually changed), a targeted grep (confirm the old pattern is gone and the new one is present), or a read of the specific output file (confirm the artifact exists and has the expected content). Move the work-order to `resolved/` only after the verification step, not on the agent's report alone. Record what you verified in the work-order's adjudication.

**Verify what is running, and stamp the evidence.** A change on disk is not a change in the running system: check the version the running process reports, not the one you built. Every result records the code, data and config that produced it; when any of them changes, results made with the old ones stop being citable until they are re-run. Software: a proof run was counted as passed on a build other than the one under test. (Quant instance: after nine fixes to a validation gate battery, all 28 earlier result files had been produced by the unfixed gates and none could be cited; their run id hashed the parameters but not the code, so nothing had marked them stale.)

---

## (h) A-check-must-be-able-to-fail — the negative control

**The rule:** Before a check's green counts, show it go red. Plant the defect it claims to catch, in the direction it claims, through the path production uses, and confirm the check blocks. Confirm first that the plant actually bites; otherwise a green check and an ineffective plant look the same.

**The failure it prevents:** A check that cannot fail reports green forever, and the green is read as health. It is worse than no check, because it is the reason nobody looks.

**Where it bites:** Three shapes recur. *Not wired:* the guard exists and is unit-tested, but no production path calls it, or a literal or an empty default feeds it. *The name is a claim:* the check measures less than its name says; test it on the input it would look silliest on. *Self-referent:* the expected value or the threshold is read from the thing under test, so the check agrees with whatever the code does.

**How to apply it:** A work-order that adds or changes a gate carries a negative control in its Verification. This is distinct from (a), which proves the arithmetic on chosen inputs, and from (b), which proves a step changed something in this run: (h) asks whether the check, as deployed, can say no. Reason from the assertion, not from the comment above it.

**Software instance:** A gate used `git check-ignore` to ask whether a pattern covered a file. For a tracked file that command answers "not ignored" whatever the pattern, so the gate was blind to the case it existed for. It sat green for several versions; a deliberate mutation found it, never a passing run.

**Quant instance:** A multiple-testing gate was fed a hard-coded p-value instead of the run's own, so its verdict was fixed by construction, and a "slippage stress" gate in the same battery applied a flat haircut that could never flip the sign of a result.

---

## (i) No-answer-is-not-a-pass

**The rule:** When a check or computation cannot produce an answer (empty input, too few observations, NaN, a missing record, a skipped test, a swallowed exception, a timeout), it returns a state that names the condition and blocks the verdict. It never returns a plausible neutral value, and an absence is never read as zero. Count skips the way you count failures, and give each kind of outcome its own name so the denominator is complete.

**The failure it prevents:** The no-answer lands on the pass side. 0.0 and 1.0 are not neutral; they are usually the passing side of some threshold. A crash, an empty set and a real verdict become indistinguishable downstream.

**Where it bites:** Test summaries, health checks, statistics on small or empty groups, fallbacks and defaults, exit codes (a crash whose exit code equals a verdict's), and any read of external state that can fail partway: a torn read is not an empty one.

**How to apply it:** For each check, write down what it returns on empty, degenerate and unreadable input, and test those inputs. A check that could not run prints `skipped (reason)` and the summary counts it. Where a value has to be assumed, label it as assumed; see (m).

**Software instance:** A test run reported "29 skipped, 0 failed" and was read as green. The skipped tests had not run at all.

**Quant instance:** A deflated-Sharpe function given a trial count of one returned 1.0, its most confident value, for any Sharpe ratio, including -5.

---

## (j) A-null-needs-a-positive-control

**The rule:** Before a negative result is filed as a disproof, show the instrument could have detected a real effect of the size you claim to rule out. Plant a known effect, or run a known-good case, and require the harness to find it.

**The failure it prevents:** "No effect" that is really "no ability to see". The disproof is recorded under (f), the idea is dropped, and the cause was the apparatus.

**Where it bites:** Experiments too small for the effect in question, thresholds calibrated on one population and applied to another, scanners with nothing to find, models whose structure cannot express the behaviour being tested. (h) guards a pass; (j) guards a null. (c) asks before the spend whether the data can decide; (j) asks before the verdict whether the instrument could see.

**How to apply it:** State the sensitivity the null needs (the effect size you claim to rule out) and run the positive control at that size, not at one ten times larger. A null without a positive control is filed as inconclusive, not as disproved.

**Software instance:** A load test reports no regression from a change, but its generator never brings the service near saturation, which is the only place the change could show.

**Quant instance:** A learning agent was evaluated on a validation split, and its learned and frozen versions matched fill for fill: its policy network was too small to move its actions whatever it learned, so the null was fixed before the split was spent. The fix was to prove, on synthetic data with a planted pattern, that the model could learn it before any real data was used.

---

## (k) Attack-your-own-win

**The rule:** A positive result gets the adversary a negative one would get. Before it counts, take it apart one variable at a time, rerun it through the path and on the population production will use, rerun it on data you did not author, and remove its largest contributors. The better a result beats the baseline, the likelier it lives in a blind spot of the measuring apparatus.

**The failure it prevents:** A win that comes from the simulator, the fixture, the sample or the evaluation frame ships as a real one. Searches and optimizers are good at finding the measurement's errors, because those errors pay best.

**Where it bites:** Benchmarks against mocks or warm caches, lifts concentrated in one segment, models selected on a population other than the one they act on, detectors tested only on their authors' fixtures, any optimizer run against a simulator.

**How to apply it:** For each positive result, write down the trivial explanations it has to survive and test each one; report what is left after each removal, not only the headline. A win that rests on one segment, one period or a few contributors is reported as exactly that.

**Software instance:** The engine's state-drift detector passed every fixture its authors wrote, then produced about 240 findings, some 225 of them false, the first time it ran on a repository its authors did not control. Fixtures written to match your own conventions prove internal consistency, not that the detector works.

**Quant instance:** An entry model's edge was taken apart in two steps. Switching to realistic fills removed essentially all of it (profit factor down 0.99); the gate everyone suspected moved it by 0.00.

---

## (l) Name-the-clock

**The rule:** Every time value says which clock it is on: time zone, calendar day or business/session day, the time an event happened or the time the information became available, the start or the end of an interval, elapsed time or step count. One clock's label never stands in for another's.

**The failure it prevents:** Off-by-a-day and look-ahead defects that pass every test, because the tests share the code's assumption about the clock.

**Where it bites:** "Today" for users in another zone, scheduled jobs across daylight-saving changes, event time versus processing time in streams, features computed from data not yet available at decision time, intervals stamped at their start but read as complete.

**How to apply it:** Name the clock in the field or variable and in the docs; store one canonical clock and convert at the edges. For each input to a decision, state when it becomes knowable, and test by changing only later inputs and asserting the earlier output does not move.

**Software instance:** An agent stamped a work ledger with UTC dates while the operator's local date was a day earlier, so evening entries landed on the next day, and a release note was published with the wrong date before anyone noticed.

**Quant instance:** Bars stamped at their open were read as stamped at their close, which gave every decision one bar of look-ahead. It would have passed every test in the suite while manufacturing an edge.

---

## (m) Evidence-or-name-the-gap

**The rule:** When a value cannot be evidenced, ship the work one field short with the gap named, and ask. Never fill it with something plausible. When the value can be obtained from a first-party source, obtain it rather than infer it. The provenance travels with the value: measured, from the vendor, decided by the operator, assumed, or derived.

**The failure it prevents:** A fabricated value is indistinguishable from a verified one. It passes every local gate, because no gate can check a claim that lives outside the repo, and it fails later, downstream, after the context that produced it is gone. A visible hole costs one round-trip.

**Where it bites:** External citations and versions, measurements from another system, claims about capabilities or files the agent did not read, fallbacks that fill a missing metric, defaults standing in for observations.

**How to apply it:** A version number, a remembered default, or the absence of something from context is inference; the schema, the docs and the file are observation. When they disagree, the source wins. An assumed value is labelled as assumed and is used only by explicit opt-in, never presented as observed; see (i).

**Software instance:** An agent wrote into a committed config note that a tool exposed no effort parameter, inferring it from a version number. The parameter was in the live tool schema the whole time.

**Quant instance:** Broker reports sometimes leave a fill's fee currency unknown. The system keeps the unknown rather than recording zero; a zero fee may be used only as a labelled assumption that the caller opts into, and an average fill price is never split into individual fills presented as observed.

---

## (n) A-rule-needs-a-mechanism

**The rule:** A sound rule with no mechanism at the boundary where it must hold is a wish. Telling a person or an agent about a rule does not make it hold; put the check where the thing crosses the boundary (the commit, the publish, the read, the order) and make it refuse.

**The failure it prevents:** The rule is broken by someone who knew it, often soon after it was written, and nothing notices.

**Where it bites:** Conventions held by documentation alone, hand-maintained lists that should be derived from the code, one-time reads protected by a promise, safety limits trusted to the component they limit.

**How to apply it:** For each rule, name the mechanism that enforces it and where it sits, and give that mechanism a negative control (h). Prefer a value that arrives already checked to an obligation repeated at every call site, and derive a set from the code rather than listing it by hand. If no mechanism is possible, say so and record the rule as advisory.

**Software instance:** Implementers were told to describe a pattern's shape in shipped text, never its source. One still wrote seven private repository names into comments in a shipped file, and a person caught it by eye. The publish step now scans the shipped files against a private list and halts on any hit.

**Quant instance:** A rule that the hold-out be read once, under a pre-registered protocol, held only after the read harness refused to run unless the pre-registration page existed, was accepted, and its frozen values matched the code's constants, with a second explicit confirmation required to spend the read.

---

## (o) Finish-what-you-find

**The rule:** A finding made while working an order is fixed in that order when it sits within the order's scope of work, however many lines it takes, and is covered by the order's checks. Defer only what is clearly out of the order's scope or would cross into a new scope (another subsystem, a design or operator decision, a file another in-flight order owns), and say which. Nothing is dropped.

**The failure it prevents:** The self-feeding backlog. Each deferred finding later pays a full cycle (dispatch, setup, the full check run, review, merge), each cycle finds more, and the project ends up servicing its own list instead of its work.

**Where it bites:** Scope rules read as "touch nothing unnamed", deferral rules that make writing it down easier than fixing it, and lists that accept any "not now" without a reason.

**How to apply it:** Fix it, list it under the order's deviations, and let the reviewer review it like scope. A deferral carries its out-of-scope reason; one without it goes back into the order. The deferral forms are all last resorts, in order: a new order (out of scope and it matters), a parked order (out of scope and waits on a named event), a loose end (the rarest: a known small fix that passes the five tests). Mechanism: the list refuses a row without its fix and its reason, and the canary says when the list grows past a handful of rows or holds an old one.

**Software instance:** Several one-line fixes found during an engine change were each written down as follow-ups, and each cost a full dispatch, review and release cycle of its own, longer than the fix.

**Quant instance:** A backtest run exposes a mislabelled column in the data loader it already reads. Fixing the label in the same change and adding it to the run's checks costs minutes; filing it means the next study runs on the same mislabel.
