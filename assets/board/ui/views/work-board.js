/* Work as a board by state. A card that changes state glides to its new column; nothing else moves. */
import { h, icon, setText, reconcile, reduced, fuzzy } from "../ui.js";
import { store, SEV_RANK } from "../store.js";
import { pageHead, WORK_TABS, workSummary, openOrder, route } from "../shared.js";

const COLUMNS = [
  { id: "active", title: "In progress", hint: "A worker has it now", empty: ["Nothing in progress", "Orders appear here the moment a worker starts one."] },
  { id: "awaiting", title: "Awaiting accept", hint: "Merged, waiting for your accept", empty: ["Nothing to accept", "Merged orders wait here until the orchestrator resolves them."] },
  { id: "ready", title: "Can start", hint: "Nothing blocks it", empty: ["Nothing waiting to start", "Every open order is moving or blocked."] },
  { id: "waiting", title: "Waiting", hint: "Blocked by another order", empty: ["Nothing is blocked", "Orders that wait on another show up here."] },
  { id: "held", title: "Held", hint: "Held by you", empty: ["Nothing held", "Hold an order from its drawer and it moves here."] },
  { id: "parked", title: "Parked", hint: "Until its trigger is met", empty: ["Nothing parked", "Park an order with a trigger to set it aside."] },
];

class ViewBoard extends HTMLElement {
  connectedCallback() {
    this.className = "page";
    this.head = pageHead({ title: "Work", tabs: WORK_TABS, active: "work/board" });
    this.head.el.style.viewTransitionName = "work-head";
    this.q = "";
    const search = h("input", { class: "input", type: "search", placeholder: "Filter cards", "aria-label": "Filter cards", id: "work-search" });
    search.addEventListener("input", () => { this.q = search.value; this.render(); });
    this.cols = {};
    const board = h("div", { class: "board", role: "list" });
    for (const c of COLUMNS) {
      const body = h("div", { class: "col-body", role: "list" });
      const count = h("span", { class: "count" }, "0");
      const empty = h("gb-empty", { dense: "", title: c.empty[0], desc: c.empty[1] });
      const col = h("section", { class: "col", "data-col": c.id, "aria-label": c.title, role: "listitem" },
        h("header", { class: "col-head" }, h("gb-badge", { state: c.id, label: c.title }), count, h("span", { class: "col-hint" }, c.hint)), body, empty);
      this.cols[c.id] = { body, count, empty };
      board.append(col);
    }
    this.append(this.head.el, h("div", { class: "page-body board-body" }, h("div", { class: "toolbar" }, h("label", { class: "search grow" }, h("span", { class: "sr-only" }, "Filter cards"), icon("search"), search)), board));
    this.addEventListener("open-order", (e) => openOrder(e.detail));
    this.unsub = store.subscribe(() => this.render());
    this.render(true);
    this.onSel = () => this.select();
    addEventListener("hashchange", this.onSel);
  }
  disconnectedCallback() { this.unsub?.(); removeEventListener("hashchange", this.onSel); }
  select() { for (const c of this.querySelectorAll("gb-order-card")) { if (c.__key === route.drawer) c.dataset.selected = ""; else delete c.dataset.selected; } }

  render(first) {
    this.head.update(workSummary());
    const q = this.q.trim().replace(/^wo-?/i, "");
    const orders = store.orders().filter((o) => !q || o.id.includes(q) || fuzzy(q, o.title).score > 0).sort((a, b) => SEV_RANK[a.sev] - SEV_RANK[b.sev] || Number(a.id) - Number(b.id));

    // 1. remember where every card is, 2. move cards that changed column, 3. patch each column, 4. glide what moved
    const before = new Map(); const known = new Map();
    for (const el of this.querySelectorAll("gb-order-card")) { if (el.classList.contains("is-leaving")) continue; known.set(el.__key, el); before.set(el.__key, el.getBoundingClientRect()); }
    for (const o of orders) { const el = known.get(o.id), body = this.cols[o.status]?.body; if (el && body && el.parentElement !== body) body.append(el); }
    for (const c of COLUMNS) {
      const items = orders.filter((o) => o.status === c.id), ref = this.cols[c.id];
      reconcile(ref.body, items, {
        move: false, key: (o) => o.id,
        create: (o) => { const el = h("gb-order-card"); el.order = o; return el; },
        update: (el, o) => { el.order = o; },
      });
      setText(ref.count, items.length); ref.empty.hidden = items.length > 0;
    }
    if (!first && !reduced()) for (const [k, a] of before) {
      const el = known.get(k); if (!el || !el.isConnected || el.classList.contains("is-entering")) continue;
      const b = el.getBoundingClientRect(), dx = a.left - b.left, dy = a.top - b.top;
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) el.animate([{ transform: `translate(${dx}px, ${dy}px)`, zIndex: 5 }, { transform: "none", zIndex: 5 }], { duration: 520, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    this.select();
  }
}
customElements.define("gb-view-board", ViewBoard);
