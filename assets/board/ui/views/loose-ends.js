/* Loose ends: the last-resort list, one row per item, or an empty state when there are none. */
import { h, setText } from "../ui.js";
import { store } from "../store.js";
import { pageHead } from "../shared.js";

class ViewLooseEnds extends HTMLElement {
  connectedCallback() {
    this.className = "page";
    this.head = pageHead({ title: "Loose ends" });
    this.table = h("gb-table", { class: "panel", label: "Loose ends", static: "" });
    this.table.setColumns([
      { key: "item", label: "Item", width: "minmax(0,1fr)", cls: "title", m: "full", cell: {
        init: (td) => { const t = h("div", { class: "cell-title" }), d = h("div", { class: "cell-sub" }); td.append(t, d); return { t, d }; },
        update: (r, x) => { setText(r.t, x.item); setText(r.d, [x.source && "From " + x.source, x.id].filter(Boolean).join(", ")); return false; } } },
      { key: "added", label: "Added", width: "112px", m: "", cell: { init: (td) => { const s = h("span", { class: "muted" }); td.append(s); return { s }; }, update: (r, x) => setText(r.s, x.added) } },
      { key: "state", label: "State", width: "112px", m: "", cell: { init: (td) => { const s = h("span", { class: "muted" }); td.append(s); return { s }; }, update: (r, x) => setText(r.s, x.state) } },
    ]);
    this.empty = h("div", { class: "panel" }, h("gb-empty", { icon: "inbox", title: "No loose ends", desc: "A finding is fixed in the order that found it. A row appears here only when it is small, self-contained and cannot be done now." }));
    this.body = h("div", { class: "page-body narrow" }, this.table, this.empty);
    this.append(this.head.el, this.body);
    this.unsub = store.subscribe(() => this.render());
    this.render();
  }
  disconnectedCallback() { this.unsub?.(); }
  render() {
    const { count, rows } = store.state.looseEnds;
    this.head.update(count ? `${count} waiting` : "Nothing waiting");
    this.table.rows = rows.map((r) => ({ ...r, id: r.id || r.item }));
    this.table.hidden = !rows.length; this.empty.hidden = rows.length > 0;
  }
}
customElements.define("gb-view-loose-ends", ViewLooseEnds);
