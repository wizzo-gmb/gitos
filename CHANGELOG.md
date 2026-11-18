# GitOS engine — CHANGELOG

One entry per `VERSION` bump (the integer in `VERSION` at the repo root is the engine
version; each bump adds exactly one entry here, newest first). An entry is its header, its `breaking:` line, an `audit:` line for each audit the version adds and one
line per change naming its order (`- Owner board in every home (WO-122)`); the detail is in the order file and the release commit.

**Bump rule.** `VERSION` increments by +1 on any change to engine *directives* (the
behaviour-governing payload: `SKILL.md`, `references/`, scaffold/upgrade behaviour). Pure
doc/cosmetic edits don't bump. (Rule pinned by WO-002.)

**`breaking:` flag.** Each entry carries `breaking: yes` or `breaking: no`. A version is
`breaking: yes` if adopting it requires a downstream repo to take migration action *beyond*
a clean directive adoption — it changes or removes an existing directive, contract, gate, or
profile-facing interface, so an un-migrated repo would behave incorrectly. `breaking: no` =
additive (new directives/capabilities that don't invalidate existing ones). The `upgrade`
flow reads these flags: an upgrade crosses a breaking boundary iff some `breaking: yes`
version exists in the range `(min_compatible_engine, target_version]`.

---

## v62 — 2026-11-18
breaking: no
audit: brain (references/upgrade.md step 4u)
audit: tests (scripts/audit_tests.py)

- Upgrade step 4v audits the repo against what the crossed versions introduced and puts the findings on one owner-board card of proposed orders; a version that adds an audit carries an `audit:` line (WO-130)
- `scripts/audit_tests.py` reports test files per area, those over the line limit and fixtures over 1 MB; discipline (p) sets how tests are written (WO-130)
- Upgrade step 4p has descriptions written by reading each page and 4u audits the brain against the write test; `brain_lint` flags `placeholder-description` and advises on `engine-upgrade-v<N>` pages (WO-129)
- An order with `pending: <what it waits on>` is marked on the board and listed once by the canary as `order-pending`; `order-ready-to-close` is withheld from it (WO-125)
- `worktree.py reap` retries a removal git refuses over a long path with `core.longpaths` and `--force` when the worktree reads clean, removes the leftover through the extended-length prefix and prints each fallback (WO-125)
- The canary reports a home tool copy or `board/board.py` that differs in a home at the install's version as the advisory `tool-locally-edited`, apart from the gating `tool-stale` (WO-125)

---

## v61 — 2026-11-17
breaking: yes (the INDEX becomes a generated board; `ledger_migrate.py` lays it, moves hand-written sections to RESUME.md and deletes `footprints.md` and the per-order `log.md` files)

- The INDEX is the board and nothing else: generated header, Open and Parked, no Resolved table, no hand-written sections (WO-124)
- `footprints.md` and the per-order `log.md` are retired; a footprint is `git show --name-only <sha>` (WO-124)
- `ledger_migrate.py` lays the board, moves hand-written sections to RESUME.md, stamps `released:` and deletes both files (WO-124)
- Canary: `index-oversized` advisory over 16 KB, and the resolved-notes check reads each order's `released:` (WO-124)
- CHANGELOG is one line per change (WO-124)
- The brain is back to its rule: page front matter is the source of truth, `wiki/index.md` is generated and capped, `wiki/log.md` is gone, `brain_lint` checks schema and stale `rests_on` (WO-126)
- The selftest is split per area, dev-only (WO-127)
- Rule tags replace the brief phrase gates (WO-127)
- Implementer brief: run the narrow check while iterating, the full suite once (WO-127)
- The orchestrator brief is a core of at most 15 KB with step files in `references/orchestrator/` opened by a trigger table; every rule keeps its tag and hash (WO-128)
- The CLAUDE.md anchor's canary, board and dispatch-tier text is generated from the canonical paragraphs; a reworded block refreshes cleanly (WO-128)
- Implementer brief holds the standing dispatch rules (commits, tool copies, no release, processes and data not its own), so a dispatch is a pointer (WO-128)

---

## v60 — 2026-11-17
breaking: no

- Note boxes grow with their text (board) (WO-123)
- The publish tools remove files the engine dropped (WO-123)

---

## v59 — 2026-11-17
breaking: yes (the Artifact owner board is removed; every owner approval moves to the local board, which `/gitos upgrade` step 4s builds)

- A local, durable owner board in every home; the Artifact owner board is retired (WO-122)
- The decisions-page gate sees a `<link>` again (WO-122)
- Migration keeps every Parked row; an empty heading is not a report (WO-121)

---

## v58 — 2026-11-16
breaking: yes

- An order finishes what it finds (WO-116)
- Deferral forms are last resorts (WO-116)
- Parked work-orders replace the `parked:` list state (WO-116)
- Convergence: A second follow-up order on the same scope is not opened (the open order gets a slice); each... (WO-116)
- Unreviewed notes are flagged at Stop (WO-117)
- A current repo still gets the offer round (WO-120)
- The drain is never by hand (WO-120)
- System One machine setup ships as templates (WO-119)
- The decisions page was checked in a real browser engine (WO-118)

---

## v57 — 2026-11-16
breaking: yes

- One "not now" list (WO-115)
- One "waiting on you" view (WO-115)
- One consent round (WO-115)
- SKILL.md is a router again (WO-115)

---

## v56 — 2026-11-16
breaking: yes

- The discipline layer is first-class again (WO-114)
- One lexicon (WO-114): `references/glossary.md` is the source of truth (about 80 entries); the operator is the thesis's...
- Canary output (breaking for anything that matches kinds or the report text) (WO-114)
- Printed text follows the glossary (WO-114)
- Drain safeguards (WO-112): A new loose end that a later order or commit already fixed becomes a `close` proposal naming the...
- brain_lint does not count linked orders (WO-113)
- v55's date in this file is corrected to 2026-11-16 (it was written in UTC) (WO-113)

---

## v55 — 2026-11-16
breaking: no

- Small engine fixes (WO-111)

---

## v54 — 2026-11-16
breaking: yes

- Work orders with two or more slices are folders (WO-110)
- INDEX regions are generated (WO-110)
- Slice workers are bound by a hook (WO-110)
- Drain accepts into a folder order need `--new-slice NAME` (WO-110)
- Canary: gating `slice-landed-no-commit`, `slice-depends-dangling`, `slice-depends-cycle`... (WO-110)
- Retired: `history/`, the `## History` pointer, the canary's history check, the whole-order 400-line / 60 KB... (WO-110)
- Migration: `ledger_migrate.py HOME [--write]` (dry run by default) converts multi-slice single-file orders and... (WO-110)

---

## v53 — 2026-11-16
breaking: no

- Fix: a fresh declared worktree is in flight

---

## v52 — 2026-11-15
breaking: no

- Fix: an integration checkout is never reapable

---

## v51 — 2026-11-15
breaking: yes

- A suggested loose end lives in the drain pile only

---

## v50 — 2026-11-15
breaking: yes

- System One drains the loose-ends list and does nothing else

---

## v49 — 2026-11-15
breaking: yes

- System One works the loose-ends drain, and only out-of-pass work

---

## v48 — 2026-11-14
breaking: no

- A loose-ends list, drained at the seams (WO-093)
- The deferral rule is now "written down in the same turn": a Parked row when there is a trigger, otherwise the list (WO-093)
- The orchestrator drains the list after a resolve, at each checkpoint, at first action when the canary reports `loose-ends-stale`... (WO-093)
- System One: `loose-end-join` and `loose-end-bundle`, a `loose-ends` triage group, registry v9; a follow-up with no trigger now routes to `loose-end`... (WO-093)
- Canary: `loose-ends-malformed`, `loose-ends-oversized`, `loose-ends-stale`; items waiting on the operator are an info line, never a finding (WO-093)
- Upgrade: a legacy loose-ends register is offered for import at most once per file, and the answer is recorded... (WO-093)

---

## v47 — 2026-11-14
breaking: yes

- System One is opt-in per repo (WO-092)

---

## v46 — 2026-11-14
breaking: yes

- Migration: Lenses are now off unless a repo has `<home>/lenses.json` with `enabled: true`
- System One: an optional local decision model the engine's scripts can ask (WO-084, WO-090)
- Lenses are opt-in per repo (WO-091)

---

## v45 — 2026-11-12
breaking: no

- The owner board copies only what is new (WO-083)

---

## v44 — 2026-11-11
breaking: no

- Nothing saved for later gets lost
- Deferrals and implementer open points get a ledger home the canary can see (WO-079)
- A large decision round can go on one page (WO-080)
- An owner board when many items wait on the operator (WO-081)
- The owner board comes with a page and a guide (WO-082)

---

## v43 — 2026-11-02
breaking: no

- After a compaction or a clear, the agent re-reads its directives in full (WO-078)

---

## v42 — 2026-11-02
breaking: no

- One worktree per work order, and nothing lingers after it lands (WO-077)

---

## v41 — 2026-11-02
breaking: no

- The engine keeps its own state through compaction, and the orchestrator outranks every worker
- Working state comes back after `/compact` and `/clear` (WO-074, WO-076)
- RESUME stays current without bloating (WO-076)
- The orchestrator outranks every worker (WO-075)
- Dispatch tier is visible (WO-073)
- A repo can carry its own root `CLAUDE.md` without shipping it (WO-073)

---

## v40 — 2026-10-30
breaking: no

- What the federated engines found, fixed
- The orchestrator knows its own effort (WO-071)
- Unrelated settings edits no longer reset effort (WO-066)
- The light tier can dispatch (WO-066)
- Confirmed removals apply in a repo whose `harness.json` is `adopted: false` (WO-067)
- Cloud sync is a popup in both directions (WO-072)
- Plugin update channels act on documented levers only (WO-072)
- brain_lint stops misreading upgrade records (WO-068, WO-070)
- `federation intake` accepts the 8-character id its own listing shows (WO-069)

---

## v39 — 2026-10-29
breaking: no

- The removal popup works on a real repo (WO-065)

---

## v38 — 2026-10-29
breaking: no

- The first real v37 upgrade found the gaps, and this release closes them
- A correctly routed dispatch is no longer refused (WO-061)
- The binding accepts the Agent tool's model aliases (WO-064)
- The audit counts what the operator types (WO-062)
- Every upgrade measures the harness budget (WO-060)
- The operator confirms every skill removal (WO-063)

---

## v37 — 2026-10-29
breaking: no

- The routing invariants gained mechanisms, and one store gained a boundary
- The optimization baseline can no longer silently serve an expired pair (WO-057)
- The dispatch boundary has a gate (WO-055)
- A repo can declare the harness it actually uses (WO-052)
- One orchestrator can span many windows (WO-053)
- Two gate assertions that could not fail, can now (WO-058, WO-059)

---

## v36 — 2026-10-29
breaking: no

- The session baseline is untracked by mechanism

---

## v35 — 2026-10-25
breaking: no

- Work-order documentation matches practice, and effort stops being spent on ambiguity it cannot resolve

---

## v34 — 2026-10-11
breaking: yes

- Session model and effort comparison

---

## v33 — 2026-10-11
breaking: no

- Optional repo-local model optimization

---

## v32 — 2026-09-01
breaking: no

- `brain_lint`'s stale check stops flagging record-dated pages

---

## v31 — 2026-07-31
breaking: no

- The adoption offer is asked with a PROMPT, not a paragraph

---

## v30 — 2026-07-31
breaking: no

- Federation — adoption becomes a mechanism instead of a directive (WO-043)

---

## v29 — 2026-07-31
breaking: no

- Federation — adoption: the four built stages become reachable

---

## v28 — 2026-07-29
breaking: no

- Federation — cross-file and intake

---

## v27 — 2026-07-29
breaking: no

- Federation — consult: (stage F3): the first federation capability that **acts across repos**, and the only one that ever...

---

## v26 — 2026-07-29
breaking: no

- Federation — the canary category and the fleet view (WO-041)

---

## v25 — 2026-07-29
breaking: no

- Federation — the primitive, the opt-in, and groups (WO-040)

---

## v24 — 2026-07-17
breaking: no

- Record each commit's footprint in the ledger — visibility without judgement (WO-039)

---

## v23 — 2026-07-17
breaking: no

- A ledger section is a table UNION its prose, not a table XOR its prose (WO-038)

---

## v22 — 2026-07-17
breaking: no

- A commit is scoped to one work-order, the same way an edit is (WO-035)
- One rule about staging, not one bullet per git incantation (WO-031)

---

## v21 — 2026-07-16
breaking: no

- The canary reports a home tool copy that differs from the skill's (WO-034)

---

## v20 — 2026-07-16
breaking: no

- The canary identifies a work-order by a RULE, not by a list of forms (WO-033)
- The blindness risk, pinned rather than wished away (WO-007)

---

## v19 — 2026-07-16
breaking: no

- `upgrade` never refreshed a home tool, so no tool fix reached any repo that had the tool (WO-032)
- The distinction the old rule missed: engine artifacts are not operator content (WO-032)
- Step 4 now delivers, and says so (WO-032)
- One rule over `<home>/tools/`, not one bullet per tool (WO-031)
- No new engine state (WO-031)
- Seeding still is not delivering (WO-031)
- New gate 13: (`.gitos/tools/selftest.py`) pins the rule and both boundaries: the shipped directive must express... (WO-031)

---

## v18 — 2026-07-16
breaking: no

- The canary's work-order filename list was short by one form (WO-031)

---

## v17 — 2026-07-16
breaking: no

- Payload hygiene, made structural (WO-030)

---

## v16 — 2026-07-16
breaking: no

- Canary **external validity** (WO-029) — the canary encoded the engine's *own* conventions as if they were the schema

---

## v15 — 2026-07-14
breaking: no

- Durable context anchor (WO-028) — closes the v14 canary's **self-reference hole**

---

## v14 — 2026-07-13
breaking: no

- The canary system (WO-027) — cheap, always-on early-warning for the two places AI drift accumulates

---

## v13 — 2026-07-02
breaking: no

- Lens distribution model (WO-026; completes v12)

---

## v12 — 2026-07-02
breaking: no

- Global lens library (WO-025)

---

## v11 — 2026-06-27
breaking: no

- Steering lenses (WO-023): Operators can import their own specialist prompts as domain-tagged **lenses**...

---

## v10 — 2026-06-27
breaking: no

- `upgrade` offers to pull the latest engine first (WO-022)

---

## v9 — 2026-06-25
breaking: no

- Post-landing revision loop (WO-021)

---

## v8 — 2026-06-23
breaking: no

- Implementer is operator-enterable (WO-020)

---

## v7 — 2026-06-22
breaking: no

- No-fork directive for the diagnostic role (WO-017)

---

## v6 — 2026-06-22
breaking: no

- Hardened orchestrator work loop (WO-016)

---

## v5 — 2026-06-20
breaking: no

- Two engine-directive changes
- Ensure version control (WO-011)
- Forward-positive brain invariant (WO-012)

---

## v4 — 2026-06-20
breaking: no

- Define the implementer as a fourth, dispatched role (WO-009)

---

## v3 — 2026-06-20
breaking: no

- Role-boundary hardening (WO-006 + WO-007) — extends the find/fix separation to the orchestrator and implementer sides so every edit traces back to a...

---

## v2 — 2026-06-19
breaking: no

- BRIDGE-aware upgrade (WO-005): `references/upgrade.md` gains a **Step 0** that classifies a repo as Standard (engine-only) or...

---

## v1 — 2026-06-19
breaking: no

- Baseline — the engine state at this repo's inception (the recursive self-bootstrap, when gitos was first brought under its own pipeline)

---
