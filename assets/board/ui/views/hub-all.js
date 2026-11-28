/* All repos (a hub): one row per repo the hub routes, with counts only: open, in progress, waiting, parked, running sprints and
   the cards that need you. A row opens that repo's own tab, whose state is built from that repo's home alone. A repo whose home
   cannot be read is an error row and the others still show. */
import { h, setText } from "../ui.js";
import { store } from "../store.js";
import { pageHead, go } from "../shared.js";

const num = (key, label, pick) => ({ key, label, width: "92px", cls: "num", m: "", cell: {
  init: (td) => { const s = h("span"); td.append(s); return { s }; },
  update: (r, x) => setText(r.s, x.ok ? String(pick(x)) : "-") } });

class ViewHub extends HTMLElement {
  connectedCallback() {
    this.className = "page";
    this.head = pageHead({ title: "All repos" });
    this.table = h("gb-table", { class: "panel", label: "Repos this hub serves", static: "" });
    this.table.setColumns([
      { key: "name", label: "Repo", width: "minmax(0,1fr)", cls: "title", m: "full", cell: {
        init: (td) => { const t = h("div", { class: "cell-title" }), d = h("div", { class: "cell-sub" }); td.append(t, d); return { t, d }; },
        update: (r, x) => { setText(r.t, x.name); const c = setText(r.d, x.ok ? `Tab ${x.tab}` : `Tab ${x.tab}: ${x.error || "cannot be read"}`); r.d.classList.toggle("is-error", !x.ok); return c; } } },
      num("open", "Open", (x) => x.open), num("active", "In progress", (x) => x.active), num("waiting", "Waiting", (x) => x.waiting),
      num("parked", "Parked", (x) => x.parked), num("sprints", "Sprints", (x) => x.sprints), num("needs", "Needs you", (x) => x.needs),
    ]);
    this.table.rowKey = (r) => r.tab;
    this.table.addEventListener("row-open", (e) => go("work/list", e.detail.tab));
    this.empty = h("div", { class: "panel" }, h("gb-empty", { icon: "layers", title: "No repos routed", desc: "A repo appears here once the hub routes a tab to it (board.py register-tab TAB --repo PATH)." }));
    this.append(this.head.el, h("div", { class: "page-body" }, this.table, this.empty));
    this.unsub = store.subscribe(() => this.render());
    this.render();
  }
  disconnectedCallback() { this.unsub?.(); }
  render() {
    const rows = store.state.repos;
    const bad = rows.filter((r) => r.ok === false).length;
    this.head.update(rows.length ? `${rows.length} repo${rows.length === 1 ? "" : "s"}` + (bad ? `, ${bad} cannot be read` : "") : "Nothing routed");
    this.table.rows = rows.map((r) => ({ ...r, id: r.tab }));
    this.table.hidden = !rows.length; this.empty.hidden = rows.length > 0;
  }
}
customElements.define("gb-view-hub", ViewHub);
