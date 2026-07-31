# GitOS engine — CHANGELOG

One entry per `VERSION` bump (the integer in `VERSION` at the repo root is the engine
version; each bump adds exactly one entry here, newest first).

**Bump rule.** `VERSION` increments by +1 on any change to engine *directives* (the
behaviour-governing payload: `SKILL.md`, `references/`, scaffold/upgrade behaviour). Pure
doc/cosmetic edits don't bump. (Rule pinned by the engine's version-bump-semantics
decision — WO-002.)

**`breaking:` flag.** Each entry carries `breaking: yes` or `breaking: no`. A version is
`breaking: yes` if adopting it requires a downstream repo to take migration action *beyond*
a clean directive adoption — it changes or removes an existing directive, contract, gate, or
profile-facing interface, so an un-migrated repo would behave incorrectly. `breaking: no` =
additive (new directives/capabilities that don't invalidate existing ones). The `upgrade`
flow reads these flags: an upgrade crosses a breaking boundary iff some `breaking: yes`
version exists in the range `(min_compatible_engine, target_version]`.

---

## v29 — 2026-07-31
breaking: no

**Federation — adoption: the four built stages become reachable** (stage F5). v25–v28 built
federation; nothing told anybody it was there. `references/upgrade.md` mentioned it **zero
times**, so a repo upgrading past those versions got the code refreshed inside its install and
was told nothing — and the capability is *invisible when off* by design, so there was no sign of
it to stumble over either. **A feature nobody is told about is a feature nobody has.** No new
capability ships here; what ships is the way in.

- **`upgrade` now OFFERS federation — and does not enable it.** On a repo with no
  `<home>/federation.json` the upgrade says once that federation exists, names it as off by
  default and invisible when off, and points at the one page that carries the join path. On a
  repo that already has the file it says nothing: that repo has decided. **The step runs no
  federation command and writes no config** — the only thing it reads is whether that one file
  exists. *Opting in is per checkout and it is the operator's word, and it is the first of two
  consents (the exposure flags are the second); a repo that came back federated because somebody
  asked for a directive refresh would have spent a consent nobody gave — the precise surprise
  this subsystem was built to avoid.* It is the same **report-then-ask** shape the engine already
  uses for the engine `git pull` offer and the lens refresh.
- **How a repo JOINS is written down, once** — in `references/federation.md` → *Joining*, which is
  the only place the sequence lives. Everything else, this entry included, points at it rather than
  repeating it: a second copy is what the previous stage spent eight rounds proving drifts.
- **THE MIXED FLEET: a sibling's engine stamp is REPORTED, and nothing consults it.** A stamp is
  the version that repo **last ran**, not one it is pinned to — one skill install per machine
  means "behind" almost always means *"has not run gitos since you upgraded"*, which `last_seen`
  says better and which running it fixes. So no version gate was added, and one cannot be added
  quietly: `consult` allowing and `file` landing a real file into a sibling stamped older,
  stamped newer, or carrying **no stamp at all** — in both orientations — is now pinned end to
  end through the CLI, in both directions, with the fixture's own stamps asserted so the pin
  cannot pass while measuring two repos on one version. **A sibling being behind is not a reason
  to refuse**: that is the *degrade to the status quo, never below* invariant inverted into
  version form, and one participant's state must not disable a tool for another. The pin holds
  the reporting half too — report-only fails if the number disappears as surely as if it starts
  refusing. And whatever is refused, the finding or the question is still open: every refusal
  already names the by-hand fallback at the point of refusal, which is what keeps an
  under-versioned or unfederated sibling reachable.
- **One source of truth, applied to this change and to the page it edits.** The join path is
  written in `references/federation.md` and *pointed at* from the upgrade step rather than
  restated. And the fleet-view sample transcript in that page was **deleted, not corrected**: it
  had drifted from the code it copied — a deliberate change to how the engine stamp is spelled
  and to how a sibling's own words are delimited went into the renderer and not into the sample.
  The page now says which functions render it and tells you to run the command. *Correcting a
  copy re-arms it; the drift was the argument.*

---

## v28 — 2026-07-29
breaking: no

**Federation — cross-file and intake** (stage F4): the first federation capability that **writes
into another repo**, and the one the subsystem exists for — *the copy-paste that never happens*. An
orchestrator that finds something belonging to a sibling repo can file it there as a **proposal**,
which becomes real work only when that repo's own operator accepts it. Everything before this could
only read.

- **It writes ONE file into ONE directory — `<target-home>/intake/` — and nowhere else.** That is a
  property of the code's *shape*, not of its current control flow: a single function composes the
  destination from one hard-coded directory name plus a validated hex id, so a second destination
  is not expressible. Proved structurally, then measured against a target seeded with decoys (a
  brain, a ledger, work-orders, a footprint log — all byte-identical afterwards). *You are writing
  into somebody else's repo: one directory, provably, or nothing.*
- **What lands is a PROPOSAL, never a work-order (the sovereignty keystone).** Accepting one
  **requires naming a work-order that already exists in the receiving repo's own ledger** — so
  *acceptance is only expressible as a reference to something that repo authored*, and **the
  foreign file cannot become the board item**. The proposal is archived as **evidence** for that
  work-order with its body preserved byte-for-byte. A directive saying "author a native work-order"
  would be one more rule to remember; a required argument that must resolve to a real file is the
  same rule with a mechanism under it.
- **A PROPOSAL BODY IS DATA, NEVER A DIRECTIVE — AND THAT IS MECHANICAL.** A receiving
  orchestrator is an LLM that reads whatever is in front of it, so a proposal body is an
  instruction-injection surface. **The listing emits metadata only because it *cannot* emit
  anything else**: the reader that feeds it stops at the header terminator, refuses to read past a
  bounded window, and returns a fixed key set — on `--json` as much as in print. A non-conforming
  file is refused and reported **by name**, its content neither read nor quoted, because an error
  message is a surface too. The title — the one foreign string the listing *does* show — is
  collapsed to a single bounded line on write **and** on read. *A directive telling an orchestrator
  not to obey a file is exactly the kind of rule this engine has watched decay; a tool that does
  not print the body makes the DEFAULT path safe.* **Honest limit, stated rather than dressed up:
  this is not a sandbox** — an LLM with file tools can open the file, and `--show` exists so the
  **operator** can read it deliberately. What is mechanical is that the default path cannot hand it
  over. Two further limits are stated rather than implied: `intake/` is a **path**, so a symlink
  planted by the receiving repo's own operator redirects the write (cooperative, not a sandbox —
  a resolve-and-refuse check would imply a guarantee the machine boundary does not make); and the
  fingerprint splits as well as merges, so **a declined finding re-titled by one character comes
  back as a fresh pending proposal** — the correction is a rule for the sender (do not re-title a
  settled finding), not a change to the hash.
- **AND A HEADER *VALUE* IS A SURFACE TOO — closed as a class, at one choke point.** A refusal
  message reaches four places: the listing, `--json`, the bootstrap checker's **unbidden**
  findings, and — in the other direction — the **sender**, when a settled finding is re-filed.
  So the readers of a foreign proposal **build no messages at all**: they
  name a fault code, and every refusal they can emit is chosen from **one table of literal
  templates** whose only substitutions are the *bounded, quoted* file name, this engine's own
  constants, and the **type** of the offending value — with an integer's digits kept, because
  *"this engine reads 1, that file says 2"* is the entire content of the forward-compatibility
  refusal. The values that survive parsing are bounded the same way, in **both directions**: the
  receiver's decline note reaches the sender collapsed to one quoted line and its state word
  forced into a fixed vocabulary, because an archive is a foreign-authored file whichever end
  reads it. The two columns that *are* the sender's words — display name and title — are shown
  **in quotes their content cannot forge**, so the foreign span is structural rather than
  positional. *The lesson banked with it: any foreign value in any message is a surface, and
  reasoning about that field by field is exactly how the field nobody reasoned about ships.*
- **AND THE COMPLETENESS QUESTION IS ASKED WITH THE QUANTIFIER THE OTHER WAY ROUND.** Two rounds
  answered *"a message is a surface"* by widening the list of what counts as foreign — nine header
  fields, then an enumerated category of foreign-controlled inputs — and each time the next channel
  shipped anyway: first the **file name** (foreign, but not a header field), then **archive names**,
  the **target repo's display name** and the whole **registry tier**. A list of what IS foreign is
  an *open-world* claim: anything unlisted is implicitly safe, which cannot be proved finished. So
  the guarantee is now the opposite one, and it is the shape this engine already had twice — *the
  listing cannot reach the body reader*, *the header readers contain no formatting at all*. The
  enumeration of foreign inputs is kept, and is now described as what it is: *the map, not the
  authority.*
- **AND CLASSIFICATION IS A RUNTIME PROPERTY, ENFORCED AT ONE SERIALIZER.** The inversion above was
  first built as a static walk over the emitters, and that lost: ten shapes put unbounded foreign
  prose on a default surface with every gate green — two of them *inside* an emitter's own body, one
  through a helper that mutated the returned payload **in place** (so the value appears in no
  expression at any depth), and the acceptance test that certified the whole mechanism went green on
  a **rename**, because classifiers were matched by call *name*. Static analysis of a dynamic
  language loses that game, so the leak is now **impossible to express** rather than detectable.
  Every string placed into a surface payload says which it is — `Engine` (ours) or `Foreign`
  (somebody else's) — and **one serializer** produces every default surface from it. A **bare,
  unmarked string reaching it is a hard refusal**, values and keys alike, so a channel nobody has
  thought of fails at the boundary instead of sailing through it. `Foreign` is not a string and
  refuses every rendering operation there is, so a leak cannot even be *composed*; the cap and the
  delimiter are applied **at serialization**, which makes a forgotten render impossible rather than
  merely unlikely. And because the check runs on the value **actually being emitted, at the moment
  it is emitted**, in-place mutation, out-parameters and renaming are irrelevant to it *by
  construction*.
- **AND THE MARKING HAPPENS WHERE THE BYTES ARRIVE, NOT WHERE THEY ARE PRINTED.** The serializer
  makes an unmarked string unemittable; what it cannot see is a caller *lying* about provenance.
  While that mark was applied where a value was placed into a payload, it was a **one-word edit at
  an emission site with nothing behind it** — and three of them (`home_path`, `last_seen`, a fleet
  member's `groups`) each put a ~4,900-character `<system-reminder>` back on `status --json` with
  every gate green. So the four readers that ingest another repo's file now **return records whose
  foreign fields are already marked**. No payload builder downstream sees a bare string for those
  fields, and a mis-mark stops being a one-word edit: `Engine` is a `str` subclass, so wrapping a
  value that arrived foreign **raises at the line where somebody writes it**, on every run that
  touches a record. A tenant record gets a *walk* — every string at every depth — rather than a
  field list, because `home_path` was the field nobody listed four rounds running and a record is
  arbitrary JSON that somebody else will add a field to. *A per-site obligation is a directive; a
  value that arrives already typed is a mechanism.* **And that walk is TOTAL** — values, dict
  **keys** and **numbers**, at every depth. Numbers are not safe merely for not being strings:
  `engine_version` is an integer in every record this engine writes, `json.loads` accepts `NaN` and
  `Infinity` by default, and an unmarked number went verbatim onto `--json`, so one sibling could
  hand every consumer of that surface a document **no strict JSON parser accepts**. Keys were left
  bare on the stated ground that *"nothing hands a raw record to a surface (every consumer
  projects)"* — but the fleet view projects **by copy**, so an object-valued field handed the whole
  subtree, keys included, to the serializer. Booleans and `null` stay bare, and that exception is
  closed rather than convenient: three tokens this engine spells itself, of fixed length, with no
  prose available through them.
- **One participant's malformed record no longer breaks the tool for every repo on the machine.**
  A registry is a directory every tenant writes into **by design**, so a half-written record from a
  crashed process is an ordinary event — and two shapes of one were measured taking
  `federation status` to **exit 1 in repos that did not write the record**: a `name` that was an
  object ("*an internal emission fault … a defect in the tool, not something to repair in this
  repo*" — false, the fault was a sibling's file) and a `groups` that was not a list ("*fix `groups`
  in federation.json*" — pointing at the reader's **own** file for a fault in a file they do not own
  and the message never named). That is `INV-10` inverted, and it is the failure a *cooperative*
  design is most exposed to. The fleet reader already reported an **unreadable** record as a row;
  that contract now covers **malformed-but-readable** ones too, naming which record and which
  field, with a correction that points at the repo that owns it. **A fleet reader degrades per
  record or it is not a fleet reader.**
- **A carve-out is a claim about a category, so it is restricted to that category.** Paths were
  rendered uncapped on the human surface because *a truncated path stops resolving* — true for a
  path this engine derived from a directory it resolved, and false for a `home_path` sitting in a
  file somebody else wrote, which is never opened at all. 200 KB of directive text reached the
  canary's **unbidden bootstrap report** through that gap, twice. The carve-out now takes a path
  *object* and refuses a raw string and refuses an already-marked value, so a `home_path` read out
  of a registry record cannot be passed to it; and it is bounded at the OS's own path limit for the
  case where the type is unavoidably lost. The documented justification's closing sentence —
  *"what bounds them is the filesystem that has to hold them, not this engine"* — was false for
  exactly that case, and is corrected rather than softened. The justification's *other* clause —
  "a path this engine *composed*" — over-claimed at two refusals that pass the resolved directory
  itself with nothing of ours joined on; the words are narrowed to what the code does (**a
  directory this process confirmed exists**), because that is the case where "the filesystem that
  has to hold it" is most literally a real bound.
- **A sentence describing behaviour is a second source of truth, and it drifts.** The claim about
  what the canary's surfaces carry was corrected six times — and the sixth false instance was
  written **by the round that was correcting the fifth**, on the lines being corrected, in a new
  spelling the class check meant to prevent it could not see (that check tested whether a sentence
  contained one of eighteen substrings, several of which occur naturally in a fresh affirmative
  sentence). Six rounds is a long enough experiment. The prose is **deleted** rather than corrected
  a seventh time: the property is measured by one named assertion, the documents point at that
  assertion, the pointers are checked live, and the drifted spelling is banned outright.
  *Do not describe behaviour beside the thing that measures it — point at the measurement.*
  **[CORRECTED in WO-043 Revision 9. The ban did not work: EIGHT restatements survived it — seven
  found in the eighth round, and an eighth in a gate summary string, which a comments-and-docstrings
  scan does not read. The successor remedy (a generated table plus a claim-shape detector) was
  defeated by ordinary paraphrase and exempted long paragraphs by length, which is exactly where
  the eighth was. Revision 9 deleted the prose, the generated table and the detector together;
  what a canary finding carries is described by the assertion that measures it.]**
- **Three foreign-controlled inputs no longer produce a traceback where a refusal was promised.**
  `intake --decline <id> --json` with no `--reason` exited 1 with a stack trace instead of 2 with a
  sentence — *the mechanism worked and the integration did not*, since the serializer correctly
  refused an unmarked string from the one command return that skipped the payload builder and
  nothing caught it. A proposal whose **body is not valid UTF-8** listed fine and could never be
  shown, accepted or declined: it pended forever and reddened the receiver's canary forever, which
  is **a denial-of-service on the human checkpoint, available to any sender**. And a `home_path`
  past the OS path limit crashed the canonicalizer *before* the `target-path-unresolvable` refusal
  that exists for exactly that case could run — `INV-10` promises degrade-to-fallback, and a
  traceback is below the status quo it promises never to fall under.
- **`--json` carries no foreign string at all.** Machine surfaces are read by tooling, so ids,
  counts, ages and engine-derived paths are sufficient — a display name, an engine stamp, a
  `last_seen`, a home path, a decline note and a foreign object **key** are all withheld from
  `status --json`, `file --json`, `consult --json`, `intake --json` and `canary --json`. A surface
  that carries no foreign data needs no classifier, no bound, and **cannot regress**. A person
  reads a name on the human surface; a program that needs an identifier gets the **id**, which this
  engine mints.
- **The registry is a weaker tier, and it is no longer treated as an absent one.** A tenant record
  lives on the operator's own machine, but it is still a directory other repos write into, and its
  strings reach `federation status`. A record's **file name**, a sibling's **display name**, a
  **group label** (`normalize_group` does not bound length) and the engine stamps are all bounded
  and delimited there now, and a record that will not parse is reported with **one sentence of
  ours** — never the parser's, which names the *path*. The **target repo's own display name** is
  bounded at the reader every cross-repo action goes through, and delimited at every print —
  including the outbound confirm preview, the line directly above the one asking the operator to
  authorize a write into somebody else's repo.
- **The OUTBOUND CONFIRM is a named gate AT THE SEND STEP.** `file` is **dry-run by default** — the
  same shape every other outward-facing action in this engine ships with — and without `--confirm`
  nothing is written, not even the intake directory. The gate binds **by reference** to the
  orchestrator's standing *irreversible / outward-facing actions* boundary rather than restating
  it, and it is printed only where it applies: *a rule placed away from its step is read at
  dispatch time and applied many turns later.* **Both ends confirm** — the sender's operator
  authorizes the send, the receiver's authorizes the receive.
- **Payload minimization is a rule, not advice.** A summary plus a **required** pointer back to the
  sender's own work-order, never verbatim evidence: the file lands in the receiver's *git-tracked*
  home and rides their history forever. An over-cap summary is refused with nothing written — the
  tool will not trim somebody's finding on their behalf.
- **The proposal id is a fingerprint of sender + title + source-ref, so re-filing is safe.** The
  same finding re-filed **overwrites its own proposal** instead of accumulating duplicates, and a
  byte-identical re-file writes *nothing at all* (no churn in the receiver's git history). A
  reworded summary is the same finding said again and updates in place, **preserving the original
  `filed` stamp** so a noisy sender cannot keep resetting the receiver's ageing clock; a different
  title is a different proposal; and a finding the receiver already accepted or declined is
  **refused**. *Idempotence is what keeps the human checkpoint from decaying into rubber-stamping —
  a queue that grows a duplicate on every re-run is a queue that gets skimmed.* False-merge risk
  stated honestly: same sender + same title + same source-ref collide, and the correction is to
  name distinct findings distinctly.
- **One authorization path, not two.** `consult` and `file` go through the *same* function — live
  re-read of the target's own `federation.json`, group intersection first, then that action's flag.
  A second decision procedure would be a second place for the act-time re-read to rot. The
  write-side revocation is immediate and asserted: a live `accept_proposals: off` behind a cached
  `on` is refused.
- **Delivery observability, so the motivating case cannot fail silently.** A successful send is
  recorded in the sender's own home, and `federation status` correlates each outbound against that
  target's `last_seen` — *"filed 9d ago, target last ran 41d ago"*. Without it a proposal rots in a
  dormant repo while the sender believes it delivered, which is **worse** than copy-paste, where
  the operator at least knew. **Delivery is not acknowledgement and the view does not pretend
  otherwise.**
- **The canary gained the intake's observer** (the stage that ships a capability ships its watcher):
  a malformed proposal · a sender with no tenant record · **proposals pending while
  `accept_proposals: off`** — the flag is *cooperative*, so this check is the only thing that
  notices it was not honoured — · a proposal pending past 14 days. All **local and gating**, because
  every one is fixable here by the operator who is already in this repo. **A repo with no `intake/`
  gets no finding, no skip and no line** — not-applicable is not skipped, one level down from where
  that rule was pinned. A bootstrap finding arrives in the orchestrator's context unbidden, so the
  checker is deliberately stricter than the listing; the `CANARY-SURFACE-CONTENTS` assertion in
  `.gitos/tools/selftest.py` is what measures its surfaces.
- **Refusals stay outcomes**: every one exits 0, names what would change the answer, and prints the
  fallback — hand the finding over the way you would have before federation. **A refused cross-file
  must never become a dropped finding.**
- **Unfederated repos are unaffected**, which is why this is `breaking: no`: no new step, no new
  output, no new failure mode. A federated repo gains two subcommands and one bootstrap line that
  exists only once somebody has actually filed something into it.

---

## v27 — 2026-07-29
breaking: no

**Federation — consult** (stage F3): the first federation capability that **acts across repos**, and
the only one that ever exposes a repo's content. An orchestrator in one repo can ask a sibling repo's
brain a question and get an answer *in that repo's context* — refusable by the target and recorded on
the asking side. Everything before this was plumbing that touched nobody else. It is read-only in two
different ways, stated apart rather than together: **the tool writes nothing into the target**
(mechanical, asserted), and **the dispatched agent is *directed* read-only** by the role contract it
inherits — a directive, not a sandbox.

- **The tool AUTHORIZES; the orchestrator CONSULTS — and they are deliberately different things.**
  `federation consult TARGET` is a **function**: resolve the target through the registry, **re-read
  that target's own `federation.json` at that path, at act time**, apply the group intersection and
  then `consultable`, and answer **ALLOW + a path** or **REFUSE + a reason**. Dispatching the agent,
  framing the question and deciding what is worth recording is **judgement** and stays with the
  orchestrator. The authorization half is code rather than prose because *"re-read the source of
  truth, never the cache"* is exactly the kind of rule that decays when it is a directive — a
  function makes authorizing from the cache **impossible** rather than merely forbidden.
- **A revocation takes effect immediately.** The cached record is a snapshot of the last time that
  repo ran; a decision made from it would keep granting access until the revoker's next session,
  which is a revocation that did not happen. **A target whose live file says `consultable: off` is
  refused even while its registry row still says `on`** — asserted in both directions, because a
  program that always refuses would satisfy the one-sided test.
- **Groups are checked before the flag, and the order is observable.** A target you cannot reach must
  not have its exposure posture reported to you at all: a group-disjoint target that is *also*
  `consultable: off` reports the **group** reason. Reporting the flag would answer a question the
  caller was not entitled to ask, and would send the operator to request a flag flip when the real
  gap is a group label. **The verdict discloses to match**: a `no-shared-group` refusal names the
  target and both group sets but does **not** carry `consultable` — on `--json` as much as in print,
  because a disclosure rule that only one surface obeys is a courtesy rather than a rule.
- **Every refusal is distinct, actionable, and exits 0.** Nine reasons — this repo not federated ·
  unknown target · ambiguous name (**both ids named; the tool never guesses which repo gets read**) ·
  target path unresolvable · target no longer federated · target config unparseable · no shared group
  · `consultable: off` · target is this repo — each naming what would change the answer. **A refusal
  is an outcome, not a tool error**; non-zero is reserved for the tool genuinely failing.
- **The exposure flags are never coerced, in either direction.** A live file saying
  `"consultable": "off"` carries a *string* — and a truthy one — so it is refused as an unreadable
  config rather than read as `on`. Guessing at a malformed posture would grant an access the target
  never granted (or silently close one it did); a malformed posture is a fault to report.
- **The tool dispatches nothing and reads no brain.** Structurally, not by good manners: it imports no
  process, thread or network library at all; the deciding function reaches an allowlisted set of
  helpers that excludes every registry reader; discovery hands back `{id, name, home_path}` and
  nothing else, so a cached flag has no route into the decision; and the only path it ever opens under
  a target is that target's `federation.json`.
- **Said plainly, and not softened: "scoped to the target's brain" is a PROMPT-LEVEL SCOPE, NOT A
  SANDBOX.** The dispatched agent is an LLM with file tools, and the read-only contract it inherits
  is a **directive**: it addresses **writes** rather than read breadth, and even that write half is a
  role contract, not a sandbox. On one operator's machine that is proportionate — any session there
  can already read the drive — and it is documented rather than dressed up as enforcement. Anything
  that must not be readable belongs on a different machine. **The ALLOW verdict says this at the
  terminal too**, separating what is *directed* (the agent's scope) from what is *enforced* (this
  tool authorized; it dispatched nothing and read no brain).
- **Exposure ratchets one way, so the asking side records the minimum.** The answer is recorded in the
  **asking** repo's brain (question → answer → target id) and the target's brain is never mirrored
  across. Whatever lands thereafter lives under the recording repo's posture and remotes:
  responsibility for re-exposure sits with the repo that writes it down.
- **A refused or unreachable target falls back to the manual path**, and the command prints that line
  on every refusal. Federation must never make a cross-repo question *less* likely to be answered
  than it already was.
- **Unfederated repos are unaffected**, which is why this is `breaking: no` — there is no new step, no
  new output and no new failure mode for a repo that never opted in. For a repo that *is* federated
  nothing changes either until someone runs the new subcommand: it adds a capability and removes none.

---

## v26 — 2026-07-29
breaking: no

**Federation — the canary category and the fleet view** (WO-041; stage F2, the observer half of the
pair v25 opened). v25 shipped the bootstrap heartbeat as a directive with **nothing watching it**, which
is the decay shape this engine keeps naming. This version supplies the watcher — and puts fleet-wide
freshness where it informs without blocking.

- **The canary gains a `federation` category, and it is STRICTLY LOCAL.** For a federated repo it
  reports: **no tenant record** (the heartbeat has never run here, or the record was removed), **a record
  that has not been refreshed recently** (the heartbeat has stopped), **a record that names another
  checkout's home path** (something that is not this repo is refreshing it, so its freshness proves
  nothing here), **a record stamped in the future** (a clock that jumped forward or a hand-edit — a
  stamp ahead of now is not evidence the heartbeat ran, and a one-sided staleness test would read it
  as fresh forever, hiding a heartbeat that had stopped behind it), **a record with no usable
  `home_path`** (the heartbeat always writes one, so a missing or non-string value is a corrupt
  record — and without it, which checkout owns the record cannot be established), and **a corrupt
  `federation.json` or record** (a parse failure is a finding, never a silent "not federated"). Each
  names its correction, and each says what it actually saw rather than reaching for the nearest
  existing label. It **reads no other tenant** — it opens this repo's
  own opt-in file and the single record its own id names, and never enumerates the registry, so a
  sibling's state cannot redden this board.
- **Read this if you are already federated: a repo whose heartbeat is not running now goes RED where it
  was green.** Nothing about federation changed — the finding was always deserved and nothing was
  watching for it. The correction is one idempotent command (`federation heartbeat`, which the
  orchestrator's First action already runs every session). For **unfederated** repos this version is
  purely additive and byte-for-byte invisible, which is why it is `breaking: no`.
- **Not-applicable is not skipped** — the rule this version pins, because two of the canary's own
  disciplines collide here. A repo that never opted in does not *have* this module: there is no check
  that failed to run, so it gets **no line at all** and appears in **neither `checked` nor `skipped`**. A
  repo that **is** federated but where the check cannot run takes the ordinary **visible skip**, because
  there the question was asked and went unanswered. Both halves are asserted.
- **"Refreshed recently" is an honest proxy, and the payload says so.** The question worth asking is
  *"was my record refreshed this session"*, and a timestamp cannot answer it — there is no session marker
  to read, and inventing one is the heartbeat's business, not a checker's. The check asks the strongest
  observable question instead, *"was it refreshed in the last 12 hours"*, and owns both error directions:
  a session running longer than the window will see the finding (harmless — the record really is that
  old, and the named correction is the right action, so the false positive self-clears), and a heartbeat
  that died under 12 hours ago still looks healthy (a **latency bound**, not a session boundary — a dead
  heartbeat is caught within one window and stays caught).
- **Federation gets its own thresholds, rather than overloading one knob across three contracts.** The
  local check is **hours-scale and not a knob at all**; reusing the canary's `--stale-days` (60 — "is this
  brain page stale") would let a presence record rot for two months and still pass, which is the exact
  blindness the observer exists to end. The fleet view gets `--dormant-days` (default 30) for "has this
  tenant run recently" — **report-only**, so a mis-tuned value is cosmetic rather than board-freezing.
- **`federation status` becomes the fleet view.** Tenants grouped by group, each member with derived
  freshness, posture flags, engine version, and markers for dormancy and a home path that no longer
  resolves; defaults to this repo's groups, `--all` shows every group on the machine. The
  **singleton-group line is informational, not a finding** — a solo group is normal while a domain is
  stood up, and it exists so a typo'd group name is at least legible.
- **The gating split, stated plainly: local gates, fleet reports.** `status` exits `0` whatever it finds.
  With one operator and many repos, dormancy is the *steady state* and external drives unmount routinely,
  so gating on a sibling's silence would redden every federated board over repos doing nothing wrong —
  and the only remedy would be switching the check off. What gates is what is fixable *here*.
- **Freshness is derived at read time and never persisted** — no `stale` field is written, ever; the mark
  *is* the report. The canary never writes the registry, never refreshes a heartbeat, never prunes.
- **The first cross-tenant reader is named for what it is.** v25 deliberately shipped none, so that "read
  the cache and act" could not become the idiom. The one that now exists is `read_fleet_for_report` —
  **read-to-report**, documented at its definition as never an authorization path: consult and cross-file
  will re-read the target's own `federation.json` at act time, because a revocation that waits for the
  revoker's next session is a revocation that did not happen.
- **Selftest 19 → 21 gates, and the invisible-when-off gate got wider.** Its "no registry read" half
  instrumented only the module's parsed-read path, so a bare `stat`/`exists` probe under the registry
  slipped past it (measured: such a mutation stayed *green*). It now records the whole stdlib filesystem
  surface underneath the module, so a *look* is caught, not only a read. Twenty-one mutations across
  both directions — neutered checks, over-broadened ones, a fleet reader wired into the gating path, a
  persisted staleness mark, and `status` made to gate — were all caught, each with an anchor `count == 1`
  asserted before it was applied. The new category's own gate also stopped measuring the wrong thing:
  its invisible-when-off assertion read the *whole rendered report*, whose header embeds the repo's
  absolute path, so it was coupled to what the fixture directory happened to be **called**. It now
  asserts over the report's `[OK]`/`[!!]`/`[--]` category lines — the rows the rule actually governs —
  and the fixture is deliberately named with "federation" in it so the coupling cannot return unnoticed.

---

## v25 — 2026-07-29
breaking: no

**Federation — the primitive, the opt-in, and groups** (WO-040; stage F1 of a new subsystem). Independent
gitos instances **on one machine** can now declare themselves, join groups, and register their presence, so
a later stage can route work that belongs to a sibling repo instead of leaving it to a copy-paste that never
happens. This version ships the **plumbing only**: the per-repo opt-in file, the machine-level registry, the
`federation` command, the bootstrap heartbeat, and the one group-reachability predicate. **Nothing here acts
on another repo** — no consult, no cross-filing, no intake.

- **Invisible when off — proven by a test, not intended.** A repo with no `<home>/federation.json` produces
  **no registry entry, no registry read or write, no extra output line, and no error**; the tenants directory
  is not even created, and the repo's tree is byte-identical before and after a heartbeat. Opting in is one
  explicit command. Unfederated repos are unaffected by this version, which is why it is `breaking: no`.
- **`<home>/federation.json` is the source of truth, and it is git-IGNORED.** It carries a stable `id`, a
  display `name`, `groups`, and the exposure flags `consultable` (**off** by default — the one capability
  that reveals repo content) and `accept_proposals` (on). Ignoring it makes opt-in **per checkout**: a clone
  or worktree arrives unfederated instead of inheriting an identity and an exposure posture. **Exactly one
  path is ignored** — the rest of the pipeline home stays tracked, because the ledger and the brain are the
  audit trail. `scaffold` seeds the line for new repos; `federation enable` back-fills it for existing ones.
- **Identity is minted once and derived from nothing** — so it survives a **rename** *and* a **move**. Not
  derived from the path (a move would change the identity — the identity-by-position lesson in path form)
  and not from the repo's history (every clone would derive the same id and two checkouts would fight over
  one record). A changed path is a **move**: the same record's `home_path` is updated, never forked.
- **The registry is ONE FILE PER TENANT** at `~/.claude/gitos-federation/tenants/<id>.json`, and a session
  writes **only its own** (write-temp-then-`os.replace`). A single shared registry file has no per-row write,
  so two sessions refreshing at once would silently lose each other's updates; with one file per tenant there
  is no lost-update window and no cross-tenant merge to get wrong. `home_path` is **stored and compared
  canonicalized** (resolved + case-folded) — one repo has many live spellings, and comparing raw strings
  manufactures phantom conflicts out of OS artifacts.
- **The cache is never the authority.** A tenant record's `groups` and `flags` are **discovery hints**;
  whether anyone may act on a repo is decided by re-reading **that repo's** `federation.json` at act time.
  Without that rule a revocation would be silently ineffective until the revoker's next session — so the
  shape is pinned now, before the first caller exists.
- **Groups scope reachability by set intersection** (`reachable()` — **exactly one implementation**, exported,
  and shipped with its tests before any caller exists, so later stages cannot drift on what *reachable* means).
  Names are normalized (trimmed, lowercased, deduped, order-insensitive); no `groups` field means `[default]`,
  so a machine that never partitions behaves exactly as one ungrouped federation. **Multi-membership is the
  sharing primitive** — a repo several domains depend on joins them all. Groups answer *who can reach me*;
  the flags answer *what they may do*; neither does the other's job. A typo makes a silent group of one, and
  the mitigation is **legibility** (`federation status` lists the groups), not validation — flagging a solo
  group would cry wolf while a domain is being stood up.
- **The heartbeat is a BOOTSTRAP step, never a canary check.** A federated repo refreshes **its own** record
  and stamps `last_seen` at first-action — beside ensure-git and the engine-drift check, and **before** the
  canary. Refreshing your own presence is an *attendance signature*, not a repair; a checker reports and
  never mutates shared state. Staleness is derived at read time and is **never persisted**.
- **Cooperative, not a sandbox — stated plainly everywhere.** No daemon, no process, no network: the registry
  is a lazy cache maintained as a side effect of participants running gitos, and it is eventually consistent.
  Federation is machine-local **by construction**, so the machine is the only isolation involved. Flags and
  groups are graduated-sharing policy that participants honor — they reduce blast radius and noise; they are
  not an enforcement boundary and they keep no secrets. Presence is *machine-visible metadata*, not "none".
- **Known gap, stated rather than hidden:** the heartbeat is a directive whose observer (the canary category
  that notices a federated repo whose own record is missing or not refreshed this session) is the **next**
  stage. Delivery and its observer ship as a pair, and until the second half lands this step is a directive
  with no observer — the decay shape this engine has named before, accepted only because the pair closes it.
- **Opting out is clean under a live heartbeat.** `disable` removes the **truth file first**, then the
  record, then sweeps once more after a brief settle. `federation.json` is the master switch, so once it is
  gone any heartbeat that *starts* writes nothing — deleting it first is what makes the window *closeable*
  rather than merely narrow; the settled second sweep collects a writer that was already in flight. The
  other order leaves a record naming an opted-out repo's path, groups and flags that nothing will ever
  refresh. *Residual, stated rather than implied away:* a heartbeat descheduled longer than the settle
  between its read and its write can still leave a row — this is a cooperative mechanism, not a lock, and
  the next stage's own-record observer is what reports such a row.
- Selftest gains **five** gates (primitive/groups/reachability; opt-in + registry incl.
  rename/move/canonical path/legacy homes/`.gitignore` precision; invisible-when-off; concurrency; and the
  opt-out race), each mutation-tested both directions.

---

## v24 — 2026-07-17
breaking: no

**Record each commit's footprint in the ledger — visibility without judgement** (WO-039). Work-loop
**step 7** now records each landing's *footprint* — the set of paths its commit touched — in an
append-only footprint log (`<home>/footprints.md`) that the resolved row's sha joins into. It is the
same staged set the orchestrator already reads back at step 6, written down instead of left buried in
git history, so a human reading the board can notice a commit whose paths span work-orders — the one
genuine signal a cross-work-order sweep leaves — rather than relying on an agent to catch it after the
fact.

- **Visibility, not judgement — recorded, never checked.** The footprint is *disclosed for a human to
  read*; nothing compares it against a scope field, an owned-paths list, or any expected set, and the
  step-7 gate is unchanged. A footprint-vs-scope gate was measured against the whole work-order corpus
  and rejected: scope shape tracks work-order *type* (fix-a-known-surface → path list; investigate /
  decide → prose), and ownership is a **relation, not a function** — a file is legitimately co-owned
  across many work-orders, sequenced by a human — so such a gate is *red on correct work*, and a guard
  that cries wolf gets disabled. The human supplies the judgement a footprint alone cannot; this only
  makes the footprint legible, and it *cannot prevent* a sweep, only surface one.
- **One habit, not a git recipe; no new tool, no hook.** Step 7 names the *what* — record the footprint
  you already read at step 6 — not a sequence of git incantations. A plain `git show --stat <sha>`
  re-derives a footprint, so no helper script (one more thing to remember to run) and no git hook (an
  undeliverable, off the engine's delivery path) were added.
- **Additive.** New disclosure at resolve time; it changes no existing directive, gate, or contract.

---

## v23 — 2026-07-17
breaking: no

**A ledger section is a table UNION its prose, not a table XOR its prose** (WO-038). The canary read each
INDEX section as a table *or* a prose/blockquote ledger, table-first: `_table_rows` returns non-None the
moment a section carries **any** table — even a header-only or one-row summary/subsection table — so the
prose branch never ran, and every work-order tracked **only** by a blockquote/list row went unparsed.
Because the files→rows scan then sees those work-order files with no matching row, each one was reported
as `orphan-file` — a phantom. The failure was **loud *and* blind**: it manufactured false `orphan-file`
findings while the section's real prose rows stayed invisible, and the ledger category **gates**
work-order resolution, so a single prose-only row in an otherwise-healthy mixed section would freeze the
board. `check_ledger` now folds each section's prose rows into its tracked set as a **union** with the
table rows.

- **Line-head prose rows only — never the citation-link top-up.** The prose fallback for a *no-table*
  section has two signals: line-head identity rows (`> 042 = …`, `- **Bug 042** …`) and a top-up that
  recovers a row carried solely as a markdown link. Only the **line-head rows** (new `prose_row_nnns`)
  are folded into a section that also has a table. In a table section a markdown link is a **citation**,
  not a row — folding the link top-up would turn every cross-reference in a cell into a phantom row and
  manufacture *new* false positives (a cited-but-resolved work-order would surface as a bogus open row).
  The link top-up stays exclusive to a no-table section, whose behaviour is unchanged.
- **UNION is the safe direction for orphans, and it stays tolerance-not-blindness.** Adding NNNs to a
  section's tracked set can only **remove** `orphan-file` findings, never add one; a genuinely stray file
  (no table row **and** no prose row) is still absent from the union and **still orphans**. What the fix
  does newly surface is *correct*: a prose row whose file is missing is now caught as
  `open-row-missing-file`, and one whose file sits in the wrong directory as `open-row-file-in-resolved` /
  `resolved-row-file-in-root` — real inconsistencies the XOR was hiding, not new false positives.
- **Every true-positive guard is intact, and prose parsing is now *stricter* inside a table section.** The
  line-head anchor (a bare mid-line number can't manufacture a row), the `NNN\b` closer, duplicate
  detection (a prose-internal collision is still caught — the union dedups a prose row against the
  **table** set only, never against itself), and the fenced-code skip all hold. The row scan now skips
  fenced code, so an **example** ledger row shown in a ``` block is never read as a real row — this matters
  more now that prose is parsed inside table sections, which are likelier to carry examples.
- **`cannot-parse` is unchanged:** a section that is neither a table nor a recognizable prose ledger is
  still `cannot-parse`, never silently CLEAN. The orphan-scan guard (`open_rows is not None and res_rows
  is not None`) is deliberately **left as-is**: a *pure-prose* section keeps its conservative best-effort
  treatment; this defect is specific to the **mixed** section, where that guard already passes. Widening
  the orphan scan to pure-prose ledgers is a separate question, not folded in here.
- **New selftest gate** (`.gitos/tools/selftest.py`, 14 gates) pins a mixed table+prose section:
  blockquote rows whose files exist are tracked (no phantom orphan), a genuinely stray file **still**
  orphans (anchored on `count == 1`), a citation link / a fenced example / a mid-line number **never**
  become rows, a prose row with no file **does** fire `open-row-missing-file`, and a prose-internal
  duplicate is still caught. Mutation-tested five ways, each RED: revert to the XOR, neuter the fold, fold
  the link top-up, drop the fence skip, and over-broaden the row match to a bare mid-line number.

`breaking: no` — strictly more tolerant on the false-positive it removes (a repo phantom-frozen by a mixed
section goes green), and measured **finding-neutral on every reachable ledger today**. ⚠️ **One thing to
know:** a repo with a *mixed* section whose prose rows point at a **missing** or **misplaced** file will
now see the correct `open-row-missing-file` / `*-file-in-*` finding that the XOR was hiding — a real
ledger inconsistency surfaced, not a migration burden; the pressure valve (descope the category to
report-without-gating) is unchanged.

---

## v22 — 2026-07-17
breaking: no

**A commit is scoped to one work-order, the same way an edit is** (WO-035). The work loop pinned
*"anything concurrent touches disjoint files"* at **dispatch** (step 3) and then said only *"Commit the
verified work; record the sha"* — no rule about **what gets staged**. That gap is not theoretical: staging
is **directory-shaped and work-orders are not**, so a bulk stage takes whatever a dispatched agent has in
flight, and the disjointness the orchestrator guaranteed at dispatch dies at its own commit. The gate is
honoured; the commit defeats it. Step 6 now carries the staging rule: **stage by explicit path**; read the
staged set back (`git diff --cached --stat`) and compare it against the work-order's scope before
committing — **an unexpected path there is the same defect as an implementer editing an unnamed file**
(out-of-scope footprint, the boundary step 5 already enforces on implementers, now applied to the
orchestrator's own act). The step-6 gate is extended accordingly.

**Disclose, don't rewrite — but disclosure is not a licence.** Two moments, kept distinct: a stray caught
*at the read-back* is **unstaged**, because the gate forbids committing it; **disclosure is for the sweep
you find too late** — once the commit exists, it is named in the next one and corrected forward, never
rewritten to look clean. **The ledger is an audit trail, not a tidy story**, and a commit that
misdescribes its own contents corrupts the record the engine exists to keep honest. Rewriting would
destroy the evidence that the boundary failed, which is the fact worth keeping.

**One rule about staging, not one bullet per git incantation** — WO-031's lesson applied at authorship,
for the fourth work-order running. A list of forbidden commands is an enumeration, and **an enumeration
fails once per novel form** (`-a`, `.`, `-u`, a GUI's "stage all", whatever ships next). The invariant is
*explicit paths*; every bulk form is excluded by it without being named, including forms that don't exist
yet.

**Placement is the point, and it is reasoned:** the rule lands in **step 6, where the promise is kept or
broken** — not in *Dispatch + verify*, which steps 3–5 point to and step 6 does not. A commit-time rule
read at dispatch time is a rule read once and applied many turns later under context pressure; that
distance *is* the failure mode. Per the work-loop spine's own governing choice (a spine **points** to the
detailed sections rather than restating them), the rule is stated once, at the boundary, and binds to the
existing out-of-scope-footprint notion by reference rather than by copy.

**Known limit, stated plainly rather than implied away: this is a directive, and directives decay.** The
engine's own thesis — *if an invariant depends on someone remembering, it eventually fails* — applies to
this fix as much as to any other, and this rule exists precisely because a correct rule was forgotten one
turn after it was written. The directive is necessary and demonstrably followable; it is **not** claimed to
be sufficient. The mechanism that would close it (a check comparing a commit's footprint against the
work-order that owns it) is **blocked on a primitive the engine does not have** — no machine-readable
binding from a work-order to the paths it owns; scope is prose. That primitive, not the check, is the
next question.

---

## v21 — 2026-07-16
breaking: no

**The canary reports a home tool copy that differs from the skill's** (WO-034). v19 fixed the *rule* —
`upgrade` now **delivers** the engine's `<home>/tools/` copies instead of only seeding them. Nothing made
that observed. The gate that shipped the rule named its own residual gap plainly: *an upgrade step is
prose an orchestrator performs; there is no function to call, so no gate proves an orchestrator
complied.* This is the structural counterpart — a new **`tool` category**: for each engine tool a home
carries a copy of, compare it against the installed skill's. Identical → silent. Different →
`tool-stale`, naming the tool and the correction (`/gitos upgrade`). The canary already runs at every
orchestrator bootstrap, so drift now surfaces on the **next session in the repo that has it**, without
anyone remembering to look. **If an invariant depends on someone remembering, it eventually fails** —
so it is now a check, not a directive.

**⚠️ Adopters: a repo carrying a stale or hand-edited home tool copy now goes RED where it was green —
and because the canary gates work-order resolution, that red BLOCKS resolution until the copy is
refreshed.** Flagged `breaking: no` deliberately, and the reasoning is stated rather than assumed: this
removes no directive and demands no migration *beyond* a clean adoption — the documented `upgrade` flow
refreshes the tools in step 4, so a repo adopting v21 through that path is silent on the new category by
the time the canary runs. An un-migrated repo does not behave *incorrectly*; it gets a finding it always
deserved. But the red is real, it is new, and a repo that adopts the canary while skipping the refresh
will feel it — hence the warning, not a silent flag. **The pressure valve already exists and is
unchanged:** a repo that wants this category to report without gating **descopes** it (SKILL.md →
*Canary*), the mechanism v16 established for exactly this.

**Says "different", not "why" — and reports, never fixes.** The compare proves the content is not the
skill's; it cannot distinguish *stale* from *hand-modified*, so it does not guess (v19's honesty, kept).
Both have the same correction, so naming a cause would add a claim without adding an action. And the
canary does not refresh what it finds: **refreshing is `upgrade`'s job**. A canary that edited would be
the same category error v19 had just corrected.

**Line endings are normalized before comparing — a CRLF checkout is not a stale tool.** `<home>/` is
deliberately git-tracked and `core.autocrlf=true` is the Git-for-Windows installer default, so a raw
byte-compare calls **every fresh Windows clone of a fully compliant repo** stale — and since this
category gates, it would hard-block a board that did nothing wrong, printing a correction (`upgrade`)
that rewrites the bytes and lets the next clone bring the finding right back. *A correction that does
not correct is worse than no finding.* Both `upgrade`'s step-4 rule and the canary now apply the same
predicate, so the rule and the check observing it cannot disagree about what a changed tool is.
Byte-identity remains the right contract for a **mirror** — it was never the right one for *"is this the
same tool?"*. Caught pre-landing against the real fleet rather than a fixture: normalizing silenced a
line-endings-only copy while both genuinely-drifted copies stayed red — tolerance, never blindness.

**The tool set is DERIVED, not enumerated** — the fourth work-order to say so, applied at authorship.
The engine's home tools are the names present in **both** `<home>/tools/` and the skill's `scripts/`.
Neither side alone is the rule: the skill's side alone would demand `scaffold.py` in every home (it is
never copied there), and the home's side alone would claim every repo-local tool an operator parked in
the dir. The intersection is exactly *"an engine script this home carries a copy of"* — the set the
upgrade rule already governs and scaffold already lays. A future tool the engine ships into a home is
covered the day it ships, with no edit here and no release for the repo that meets it first.

**Boundaries kept.** `<home>/agents/` is **operator content, not a tool**, and is not reachable from
this check by construction — the selftest plants a decoy in `agents/` named exactly like an engine
script and differing from it; if the check ever reaches there, the gate goes red. A tool **absent** from
`<home>/tools/` is **not** a finding: SKILL.md's fallback runs the skill's own current copy, so a home
without a copy cannot be stale — those repos were never victims. No `<home>/tools/`, no resolvable skill
install, or no engine copies to compare → **visible skip**, never a false-CLEAN (*tolerance, never
blindness*).

**The self-reference limit, named rather than papered over.** A **stale canary cannot report its own
staleness** — a copy predating this check has no such check to run. A detector cannot detect its own
absence. This is not solvable from inside, and it does not need to be: the **layer above** terminates it.
`upgrade` delivers the checking canary (v19), and a home with no copy at all already runs the skill's
current one. This category is what keeps the copy honest *afterwards*. No bootstrap trick was attempted.

Gate 9 extended to the new category in all three phases, mutation-tested **both** directions (5/5 RED:
neuter; flag-an-identical-copy; reach into `agents/`; and both one-sided derivations). Its positive case
asserts the compare **ran** — this category skips itself into silence, so "no findings" alone would pass
a check that never looked. Its negative case mutates the home copy to be byte-different but
behaviourally **identical**, which is the honest test of a check that promises *different, not why*.

---

## v20 — 2026-07-16
breaking: no

**The canary identifies a work-order by a RULE, not by a list of forms** (WO-033). Three work-orders,
one error, three altitudes: the check hardcoded the engine's own filename regex (*"they were one
sample"*), the remedy enumerated three samples (*"a four-item list is still a list of samples"*), and
v18 folded the underscore forms but still enumerated **prefixes**. Enumeration is a strategy that
**fails once per novel downstream**, and each failure costs that repo its resolution gate until the
engine ships — so the next ledger writing `task_007_x.md` or `WO007-x.md` was already scheduled to land
in the same place. This ends the class instead of lowering its rate.

**The rule: the directory is the scope.** Files under `<home>/work-orders/` are work-orders by
construction, so a filename does not have to prove it is one — it only has to yield an **identity**: an
optional letter prefix and separator, then **exactly three digits**, then a separator and a slug. The
prefix carries no meaning and is no longer inspected. `WO-007-x.md`, `wo_007_x.md`, `bug_007_x.md`,
`task_007_x.md`, `WO007-x.md`, `007-x.md` and whatever the next repo invents all resolve, with no engine
release. Measured against **every ledger reachable from the engine's environment (312 files)**: the new
rule and the old list agree on **all 312** — the change buys no existing repo anything, and that is the
honest claim. Its entire value is that the next novel form costs nothing.

**Tolerance, never blindness — both halves tested.** `IDENT_NNN` is now the engine's single notion of
"exactly three digits, closed", shared by the filename rule and the prose-row rule so the two cannot
drift; a name with no readable identity is still reported (`wo_1234_x.md` four digits, `wo1234_x.md` the
backtrack trap — the rule's prefix is letters-only precisely so a digit cannot be backtracked out of it
into a phantom WO-234, `WO-1-x.md` one digit, `notes.md` none, `wo_029b_x.md` a suffixed identity this
ledger model cannot represent and therefore reports rather than flattening onto its sibling). The two
identity rules share a core but **not** a prefix policy, deliberately: a filename is scoped by its
directory, a prose line by nothing but its anchor, so an open prose prefix would read `**Fixed 240
findings**` as row 240. Gate 11 now bites in **both** directions — narrowing to any prefix enumeration,
widening to `\d{3,4}`, tolerating digits in the prefix, re-importing enumeration from the other end (a
`notes_` exclusion), or "unifying" the two rules by opening the prose prefix each turn it red.

**The blindness risk, pinned rather than wished away.** A non-work-order carrying an identity
(`notes_007_draft.md`) **is** adopted as WO-007; no filename signal separates it from `task_007_real.md`,
and a name-shaped heuristic to tell them apart would re-import the enumeration just removed. What is
guaranteed is that adoption is never **silent** — with no INDEX row it surfaces as `orphan-file`, against
a real WO-007 as `duplicate-file` naming both. The cost is a finding with a different **label**, never a
missed one, bounded by a directory that holds nothing but work-orders. The probe found **zero**
non-work-order `.md` files across every reachable ledger, and the one near-miss — a memo deliverable
named after its own work-order — **already** matched v18's enumeration, so the prefix list never
protected against this class in the first place.

`breaking: no` — the rule is strictly more tolerant (nothing v18 accepted is now rejected, proved on all
312 real files); no migration action is required. Two caveats named rather than buried: a ledger holding
an identity-carrying non-work-order will see that finding change **label** (`nonconforming-wo-filename` →
`orphan-file`/`duplicate-file`), and the module constant `WO_FILE_FORMS` is gone, replaced by
`WO_FILE_RE` + `IDENT_NNN` (a plural "forms" name would have preserved the framing this WO removes).

---

## v19 — 2026-07-16
breaking: no

**`upgrade` never refreshed a home tool, so no tool fix reached any repo that had the tool**
(WO-032). Step 4 read *"copy `brain_lint`/`canary.py` into the home if missing — never clobber an
existing copy"*. So a repo that adopted a tool at v14 kept the **v14 tool forever**. v16, v17 and v18
were each, in substance, a `canary.py` fix; through the documented path, all three reached **zero**
adopting repos. The engine had been fixing a checker its own upgrade could not deliver — and two
downstream adoptions each had to declare a **deliberate deviation** to receive the last fix. A rule
adopters must knowingly break to get value is not a rule; it is a bug with a paper trail.

- **The distinction the old rule missed: engine artifacts are not operator content.**
  `<home>/tools/*.py` are byte-copies of the engine's own scripts — a *cache of the installed skill*,
  which the briefs invoke by home path. They are not project state. The never-clobber instinct came
  from the right place (never overwrite state) and was aimed at something that is not state. Contrast
  `<home>/agents/` — the lens library, genuinely operator content, correctly report-and-**ask** since
  v12/v13 and **untouched by this change**. The line is the category, not the folder.
- **Step 4 now delivers, and says so** (`references/upgrade.md`): **missing** → copy; **byte-identical**
  → silent no-op (no churn, no false "updated"); **different** → **report it, then refresh it**. A
  byte-compare proves *different*, not *why* — so the report says exactly that (stale or hand-modified,
  the tool cannot tell which) and notes the prior bytes are recoverable from git.
  **Never silently skip; never silently overwrite** — the two are the same failure wearing different
  clothes, and the old rule traded one for the other.
- **One rule over `<home>/tools/`, not one bullet per tool.** The predecessor enumerated two tools; any
  future tool laid in the home would have inherited the trap by default. WO-031's lesson applied at the
  point of authorship rather than one iteration later: a convention is written as a rule, not as a list
  of its current samples.
- **No new engine state.** A manifest of previously-shipped tool versions would positively separate
  "pristine but stale" from "hand-modified" — and costs a permanent, per-release bookkeeping surface
  that can itself go stale, to resolve a case that has one right answer anyway. Rejected as out of
  proportion. The refresh is not asked-about either: a prompt per tool per upgrade trains the operator
  to skip the very fix the upgrade exists to deliver.
- **Seeding still is not delivering** (`scripts/scaffold.py` — unchanged, deliberately). Laying a tool
  into a *fresh* home and delivering a fix to an *existing* one are different acts; scaffold keeps its
  `SKIP exists`, and its idempotency gate ("second run writes 0") still passes.
- **New gate 13** (`.gitos/tools/selftest.py`) pins the rule and both boundaries: the shipped directive
  must express all three branches, forbid silence in both directions, stay one rule over the folder, and
  claim no authority over `<home>/agents/`; behaviourally, scaffold must still *refuse* to refresh a
  stale tool and must leave operator lenses byte-untouched. The gate states plainly which half it
  executes and which half it asserts — an upgrade step is prose an orchestrator performs, and prose is
  what regressed here.

`breaking: no` — it removes no directive and demands no migration action: adopting it *is* the whole
change, and an un-migrated repo keeps behaving exactly as it did. It only makes an upgrade deliver what
it always claimed to. **One thing to know before you run it:** if you have hand-edited a
`<home>/tools/` copy, the next upgrade will refresh it and tell you — that is the intended correction,
not a migration burden (a forked tool copy was never a supported surface; descope a canary category or
file a work-order instead), and your bytes remain in git.

## v18 — 2026-07-16
breaking: no

**The canary's work-order filename list was short by one form** (WO-031) — and it was the form the
engine's own template implies. v16 replaced a hardcoded filename regex with a list of three known
forms; the list covered an underscore `work_` form and a diagnostic `bug_` form, but not the forward
`wo_` sibling that sits alongside `bug_` in any ledger following that template. A repo naming its
work-orders `wo_NNN_<slug>.md` therefore had every one of them reported as nonconforming, and any
ledger row whose file could not be resolved to an NNN reported as missing its file — the v16 fix
reproduced, one iteration in, the exact failure v16 named: **loud *and* blind** on the repo it was
meant to serve. A category that must be descoped to be usable does not gate.

- **Underscore forms are now ONE pattern, not an enumeration** (`scripts/canary.py`):
  `<prefix>_NNN_<slug>.md` is a *convention*, so it is written as one regex covering `wo_`/`work_`/
  `bug_` rather than a fourth sample beside three others. Adding a fourth line would have re-armed
  the same trap at a lower rate. The operator-facing "rename to one of them" advice now names every
  accepted form.
- **Tolerance, never blindness — unchanged and now pinned harder.** This widens tolerance by one
  prefix; it removes no report. A name matching no form is still reported, including the near-misses
  the widened pattern must *not* swallow: a 4-digit `wo_1234_x.md` is not an NNN.
- **The relaxation keeps its true-positive test** (`.gitos/tools/selftest.py`): the external-validity
  gate now carries a `wo_` fixture reproducing both original findings, and asserts that a duplicate-NNN
  collision **across two forms** is still caught — the exact defect the enumeration exists to expose.
  Reverting the pattern turns the gate red.
- **Recorded, not decided:** enumerating forms — even one level up, as a list of prefixes — is still a
  strategy that fails once per novel convention. Deriving NNN by a general identity-position rule, or
  letting a repo declare its form, is deliberately left to an operator decision; this buys back the
  gate for the conventions that exist today. Noted in the code so the next author does not mistake the
  pattern for the destination.

Additive and strictly more tolerant: every ledger clean at v17 stays clean (a repo with no
nonconforming filenames cannot be newly flagged by a wider pattern).

## v17 — 2026-07-16
breaking: no

**Payload hygiene, made structural** (WO-030). The publish gate scanned for private filesystem
*paths* only — so a private **name** (a repo, product, client, or domain) written into a payload
file sailed straight through it. That is not hypothetical: a dispatched implementer put private
repo names into `scripts/` comments, and the only thing that caught them was the operator reading
the diff. The engine's own thesis applies to the engine: **an invariant that depends on someone
remembering eventually fails.**

- **Publish gate — names, not just paths** (dev tooling): the guard now carries a private-*name*
  denylist beside its path patterns, word-boundary and case-insensitive, reported the same way
  (file + line + the rule that fired) and halting the publish identically. The list is dev-only and
  is structurally unable to ship — it lives under `.gitos/`, which the payload enumeration excludes.
- **Precision over coverage.** A guard that cries wolf gets switched off, taking the useful patterns
  with it — so ambiguous names are matched only in their distinctive hyphenated/underscored form
  (generic spaced prose still passes), and a name that cannot be told apart from ordinary
  vocabulary is *deliberately not covered*, recorded in the file with its reason rather than shipped
  as a false-positive generator.
- **A new acceptance gate proves the detector detects** (positive *and* negative): innocent payload
  prose passes; real private names are caught; the original leak scenario is reproduced end-to-end
  and halts.
- **Directive** — `references/roles/implementer.md` now pins the boundary: private names belong in
  `.gitos/**` (work-order, notes, INDEX, brain); payload text — **comments included** — describes
  the **shape**, never the **source**. The trap is that the honest motivation for a change usually
  *is* "repo X does Y", which makes writing it down feel natural.

## v16 — 2026-07-16
breaking: no

Canary **external validity** (WO-029) — the canary encoded the engine's *own* conventions as if they
were the schema. They were one sample. On an independently-evolved downstream repo the ledger check was
**loud *and* blind**: hundreds of findings, nearly all false, while a real duplicate-NNN collision sat
in front of it unseen. Fixed as *tolerance, never blindness* — every relaxation keeps its true-positive
test:

- **Work-order filenames** (`scripts/canary.py`): the hardcoded `WO-NNN-<slug>.md` regex became a list
  of known forms — the engine's hyphen form plus an underscore `work_NNN_` form and a diagnostic
  `bug_NNN_` form — each yielding NNN, so duplicate / orphan / row→file detection **actually runs** on a
  ledger that doesn't use the engine's naming. A name matching no known form is still reported.
- **Ledger section headings**: matched by prefix, not by a literal — the heading's tail (e.g. a
  `(by severity)` parenthetical) is legitimate variation. When a section carries no table, a
  **prose/blockquote ledger** is parsed via each item's identity-position NNN plus a top-up from linked
  work-order files. A section that is neither remains `cannot-parse`.
- **Link resolution**: a target now resolves against the containing file's dir **or** the repo root, and
  is reported only when **neither** resolves. Flagging a path that demonstrably exists was a false
  positive against the tool's purpose (it detects drift; it does not lint markdown).
- **Lens registries**: a Lens cell may be a bare stem **or** a markdown link (the target's stem is the
  name) — a link cell used to double-report one condition as two findings. Lens provenance accepts
  `imported:` **or** `authored:`: a distilled lens should not have to record false provenance.
- **Managed-block data loss** (`scripts/scaffold.py`): `ensure_claude_section` replaced the block's
  contents wholesale, silently destroying anything inside it — on a refresh the engine itself
  recommends, while the docs pointed a profile pointer *into* that file without saying to keep it
  outside the markers. It now carries unrecognized in-block lines through the refresh and **reports**
  them (status `preserved`); ordinary drift is still replaced. Silence was the defect. The docs
  (`assets/CLAUDE-section.md.tmpl`, `references/bridge.md`, `references/upgrade.md`) now pin `_meta` and
  anything repo-owned **outside** the markers.
- **Gate escape** (`SKILL.md`): a convention mismatch must never freeze a healthy ledger. An operator or
  a repo's BRIDGE may **descope a canary category**, recording the deviation; a descoped category
  **reports but does not gate**. The gate binds on *actionable* findings.
- **Root cause — fixture bias** (`.gitos/tools/selftest.py`): the prior gate's fixtures were hand-built
  to match the canary's assumptions, so a green suite proved internal consistency, not external
  validity. A new gate runs the canary against shapes observed in real downstream repos and asserts both
  directions: legitimate shapes are silent, and the seeded real collision **is** caught.

Additive and strictly more tolerant: every shape that passed at v15 still passes (a repo clean at v15
had no nonconforming filenames by definition, so the widened forms cannot newly flag it), and the block
refresh now preserves what it used to delete.

## v15 — 2026-07-14
breaking: no

Durable context anchor (WO-028) — closes the v14 canary's **self-reference hole**. The per-reply
marker and its own absence-detector both lived in the skill directive layer, which compaction
summarizes away, so the detector degraded in lockstep with what it watched. The recovery seed now
*also* lives in the **durable layer**: inception writes a managed `<!-- gitos:agent-system -->` block
into the repo-root `CLAUDE.md` — which the harness re-injects into every context window — carrying the
marker requirement + the trigger to re-read SKILL.md and run `canary.py`. Even after the skill directive
washes out, that block re-asserts the marker and points the way back. `scripts/scaffold.py` gains
`ensure_claude_section()` (idempotent managed-block **upsert**, creates the file if absent, never
clobbers content outside the markers — replacing the old append-once behavior); `upgrade` refreshes it;
`canary.py` gains an `anchor` category (`anchor/missing`, `anchor/stale`); selftest grows a 10th gate
(the upsert's create / no-clobber / idempotency) and gate 9 now covers the anchor. Custom repos treat
the block as a **MERGE** (engine-managed section inside a profile-owned `CLAUDE.md`). Also fixes
cold-start drift + the misroute class — the repo self-announces through the durable layer. Additive — a
repo without the anchor simply lacks the durable backstop.

## v14 — 2026-07-13
breaking: no

The canary system (WO-027) — cheap, always-on early-warning for the two places AI drift
accumulates. **State:** new `scripts/canary.py` (payload; stdlib-only, read-only, the
`brain_lint` invocation/report contract) deterministically checks the *home state layer* none of
the existing watchers cover — INDEX ↔ work-order files (stale / orphan / duplicate rows),
`.brainmeta.json` counts vs on-disk pages + ahead-stamps, lens registries on both layers
(rows ↔ files, `name` = filename, `applies-to` list-form), link rot in `INDEX.md` + open WOs —
and delegates to `brain_lint` when a brain exists; parse failure = finding, skipped checks report
as skipped, never false-CLEAN. Exit 0 = CLEAN / 1 = findings (a deliberate divergence from
`brain_lint`'s reporter semantics: the gate needs red/green). Strictness: **report at bootstrap,
gate at resolution** — the orchestrator runs it at first-action (one line: `canary: CLEAN`, or
findings-first, forward-positive) and may not resolve a work-order while it is red (joins
verify-before-commit). **Context:** `SKILL.md` gains a `## Canary` section (the SSOT) + a
one-line echo in all four role briefs — every reply opens with the **stateful marker**
`[gitos · <role> · <focus>]` (recomputed each reply: WO + work-loop/lifecycle step / phase /
interview stage), so a missing, wrong-role, or stale marker is live evidence of context
degradation; slippage → directive reinjection, a second slip in the same window → checkpoint +
fresh window; honesty clause (the slipped agent is the least reliable detector of its own slip —
the operator's first-line glance is the primary monitor). An operator may opt out per repo
(reduces coverage to state-only). `/gitos canary` runs both on demand. `scripts/scaffold.py`
lays `<home>/tools/canary.py` on fresh scaffolds and `upgrade` step 4 copies it into existing
homes (the `brain_lint` pattern; never clobber); selftest gains gate 9 (seeded clean home
silent, six seeded defect classes each caught — dev-only). Additive — a repo that ignores the
marker just has no context canary.

## v13 — 2026-07-02
breaking: no

Lens distribution model (WO-026; completes v12). `/gitos agent import` now writes each lens to **both
layers by default** — the current repo's `<home>/agents/` (git-tracked, travels with the repo) *and*
the global `<skill>/agents/` (the machine-wide distribution hub) — with repo-only / global-only on
request. `/gitos upgrade` gains a **lens-refresh step**: for each repo lens that also exists globally,
byte-compare and report-and-ask to refresh the repo copy from the global (a deliberately-forked local
variant survives by declining — never a silent clobber), then offer any global lens not yet in the
repo. Read-time collision rule unchanged (repo wins). Scaffolded lens-registry template mentions the
global layer. Additive — no global library / no repo lenses → the new steps no-op.

## v12 — 2026-07-02
breaking: no

Global lens library (WO-025). Lenses now resolve from **two layers**: the repo's own `<home>/agents/`
(v11) plus an operator-maintained **global library** at `<skill>/agents/` — the installed skill's own
`agents/` directory, catalogued in `<skill>/agents/index.md` — whose lenses apply in *every* repo the
skill runs on, no per-repo copying. Roles check both registries; on a name collision the repo's lens
wins (more specific). Same boundary rules on both layers. `/gitos agent import` gains a global
destination ("import globally"); `list` prints both registries labeled by layer. The global library is
**operator content**: engine updates never ship, overwrite, or delete it (the dev→live sync's mirror
mode now explicitly protects `<live>/agents/`). SKILL.md Lenses section + the four role-brief echoes
extended. Additive — a skill install with no `agents/` behaves exactly as v11.

## v11 — 2026-06-27
breaking: no

Steering lenses (WO-023). Operators can import their own specialist prompts as domain-tagged **lenses**
(`/gitos agent import <path>`), stored under `<home>/agents/` and catalogued in `<home>/agents/index.md`.
Any of the four roles reads a lens whose domain matches its current work and folds the guidance in
**within its role boundary** — injected context, not a dispatched role: a read-only role stays read-only,
a scoped implementer stays scoped. On import the **orchestrator normalizes** each prompt into the gitos
idiom (forward-positive framing, role-boundary-aware phrasing, standard vocabulary), preserving the
operator's domain substance; the operator confirms the reframe (raw prompts are never stored as-is), and a
`source` field keeps provenance. A new `references/agent-import.md` brief + an `assets/` index template ship
with the engine; `scripts/scaffold.py` creates the `<home>/agents/` library + registry. Distinct from the
brain (a lens = how to approach a domain; the brain = the project's facts). Additive — a repo with no lenses
behaves exactly as before (empty registry = no-op); Custom repos preserve imported lenses across upgrades via
their BRIDGE PRESERVE set. Downstream adopts on upgrade.

## v10 — 2026-06-27
breaking: no

`upgrade` offers to pull the latest engine first (WO-022). `/gitos upgrade` reconciles a repo against
the **installed** engine (`~/.claude/skills/gitos/`), not GitHub — so a public user on a git-clone
install had to `git pull` the engine by hand before upgrading, and a bare `/gitos upgrade` would
no-op ("did it upgrade?"). v10 closes that: `references/upgrade.md` step 2 ("live-read the installed
engine") becomes **"refresh + live-read"** — if `~/.claude/skills/gitos/` is a git clone, the
procedure **reports intent and asks the operator** to `git -C ~/.claude/skills/gitos pull` before
reading the VERSION/briefs (never auto-pulls; notes that a session reload is what reloads the agent;
on "no" or a non-clone copied install it skips and upgrades as-installed). `SKILL.md`'s upgrade blurb
gains the same one-line note. Additive — the reconcile steps are unchanged; it front-loads an optional
engine refresh so "upgrade" can fetch-then-apply in one prompt. (Pairs with the README install moving
to a direct clone + an *Updating* section.)

## v9 — 2026-06-25
breaking: no

Post-landing revision loop (WO-021). A landed work-order had a channel *up* — **Implementer notes**
(implementer → orchestrator) — but none *back down* for the common case the operator flagged: a WO
lands, the operator verifies it, and wants a small change. With no in-WO place for that, a tweak meant
an out-of-band ask or a near-duplicate WO. v9 adds the return path, additively:
- `references/work-order-template.md` gains a **`## Revisions (post-landing)`** section: after a WO
  lands and the operator verifies it, the **orchestrator** writes the requested change as a scoped
  item, the **implementer** handles it on a re-dispatch (a fresh window on the same WO) and records the
  result — repeat per round until satisfied. A genuinely new direction stays a follow-up work-order,
  not a revision (the bloat guard).
- `references/roles/orchestrator.md` work-loop step 4 becomes **"verify → accept or revise"**: on
  revise, write the change into the WO's Revisions section and re-dispatch; don't resolve a WO the
  operator hasn't accepted.
- `references/roles/implementer.md` lifecycle step 1: on entry, **open `## Revisions` are your scope
  for this round** (else the Proposed fix scope is).
Additive — turns a landed WO into an iterable artifact (land → verify → revise → re-land) without a new
work-order for every tweak. Downstream adopts on upgrade (new WO files carry the section).

## v8 — 2026-06-23
breaking: no

Implementer is operator-enterable (WO-020). The implementer role was modeled as **dispatch-only**
("never entered, never invoked by user phrasing"), but the canonical workflow opens a *fresh window
on one work-order* and says "implement this" — which `SKILL.md`'s intent-routing fell through to the
**orchestrator**, so the agent assumed it drove the ledger. v8 reframes the implementer as entered on
**one work-order** — by orchestrator dispatch OR by an operator pointing a fresh window at it — and
adds the routing + signage to land there:
- `SKILL.md` First-action gains an **implementer-entry branch** ("implement/do THIS work-order" →
  Implementer: read that WO + plan-first, **not** the full orchestrator bootstrap); the role table and
  the "four-role" framing shift from "operator-entry / dispatched" to **repo-entry / work-order-entry**.
- `references/work-order-template.md` gains a **role-pointer banner** at the top of every WO file
  (opened to do the work → you are the Implementer; plan-first; scope = `## Proposed fix scope`).
- `references/roles/implementer.md` + `references/agent-system.md` reframe "dispatched, not entered"
  → "entered on a work-order, not on the repo" (dispatch or operator-pointed; same boundary).
Additive: the dispatch path and the implementer's scope boundary are unchanged — it only adds the
operator-direct entry the workflow already used. Downstream repos adopt on upgrade (new WO files carry
the banner; the routing fix covers WOs already on disk).

## v7 — 2026-06-22
breaking: no

No-fork directive for the diagnostic role (WO-017). `references/roles/diagnostic.md` gains a
**"Don't fork this role"** discipline rule (echoed in the Role-boundary "You DO NOT" column): the
diagnostic role is owned by the engine brief + the repo's profile `prompts/diagnostic_agent.md` (Custom
repos) + an optional in-home `<home>/DIAGNOSTIC_AGENT_BRIEF.md`, and must **not** be re-implemented
outside those homes — not as a project-local `.claude/skills/*` debug/triage skill, a repo-root
`*_AGENT_BRIEF.md`, or a stray duplicate `diagnostic_agent.md`/`debug_agent.md` that splits the role's
source of truth. When a fork exists, **migrate its durable knowledge into the profile/brain FIRST, then
retire it** (reversible via a branch); never delete load-bearing contracts before they are migrated.
`references/roles/orchestrator.md` gains a one-line intake watch that opens a migrate-then-retire
work-order when a fork is spotted. Additive — no existing directive/contract is removed, and a repo that
already doesn't fork is a no-op (WO-013's repos already comply). Promotes WO-013's spawned consideration.

## v6 — 2026-06-22
breaking: no

Hardened orchestrator work loop (WO-016). `references/roles/orchestrator.md` gains an explicit
**"The work loop"** section (after *First action*) — an ordered, gated spine that makes the role's
previously-implicit per-session / per-work-order cadence checkable. The gates are non-skippable
operator-control + correctness points: **the operator confirms proposed work-orders before any are
activated/dispatched** (the brake on runaway work-order creation), plan-approved + disjoint-files +
scope-bound before any edit, verify-the-diff before commit, and never-advance-with-anything-half-done.
**Window topology** (fresh-per-WO vs. batching similar work vs. sequence/parallel) is explicitly left
to the orchestrator's judgment — an optimization, not a rule. Additive: it makes existing-good
behaviour explicit and harder to skip; no role behaviour is removed, so a repo on an older engine
keeps prior behaviour until it upgrades. Adopted cleanly on upgrade.

## v5 — 2026-06-20
breaking: no

Two engine-directive changes.

**Ensure version control (WO-011).** `scripts/scaffold.py --git ensure` (now the default) and the
orchestrator's first-action **auto-init git when none is detected** — robust detection (`.git` as a
dir or file, or a parent work-tree via `rev-parse`), a report printed *before* any git runs, then
`git init` + a starter `.gitignore`/`.gitattributes` (`* text=auto`); the inception agent makes the
baseline commit. `--git skip` opts out; `offer` is the legacy recommend-only mode. **Behavior change:
the engine now RUNS `git init`** (it previously only offered). Additive — a repo already under git is
a no-op, and a fresh init is a safe guarantee, not a migration.

**Forward-positive brain invariant (WO-012).** `references/brain-schema.md` §6 gains a "no
self-pollution" rule: brain pages stay factual and forward-useful (capture cause + correction; valid
issue-records — findings, bug work-orders, lessons — stay), with no dwelling/blame/negative
editorializing. Semantic, so it is enforced in the orchestrator's reflection pass, not `brain_lint`.

Additive overall; downstream repos adopt both directives on upgrade.

## v4 — 2026-06-20
breaking: no

Define the implementer as a fourth, dispatched role (WO-009). Adds
`references/roles/implementer.md` — the single source of truth for the dispatched implementer's
definition + boundary (the `specified-vs-self-designed` rule from v3's WO-007, now with one home).
The three former restatement sites (the SKILL.md dispatch section, the orchestrator brief's
"Dispatch + verify", and the work-order template's "Proposed fix scope") are consolidated to a
one-line application + a pointer to the brief. Reframes the role model to **four defined roles in
two tiers** — three operator-entry (inception/orchestrator/diagnostic) + one dispatched
(implementer) — across `SKILL.md`, `references/agent-system.md`, `references/profiles.md`, and a
new `references/glossary.md` entry. Additive: no implementer *behaviour* changes (definition +
consolidation only); no `.gitos/roles/` pointer and no scaffold change, since you never resume as
an implementer.

## v3 — 2026-06-20
breaking: no

Role-boundary hardening (WO-006 + WO-007) — extends the find/fix separation to the
orchestrator and implementer sides so every edit traces back to a specified work-order.
**WO-006:** the orchestrator now writes **no code, ever** — every executable change
(application source AND pipeline tooling under `.gitos/tools/`, `scripts/`) is dispatched to
an implementer; the orchestrator writes only markdown/state (work-orders, INDEX, brain, role
pointers, handoff). Removes the prior "you write code" / "may edit code" authorization from the
orchestrator brief and the SKILL.md role-boundary table, and tightens the agent-system
Four-Artifacts map (`Code` = Implementers only, never the orchestrator). **WO-007:** an
implementer edits **only what its work-order's Proposed fix scope specifies** — out-of-scope
edits (INDEX, brain, other work-orders, directives) are the orchestrator's, surfaced by the
implementer as proposed notes/follow-ups, never self-executed; stated in the SKILL.md dispatch
section, the orchestrator brief's "Dispatch + verify", and the work-order template. Additive
tightening of directive guidance — adopted cleanly on upgrade with no migration action, so a
repo on an older engine keeps prior behaviour until it upgrades.

## v2 — 2026-06-19
breaking: no

BRIDGE-aware upgrade (WO-005). `references/upgrade.md` gains a **Step 0** that classifies a repo
as Standard (engine-only) or Custom (profiled product) and routes Custom repos through their
`BRIDGE.md` (SYNC/PRESERVE/MERGE) instead of the generic engine-only path; a Custom-but-unbridged
repo HALTs rather than risk overwriting deployed profile/state. Adds the BRIDGE contract
(`references/bridge.md`), the `_meta.bridge` pointer convention, the Custom-only version-gap
warning (reads `CHANGELOG.md` `breaking:` flags against the bridge's `min_compatible_engine`), and
a gated `scripts/scaffold.py` stamp of `bridge` / `last_reconciled_engine` / `min_compatible_engine`
into `.brainmeta.json` when a profile BRIDGE is present. Additive: Standard repos fall straight
through steps 1–7 unchanged, and the new HALT is a safe refusal — no already-correct repo must
migrate.

## v1 — 2026-06-19
breaking: no

Baseline — the engine state at this repo's inception (the recursive self-bootstrap, when
gitos was first brought under its own pipeline). Includes the three-role system (inception /
orchestrator / diagnostic) plus the per-repo brain, the `.gitos/` home,
`scripts/scaffold.py`, `scripts/brain_lint.py`, and the `references/` directive tree. First
recorded version; no predecessor to migrate from.
