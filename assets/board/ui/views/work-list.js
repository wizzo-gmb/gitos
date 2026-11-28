/* Work as a list: sortable, filterable, searchable, with completion per order. */
import { h, icon, setText, setAttr, highlight, fuzzy, LABELS } from "../ui.js";
import { store, STATUS_ORDER, SEV_RANK, completionText } from "../store.js";
import { pageHead, WORK_TABS, workSummary, openOrder, queryParams, setQuery, route } from "../shared.js";

const SEVS = ["high", "medium", "low"];
const STATUSES = ["active", "awaiting", "ready", "waiting", "held", "parked"];
const SORTS = { sev: "Severity", id: "Order number", status: "Status", progress: "Completion", title: "Title" };

function readFilters() {
  const p = queryParams();
  const set = (k) => new Set((p.get(k) || "").split(",").filter(Boolean));
  return { q: p.get("q") || "", sev: set("sev"), st: set("st"), sort: p.get("sort") || "sev", dir: p.get("dir") || "asc", res: p.get("res") === "1" };
}
function writeFilters(f) {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.sev.size) p.set("sev", [...f.sev].join(","));
  if (f.st.size) p.set("st", [...f.st].join(","));
  if (f.sort !== "sev" || f.dir !== "asc") { p.set("sort", f.sort); p.set("dir", f.dir); }
  if (f.res) p.set("res", "1");
  setQuery(p);
}

const progressValue = (o) => (o.total ? (o.done + (o.awaiting ? 0.5 : 0)) / o.total : -1);
const SORTERS = {
  sev: (a, b) => SEV_RANK[a.sev] - SEV_RANK[b.sev] || Number(a.id) - Number(b.id),
  id: (a, b) => Number(a.id) - Number(b.id),
  status: (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || SEV_RANK[a.sev] - SEV_RANK[b.sev],
  progress: (a, b) => progressValue(b) - progressValue(a) || Number(a.id) - Number(b.id),
  title: (a, b) => a.title.localeCompare(b.title),
};

class ViewList extends HTMLElement {
  connectedCallback() {
    this.f = readFilters();
    this.className = "page";
    this.head = pageHead({ title: "Work", tabs: WORK_TABS, active: "work/list" });
    this.head.el.style.viewTransitionName = "work-head";

    this.search = h("input", { class: "input", type: "search", placeholder: "Search orders by number or title", "aria-label": "Search orders", value: this.f.q, id: "work-search" });
    this.search.addEventListener("input", () => { this.f.q = this.search.value; this.changed(); });
    const chips = (list, key, fmt) => list.map((v) => {
      const b = h("button", { class: "chip", type: "button", "aria-pressed": this.f[key].has(v), style: { "--c": `var(--c-${v})` } }, key === "st" ? h("i", { class: "dot" }) : null, fmt(v));
      b.addEventListener("click", () => { const on = !this.f[key].has(v); on ? this.f[key].add(v) : this.f[key].delete(v); b.setAttribute("aria-pressed", on); this.changed(); });
      return b;
    });
    this.sortSel = h("select", { class: "select sort-select", "aria-label": "Sort by" }, Object.entries(SORTS).map(([k, l]) => h("option", { value: k, selected: k === this.f.sort }, "Sort: " + l)));
    this.sortSel.addEventListener("change", () => { this.f.sort = this.sortSel.value; this.f.dir = "asc"; this.table.setSort(this.f.sort, "asc"); this.changed(); });
    this.resChip = h("button", { class: "chip", type: "button", "aria-pressed": this.f.res }, "Recently resolved");
    this.resChip.addEventListener("click", () => { this.f.res = !this.f.res; this.resChip.setAttribute("aria-pressed", this.f.res); this.changed(); });
    this.count = h("span", { class: "result-count", role: "status" });

    const toolbar = h("div", { class: "toolbar" },
      h("label", { class: "search grow" }, h("span", { class: "sr-only" }, "Search orders"), icon("search"), this.search),
      h("div", { class: "chips", role: "group", "aria-label": "Severity" }, ...chips(SEVS, "sev", (v) => LABELS[v] || v[0].toUpperCase() + v.slice(1))),
      h("div", { class: "chips", role: "group", "aria-label": "Status" }, ...chips(STATUSES, "st", (v) => LABELS[v])),
      h("div", { class: "chips" }, this.resChip),
      this.sortSel);

    this.table = h("gb-table", { class: "panel", label: "Work orders" });
    this.table.label = "Work orders";
    this.table.setColumns(columns());
    this.table.setSort(this.f.sort, this.f.dir);
    this.table.addEventListener("sort", (e) => { this.f.sort = e.detail.key; this.f.dir = e.detail.dir; this.sortSel.value = e.detail.key; this.changed(); });
    this.table.addEventListener("row-open", (e) => openOrder(e.detail.id));
    this.empty = h("gb-empty", { icon: "search", title: "No orders match", desc: "Clear a filter or change the search." },
      h("button", { class: "btn sm", type: "button", onclick: () => this.clear() }, "Clear filters"));
    this.empty.hidden = true;

    this.append(this.head.el, h("div", { class: "page-body" }, toolbar, this.count, h("div", { class: "table-wrap" }, this.table, this.empty)));
    this.unsub = store.subscribe(() => this.render());
    this.render();
    this.onSel = () => this.table.select(route.drawer);
    addEventListener("hashchange", this.onSel);
  }
  disconnectedCallback() { this.unsub?.(); removeEventListener("hashchange", this.onSel); }

  clear() { this.f.q = ""; this.f.sev.clear(); this.f.st.clear(); this.search.value = ""; this.querySelectorAll(".chips .chip[aria-pressed]").forEach((c) => { if (c !== this.resChip) c.setAttribute("aria-pressed", false); }); this.changed(); }
  changed() { writeFilters(this.f); this.render(); }

  rows() {
    const f = this.f, q = f.q.trim().replace(/^wo-?/i, "");
    let rows = (f.res ? store.all() : store.orders());
    rows = rows.filter((o) => (!f.sev.size || f.sev.has(o.sev)) && (!f.st.size || f.st.has(o.status)));
    if (q) rows = rows.filter((o) => o.id.includes(q) || fuzzy(q, o.title).score > 0);
    const s = Object.hasOwn(SORTERS, f.sort) ? SORTERS[f.sort] : SORTERS.sev;
    rows = [...rows].sort((a, b) => (a.resolved ? 1 : 0) - (b.resolved ? 1 : 0) || (a.resolved ? Number(b.id) - Number(a.id) : s(a, b)));
    if (f.dir === "desc") rows = rows.filter((o) => !o.resolved).reverse().concat(rows.filter((o) => o.resolved));
    return rows;
  }
  render() {
    this.head.update(workSummary());
    const rows = this.rows(); this.q = this.f.q.trim();
    this.table.q = this.q;
    this.table.rows = rows;
    this.table.hidden = !rows.length; this.empty.hidden = !!rows.length;
    const total = this.f.res ? store.all().length : store.orders().length;
    setText(this.count, `${rows.length} of ${total} orders`);
  }
}

function columns() {
  return [
    { key: "id", label: "Order", width: "78px", sortable: true, cls: "id", m: "", cell: {
      init: (td, o) => { const a = h("span", { class: "oid" }); td.append(a); return { a }; },
      update: (r, o) => setText(r.a, "WO-" + o.id) } },
    { key: "title", label: "Title", width: "minmax(0,1fr)", sortable: true, cls: "title", m: "full", cell: {
      init: (td) => { const t = h("div", { class: "cell-title" }), s = h("div", { class: "cell-sub" }); td.append(t, s); return { t, s, td }; },
      update: (r, o) => {
        const q = r.td.closest("gb-table")?.q || "";
        const key = o.title + "|" + q; let ch = false;
        if (r.t.dataset.k !== key) { r.t.dataset.k = key; r.t.textContent = ""; r.t.append(q && !/^\d+$/.test(q) ? highlight(o.title, fuzzy(q, o.title).ranges) : o.title); }
        const sub = o.resolved ? (o.released ? `Resolved, released in ${o.released}` : "Resolved") : o.parked ? "Until: " + o.trigger : o.waitsOn.length ? "Waits on " + o.waitsOn.map((i) => "WO-" + i).join(", ") : o.held ? "Held by you" : o.approved && o.status === "ready" ? "Approved for dispatch" : "";
        if (setText(r.s, sub)) ch = true; r.s.hidden = !sub;
        return ch;
      } } },
    { key: "sev", label: "Severity", width: "104px", sortable: true, m: "hide", cell: {
      init: (td) => { const e = h("gb-sev"); td.append(e); return { e }; },
      update: (r, o) => setAttr(r.e, "level", o.sev) } },
    { key: "status", label: "Status", width: "132px", sortable: true, cls: "status", m: "", cell: {
      init: (td) => { const e = h("gb-badge"), p = h("gb-badge", { state: "pending", label: "Pending" }); p.hidden = true; td.append(e, p); return { e, p }; },
      update: (r, o) => { const c = setAttr(r.e, "state", o.status); r.p.hidden = !o.pending; return c; } } },
    { key: "progress", label: "Completion", width: "minmax(150px,200px)", sortable: true, cls: "prog", m: "full", cell: {
      init: (td) => { const s = h("gb-strip"), n = h("span", { class: "muted" }); td.append(s, n); return { s, n }; },
      update: (r, o) => {
        if (!o.total) { r.s.hidden = true; const c = setText(r.n, o.resolved ? "Done" : "No slices"); r.n.hidden = false; return c; }
        r.n.hidden = true; r.s.hidden = false;
        const before = r.s.querySelector(".num")?.textContent;
        r.s.set(o.slices.map((s) => s.state), o.awaiting ? "acceptance open" : `${o.done}/${o.total}`, completionText(o));
        return before !== undefined && before !== r.s.querySelector(".num").textContent;
      } } },
  ];
}

customElements.define("gb-view-list", ViewList);
