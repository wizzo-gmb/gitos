# Owner board

Every gitos home carries a small local web app where the owner sees the work and answers what the agent asks: the owner
board, `<home>/board/`. It shows the ledger live (orders with their slices, sprints, decisions, loose ends), takes the
owner's answers and actions, and a repo adds its own pages to it. A plan with several items, a send to an outside party, anything a tool takes with `claim()` and anything
asked while the operator is away (a sprint stop, a question left for the next window) goes through it; a single question
asked while the operator is in the window is answered in chat and recorded in the ledger the same turn. It is stdlib-only Python served on a loopback address (127.0.0.1 unless `board.json`
says otherwise), its answers are files in the home, and any session finds it again after compaction, `/clear`, a new window or another account. A
workspace of several repos can share one board, the *Hub* below. The rules are summarized in
`references/roles/orchestrator.md` (*Ask on the board*); this file holds the detail.

## Where it lives

| Path | What | Tracked |
|---|---|---|
| `<home>/board/board.py` | the board: CLI, server and the module API (a copy of the engine's `assets/board/board.py`) | yes |
| `<home>/board/board.json` | `port` and `board_id`, written once; optional `host`, `tabs`, and a hub's `routes` (`register-tab` adds a tab and its route) | yes |
| `<home>/board-route.json` | a repo that uses a hub's board instead of its own (see *Hub*) | yes |
| `<home>/board/ui/` | the engine's page code (`app.js`, `ui.js`, `store.js`, `ui.css` and the rest), copied from the engine's `assets/board/ui/`; an upgrade replaces it with `board.py` | yes |
| `<home>/board/views/<name>.js`, `views/theme.css` | a repo's own views and look (optional; see *Repo views*) | yes |
| `<home>/board/providers/<name>.py` | a repo's own data for its views (optional; see *Repo views*) | yes |
| `<home>/board/data/` | cards, answers, notes, closes, the stored plan and draft bytes, the read mark | no (git-ignored) |
| `<home>/board/inbox/`, `outbox/` | a hub's card requests from seats, and the answers mirrored back (see *Hub*) | no (git-ignored) |

The port is derived from the home's resolved path (SHA-256, folded into 8800-8999), bind-tested when the board is
built and walked to the first free one. Two pointers lead a fresh window to it: a line in the CLAUDE.md managed
block (`**Owner board:** python <home>/board/board.py ensure (http://127.0.0.1:<port>/); ...`) and the
`## Owner board` section of `RESUME.md`. `scaffold.py` builds the board and both pointers; on an existing repo
the same run is the upgrade step (`references/upgrade.md`). The canary's `board` category reports a pointer with
no board (`board-missing`), a board nothing points at (`board-pointer-missing`), a `board.py` with no `ui/` beside it
(`board-ui-missing`, gating: re-run `scaffold.py`, which copies `ui/`) and a leftover `board/local/*.html` page
(`board-legacy-page`, advisory: see *Migrating a page*). <!-- rule:guide-canary-kinds --> <!-- rule:guide-pointers -->

## The agent's side

```
python <home>/board/board.py ensure [--tab T]   # start it if this home's board is not answering; print one line
python <home>/board/board.py add-decision TITLE BODY value=Label... [--details FILE] [--tech FILE] [--tab T] [--replaces ID] [CARD]
python <home>/board/board.py add-plan PLAN_FILE TITLE [--table ROWS.json] [--tech FILE] [--item NAME] [--tab T] [CARD]
python <home>/board/board.py add-send DRAFT_FILE TITLE --to ADDR [--cc ADDR] [--subject TEXT] [--tech FILE] [--item NAME] [--tab T] [CARD]
    # CARD: [--ref WO-NNN] [--where TEXT] [--group close|decision|action|parked]
python <home>/board/board.py list [--open] [--tab T]  # cards with their latest answer; locks each answer it shows
python <home>/board/board.py answer-for ID [--tab T]  # the latest answer as JSON, with `valid` and `locked`; locks it
python <home>/board/board.py close ID OUTCOME [--tab T]
python <home>/board/board.py notes [--tab T]          # the owner's notes; marks them read
python <home>/board/board.py summary [--tab T]        # counts as JSON, read-only (the waiting view runs it)
python <home>/board/board.py actions [--json]         # the owner's open actions on orders (see Owner actions); marks them read
python <home>/board/board.py action-done ID [--rejected REASON]   # close one: applied to the ledger, or rejected with the reason the page shows
python <home>/board/board.py register-tab TAB --repo PATH   # a hub: route a repo's tab here (see Hub)
python <home>/board/board.py url | serve
```

`--tab T` limits a command to one tab (a hub repo works only in its own tab): `list`, `summary` and `notes` show that tab
alone, `answer-for` and `close` find no card of another tab, `--replaces` and a newer plan or send for the same item
reach only the same tab, and `add-plan` and `add-send` put the card on that tab (default `decisions`; a send goes to
`email` when the board has that tab).

`ensure` finds this home's board by the `board_id` it serves at `/api/identity` (with the home path), so another
repo's board on the same port is never taken for this one; it starts `serve` detached only when nothing answers,
and it never stops a process. Its one line: `board: http://127.0.0.1:<port>/ · N open · A new answers · M new notes`
(`--tab T`: that tab's counts, and the address ends `#T`),
where a new answer is one on an open card that no read has locked yet (`list`, `answer-for` and a close each clear
it) and a new note is one since the last `notes`; it adds `· K waiting to be acted on` while answered
cards are not closed, and `· P problem(s) in its files` when some file fails validation. Everything the CLI prints
from a card or a note is one cleaned line (control, bidi and zero-width characters removed), so a title cannot fake
output. <!-- rule:guide-ensure-line -->

**No command records an answer.** Only the board page does, through `POST /api/answer`. <!-- rule:guide-no-cli-answer -->

- **Every card** may carry `--ref` (the work-order id, shown beside the title), `--where` (one line pointing into the
  ledger or the code) and `--group`: `close` (close or keep open), `decision` (the default), `action` (only the owner
  can do it) or `parked` (a parked order whose trigger fired). The page filters by group. <!-- rule:guide-groups -->
- **A decision** has the options you give (`value=Label`, the value 1-32 of `a-z 0-9 _ -`); `value=Label*` marks the
  option you recommend. `--replaces ID`
  closes the card it replaces as "replaced by <id>".
- **A plan** (`add-plan`) stores a copy of the file at `data/plans/<sha256>.<ext>`, binds the card to the full
  SHA-256 of those exact bytes and prints the stored path: dry-run and apply that file and no other. `--table`
  is a JSON list of `{label, count, what}` (or `[label, count, what]`) rows, shown as a plain table; the raw tool
  output goes in `--tech`, folded. Options: Apply it / Change it / Skip. A plan or draft must be UTF-8 text, so the
  card shows exactly the bytes it binds; one holding bidi or zero-width characters is flagged on the card ("this file
  contains invisible characters"; any format character, or a control
  character other than tab and line breaks).
- **A send** (`add-send`) stores the draft at `data/drafts/<sha256>.<ext>` the same way and shows the whole draft.
  Options: Send it / Change it / Don't send.
- A newer plan or send card for the same item (`--item`, default the file's name) closes the older open ones (created
  before it) as "replaced by <id>". `--replaces ID` refuses a card that is not open, and writes nothing then.

Tabs come from `"tabs": ["..."]` in `board.json`; the default is `decisions` alone, and `decisions` is always
there. A send card goes to an `email` tab when the repo has one, else to `decisions`.

In a named sprint's session (`GITOS_SPRINT=1`, `GITOS_SPRINT_ID` set), every command and the module API use the board of
`GITOS_SPRINT_HOME`, not the worktree's copy of the data, so cards and approvals are the operator's real ones. With no
board in that home, the copy's own board is used.

### The module API, for a tool that acts on an approval

Load `board.py` by its path (`importlib.util.spec_from_file_location`), never through `sys.path`, then:

- `approved(kind, key, value, go=None, tab=None)`: reads and locks, then returns the newest card of `kind` (in `tab`,
  on a hub) whose field `key` equals `value`
  (`approved("plan", "item", "q3-cleanup.json")`), when it is not closed and its latest answer chose the go option
  (`apply` for a plan, `send` for a send) against the card's current content. Otherwise `None`. A newer card for
  the same item, answered or not, blocks an older approval; cards are ordered by a microsecond `created` time that
  is strictly increasing within a board. <!-- rule:guide-api-approved -->
- `verify_bytes(card, data)`: `True` only when `data` hashes to exactly the card's `sha256`. Read the stored file
  and verify it immediately before using it. <!-- rule:guide-api-verify -->
- `consume(card_id, outcome)`: close the card **before acting on it**, with the outcome you are about to produce.
  A closed card never approves again, and closing it twice is refused (the check and the close are one step under
  the board's lock). A seat's card (`source: inbox`, see *Hub*) is never approved: a tool acts on what its own repo asked. <!-- rule:guide-api-consume -->
- `claim(kind, key, value, go, outcome, tab=None)`: `approved()` and `consume()` as one step under the lock: the approved
  card, now closed, or `None`. **Tools use this**: of two tools claiming the same approval, exactly one gets it, and
  it acts only after `claim()` returned the card (then `verify_bytes()` on the stored file). <!-- rule:guide-api-claim -->
- Every write (an append, a lock, a close, the page's check-then-append of an answer) holds one cross-process lock,
  `data/.lock` (`msvcrt` on Windows, `flock` on POSIX). `approved()` also refuses an answer whose time is later
  than the lock that names it. <!-- rule:guide-lock-file -->

## The read lock

The owner may change an answer until the agent reads it. Reading an answer (`list`, `answer-for`, `approved()`)
**locks** it: one line in `data/read.jsonl` with the card, the answer's `at` and its `card_hash`. After that the page
refuses a new answer to the card (`409 locked: Claude read this at <time>`) and shows the buttons disabled with
"Locked: Claude read this at <time>. To change it, write in Anything else for Claude". `approved()` locks the answer
it sees, reads the card again, and returns it only when its latest answer is that locked one: an answer that arrived
in between is pending, and **a pending answer never authorizes**. Counting (`ensure`, the waiting view) never locks.
An edit of the card voids its answer, so the owner can answer the new card. <!-- rule:guide-read-lock -->

## The owner's side

Cards are answered on the **Decisions** view (*The page*), which has a tab for each card tab; on each tab, Needs you / Answered / Closed. Each card shows what it asks in plain words, its
details, a folded Technical details, the options, and a note box. One "Anything else for Claude" note sits at the
bottom. Pressing an option saves it at once, with the note in the box. **Save note** with no option is a note-only answer
(`option: null`): it counts as answered and is never a go. Cards voided by an edit come first under Needs you. Copy
my answers puts one `id -> option | note` line (`(note only)` for a note-only answer) per open card with a valid
answer on the clipboard:
never a title, never a closed card, never a voided answer. Problems in the board's files (a card file that fails
validation, a torn line) are listed at the top, never skipped silently. <!-- rule:guide-note-only -->

A card's hash is the full SHA-256 of its content, recomputed on every read. An answer binds the hash it was given
against, so a card edited after its answer **voids** that answer: the card goes back under Needs you with "the card
changed after your answer", `approved()` refuses it and Copy skips it.

## The page

The board page is an app under `<home>/board/ui/`: a sidebar (the engine's views, then the repo's own), the order detail
as a drawer over the current view, a command palette (Ctrl or Cmd-K) and shortcuts (`?` lists them). Addresses are
hashes, so a link and the back button work: `#/work/list`, `#/work/board`, `#/work/graph`, `#/sprints`, `#/decisions`,
`#/loose-ends`, `#/order/153` (the drawer) and `#/repo/<name>` (a repo's view). It runs in light and dark, down to a phone
width, and everything is reachable from the keyboard.

- **Work**: the **list** (sort, filter by severity and status, search; slices done of total per order), the **board**
  (columns in progress, awaiting accept, can start, waiting, held, parked; an order card shows its slices) and the
  **graph** (every open and parked order with its slices and their `depends_on` edges; pan, zoom, focus an order to
  light what it waits on and what waits on it). An order with `landed:` in its front matter, or with every slice landed, is
  *awaiting accept*, never *can start*.
- **Sprints**: each sprint's state, orders, last activity and its Stop card.
- **Decisions**: open cards first, answerable in place; then answered cards with their answer and outcome; then the brain's
  decision records (title, description, date, status, superseded-by, from the page's front matter, never its body).
- **Loose ends**: the count and the rows.

The page is current without a reload. Its connection indicator says live or reconnecting, and a change in the ledger, a
slice landing, a sprint starting or a new card shows within a second or two, as a diff: the changed row or node animates,
and scroll position, an open drawer and the filters stay (a filter is kept in the address).

**Endpoints** (every GET answers only to the board's own `Host`, as in *Security*):

| Request | What |
|---|---|
| `GET /` | the page (the token and a script nonce are put into it) |
| `GET /ui/<file>` | the engine's page code and styles |
| `GET /views/<file>` | a repo's own view (`<name>.js`) or `theme.css`, nothing else |
| `GET /api/state` | the whole state as JSON |
| `GET /api/events` | `text/event-stream`: a `state` event (the whole state, its version as the event id) when anything changes, a comment every 15 s of quiet. `EventSource` reconnects by itself and sends `Last-Event-ID`. At most 16 streams are open; the 17th gets 503 |
| `GET /api/identity` | the `board_id` and home path, for `ensure` |
| `POST /api/answer`, `/api/action`, `/api/note` | the owner's answer, action and note, with the checks in *Security* |

**The state** is derived data only, built by the engine's own readers (`ledger_index.py`, `sprint_log.py`, `loose_ends.py`
and the board's card code): orders (id, title, severity, status, parked trigger, `landed`, slices with state and
`depends_on`, a `hash` of the entry), the links between orders, sprints, loose ends, cards and notes, the decision records'
metadata, the canary's summary line, the owner's actions, and for a repo its `views`, `theme` and `ext` (provider output).
Never a raw file, a brain page body or an intake body. A reader that fails is an entry in `errors`, and the rest of the state
is still served. One watcher thread notices changes by file times and builds the state once per change for every connection.

## Owner actions

From an order's drawer, the menu or the palette the owner can: reprioritize (severity), park with a trigger, unpark, hold,
release, approve for dispatch and add a note. Each opens the board's own confirm, which shows the action and the state the
owner saw. **An action is a request.** `POST /api/action` records one line in `data/actions.jsonl` (id, order, kind, value,
the state version and the order's `hash` the owner saw, the time); a record whose order hash no longer matches is marked
`stale` and is still recorded, for the orchestrator to judge. **The board never edits a work-order file.** The order shows the
action as pending until the orchestrator closes it; then the page says "applied" or shows the reason it was rejected.

The orchestrator's side is one rule, three commands:

1. `board.py ensure` and `summary` count new actions (`new_actions`: open and not yet read), and the waiting view lists them.
2. `board.py actions [--json]` lists the open actions, each with the order, the kind, the value and whether it is stale, and
   marks them read.
3. Apply each to the ledger as the orchestrator does any ledger change (severity in the order's front matter, a parked
   order's trigger, and so on), commit it, then close it: `board.py action-done ID` when applied, `board.py action-done ID
   --rejected "<reason>"` when not (a stale one the order no longer fits, or one that contradicts the ledger). `hold`,
   `release` and `approve` have no ledger field: the board reads them from the actions closed as applied (a later release or
   park undoes a hold), so close those as applied once you will honour them.

A closed action never reopens. A note is read before the next step on its order.

## Repo views

A repo adds pages to the board, with its own data and look, by putting files under `<home>/board/` (committed; an upgrade
and `scaffold.py` never touch them). Nothing is configured: the board lists the folders.

- **A view**: `views/<name>.js` (the name is `a-z 0-9 -`, 1-32 characters), a native ES module. It exports `meta` and
  registers one custom element named `gb-repo-<name>`. The sidebar lists it under *This repo* and `#/repo/<name>` mounts it.
  There is no frame: it runs in the page like an engine view.
- **Data**: `providers/<name>.py`, a script for what the state does not hold. The board runs it in its own `python -I -B -X
  utf8` process (argument 1 and the working directory are the home) whenever the home changes, at most once every 5 s, with a
  10 s limit. It prints one JSON value (at most 256 KB, no NaN or Infinity) and exits 0; the value appears as
  `state.ext.<name>`. A provider that crashes, hangs, exits non-zero or prints anything else is an entry in `errors` and the
  board keeps serving, with that provider's last good output still in `ext`. A hung provider is killed with the processes it
  started. The output goes into the state as it is: print nothing the owner should not see.
- **Look**: `views/theme.css`, CSS only, loaded after the engine's styles in a `theme` layer, so a rule there wins without a
  selector contest. It follows the file live. The engine's design tokens are CSS custom properties (`--accent`, the radii,
  the colors; dark mode is `:root[data-theme="dark"]`).

**The module.** A view imports only the engine's modules, `/ui/ui.js`, `/ui/store.js` and `/ui/actions.js` (and `/ui/graph.js`
for `<gb-graph>`):

```js
import { h, setText, setAttr, reconcile } from "/ui/ui.js";
import { store } from "/ui/store.js";
import { requestAction } from "/ui/actions.js";

export const meta = { title: "This week", icon: "calendar", position: 10 };   // title 1-40 chars; icon a kit icon name (else a dot); position orders the sidebar
class RepoThisWeek extends HTMLElement { /* connectedCallback: build once, store.subscribe(() => this.render()) */ }
customElements.define("gb-repo-this-week", RepoThisWeek);
```

- **The store.** `store.state` is the live state (`state.orders`, `state.sprints`, `state.cards`, `state.records`,
  `state.looseEnds`, `state.ext.<provider>`, ...). `store.orders()` lists the open and parked orders as the views read them
  (`id`, `title`, `sev`, `status` of `active`, `awaiting`, `ready`, `waiting`, `held` or `parked`, `slices` with their
  `state` and `dependsOn`, `done`, `total`, `waitsOn`, `blocks`, `trigger`, `pending`); `store.order(id)` finds one.
  `store.subscribe(fn)` calls `fn(store, changes)` on every new state; `changes.has("o:153")`, `"s:153/S2"`, `"p:<sprint>"`,
  `"c:<card>"` and `"x:<provider>"` say what moved, so a view patches only that. It returns an unsubscribe function: call it
  in `disconnectedCallback`. `state.ext.<name>` is undefined until the provider's first good run: handle that.
- **The kit** (`/ui/ui.js`): the elements `<gb-badge state>`, `<gb-sev level>`, `<gb-strip>` (`set(states, text)`),
  `<gb-stat label value hint>`, `<gb-empty icon title desc>`, `<gb-skeleton>`, `<gb-segmented>`, `<gb-order-card>` (set its
  `order` property to a store order; clicking it opens the order's drawer) and `<gb-table>` (`setColumns`, `rows`, a
  `row-open` event); `<gb-graph>` comes from `/ui/graph.js`. The helpers: `h(tag, props, ...kids)` builds elements,
  `setText` and `setAttr` change a node only when the value differs, `reconcile(parent, items, {key, create, update, move})`
  keeps keyed children in place and animates entering and leaving, and `toast`, `openMenu`, `confirmDialog` and
  `viewTransition` are there too. Update in place; do not rebuild the view with `innerHTML` on each state, or it flashes and
  loses scroll, focus and open menus. Write text with `textContent` or `h`, never `innerHTML`: titles come from files.
- **Actions.** A view asks for an owner action only through `requestAction(kind, order)` of `/ui/actions.js`, with `kind` one
  of `severity`, `park`, `unpark`, `hold`, `release`, `approve`, `note`: the board's own confirm opens and the owner decides.
  **A view never posts an answer or an action itself.** The store's `post` is reachable from any same-origin code and the
  kit does not stop a view from using it; the contract does, and a view that breaks it is a bug in the repo.
- A view that throws or fails to load shows an error panel in its place; the shell keeps working. A view module is loaded once
  per page load, so a changed `<name>.js` shows after a reload (the page says so); `theme.css` changes live.

**The worked example** is `assets/board/examples/this-week/` in the engine: `views/this-week.js` (the open orders the ledger
touched this week, with an *Add a note* action on each card), `providers/week.py` (the data it reads: the orders whose file
or slices changed in the last 7 days) and `views/theme.css` (every rule commented out). Copy `views/this-week.js` and
`views/theme.css` into `<home>/board/views/` and `providers/week.py` into `<home>/board/providers/`; "This week" appears in
the sidebar, updates as orders change and sends a note through the confirm. A useful view is a few dozen lines like it: read
the state or a provider's `ext`, show it with the kit, ask for an action through `requestAction`.

## Migrating a page

The engine no longer serves `<home>/board/local/<name>.html` (the sandboxed page of earlier versions): it shows nowhere, and
the canary reports each leftover as `board-legacy-page`. The engine ships no converter; the repo's orchestrator rebuilds
each page as a native view, as its own work-order, in these steps:

1. **Read what the page shows and where its data comes from.** Open the old file. List each thing it displays and its
   source: the ledger (work-orders, slices, sprints, cards: already in the state), a file the page embeds or reads, or
   something an outside job (a scheduled task that rebuilds the page) computes.
2. **Move the data source into a provider** when it is not in the state already: a `providers/<name>.py` that reads the file
   or runs the computation and prints it as JSON. A job whose only purpose was to rebuild the static page goes away.
3. **Rebuild the page as `views/<name>.js`** on the kit (*Repo views*): `meta`, one `gb-repo-<name>` element, `store` and
   the provider's `state.ext.<name>`, kit components in place of hand-written markup, `requestAction` in place of any button
   that answered or acted. Take the layout from the old page, the data from the state; move a style that mattered into
   `views/theme.css`.
4. **Open it on the board and check it against the old page**: each thing the old page showed is there, it changes when the
   ledger changes (touch a work-order and watch it), and a provider that fails shows as an error with the page still up.
5. **Delete the old page** `board/local/<name>.html` and any job or script that existed only to rebuild it.
6. **Commit** the view, the provider, the theme and the deletions.

Write this as one work-order in the repo, with the page list from `ls <home>/board/local/` as its scope; each page is a
slice. The sprint driver's own `local/sprint*.html` are not a repo's pages: the board shows no sprint page at all, and the
canary leaves them out.

## Hub

A workspace of several gitos repos has one **hub**: a gitos home whose board is the central owner board. Every other
repo in the workspace points at it and has no board of its own; its questions land in their own tab on the hub page, and
the owner answers on that page and nowhere else. **A repo with no route file keeps its own board, as above.**

`<home>/board-route.json` (committed): `{"mode": "hub", "board": "<absolute path of the hub's board dir>", "tab":
"<short name>"}`. `mode` is `local` or `hub`; the tab is `a-z 0-9 -`, 1-24 characters, a letter first (a long repo name
needs a short tab). In hub mode the CLAUDE.md line and RESUME section name `python <hub>/board.py ensure --tab <tab>`,
every command takes `--tab <tab>`, `approved()` and `claim()` take `tab=`, and the waiting view reads the hub's
`summary --tab <tab>`.

**Set one up.**
1. Install gitos in a folder outside the seats' reach: that home's board is the hub. Set `"host": "127.0.0.2"` in its
   `board.json` and restart the board: Docker Desktop's host gateway forwards a container to 127.0.0.1 only, and a
   container can send any header, so a board on 127.0.0.1 can be read (the page token with it) and answered by a seat.
   `ensure` warns on stderr when Docker is present and `host` is 127.0.0.1, and the canary reports `board-exposed`
   (advisory).
2. In each repo write `board-route.json` and run `scaffold.py <root> --git skip`. It builds no board there; it runs the
   hub's own `board.py register-tab <tab> --repo <root>` (adds the tab and its route to the hub's `board.json`, makes
   `inbox/` and `outbox/<tab>/` with a `.gitignore` for both, and refuses a tab already routed to another repo), then
   writes the two pointers. Running it again changes nothing. The canary's `board` category reports a route file that
   does not parse (`board-route-unparseable`), a hub without its files (`board-hub-missing`), a tab the hub does not route to
   this repo (`board-tab-unregistered`), a `<home>/board/` left behind (`board-unrouted`) and pointers that do not name
   the hub (`board-pointer-missing`).
3. Mount `inbox/` read-write and `outbox/<tab>/` read-only into each seat.

**Seats propose; they never answer.** A seat keeps its routine calls. What needs the owner it asks as a card request:
a file `inbox/<name>.json`, written under another name and renamed when complete:
`{"tab", "title", "body", "options": [{"value", "label"}], "ref"?, "group"?}`. Decision cards only: no plan or send (the
hub cannot bind files it did not receive), no details, no answer. The serving process (and `list`) turns a valid request
into a card marked `source: inbox` (the page says "proposed by a seat"; its text is escaped as everything is); an invalid
one (not JSON, over 64 KB, an unknown field, an unknown tab, invisible characters, a title over 200 or a body over 4,000
characters) moves to `inbox/rejected/` with a `.reason` file and shows as a problem until that folder is cleared.
Creating a card never answers it. The seat reads answers from `outbox/<tab>/<card id>.json`
(`card`, `card_hash`, `answer`, `answered_at`). Writing that file **is the read that locks the answer**: the server
mirrors once a minute and only an answer at least a minute old, so the owner can still change a fresh answer; a changed
or voided card loses its file. `list` and `answer-for` never lock a seat's card, and `approved()` never approves one.

**The hub page.** The hub's own page has an *All repos* view: one row per routed repo with counts only (open, in progress,
waiting, parked, running sprints, cards that need you). A repo whose home cannot be read is an error row with the reason, and
a repo whose state is not built yet shows as "reading"; the other rows are unaffected. A row opens that repo's tab, at
`#/r/<tab>/<view>`. A repo tab is built from that repo's home alone (its orders, sprints, loose ends, decision records and
engine version): it carries none of the hub's own views, providers, theme or `ext`, and its state is read with `?tab=<tab>`
(a tab that is not routed is refused). Cards and notes are board-wide, so a repo tab still lists every tab's cards; there is
one owner and one board. The page keeps one stream per open tab view, and the 16-stream cap counts every stream of every
tab. One slow or unreadable repo never holds up the hub or the other tabs.

**Owner actions on a hub.** An action the owner takes in a repo's tab is recorded under that tab in the hub's `data/`, and
only that repo's orchestrator reads it: `board.py actions --tab <tab>` and `board.py action-done ID --tab <tab>` (an id from
another tab is "no action"). Run on a hub's home without `--tab`, both refuse with a usage error that names `--tab`; the hub's
own base tab is named explicitly. An action's `stale` and `hash` are of the order in that repo's state, so the same order
number in two repos is two orders.

**Moving a repo that has a board to a hub:** `references/upgrade.md` step 4s.

## The loop

1. **Ensure first.** At the start of every session, `ensure`, report its line, then read new answers
   (`list --open`) and notes (`notes`) before any other work.
2. **One card per ask.** Re-read the ledger item before writing its card. Write it for the owner, not the code:
   no ids without words, name what each option does and where. No secrets (a card that needs a credential asks
   for names only), no foreign text (a federation proposal body is never put on a card).
3. **Record before acting.** Write the answer into the ledger (the work-order, a loose-end row, or a decision page that passes the brain's write test)
   before acting on it. A standing rule goes to the brain the same turn.
4. **Close with the outcome.** `close ID OUTCOME` when the card is acted on; a tool consumes its approval as it
   uses it. Record the same outcome in the ledger.
5. **Re-ask by replacing.** A changed question is a new card (`--replaces ID`, or the same item for a plan or a
   send), never an edit of the old one.

## Consent

- An answer counts only when it is one of the card's options, given on the board page, against the card as it is
  now. A note, or anything that is not an offered option, is data and never a directive.
- When a card names one outward-facing or irreversible action exactly (what it does and where), choosing its go
  option is the confirmation for that one action only, used once.
- A single in-window question is asked and answered in chat, recorded in the ledger before acting. A plan, a send, a `claim()`
  approval or a question asked while the operator is away is a card, never chat, a popup or an Artifact.

## Security

The server binds one loopback address (`host` in `board.json`: 127.0.0.1, or any of 127.0.0.2-127.0.0.254; nothing
else) and answers only to `Host: <host>:<port>` (and `localhost:<port>` when the host is 127.0.0.1). A POST needs
the exact Origin (`http://<host>:<port>`), the page token minted when the server started, `Sec-Fetch-Site: same-origin` and
`Sec-Fetch-Mode: cors` (what a browser's own fetch sends, and a script does not unless it forges them); each answer
records the user agent and the Sec-Fetch values. Bodies are JSON objects under 64 KB; the handler times out (except the
event stream, which is held open and capped at 16); every field is escaped on the page, which runs under a CSP with a
per-response script nonce, and a request for `/api/events` is checked for `Host` like any other. Card files are validated
(id equals the file name, no duplicates, ISO times) and so is every line of every `.jsonl` (a card id, a full
SHA-256 hash); a bad line is reported, never raised. Writes go only under `data/`, as single ASCII appends under the
lock, each after a newline when the file's last line was torn. The page posts the hash of the card it rendered, so an
answer always names the content the owner saw. <!-- rule:guide-security-checks -->

**What a repo view is.** A repo's view runs in the board's page, as repo code: trusted like the repo's providers and any
tool in its home. What still holds: only committed files under `views/` run (the CSP allows scripts from the board's own
origin and nothing inline or remote, and a request outside `views/` and `ui/` finds nothing), so another local page or
program cannot inject a view; the contract forbids a view posting an answer or an action itself (*Repo views*), and a view
could still reach the page token, since nothing in the browser stops it; every answer binds the hash of the card the owner
saw and every action the hash of the order. A provider is repo code the board runs with the user's rights, with a time and
size limit, and the board kills what it started. This is the honest limit below, not a stronger promise.

**The waiting view runs the home's `board.py`** (`summary`) in its own `python -I` process with a timeout and reads
its JSON, so a crash, a hang or forged output from that file stays out of the view. It is not a sandbox: that
`board.py` still runs with the user's rights, like any tool in the home. <!-- rule:guide-waiting-isolated -->

**The honest limit.** On a single-user machine the agent runs as the owner, so it could forge a browser request or
write the files itself. The board guards against accidents and against other local pages and programs, not against
a deliberately hostile agent. Signing answers with a key held in the OS keychain would close that gap; it needs a
non-stdlib keychain binding and is not done. <!-- rule:guide-honest-limit -->
