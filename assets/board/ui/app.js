/* app.js - the app shell: sidebar, hash routing, the order drawer, the command palette, shortcuts, theme, the connection
   indicator and the toasts for live events. It mounts each view as a custom element; a view is one row of ENGINE. */
import { h, icon, setText, viewTransition, toast, fuzzy, LABELS } from "./ui.js";
import "./graph.js";
import { store } from "./store.js";
import { route, go, openOrder, viewHash, hashOf } from "./shared.js";
import { createOrderPanel } from "./drawer.js";
import { actionLabel, orderActionItems } from "./actions.js";

/* ---------------------------------------------------------------- route table
   `tabs: true` expands into one sidebar item per card tab of the board (board.json `tabs`). The repo's own views (below) join it. */
const openCount = () => store.orders().length;
const ENGINE = [
  { path: "work/list", tag: "gb-view-list", load: () => import("./views/work-list.js"), label: "List", icon: "list", group: "Work", crumb: ["Work", "List"], key: "l", count: openCount },
  { path: "work/board", tag: "gb-view-board", load: () => import("./views/work-board.js"), label: "Board", icon: "board", group: "Work", crumb: ["Work", "Board"], key: "b" },
  { path: "work/graph", tag: "gb-view-graph", load: () => import("./views/work-graph.js"), label: "Graph", icon: "graph", group: "Work", crumb: ["Work", "Graph"], key: "g" },
  { path: "sprints", tag: "gb-view-sprints", load: () => import("./views/sprints.js"), label: "Sprints", icon: "sprint", crumb: ["Sprints"], key: "s", count: () => store.state.sprints.filter((s) => s.state === "running" || s.state === "closing").length },
  { path: "decisions", tag: "gb-view-decisions", load: () => import("./views/decisions.js"), label: "Decisions", icon: "decision", crumb: ["Decisions"], key: "d", tabs: true },
  { path: "loose-ends", tag: "gb-view-loose-ends", load: () => import("./views/loose-ends.js"), label: "Loose ends", icon: "inbox", crumb: ["Loose ends"], key: "e", count: () => store.state.looseEnds.count },
];

/* A hub (WO-153/S7) adds the `all` view: one row per repo, counts only. Each repo is a scope (#/r/<tab>/...): the same views over that
   repo's own state, which the board builds from that repo's home alone. */
const HUBDEF = { path: "all", tag: "gb-view-hub", load: () => import("./views/hub-all.js"), label: "All repos", icon: "layers", crumb: ["Hub", "All repos"], key: "a" };
const TAB = /^[a-z][a-z0-9-]{0,23}$/;
const defs = new Map(ENGINE.map((d) => [d.path, d]));
const $ = (id) => document.getElementById(id);
const main = $("main"), viewEl = $("view"), drawer = $("drawer"), palette = $("palette"), conn = $("conn");
const BASE_TITLE = document.title;
const label = (t) => t.charAt(0).toUpperCase() + t.slice(1);

/* ---------------------------------------------------------------- the repo's own views (WO-153/S6)
   <board dir>/views/<name>.js is an ES module that exports `meta` {title, icon, position} and registers the custom element
   gb-repo-<name>. It imports only /ui/ui.js, /ui/store.js and (to ask for an owner action) /ui/actions.js. A view asks for an
   action only through `requestAction` of /ui/actions.js (the board's own confirm decides) and never posts an answer or an action
   itself: the store's `post` is reachable by any same-origin code, so the contract forbids that use, the kit does not prevent it. The board lists the folder (state.views) and serves each file from 'self'. A view that fails to load,
   does not register its element or throws while it starts is an error panel in its place; the shell keeps working. It is repo
   code running in this page, trusted like the repo's providers. A module is imported once per page load: a changed file is
   announced and used after a reload. */
const REPO_NAME = /^[a-z0-9-]{1,32}$/;
const repo = new Map();   // name -> { v, tag, meta, error, told, promise }
function loadRepoView(name, v) {
  let r = repo.get(name);
  if (r) {
    if (r.v !== v && !r.told) { r.told = true; toast({ title: `views/${name}.js changed`, body: "Reload the page to use the new version.", kind: "info", icon: "file", life: 6000 }); }
    return r.promise;
  }
  r = { v, tag: "gb-repo-" + name, meta: { title: label(name), icon: "layers", position: 100 }, error: null, told: false };
  r.promise = import("/views/" + name + ".js").then((m) => {
    const x = m && typeof m.meta === "object" && m.meta ? m.meta : {};
    r.meta = { title: typeof x.title === "string" && x.title.trim() ? x.title.trim().slice(0, 40) : r.meta.title, icon: typeof x.icon === "string" && /^[a-z0-9-]{1,24}$/.test(x.icon) ? x.icon : "layers", position: Number.isFinite(x.position) ? x.position : 100 };
    if (!customElements.get(r.tag)) throw new Error(`it did not register the element <${r.tag}>`);
  }).catch((err) => { r.error = String(err?.message || err); r.meta.icon = "alert"; });
  repo.set(name, r);
  return r.promise;
}
const repoViews = () => store.state.views.filter((v) => REPO_NAME.test(v.name) && repo.has(v.name));
function repoDef(name) {
  const r = repo.get(name), v = store.state.views.find((x) => x.name === name);
  const title = r ? r.meta.title : label(name);
  return { path: "repo/" + name, repo: name, tag: "gb-repo-" + name, label: title, icon: r ? r.meta.icon : "layers", group: "This repo", crumb: ["This repo", title], load: () => loadRepoView(name, v.v) };
}
function viewError(name, message) {
  return h("div", { class: "page" }, h("div", { class: "page-body" }, h("gb-empty", { icon: "alert", title: `The view "${name}" could not run`, desc: `${message}. Fix views/${name}.js in the board folder and reload the page.` })));
}
/* An error a repo view throws on its own (while it starts, or later from a timer or an event) shows as the error panel. */
addEventListener("error", (e) => {
  if (!mounted?.repo || !e.filename) return;
  let file = ""; try { file = new URL(e.filename, location.href).pathname; } catch { /* not a URL */ }
  if (file === `/views/${mounted.repo}.js`) { const el = viewError(mounted.repo, e.message || "it threw an error"); viewEl.replaceChildren(el); mounted.el = el; }
});

/* The view a path names: an engine view, or one of the repo's own (`repo/<name>`) the board lists. */
function defFor(path) {
  if (defs.has(path)) return defs.get(path);
  if (path === HUBDEF.path) return store.state.hub ? HUBDEF : null;
  const m = /^repo\/([a-z0-9-]{1,32})$/.exec(path);
  return m && store.state.views.some((v) => v.name === m[1]) ? repoDef(m[1]) : null;
}

/* The repo's own look: views/theme.css, loaded after the engine's styles (its `theme` layer wins). It follows the file. */
function syncTheme() {
  const t = store.state.theme;
  const link = document.getElementById("repo-theme");
  if (!t) { link?.remove(); return; }
  const href = "/views/theme.css?v=" + encodeURIComponent(t);
  if (!link) document.head.append(h("link", { id: "repo-theme", rel: "stylesheet", href }));
  else if (link.getAttribute("href") !== href) link.setAttribute("href", href);
}

/* A view file that appeared: load it for its title and icon, then list it. */
function syncViews() {
  for (const v of store.state.views) if (REPO_NAME.test(v.name)) { const fresh = !repo.has(v.name); loadRepoView(v.name, v.v).then(() => { if (fresh) syncCounts(); }); }
  syncTheme();
}

/* ---------------------------------------------------------------- theme */
const theme = () => document.documentElement.dataset.theme;
function setTheme(t) {
  const apply = () => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("gb-theme", t); } catch { /* private mode: the choice lasts until the tab closes */ }
    const b = $("theme-btn"); b.replaceChildren(icon(t === "dark" ? "sun" : "moon", "ic-md")); b.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme");
  };
  document.documentElement.classList.add("theme-switching");
  const vt = viewTransition(apply);
  (vt ? vt.finished : Promise.resolve()).finally(() => document.documentElement.classList.remove("theme-switching"));
  if (!vt) document.documentElement.classList.remove("theme-switching");
}
const toggleTheme = () => setTheme(theme() === "dark" ? "light" : "dark");

/* ---------------------------------------------------------------- static chrome */
$("menu-btn").append(icon("menu", "ic-md"));
$("palette-btn").append(icon("search"), h("span", null, "Search or jump to"), h("span", { class: "keys" }, h("kbd", null, /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"), h("kbd", null, "K")));
$("theme-btn").append(icon(theme() === "dark" ? "sun" : "moon", "ic-md"));
$("theme-btn").setAttribute("aria-label", theme() === "dark" ? "Switch to light theme" : "Switch to dark theme");
$("theme-btn").addEventListener("click", toggleTheme);
$("palette-btn").addEventListener("click", () => palette.open());
$("skip").addEventListener("click", () => main.focus());
$("menu-btn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
$("scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));

/* ---------------------------------------------------------------- sidebar */
const needs = (tab) => store.state.cards.filter((c) => c.tab === tab && c.status === "needs").length;

/* What the sidebar lists now: each engine view (a `tabs` view once per card tab), then the repo's own views. `id` is stable, so a count updates in place and the list is rebuilt only when it changes. */
function navItems() {
  const st = store.state, items = [];
  const extra = [];
  if (st.hub) {   // where the page is: all repos, the hub's own home, or one repo (each switch is an address of its own)
    items.push({ id: "hub:all", abs: true, scope: null, path: "all", label: "All repos", icon: "layers", group: "Repos", count: () => store.state.repos.length, key: "" });
    items.push({ id: "hub:own", abs: true, scope: null, path: "work/list", label: "This hub", icon: "home", group: "Repos", count: null, key: "" });
    for (const r of st.repos) if (TAB.test(r.tab)) items.push({ id: "hub:" + r.tab, abs: true, scope: r.tab, path: "work/list", label: r.name || r.tab, icon: "folder", group: "Repos", count: null, key: "" });
  }
  for (const d of ENGINE) {
    if (d.tabs) st.tabs.forEach((t, i) => (i ? extra : items).push({ id: `${d.path}:${t}`, path: d.path, query: i ? "tab=" + t : "", tab: t, label: i ? label(t) : d.label, icon: d.icon, group: i ? "Cards" : undefined, count: () => needs(t), hot: true, key: i ? "" : d.key }));
    else items.push({ id: d.path, path: d.path, query: "", label: d.label, icon: d.icon, group: d.group, count: d.count, key: d.key });
  }
  items.push(...extra);
  repoViews().map((v) => ({ v, r: repo.get(v.name) })).sort((a, b) => a.r.meta.position - b.r.meta.position || a.v.name.localeCompare(b.v.name))
    .forEach(({ v, r }) => items.push({ id: "repo:" + v.name, path: "repo/" + v.name, query: "", label: r.meta.title, icon: r.meta.icon, group: "This repo", count: null }));
  return items;
}
let items = [], itemsSig = "";
const counts = new Map();
function buildNav() {
  items = navItems();
  const sig = JSON.stringify([route.scope, items.map((i) => [i.id, i.label, i.path, i.query])]);
  if (sig === itemsSig) return;
  itemsSig = sig; counts.clear();
  const nav = $("nav"); nav.textContent = "";
  let group = null;
  for (const it of items) {
    if (it.group !== group) {
      if (group && !it.group) nav.append(h("div", { class: "nav-sep" }));
      group = it.group; if (group) nav.append(h("div", { class: "nav-label" }, group));
    }
    const a = h("a", { class: "nav-item", href: hashOf(it.path + (it.query ? "?" + it.query : ""), it.abs ? it.scope : route.scope), dataset: { id: it.id } }, icon(it.icon), h("span", null, it.label));
    if (it.count) { const c = h("span", { class: "count" }, "0"); a.append(c); counts.set(it.id, { el: c, last: null }); }
    nav.append(a);
  }
  syncNav();
}
function syncCounts() {
  buildNav();
  for (const it of items) {
    const c = counts.get(it.id); if (!c) continue;
    const v = it.count();
    setText(c.el, v); c.el.toggleAttribute("data-zero", v === 0);
    c.el.classList.toggle("hot", !!it.hot && v > 0);
    if (c.last != null && c.last !== v) { c.el.classList.remove("bump"); void c.el.offsetWidth; c.el.classList.add("bump"); }
    c.last = v;
  }
}
function isCurrent(it) {
  if (it.abs) return it.id === "hub:all" ? route.view === "all" : it.id === "hub:own" ? !route.scope && route.view !== "all" : route.scope === it.scope;
  if (it.path !== route.view) return false;
  if (!it.tab) return true;
  const t = new URLSearchParams(route.query).get("tab") || store.state.tabs[0];
  return t === it.tab;
}
function syncNav() {
  for (const a of $("nav").querySelectorAll(".nav-item")) {
    const it = items.find((i) => i.id === a.dataset.id);
    if (it && isCurrent(it)) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  const d = defFor(route.view);
  const cur = items.find((i) => !i.abs && isCurrent(i));
  const repoName = route.scope ? store.state.repos.find((r) => r.tab === route.scope)?.name || route.scope : "";
  const parts = [...(repoName ? [repoName] : []), ...(d ? (cur?.tab ? ["Cards", cur.label] : d.crumb) : ["Board"])];
  $("crumbs").replaceChildren(h("span", { class: "dim" }, "gitos"), icon("right"), ...parts.flatMap((p, i) => [...(i ? [icon("right")] : []), h("span", { class: i === parts.length - 1 ? "cur" : "dim" }, p)]));
  document.title = `${cur ? cur.label : d ? d.label : "Board"}${repoName ? " · " + repoName : ""} · ${BASE_TITLE}`;
}

/* The foot of the sidebar: whose board this is, the engine version and the canary's last answer. */
function syncFoot() {
  const st = store.state, c = st.canary || {};
  const canary = st.tab ? "" : c.total == null ? "Canary: not run yet" : c.total === 0 ? "Canary: clean" : `Canary: ${c.total} finding${c.total === 1 ? "" : "s"}`;
  const lines = [st.name || "", st.host ? `${st.where} · ${st.host}:${st.port}` : "", [st.engine ? `Engine ${st.engine}` : "", canary].filter(Boolean).join(" · ")];
  if (st.errors.length) lines.push(`${st.errors.length} read error${st.errors.length === 1 ? "" : "s"}: ${st.errors[0].section}`);
  const foot = $("side-foot");
  const sig = lines.join("\n");
  if (foot.dataset.sig === sig) return;
  foot.dataset.sig = sig;
  foot.replaceChildren(...lines.filter(Boolean).map((l, i) => h("span", { class: i === 0 ? "mock" : "", title: st.errors.map((e) => `${e.section}${e.ref ? " " + e.ref : ""}: ${e.error}`).join("\n") }, l)));
}

/* ---------------------------------------------------------------- routing */
let mounted = null, drawerDepth = 0, drawerBase = "", panel = null, panelId = null, panelUnsub = null, panelTick = null;
const DEFAULT = "work/list", CARDS = "decisions";

/* The repo a hash is in (`#/r/<tab>/...`): the tab, or null. The first state is fetched for it before the page knows which tabs exist. */
const hashScope = () => { const m = /^#\/r\/([a-z][a-z0-9-]{0,23})(?:[/?]|$)/.exec(location.hash || ""); return m ? m[1] : null; };

function parseHash() {
  let raw = (location.hash || "").replace(/^#/, "");
  const st = store.state;
  let scope = null, fix = false;
  const sm = /^\/r\/([a-z][a-z0-9-]{0,23})(?=[/?]|$)/.exec(raw);
  if (sm) { if (st.hub && st.repos.some((r) => r.tab === sm[1])) { scope = sm[1]; raw = raw.slice(sm[0].length); } else { raw = ""; fix = true; } }   // a tab the hub does not route: back to the hub's own address
  const dflt = st.hub && !scope ? "all" : DEFAULT;
  // the old address `#<tab>` for a card tab
  if (raw && !raw.startsWith("/") && st.tabs.includes(raw)) return { kind: "view", path: CARDS, query: raw === st.tabs[0] ? "" : "tab=" + raw, fix: true, scope };
  const [pth, qs = ""] = (raw || "/" + dflt).split("?");
  const parts = pth.split("/").filter(Boolean);
  if (parts[0] === "order" && parts[1]) return { kind: "order", id: parts[1].replace(/^WO-/i, ""), scope, fix };
  const path = parts.join("/");
  return defFor(path) ? { kind: "view", path, query: qs, scope, fix } : { kind: "view", path: dflt, query: "", fix: true, scope };
}

async function mountView(path, animate) {
  const def = defFor(path);
  await def.load();
  let el;
  const bad = def.repo ? repo.get(def.repo).error : null;
  try { el = bad ? viewError(def.repo, bad) : document.createElement(def.tag); } catch (err) { el = viewError(def.repo, String(err?.message || err)); }
  const swap = () => { mounted = { path, el, repo: def.repo }; viewEl.replaceChildren(el); main.scrollTop = 0; syncNav(); };   // `mounted` first: a view that throws as it connects is caught as this one
  if (animate) viewTransition(swap); else swap();
}

async function onRoute(first) {
  let r = parseHash();
  if (r.scope !== store.scope) {   // another repo of the hub (or back to the board's own): its own state and stream
    await store.setScope(r.scope);
    r = parseHash();
    if (r.scope !== store.scope) { r.scope = store.scope; r.fix = true; }
  }
  if (r.kind === "order") {
    route.scope = r.scope;
    if (r.fix) history.replaceState(null, "", hashOf("order/" + r.id));
    drawerDepth = first ? 0 : drawerDepth + 1;
    if (!route.drawer) drawerBase = route.query;
    route.drawer = r.id;
    if (!mounted) { route.view = route.view || DEFAULT; await mountView(route.view, false); syncNav(); }
    showOrder(r.id);
    return;
  }
  const sameScope = route.scope === r.scope;
  route.scope = r.scope;
  const wasDrawer = !!route.drawer, was = route.query, sameView = !!mounted && mounted.path === r.path && sameScope;
  drawerDepth = 0; route.drawer = null;
  // An address that names the view on screen with other filters (a link, the back button, Show in graph) remounts it, so the view
  // reads them. Returning from a drawer to the address it opened over does not: the view's own filters are newer than that address.
  const moved = sameView && r.query !== (wasDrawer ? drawerBase : was);
  route.view = r.path; route.query = !sameView || moved ? r.query : was;
  if (r.fix || (sameView && !moved && r.query !== was)) history.replaceState(null, "", viewHash());
  if (drawer.isOpen) hideOrder();
  if (!sameView || moved) await mountView(r.path, !first && !sameView);
  else syncNav();
  document.body.classList.remove("nav-open");
}

function showOrder(id) {
  const o = store.order(id);
  if (panelId !== id || !panel) {
    panelUnsub?.(); clearInterval(panelTick);
    if (!o) { drawer.body.replaceChildren(h("div", { class: "od-body" }, h("gb-empty", { icon: "search", title: `No order WO-${id}`, desc: "The ledger has no open or parked order with that number." }, h("button", { class: "btn sm", type: "button", onclick: () => closeDrawer() }, "Close")))); panel = null; panelId = null; }
    else {
      panel = createOrderPanel(id, { onClose: () => closeDrawer() }); panelId = id;
      drawer.body.replaceChildren(panel.el); drawer.body.scrollTop = 0;
      panelUnsub = store.subscribe(() => panel?.patch());
    }
  }
  drawer.open(o ? `Order WO-${id}` : "Order not found");
}
function cleanupPanel() { panelUnsub?.(); clearInterval(panelTick); panel = null; panelId = null; }
function hideOrder() { drawer.close(false); cleanupPanel(); }
/* The operator closed the drawer (button, Esc, backdrop): step back through the history entries it added. */
function leaveOrder() {
  if (drawerDepth > 0) history.go(-drawerDepth);
  else { history.replaceState(null, "", viewHash()); route.drawer = null; cleanupPanel(); }
}
const closeDrawer = () => { if (drawer.isOpen) drawer.close(true); };
drawer.addEventListener("close", (e) => { if (e.detail.user) leaveOrder(); });
addEventListener("hashchange", () => onRoute(false));
viewEl.addEventListener("open-order", (e) => { if (!e.defaultPrevented) openOrder(e.detail); });   // an order card in any view, a repo's included

/* ---------------------------------------------------------------- live chrome: connection indicator, counts, toasts */
function syncConn() {
  const st = store.state;
  conn.setAttribute("state", st.conn);
  conn.age("");
  conn.title = st.conn === "live" ? "Connected. Changes appear as they happen." : "The board is not answering. This page reconnects by itself.";
}

/* A toast for what the owner would want to know without watching: a slice landed, a sprint stopped or started, a card arrived.
   Compared against the last state shown, so the first state and a reconnect that changed nothing are quiet. */
let seen = null;
function snapshotOf(st) {
  const slices = new Map();
  for (const o of st.orders) for (const s of o.slices) slices.set(`${o.id}/${s.id}`, s.state);
  return { slices, sprints: new Map(st.sprints.map((s) => [s.id, s.state])), cards: new Set(st.cards.filter((c) => c.status === "needs").map((c) => c.id)), actions: new Set(st.pending.map((p) => p.id)) };
}
function liveToasts() {
  const st = store.state, now = snapshotOf(st), was = seen;
  seen = now;
  if (!was) return;
  const out = [];
  // an owner action the orchestrator closed: applied, or why not (first, so the three-toast limit never hides it)
  for (const d of st.log) if (was.actions.has(d.id) && !now.actions.has(d.id)) {
    const what = `${actionLabel(d)} on WO-${d.orderId}`;
    out.push(d.outcome === "rejected" ? { title: `Not applied: ${what}`, body: d.reason || "The orchestrator rejected it.", kind: "warn", icon: "alert" } : { title: `Applied: ${what}`, body: "The ledger now reflects it.", kind: "action", icon: "checkc" });
  }
  for (const [k, v] of now.slices) if (v === "landed" && was.slices.has(k) && was.slices.get(k) !== "landed") out.push({ title: `WO-${k.split("/")[0]} ${k.split("/")[1]} landed`, body: store.slice(k)?.title, kind: "landed", icon: "checkc" });
  for (const s of st.sprints) {
    const before = was.sprints.get(s.id), name = s.name || "The sprint";
    if (before === undefined && s.state === "running") out.push({ title: `${name} started`, kind: "sprint", icon: "sprint" });
    else if (before !== undefined && before !== s.state && (s.state === "stopped" || s.state === "closing")) out.push({ title: s.state === "closing" ? `${name} is stopping` : `${name} stopped`, body: s.message || undefined, kind: "sprint", icon: "sprint" });
  }
  for (const c of st.cards) if (c.status === "needs" && !was.cards.has(c.id)) out.push({ title: "A card needs you", body: c.title, kind: "card", icon: "decision", action: { label: "Open", onClick: () => go(`decisions${c.tab !== st.tabs[0] ? "?tab=" + c.tab : ""}`) } });
  for (const t of out.slice(0, 3)) toast(t);
  if (out.length > 3) toast({ title: `${out.length - 3} more changes`, kind: "info", icon: "bell", life: 3500 });
}

store.subscribe((s, ch) => {
  syncViews(); syncConn(); syncCounts(); syncFoot();
  if (ch.meta.kind === "state" || ch.meta.kind === "reload" || ch.meta.kind === "live") liveToasts();   // "live" is what the stream sends
  if (!ch.meta.kind || ch.meta.kind === "conn") return;
  // a repo view or tab that appeared or went away: the view on screen may no longer exist
  if (ch.meta.kind === "scope") seen = snapshotOf(store.state);   // the first state of another repo is not news
  if (mounted && !defFor(mounted.path)) go(store.state.hub && !route.scope ? "all" : DEFAULT);
});

/* ---------------------------------------------------------------- command palette */
const nameOf = (o) => `WO-${o.id}  ${o.title}`;
palette.source = (q) => {
  const score = (it) => { const hay = [it.label, it.sub, it.kw].filter(Boolean).join(" "); const f = fuzzy(q, hay); if (!f.score) return null; const lf = fuzzy(q, it.label); return { ...it, s: f.score, ranges: lf.score ? lf.ranges : null }; };
  const pick = (list) => list.map(score).filter(Boolean).sort((a, b) => (q ? b.s - a.s : 0));
  const views = items.map((it) => ({ label: it.label, sub: it.tab ? "Cards" : it.group || "", icon: it.icon, hint: it.key ? "g " + it.key : "", kw: "go open view", run: () => go(it.path + (it.query ? "?" + it.query : ""), it.abs ? it.scope : undefined) }));
  const orders = store.orders().map((o) => ({ label: nameOf(o), sub: LABELS[o.status], icon: "file", kw: o.sev + " " + (o.evidence || ""), run: () => openOrder(o.id) }));
  const cur = route.drawer ? store.order(route.drawer) : null;
  const acts = [
    ...orderActionItems(cur).filter((a) => !a.sep).map((a) => ({ label: `${a.label} on WO-${cur.id}`, icon: a.icon, kw: "owner action request", run: a.run })),
    { label: theme() === "dark" ? "Switch to light theme" : "Switch to dark theme", icon: theme() === "dark" ? "sun" : "moon", hint: "t", kw: "dark light mode appearance", run: toggleTheme },
    { label: "Keyboard shortcuts", icon: "keyboard", hint: "?", kw: "help keys", run: showShortcuts }];
  const groups = [{ group: "Go to", items: pick(views) }, { group: "Orders", items: pick(orders).slice(0, q ? 8 : 7) }, { group: "Actions", items: pick(acts).slice(0, q ? 10 : 8) }];
  if (q) groups.sort((x, y) => (y.items[0]?.s || 0) - (x.items[0]?.s || 0));   // the best match leads, whatever its group
  return groups;
};

/* ---------------------------------------------------------------- shortcuts */
function showShortcuts() {
  const row = (keys, text) => [h("dt", null, ...keys.map((k) => h("kbd", null, k))), h("dd", null, text)];
  const dlg = h("dialog", { class: "dlg", "aria-label": "Keyboard shortcuts" },
    h("div", { class: "dlg-head" }, h("h2", null, "Keyboard shortcuts"), h("p", null, "Press ? any time to see this.")),
    h("div", { class: "dlg-body" }, h("dl", { class: "kb-grid" },
      ...row(["Ctrl", "K"], "Command palette"), ...row(["/"], "Focus the search box, where a view has one"), ...ENGINE.filter((d) => d.key).flatMap((d) => row(["g", d.key], `Go to ${d.label.toLowerCase()}`)),
      ...(store.state.hub ? row(["g", "a"], "Go to all repos") : []), ...row(["t"], "Toggle light and dark"), ...row(["Esc"], "Close the drawer, palette or dialog"))),
    h("div", { class: "dlg-foot" }, h("button", { class: "btn primary", type: "button", onclick: () => dlg.close() }, "Done")));
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg); dlg.showModal();
}
let gPending = 0;
addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.hasAttribute("open") ? palette.close() : palette.open(); return; }
  if (e.key === "Escape" && document.body.classList.contains("nav-open")) { document.body.classList.remove("nav-open"); return; }
  if (e.key === "Escape" && drawer.isOpen && !e.defaultPrevented && !palette.hasAttribute("open") && !document.querySelector("dialog[open]")) { drawer.close(true); return; }
  const t = e.target; if (t.closest?.("input,textarea,select,[contenteditable],dialog,gb-palette") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "/") { const s = document.getElementById("work-search"); if (s) { e.preventDefault(); s.focus(); s.select?.(); } return; }
  if (e.key === "?") { e.preventDefault(); showShortcuts(); return; }
  if (e.key === "t") { toggleTheme(); return; }
  if (gPending && Date.now() - gPending < 900) {
    gPending = 0; const k = e.key.toLowerCase();
    if (k === HUBDEF.key && store.state.hub) { e.preventDefault(); go("all", null); return; }
    const d = ENGINE.find((x) => x.key === k); if (d) { e.preventDefault(); go(d.path); } return;
  }
  if (e.key === "g") gPending = Date.now();
});

/* ---------------------------------------------------------------- boot */
async function boot() {
  syncConn();
  // first paint: a skeleton while the first state arrives
  const skel = h("div", { class: "page" }, h("div", { class: "page-head" }, h("gb-skeleton", { lines: 2, class: "sk-title" })),
    h("div", { class: "page-body" }, h("div", { class: "panel pad" }, h("gb-skeleton", { lines: 5 })), h("div", { class: "panel pad" }, h("gb-skeleton", { lines: 4 }))));
  viewEl.replaceChildren(skel);
  await store.start(hashScope());
  await Promise.all(store.state.views.filter((v) => REPO_NAME.test(v.name)).map((v) => loadRepoView(v.name, v.v)));   // their titles and icons, so the sidebar lists them and a deep link finds them
  syncTheme();
  seen = snapshotOf(store.state);
  buildNav(); syncCounts(); syncFoot(); syncConn();
  await onRoute(true);
}
boot();
