/* Work as a dependency graph: every open and parked order, its slices, and what waits on what. */
import { h, icon } from "../ui.js";
import "../graph.js";
import { store, SEV_LABEL } from "../store.js";
import { pageHead, WORK_TABS, workSummary, openOrder, queryParams, setQuery } from "../shared.js";

class ViewGraph extends HTMLElement {
  connectedCallback() {
    this.className = "page page-fill";
    const p = queryParams();
    this.opts = { slices: p.get("slices") !== "0", parked: p.get("parked") !== "0", across: p.get("flow") === "across" };
    this.head = pageHead({ title: "Work", tabs: WORK_TABS, active: "work/graph" });
    this.head.el.style.viewTransitionName = "work-head";
    const toggle = (key, label) => {
      const b = h("button", { class: "chip", type: "button", "aria-pressed": this.opts[key] }, label);
      b.addEventListener("click", () => { this.opts[key] = !this.opts[key]; b.setAttribute("aria-pressed", this.opts[key]); if (key === "across") this.graph.dir = this.opts.across ? "LR" : "TB"; this.sync(); });
      return b;
    };
    this.graph = h("gb-graph"); this.graph.dir = this.opts.across ? "LR" : "TB";
    this.graph.addEventListener("node-open", (e) => openOrder(e.detail.orderId));
    this.graph.addEventListener("focus-change", () => this.sync(true));
    const bar = h("div", { class: "toolbar" }, h("div", { class: "chips", role: "group", "aria-label": "Graph layers" }, toggle("slices", "Slices"), toggle("parked", "Parked orders"), toggle("across", "Flow across")),
      h("span", { class: "muted hint-right" }, "Drag to pan, scroll to zoom, click a node to follow its dependencies"));
    this.append(this.head.el, h("div", { class: "page-body graph-body" }, bar, h("div", { class: "graph-frame" }, this.graph)));
    this.unsub = store.subscribe(() => this.build());
    this.build();
    const f = p.get("focus");
    if (f) requestAnimationFrame(() => this.graph.focusNode(f.includes("/") ? f : "o" + f));
  }
  disconnectedCallback() { this.unsub?.(); }

  sync(fromFocus) {
    const p = new URLSearchParams();
    if (!this.opts.slices) p.set("slices", "0");
    if (!this.opts.parked) p.set("parked", "0");
    if (this.opts.across) p.set("flow", "across");
    const f = this.graph.focused; if (f) p.set("focus", f.startsWith("o") ? f.slice(1) : f);
    setQuery(p);
    if (!fromFocus) this.build();
  }

  build() {
    this.head.update(workSummary());
    const nodes = [], edges = [];
    const orders = store.orders().filter((o) => this.opts.parked || !o.parked);
    for (const o of orders) {
      nodes.push({ id: "o" + o.id, kind: "order", code: "WO-" + o.id, label: o.short, state: o.status, orderId: o.id, dashed: o.parked, pending: !!o.pending,
        strip: o.total ? o.slices.map((s) => s.state) : null, foot: `${SEV_LABEL[o.sev]} severity` });
      if (this.opts.slices) for (const s of o.slices) {
        nodes.push({ id: s.key, kind: "slice", code: s.id, label: s.title, state: s.state, orderId: o.id });
        if (!s.dependsOn.length) edges.push({ from: "o" + o.id, to: s.key, kind: "has" });
        for (const d of s.dependsOn) edges.push({ from: d, to: s.key, kind: "dep" });
      }
    }
    for (const l of store.state.links) if (orders.some((o) => o.id === l.from) && orders.some((o) => o.id === l.to)) edges.push({ from: "o" + l.from, to: "o" + l.to, kind: "link", label: l.why });
    // keep the cheap check: only hand the graph new data when something it draws changed
    const sig = JSON.stringify([nodes, edges]);
    if (sig !== this.sig) { this.sig = sig; this.graph.data = { nodes, edges }; }
  }
}
customElements.define("gb-view-graph", ViewGraph);
