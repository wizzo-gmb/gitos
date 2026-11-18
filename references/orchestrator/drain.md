# Orchestrator step: draining the loose ends

Read this when you drain the list: after an order resolves, at each checkpoint, at first action when the canary reports
`loose-ends-stale` or `drain-stale`, and when the operator asks.

`<home>/loose-ends.md` holds the loose ends, the last resort (the deferral rule in `resolve.md`): a row and nothing else
holds it, and it is only worth having if it is read and kept short. A row's State is one of four: `new` (written
down, not looked at), `proposed: <kind>` (the drain proposed join, new-order, close, ask, park or read; its file in
`<home>/drain/pending/` is the attachment), `waiting: <question>` (needs the operator) or `declined: <reason>` (never
proposed again). `parked:` is retired: a trigger-wait is a parked work-order. A row whose State cannot be
read is reported (`loose-ends-unparseable`) and never treated as `new`. A routed or closed item leaves the list and
git keeps it: not on the list means routed. An item is one or two sentences; anything that needs evidence, a cause or
a fix is a work-order, and a session plan is a RESUME entry. Work is never dispatched from the list. A repo with no
file has an empty list; the first `loose_ends.py add` creates it.

**Run the drain** (a) after a work-order resolves, for the items that order added; (b) at each
checkpoint, for the whole list; (c) at first action, when the canary reports `loose-ends-stale`, before
new work; (d) when the operator asks ("drain the loose ends").

**The drain, step by step.** Get proposals: with System One on, `system_one.py drain <home>` runs the
loose-end uses on the `new` rows (each item's `loose-end-state`, its best join with an open order, the bundles),
writes **one file per proposal** under `<home>/drain/pending/<id>.md` (kinds `join`, `new-order`, `ask`, `park`,
`close`, and `read` for an item the model was unsure about: it is never left out, so read it and decide what it is),
then marks each proposed row `proposed: <kind>` (a crash in between leaves a `new` row a file holds; the next run
marks it). The body shows each item in full with its Source, age and the context code gathered: Source order titles,
paths, open orders sharing them; no model-written prose. A run never deletes a pending proposal; only `accept`,
`decline` and `withdraw` do. A `join` means "related open order: consider adding" (the item is about the same part
of the product), and you decide whether it belongs in that order, its next slice, or elsewhere. **Read each pending
proposal, author the orders from them yourself** (the local model only groups, qualifies and passes context on; you
decide and write every order), then dispose of each; every disposition sets the rows and removes the file (git
keeps it):

- `drain accept ID --work-order NNN --slice NAME`: the items become a `proposed` slice of WO-NNN with `origin:`
  naming them (`slice add`; a single-file order becomes a folder). Without `--slice` the order must already name
  every item id (an order you authored from the proposal, `origin: L3, L5`), else the accept refuses. The rows leave
  the list.
- A `park` is accepted into a parked work-order you authored naming the items (`drain accept ID --work-order NNN`;
  `--trigger` is refused); `--question Q` (or an `ask` with no flag) sets `waiting: Q`; `--reason R` closes. A `read`
  takes whichever of `--work-order`, `--question`, `--reason` fits.
- `drain decline ID --reason R --route WO-NNN|WO-NNN/SN|brain:<page>|closed:<why>` (you routed the items by hand:
  the rows leave) or `drain decline ID --reason R` (the rows read `declined: <reason>`, which the drain never
  proposes again; decide them by hand with `loose_ends.py drop`).
- `drain withdraw ID` (the rows read `new` again and are asked again) or `drain defer ID` (nothing changes).

Down, not configured, or off: the helper route (`references/system-one.md` -> *The drain without a local model*): `system_one.py drain <home> --export FILE`, run `system_one.py helper` and dispatch one helper on the model it prints with the brief there (exit 3 or an unavailable model: ask the operator once, with the harness's question UI, to pick from their harness's models and record it with `helper --set`; never guess or retry silently), then `system_one.py drain <home> --answers FILE`, and decide the proposals as above. You never answer the export yourself: if no helper can be dispatched, the drain waits (and down is still never raised to the operator). The drain is the local model's or a helper's: never yours by hand, however short the list.
Decide each item. Apply. Commit. Report the line `loose_ends.py status --brief` prints: `loose ends: N new · N proposed · N waiting · N declined`.

**The join test.** An item joins an open order only when all three hold: (a) it is in files the order's next slice
would change; (b) that slice is planned, not in flight; (c) it changes neither that slice's scope nor what counts as
done. Code checks the slice is named: `drain accept ID --work-order NNN --slice NAME` writes the follow-up as its own
`proposed` slice, so a running slice's scope never changes. (a) to (c) are yours: an item that fails any of them is a
new order, a parked order or stays on the list, never a join.

**Who decides.** You adjudicate and apply, on your own: join an open order by the test above (a proposal whose
header says `target in progress: <why>` means a worktree exists or the notes are started); bundle items into one new
order; park it as a parked work-order with a named trigger (`drop L<n> --to WO-NNN`); move a lasting fact to the brain
(`drop --to brain:<page>`). **The operator approves**, in one batch with the harness's question UI and never one by
one mid-work: every close (`closed:<reason>`), superseded item and fold; anything about money, security or what users
see; anything you are unsure of. **A question for the operator is a `waiting:` row**: accept an `ask` proposal (or
`loose_ends.py state L<n> "waiting: <question>"`), raise the `waiting:` rows yourself, at each checkpoint, in one
batch, then route each with the answer (`drop --to ...`, or `state` to `declined:` or `new`). The canary
reports `drain-stale` when a pending proposal has been undecided longer than 14 days or more than 20 are pending:
decide them before new work. Nothing is closed on silence, and nothing is done because it was proposed: a System One
outcome is a proposal, and `drop` is always your own act.

**One store, checked.** The canary gates `loose-ends-two-stores` when an item is on the list and also held by
another store (a pile file while its row is not `proposed:`, an open carried box, an open hand-kept Parked row it
was imported from, a parked order whose `origin:` names it, the retired `drain/routed.txt`), or a `proposed:` row has
no pile file. A retired `parked:` row is `loose-ends-migration` until the migration makes it a parked order. A repo from before v57
gets `loose-ends-migration` (advisory) until `ledger_migrate.py <home> --write` moves its stores onto the list
(`references/upgrade.md`).
