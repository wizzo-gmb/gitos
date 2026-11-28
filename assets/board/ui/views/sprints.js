/* Sprints: each sprint's state, orders, last activity and Stop, live. A sprint is a card, built once and patched in place; its
   orders are keyed rows. Stop answers the sprint's own Stop card through the board's answer route (see shared.js). */
import { h, icon, setText, setAttr, reconcile, relTime } from "../ui.js";
import { store } from "../store.js";
import { pageHead, openOrder, stopSprint, stopCardOf, stopRequested } from "../shared.js";

const STATE_NOTE = {
  running: "Working through its orders, one merge and one gate at a time.",
  closing: "Stop requested. It finishes the order in hand, then ends.",
  stopped: "Ended. Its remaining orders stay in the ledger.",
  stale: "Its log says running, but no driver is alive. It may have crashed or been closed.",
};
const ORDER_ID = /\d+/;
const orderOf = (ref) => (ref && ORDER_ID.exec(ref) ? ORDER_ID.exec(ref)[0].padStart(3, "0") : "");
const clock = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso ?? "") : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); };

function makeSprint() {
  const r = {};
  r.name = h("h2", { class: "sp-name" });
  r.state = h("gb-badge");
  r.stop = h("button", { class: "btn danger sm", type: "button" }, icon("stop"), h("span", null, "Stop"));
  r.stop.addEventListener("click", () => { const sp = store.state.sprints.find((s) => s.id === r.id); if (sp) stopSprint(sp); });
  r.note = h("p", { class: "sp-note" });
  r.orders = h("ol", { class: "sp-orders", "aria-label": "Orders in this sprint" });
  r.noOrders = h("p", { class: "sp-none" }, "No order yet.");
  r.started = h("span"); r.cur = h("span"); r.last = h("span", { class: "last" });
  r.recent = h("ol", { class: "sp-recent" });
  r.more = h("details", { class: "sp-more" }, h("summary", null, "Recent activity"), r.recent);
  const el = h("article", { class: "sprint card" },
    h("header", { class: "sp-head" }, h("div", { class: "sp-title" }, r.name, r.state), r.stop), r.note, r.orders, r.noOrders,
    h("div", { class: "sp-meta" }, r.started, r.cur, r.last), r.more);
  el.refs = r;
  return el;
}

function patchSprint(el, sp) {
  const r = el.refs; r.id = sp.id; r.at = sp.at;
  setText(r.name, sp.exclusive ? "Exclusive sprint" : sp.name);
  setAttr(r.state, "state", sp.state);
  const card = stopCardOf(sp), asked = stopRequested(sp);
  el.dataset.state = sp.state;
  setText(r.note, STATE_NOTE[sp.state] || "");
  // Stop is offered while the sprint runs and its Stop card is open and unanswered
  r.stop.hidden = sp.state === "stopped" || sp.state === "stale";
  r.stop.disabled = !card || !!card.answer || sp.state === "closing" || asked;
  setText(r.stop.lastChild, sp.state === "closing" ? "Stopping" : asked ? "Stop requested" : "Stop");
  r.stop.title = !card && !r.stop.hidden ? "This sprint has no open Stop card to answer." : "";

  const cur = orderOf(sp.current);
  const rows = sp.orders.map((id) => ({ id, o: store.order(id), cur: cur === id && sp.state !== "stopped" && sp.state !== "stale", sp }));
  reconcile(r.orders, rows, {
    move: false, key: (x) => x.id,
    create: (x) => {
      const strip = h("gb-strip"), pill = h("gb-badge");
      const li = h("li", { class: "sp-order", tabindex: 0, role: "button" }, h("span", { class: "dotline" }), h("span", { class: "oid" }), h("span", { class: "sp-otitle" }), strip, pill);
      li.addEventListener("click", () => openOrder(x.id));
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openOrder(x.id); } });
      li.refs = { strip, pill, id: li.querySelector(".oid"), t: li.querySelector(".sp-otitle") };
      return li;
    },
    update: (li, x) => {
      const { o } = x, f = li.refs;
      setText(f.id, "WO-" + x.id); setText(f.t, o ? o.short : "Not in the ledger's open list");
      li.dataset.cur = x.cur ? "1" : "";
      f.strip.hidden = !(o && o.total); if (o && o.total) f.strip.set(o.slices.map((s) => s.state), `${o.done}/${o.total}`, `${o.done} of ${o.total} slices landed`);
      f.pill.hidden = !o;
      if (o) { setAttr(f.pill, "state", x.cur ? "active" : o.status); if (x.cur) f.pill.setAttribute("label", "Working"); else f.pill.removeAttribute("label"); f.pill.render?.(); }
    },
  });
  r.noOrders.hidden = rows.length > 0;
  setText(r.started, sp.started ? "Started " + clock(sp.started) : "");
  setText(r.cur, sp.state === "stopped" ? "Ended" : sp.current ? "Now: " + (/^WO-?/i.test(sp.current) ? sp.current.replace(/^WO-?/i, "WO-").replace("/", " ") : sp.current) : "");
  const rsig = JSON.stringify(sp.recent);
  if (r.recent.dataset.sig !== rsig) {
    r.recent.dataset.sig = rsig;
    r.recent.replaceChildren(...[...sp.recent].reverse().map((x) => h("li", null, h("span", { class: "rt" }, clock(x.t)), h("span", { class: "rk" }, x.kind), h("span", { class: "rm" }, [x.ref, x.msg].filter(Boolean).join(" ")))));
  }
  r.more.hidden = !sp.recent.length;
}

class ViewSprints extends HTMLElement {
  connectedCallback() {
    this.className = "page";
    this.head = pageHead({ title: "Sprints" });
    this.list = h("div", { class: "sprint-grid" });
    this.empty = h("gb-empty", { icon: "sprint", title: "No sprint has run here", desc: "A sprint appears when the sprint driver starts one, and stays after it ends." });
    this.append(this.head.el, h("div", { class: "page-body" }, this.list, this.empty));
    this.unsub = store.subscribe(() => this.render());
    this.tick = setInterval(() => this.age(), 1000);
    this.render();
  }
  disconnectedCallback() { this.unsub?.(); clearInterval(this.tick); }
  age() { for (const el of this.list.children) { const r = el.refs; if (r?.at) setText(r.last, "Last activity " + relTime(Date.now() - r.at) + (el.__item?.message ? ": " + el.__item.message : "")); } }
  render() {
    const sps = [...store.state.sprints].sort((a, b) => (a.state === "stopped") - (b.state === "stopped") || b.at - a.at);
    const live = sps.filter((s) => s.state === "running" || s.state === "closing").length;
    this.head.update(sps.length ? `${live} running, ${sps.length} in all` : "None yet");
    reconcile(this.list, sps, {
      move: false, key: (s) => s.id,
      create: () => makeSprint(),
      update: (el, s) => { const was = el.dataset.state; patchSprint(el, s); if (was && was !== s.state) { el.classList.remove("flash-ring"); void el.offsetWidth; el.classList.add("flash-ring"); } },
    });
    this.empty.hidden = sps.length > 0;
    this.age();
  }
}
customElements.define("gb-view-sprints", ViewSprints);
