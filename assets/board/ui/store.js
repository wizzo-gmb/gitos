/* store.js - the live store.
   One state tree, a derived view-model and a diff: every update reports exactly which entities changed, so views patch those
   rows, nodes and cards in place instead of redrawing. The state comes from the board: GET /api/state once, then the
   /api/events stream (server-sent events) pushes each new state. `adapt()` is the one place that maps the board's state onto
   what the views read; a view never reads the wire shape. */

function blank() {
  return {
    version: "", engine: "", name: "", where: "", host: "", port: "", now: "",
    counts: { open: 0, parked: 0, resolved: 0 },
    orders: [], links: [], resolved: [], sprints: [], records: [], looseEnds: { count: 0, rows: [] },
    cards: [], controls: [], notes: [], tabs: ["decisions"], problems: [], copy: "", errors: [], canary: { total: null, at: null },
    views: [],           // the repo's own views, [{name, v}]; theme: the repo's theme.css version or null; ext: its providers' output by name (WO-153/S6)
    theme: null, ext: {},
    hub: false, tab: null, repos: [], repoError: null,   // a hub (WO-153/S7): the repos [{tab, name, ok, error, open, active, ready, waiting, parked, sprints, needs}] in the hub's own state, [{tab, name}] in a repo's; `tab` is the repo this state is of
    pending: [],          // owner actions the orchestrator has not closed yet (WO-153/S5)
    log: [],              // the newest closed ones, newest first: {id, orderId, kind, value, outcome applied|rejected, reason, doneAt}
    held: {}, approved: {},
    conn: "reconnecting", rev: 0, updatedAt: Date.now(),
  };
}

/* The board's state (the `data` of a `state` event, or GET /api/state) as the views' state. The wire shape is S2's: orders with
   `status` open|parked and slices `{id, title, state, dependsOn}`; sprints with an ISO `last`; cards as the board keeps them
   (`status` needs|answered|closed). A key the wire lacks keeps its blank value. */
export function adapt(raw) {
  const out = {};
  for (const k of ["version", "engine", "name", "where", "host", "port", "now", "counts", "orders", "links", "records", "looseEnds",
    "cards", "controls", "notes", "tabs", "problems", "copy", "errors", "canary", "views", "theme", "ext"]) if (raw[k] !== undefined) out[k] = raw[k];
  for (const k of ["hub", "tab", "repos", "repoError"]) if (raw[k] !== undefined) out[k] = raw[k];   // a hub's (WO-153/S7)
  out.resolved = (raw.resolved || []).map((r) => ({ id: r.id, title: r.title, sev: r.sev, released: r.released || "", path: r.path || "" }));
  out.sprints = (raw.sprints || []).map((s) => ({ ...s, at: Date.parse(s.last || s.started || "") || 0 }));
  if (raw.actions) out.pending = raw.actions.map((a) => ({ id: a.id, orderId: a.order, kind: a.kind, value: a.value, ts: Date.parse(a.at) || 0, read: !!a.read, stale: !!a.stale }));
  if (raw.actionsDone) out.log = raw.actionsDone.map((a) => ({ id: a.id, orderId: a.order, kind: a.kind, value: a.value, ts: Date.parse(a.at) || 0, outcome: a.outcome, reason: a.reason || "", doneAt: Date.parse(a.doneAt) || 0 }));
  if (raw.held) out.held = Object.fromEntries(raw.held.map((id) => [id, true]));
  if (raw.approved) out.approved = Object.fromEntries(raw.approved.map((id) => [id, true]));
  return out;
}

const state = blank();
const subs = new Set();
let view = derive(state);
let sig = signatures(view, state);

/* ---- derivation ---------------------------------------------------------------------------------------- */
function derive(st) {
  const orders = new Map();
  const slices = new Map();
  const blocks = new Map(); // id -> ids that wait on it
  const add = (a, b) => { if (!blocks.has(a)) blocks.set(a, []); blocks.get(a).push(b); };

  for (const o of st.orders) {
    const byId = new Map(o.slices.map((s) => [s.id, s]));
    const svms = o.slices.map((s) => {
      const key = `${o.id}/${s.id}`;
      let state_ = s.state;
      if (state_ === "proposed") state_ = s.dependsOn.every((d) => byId.get(d)?.state === "landed") ? "ready" : "waiting";
      const dependsOn = s.dependsOn.map((d) => (d.includes("/") ? d : `${o.id}/${d}`));
      const vm = { key, orderId: o.id, id: s.id, title: s.title, scope: s.scope || "", raw: s.state, state: state_, dependsOn };
      slices.set(key, vm);
      for (const d of dependsOn) add(d, key);
      return vm;
    });
    orders.set(o.id, { o, svms });
  }

  const out = new Map();
  for (const [id, { o, svms }] of orders) {
    const done = svms.filter((s) => s.state === "landed").length;
    const total = svms.length;
    const waitsOn = st.links.filter((l) => l.to === id && orders.has(l.from)).map((l) => l.from);
    for (const w of waitsOn) add(w, id);
    let status;
    if (o.status === "parked") status = "parked";
    else if (st.held[id]) status = "held";
    else if (o.landed || (total && done === total)) status = "awaiting";
    else if (total) {
      if (svms.some((s) => s.state === "in-progress" || s.state === "implemented")) status = "active";
      else if (svms.some((s) => s.state === "ready")) status = "ready";
      else status = "waiting";
    } else status = waitsOn.length ? "waiting" : st.approved[id] === "started" ? "active" : "ready";
    out.set(id, {
      id, title: o.title, short: o.short || o.title, sev: o.sev, hash: o.hash || "", status, parked: o.status === "parked", trigger: o.trigger || null,
      held: !!st.held[id], approved: !!st.approved[id], slices: svms, done, total,
      awaiting: status === "awaiting", waitsOn, evidence: o.evidence, origin: o.origin, path: o.path,
      ledgerPending: o.pending || null, notes: 0,
      pending: st.pending.filter((p) => p.orderId === id).length,
    });
  }
  for (const r of st.resolved) {
    out.set(r.id, { id: r.id, title: r.title, short: r.title, sev: r.sev, status: "landed", resolved: true, released: r.released, parked: false, trigger: null, held: false, approved: false, slices: [], done: 0, total: 0, awaiting: false, waitsOn: [], blocks: [], evidence: "", origin: "", path: r.path, ledgerPending: null, notes: 0, pending: 0 });
  }
  for (const o of out.values()) if (!o.resolved) o.blocks = blocks.get(o.id) || [];
  for (const s of slices.values()) s.blocks = blocks.get(s.key) || [];
  return { orders: out, slices };
}

function signatures(v, st) {
  const m = new Map();
  for (const o of v.orders.values()) m.set("o:" + o.id, JSON.stringify(o));
  for (const s of v.slices.values()) m.set("s:" + s.key, JSON.stringify(s));
  for (const s of st.sprints) m.set("p:" + s.id, JSON.stringify(s));
  for (const c of st.cards) m.set("c:" + c.id, JSON.stringify(c));
  for (const c of st.controls) m.set("k:" + c.id, JSON.stringify(c));   // a sprint's Stop card: a control, not one of the owner's cards
  for (const r of st.records) m.set("r:" + r.slug, JSON.stringify(r));
  m.set("tabs", JSON.stringify(st.tabs));
  m.set("views", JSON.stringify([st.views, st.theme]));
  for (const [k, v] of Object.entries(st.ext)) m.set("x:" + k, JSON.stringify(v));   // `changes.has("x:<provider>")`
  m.set("problems", JSON.stringify([st.problems, st.errors]));
  m.set("looseEnds", JSON.stringify(st.looseEnds));
  m.set("canary", JSON.stringify(st.canary));
  m.set("hub", JSON.stringify([st.hub, st.tab, st.repos, st.repoError]));
  m.set("conn", st.conn);
  m.set("pending", JSON.stringify([st.pending, st.log]));
  return m;
}

/* ---- the connection ------------------------------------------------------------------------------------ */
let es = null, retry = 0, booted = "", started = null, seen = false;
const tokenMeta = () => document.querySelector('meta[name="board-token"]');
const bootOf = (v) => String(v || "").split(".")[0];

export class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }

/* A hub's repo tab has its own state and stream: `scope` is that tab (null: the board's own). The tab is a query value the board
   checks against its routes; it is never a path. */
let scope = null;
const scoped = (path, sc = scope) => path + (sc ? "?tab=" + encodeURIComponent(sc) : "");

async function getState(sc = scope) {
  const r = await fetch(scoped("/api/state", sc), { cache: "no-store" });
  if (!r.ok) throw new ApiError("state " + r.status, r.status);
  return r.json();
}

/* A restarted server has a new page token: the first state of a new boot fetches the page again and takes its token. */
async function takeToken() {
  try {
    const text = await (await fetch("/", { cache: "no-store" })).text();
    const m = /name="board-token" content="([^"]+)"/.exec(text);
    if (m && tokenMeta()) tokenMeta().setAttribute("content", m[1]);
  } catch { /* the next state tries again */ }
}

function receive(raw, meta, sc = scope) {
  if (sc !== scope) return;                      // a state of the scope the page has left
  const boot = bootOf(raw.version);
  if (booted && boot !== booted) takeToken();
  booted = boot;
  store.update((s) => { Object.assign(s, adapt(raw)); s.conn = "live"; }, { kind: "state", first: !seen, ...meta });
  seen = true;
}

function open() {
  es?.close();
  const mine = es = new EventSource(scoped("/api/events"));
  const sc = scope;
  es.addEventListener("state", (e) => { try { if (es === mine) receive(JSON.parse(e.data), { kind: "live" }, sc); } catch { /* a bad frame is skipped; the next one replaces it */ } });
  es.onopen = () => { retry = 0; setConn("live"); };
  es.onerror = () => {
    setConn("reconnecting");
    if (es !== mine) return;
    if (es.readyState === EventSource.CLOSED) setTimeout(() => { if (es === mine) open(); }, Math.min(15000, 2000 * 2 ** retry++));   // refused (503) or ended: EventSource will not retry by itself
  };
}
function setConn(c) { if (state.conn !== c) store.update((s) => { s.conn = c; }, { kind: "conn" }); }

/* ---- public API ---------------------------------------------------------------------------------------- */
export const store = {
  get state() { return state; },
  get view() { return view; },
  orders() { return [...view.orders.values()].filter((o) => !o.resolved); },
  all() { return [...view.orders.values()]; },
  order(id) { return view.orders.get(String(id).replace(/^WO-/, "")); },
  slice(key) { return view.slices.get(key); },
  openCards() { return state.cards.filter((c) => c.status === "needs"); },
  get scope() { return scope; },
  get token() { return tokenMeta()?.getAttribute("content") || ""; },

  /* Apply a change. `fn` mutates the state; the diff says what moved. Subscribers get (store, changes). */
  update(fn, meta = {}) {
    fn(state);
    state.rev++;
    state.updatedAt = Date.now();
    view = derive(state);
    const next = signatures(view, state);
    const changed = new Set(), added = new Set(), removed = new Set();
    for (const [k, v] of next) { if (!sig.has(k)) added.add(k); else if (sig.get(k) !== v) changed.add(k); }
    for (const k of sig.keys()) if (!next.has(k)) removed.add(k);
    sig = next;
    const changes = { changed, added, removed, meta, has: (k) => changed.has(k) || added.has(k) || removed.has(k) };
    for (const fn_ of [...subs]) { try { fn_(store, changes); } catch (err) { console.error("a view failed to update", err); } }
    return changes;
  },

  subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },

  /* Fetch the state now (after an answer, or a refused one); the stream would bring the same state within a second. */
  async reload() { const sc = scope; receive(await getState(sc), { kind: "reload" }, sc); },

  /* A POST the board accepts: the page token, the JSON body. Throws ApiError with the board's own message. */
  async post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Board-Token": store.token }, body: JSON.stringify(body) });
    if (!r.ok) {
      let m = String(r.status);
      try { m = (await r.json()).error || m; } catch { /* keep the status */ }
      throw new ApiError(m, r.status);
    }
    return r.json();
  },

  /* Start: the first state, then the stream. Resolves when the first state is in (or after the first failure, with the
     indicator on "reconnecting"; the stream keeps trying). */
  start(sc = null) {
    started ||= (async () => {
      scope = sc;
      try { receive(await getState(sc), {}, sc); }
      catch (err) {
        if (sc && err.status === 404) { if (scope === sc) scope = null; try { receive(await getState(null), {}, null); } catch { setConn("reconnecting"); } }   // a tab the board does not route
        else setConn("reconnecting");
      }
      open();
    })();
    return started;
  },

  /* Move to another repo's state (a hub), or back to the board's own (null). The new state is fetched before anything changes, the
     old stream is closed first so nothing of the old repo arrives after, and the first state of the new scope is not a "live" event
     (no toast for the difference between two repos). Resolves to the scope in force: the one asked for, or null when the board
     does not route it. */
  async setScope(sc) {
    if (sc === scope) return scope;
    es?.close(); es = null;
    scope = sc;
    try { receive(await getState(sc), { kind: "scope" }, sc); }
    catch (err) {
      if (sc && err.status === 404) { if (scope === sc) scope = null; try { receive(await getState(null), { kind: "scope" }, null); } catch { setConn("reconnecting"); } }
      else setConn("reconnecting");
    }
    open();
    return scope;
  },
};

/* ---- selectors the views share ------------------------------------------------------------------------- */
export const STATUS_ORDER = ["active", "awaiting", "ready", "waiting", "held", "parked"];
export const SEV_RANK = { critical: -1, high: 0, medium: 1, low: 2, unconfirmed: 3 };
export const SEV_LABEL = { critical: "Critical", high: "High", medium: "Medium", low: "Low", unconfirmed: "Unconfirmed" };
export const SPRINT_LABEL = { running: "Running", closing: "Stopping", gate: "Needs you", stopped: "Stopped", stale: "No driver" };

export function completionText(o) {
  if (!o.total) return "";
  if (o.awaiting) return "slices done, acceptance open";
  return `${o.done}/${o.total} slices`;
}

/* Everything an order waits on, as readable text, for rows and the drawer. */
export function waitsText(o) {
  return o.waitsOn.map((id) => "WO-" + id).join(", ");
}
