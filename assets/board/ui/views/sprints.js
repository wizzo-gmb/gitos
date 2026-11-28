/* Sprints: one list, a row per sprint, live. A row is built once and patched in place: state, name, the order in hand, orders done,
   time since its last activity and Stop; it opens in place to its orders (keyed rows) and recent activity, and more than one may be
   open. Running and closing sprints come first, then "Not running": no driver, then stopped, so the two do not interleave. A row opens by default the first time a
   running sprint appears; after that the operator's choice stands for the page's life (`opened`). Stop is the one place to stop a
   sprint: it answers the sprint's own Stop card (a control the board keeps out of the owner's cards) through the board's answer
   route (see shared.js). */
import { h, icon, setText, setAttr, reconcile, relTime, flash } from "../ui.js";
import { store } from "../store.js";
import { pageHead, openOrder, stopSprint, stopCardOf, stopRequested } from "../shared.js";

const STATE_NOTE = {
  running: "Working through its orders, one merge and one gate at a time.",
  closing: "Stop requested. It finishes the order in hand, then ends.",
  stopped: "Its remaining orders stay in the ledger.",
  stale: "Its log says running, but no driver is alive. It may have crashed or been closed.",
};
const isLive = (s) => s.state === "running" || s.state === "closing";
const ORDER_ID = /\d+/;
const orderOf = (ref) => (ref && ORDER_ID.exec(ref) ? ORDER_ID.exec(ref)[0].padStart(3, "0") : "");
const refText = (ref) => (/^WO-?/i.test(ref) ? ref.replace(/^WO-?/i, "WO-").replace("/", " ") : ref);
const clock = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso ?? "") : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); };

/* sprint id -> whether its row is open. Set when a sprint is first seen (open if it is running), then only by the operator. */
const opened = new Map();
let uid = 0;

function setOpen(el, on) {
  const r = el.refs;
  setAttr(el, "data-open", on ? "1" : null);
  setAttr(r.toggle, "aria-expanded", String(on));
  r.body.hidden = !on;
}

function makeSprint() {
  const r = {}, bid = "sp-body-" + ++uid;
  r.name = h("span", { class: "sp-name" });
  r.toggle = h("button", { class: "sp-toggle", type: "button", "aria-controls": bid, "aria-expanded": "false" }, r.name);
  r.toggle.addEventListener("click", () => { const on = !opened.get(r.id); opened.set(r.id, on); setOpen(el, on); });
  r.chev = icon("right", "sp-chev");
  r.state = h("gb-badge");
  r.cur = h("span", { class: "sp-now" }); r.prog = h("span", { class: "sp-prog" }); r.when = h("span", { class: "sp-when" });
  r.stop = h("button", { class: "btn danger sm", type: "button" }, icon("stop"), h("span", null, "Stop"));
  r.stop.addEventListener("click", () => { const sp = store.state.sprints.find((s) => s.id === r.id); if (sp) stopSprint(sp); });
  r.note = h("p", { class: "sp-note" });
  r.orders = h("ol", { class: "sp-orders", "aria-label": "Orders in this sprint" });
  r.noOrders = h("p", { class: "sp-none" }, "No order yet.");
  r.started = h("span"); r.last = h("span", { class: "last" });
  r.recent = h("ol", { class: "sp-recent", "aria-label": "Recent activity" });
  r.more = h("div", { class: "sp-activity" }, h("h3", { class: "sp-sub" }, "Recent activity"), r.recent);
  r.body = h("div", { class: "sp-body", id: bid, hidden: true }, r.note, r.orders, r.noOrders, h("div", { class: "sp-meta" }, r.started, r.last), r.more);
  const el = h("article", { class: "sprint" },
    h("div", { class: "sp-row" }, r.chev, r.toggle, r.state, h("span", { class: "sp-sub-line" }, r.cur, r.prog, r.when), r.stop), r.body);
  el.refs = r;
  return el;
}

function patchSprint(el, sp) {
  const r = el.refs; r.id = sp.id; r.at = sp.at;
  setText(r.name, sp.exclusive ? "Exclusive sprint" : sp.name);
  const card = stopCardOf(sp), asked = stopRequested(sp);
  const stopping = sp.state === "closing" || (asked && sp.state === "running");
  setAttr(r.state, "state", stopping ? "closing" : sp.state);
  el.dataset.state = sp.state;
  el.dataset.live = isLive(sp) ? "1" : "";
  const note = stopping ? `Stopping after ${orderOf(sp.current) ? "WO-" + orderOf(sp.current) : "the order in hand"}. Its remaining orders stay in the ledger.` : STATE_NOTE[sp.state] || "";
  setText(r.note, note);
  r.state.title = isLive(sp) ? "" : STATE_NOTE[sp.state] || "";
  // Stop is offered while the sprint runs and its Stop card is open and unanswered
  r.stop.hidden = sp.state === "stopped" || sp.state === "stale";
  r.stop.disabled = !card || !!card.answer || sp.state === "closing" || asked;
  setText(r.stop.lastChild, sp.state === "closing" ? "Stopping" : asked ? "Stop requested" : "Stop");
  r.stop.title = !r.stop.disabled ? "" : !card ? "This sprint has no open Stop card to answer." : sp.state === "closing" || asked ? "Already stopping: it ends after the order in hand." : "This sprint's Stop card is already answered.";

  const cur = orderOf(sp.current);
  const rows = sp.orders.map((id) => ({ id, o: store.order(id), cur: cur === id && sp.state !== "stopped" && sp.state !== "stale", sp }));
  const done = rows.filter((x) => x.o?.resolved).length;
  setText(r.cur, sp.current ? (isLive(sp) ? "Now: " : "Last: ") + refText(sp.current) : "");
  setText(r.prog, rows.length ? `${done} of ${rows.length} order${rows.length === 1 ? "" : "s"}` : "No orders");
  reconcile(r.orders, rows, {
    move: false, key: (x) => x.id,
    create: (x) => {
      const strip = h("gb-strip"), pill = h("gb-badge");
      const li = h("li", { class: "sp-order", tabindex: 0, role: "button" }, h("span", { class: "dotline" }), h("span", { class: "oid" }), h("span", { class: "sp-otitle" }), pill, strip);
      li.addEventListener("click", () => openOrder(x.id));
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openOrder(x.id); } });
      li.refs = { strip, pill, id: li.querySelector(".oid"), t: li.querySelector(".sp-otitle") };
      return li;
    },
    update: (li, x) => {
      const { o } = x, f = li.refs;
      setText(f.id, "WO-" + x.id); setText(f.t, o ? o.short : "Not in the ledger's open list"); setAttr(f.t, "title", o ? o.title : null);
      li.dataset.cur = x.cur ? "1" : "";
      f.strip.hidden = !(o && o.total); if (o && o.total) f.strip.set(o.slices.map((s) => s.state), `${o.done}/${o.total}`, `${o.done} of ${o.total} slices landed`);
      f.pill.hidden = !o;
      if (o) { setAttr(f.pill, "state", x.cur ? "active" : o.status); if (x.cur) f.pill.setAttribute("label", "Working"); else f.pill.removeAttribute("label"); f.pill.render?.(); }
    },
  });
  r.noOrders.hidden = rows.length > 0;
  setText(r.started, sp.started ? "Started " + clock(sp.started) : "");
  const rsig = JSON.stringify(sp.recent);
  if (r.recent.dataset.sig !== rsig) {
    r.recent.dataset.sig = rsig;
    r.recent.replaceChildren(...[...sp.recent].reverse().map((x) => h("li", null, h("span", { class: "rt" }, clock(x.t)), h("span", { class: "rk" }, x.kind), h("span", { class: "rm" }, [x.ref, x.msg].filter(Boolean).join(" ")))));
  }
  r.more.hidden = !sp.recent.length;
  if (!opened.has(sp.id)) opened.set(sp.id, isLive(sp));
  setOpen(el, opened.get(sp.id));
}

const lastOf = (at, message) => (at ? "Last activity " + relTime(Date.now() - at) : "No activity") + (message ? ": " + message : "");

class ViewSprints extends HTMLElement {
  connectedCallback() {
    this.className = "page";
    this.head = pageHead({ title: "Sprints" });
    this.list = h("div", { class: "sp-list" });
    this.none = h("p", { class: "sp-none" }, "No sprint is running.");
    this.idleN = h("span", { class: "n" });
    this.idle = h("div", { class: "sp-list" });
    this.idleSec = h("section", { class: "sp-idle-sec", "aria-label": "Sprints that are not running" }, h("h2", null, "Not running ", this.idleN), this.idle);
    this.empty = h("gb-empty", { icon: "sprint", title: "No sprint has run here", desc: "A sprint appears when the sprint driver starts one, and stays after it ends." });
    this.append(this.head.el, h("div", { class: "page-body" }, this.list, this.none, this.idleSec, this.empty));
    this.unsub = store.subscribe(() => this.render());
    this.tick = setInterval(() => this.age(), 1000);
    this.render();
  }
  disconnectedCallback() { this.unsub?.(); clearInterval(this.tick); }
  age() {
    for (const el of [...this.list.children, ...this.idle.children]) {
      const r = el.refs; if (!r) continue;
      setText(r.when, r.at ? relTime(Date.now() - r.at) : "No activity");
      setText(r.last, lastOf(r.at, el.__item?.message));
    }
  }
  render() {
    const sps = [...store.state.sprints].sort((a, b) => b.at - a.at);
    const run = sps.filter(isLive), idle = sps.filter((s) => !isLive(s)).sort((a, b) => (a.state === "stale" ? 0 : 1) - (b.state === "stale" ? 0 : 1) || b.at - a.at);   // no driver first (they may need a look), then stopped; newest first in each
    this.head.update(sps.length ? `${run.length} running, ${sps.length} in all` : "None yet");
    const spec = (live) => ({
      move: false, key: (s) => s.id,
      create: () => makeSprint(),
      update: (el, s) => { const was = el.dataset.state; patchSprint(el, s); if (live && was && was !== s.state) flash(el); },
    });
    reconcile(this.list, run, spec(true));
    reconcile(this.idle, idle, spec(false));
    setText(this.idleN, String(idle.length));
    this.list.hidden = !run.length;
    this.idleSec.hidden = !idle.length;
    this.none.hidden = !sps.length || run.length > 0;
    this.empty.hidden = sps.length > 0;
    this.age();
  }
}
customElements.define("gb-view-sprints", ViewSprints);
