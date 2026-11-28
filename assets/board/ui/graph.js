/* graph.js - <gb-graph>, the dependency graph. Inline SVG, a layered layout written here (no library),
   pan and zoom, focus an order to light up what it waits on and what waits on it, and a layout that
   animates when the data changes instead of redrawing.

   gb.data = { nodes: [{ id, kind: "order"|"slice", label, code, state, sub, strip: [states], pending, dashed, orderId }],
               edges: [{ from, to, kind: "dep"|"has"|"link", label }] }                                            */
import { h, icon, reduced, LABELS } from "./ui.js";

const SVG = "http://www.w3.org/2000/svg";
const s = (tag, attrs, ...kids) => {
  const el = document.createElementNS(SVG, tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  for (const k of kids) if (k != null) el.append(k.nodeType ? k : document.createTextNode(k));
  return el;
};
const SIZE = { order: { w: 196, h: 68 }, slice: { w: 160, h: 50 } };

/* ---------------------------------------------------------------- layered layout */
export function layoutDag(nodes, edges, { dir = "TB" } = {}) {
  const TB = dir !== "LR", gMain = TB ? 38 : 70, gCross = TB ? 22 : 20;
  let ids = nodes.map((n) => n.id); const byId = new Map(nodes.map((n) => [n.id, n]));
  const out = new Map(ids.map((i) => [i, []])), inn = new Map(ids.map((i) => [i, []]));
  for (const e of edges) if (byId.has(e.from) && byId.has(e.to)) { out.get(e.from).push(e.to); inn.get(e.to).push(e.from); }
  // orders with no dependency either way go on a shelf beside the graph instead of widening it
  const lone = ids.filter((i) => !out.get(i).length && !inn.get(i).length), loneSet = new Set(lone);
  ids = ids.filter((i) => !loneSet.has(i));

  // 1. layers: longest path from a source
  const layer = new Map(), deg = new Map(ids.map((i) => [i, inn.get(i).length]));
  const queue = ids.filter((i) => !deg.get(i)); queue.forEach((i) => layer.set(i, 0));
  while (queue.length) {
    const u = queue.shift();
    for (const v of out.get(u)) { layer.set(v, Math.max(layer.get(v) ?? 0, layer.get(u) + 1)); deg.set(v, deg.get(v) - 1); if (!deg.get(v)) queue.push(v); }
  }
  for (const i of ids) if (!layer.has(i)) layer.set(i, 0);

  // 2. components, largest first, so a connected chain sits above the loose orders
  const comp = new Map(); let cn = 0;
  for (const i of ids) if (!comp.has(i)) { const st = [i]; comp.set(i, cn); while (st.length) { const u = st.pop(); for (const v of [...out.get(u), ...inn.get(u)]) if (!comp.has(v)) { comp.set(v, cn); st.push(v); } } cn++; }
  const csize = new Map(); for (const [, c] of comp) csize.set(c, (csize.get(c) || 0) + 1);
  const crank = [...csize.keys()].sort((a, b) => csize.get(b) - csize.get(a) || a - b);
  const cpos = new Map(crank.map((c, i) => [c, i]));

  // 3. order within layers: components, then barycentre sweeps
  const maxL = Math.max(0, ...layer.values());
  const cols = Array.from({ length: maxL + 1 }, () => []);
  for (const i of ids) cols[layer.get(i)].push(i);
  cols.forEach((c) => c.sort((a, b) => cpos.get(comp.get(a)) - cpos.get(comp.get(b)) || ids.indexOf(a) - ids.indexOf(b)));
  const pos = new Map(); const reindex = () => cols.forEach((c) => c.forEach((id, k) => pos.set(id, k)));
  reindex();
  const sweep = (L, nb) => {
    const key = (id) => { const n = nb.get(id).filter((x) => pos.has(x)); return n.length ? n.reduce((a, x) => a + pos.get(x), 0) / n.length : pos.get(id); };
    cols[L].sort((a, b) => cpos.get(comp.get(a)) - cpos.get(comp.get(b)) || key(a) - key(b) || pos.get(a) - pos.get(b)); reindex();
  };
  for (let it = 0; it < 3; it++) { for (let L = 1; L <= maxL; L++) sweep(L, inn); for (let L = maxL - 1; L >= 0; L--) sweep(L, out); }

  // 4. coordinates: along the flow by layer, across it by relaxation towards neighbours, then overlap removal
  const size = (id) => SIZE[byId.get(id).kind] || SIZE.order;
  const mainExt = (id) => (TB ? size(id).h : size(id).w), crossExt = (id) => (TB ? size(id).w : size(id).h);
  const main = new Map(); let cm = 0;
  cols.forEach((c) => { const m = Math.max(0, ...c.map(mainExt)); c.forEach((id) => main.set(id, cm)); cm += m + gMain; });
  const cross = new Map(); cols.forEach((c) => { let cc = 0; c.forEach((id) => { cross.set(id, cc); cc += crossExt(id) + gCross; }); });
  const cen = (id) => cross.get(id) + crossExt(id) / 2;
  for (let it = 0; it < 8; it++) {
    const order = it % 2 ? [...cols.keys()].reverse() : [...cols.keys()];
    for (const L of order) {
      for (const id of cols[L]) { const nb = [...inn.get(id), ...out.get(id)]; if (nb.length) cross.set(id, nb.reduce((a, n) => a + cen(n), 0) / nb.length - crossExt(id) / 2); }
      let floor = -Infinity;
      for (const id of cols[L]) { if (cross.get(id) < floor) cross.set(id, floor); floor = cross.get(id) + crossExt(id) + gCross; }
    }
  }
  const minC = Math.min(...ids.map((i) => cross.get(i)), 0);
  const res = new Map(); let maxX = 0, maxY = 0;
  for (const id of ids) {
    const z = size(id), c = cross.get(id) - minC, m = main.get(id);
    const p = { x: TB ? c : m, y: TB ? m : c, w: z.w, h: z.h, layer: layer.get(id) };
    res.set(id, p); maxX = Math.max(maxX, p.x + p.w); maxY = Math.max(maxY, p.y + p.h);
  }
  let shelf = null;
  if (lone.length) {
    const n = Math.min(TB ? 2 : 3, lone.length), x0 = TB ? (ids.length ? maxX + 64 : 0) : 0, y0 = TB ? 0 : (ids.length ? maxY + 60 : 0), lab = 30;
    lone.forEach((id, i) => {
      const z = size(id), p = { x: x0 + (i % n) * (SIZE.order.w + 22), y: y0 + lab + Math.floor(i / n) * (SIZE.order.h + 22), w: z.w, h: z.h, layer: 0 };
      res.set(id, p); maxX = Math.max(maxX, p.x + p.w); maxY = Math.max(maxY, p.y + p.h);
    });
    shelf = { x: x0, y: y0 + 8 };
  }
  return { pos: res, width: maxX, height: maxY, shelf };
}

/* ---------------------------------------------------------------- <gb-graph> */
class GbGraph extends HTMLElement {
  #data = { nodes: [], edges: [] }; #nodes = new Map(); #edges = new Map(); #lay = null;
  #dir = "TB"; #k = 1; #tx = 0; #ty = 0; #focus = null; #fitted = false; #drag = null; #pts = new Map(); #pinch = 0;

  connectedCallback() {
    if (this.svg) return;
    this.svg = s("svg", { class: "g-svg", tabindex: 0, role: "group", "aria-label": "Dependency graph. Arrow keys pan, plus and minus zoom, zero fits. Tab to a node and press Enter to focus it." },
      s("defs", null,
        s("marker", { id: "ah", viewBox: "0 0 10 10", refX: 8.5, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, s("path", { d: "M1 1.5 8.5 5 1 8.5z", class: "g-arrow" })),
        s("marker", { id: "ah-up", viewBox: "0 0 10 10", refX: 8.5, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, s("path", { d: "M1 1.5 8.5 5 1 8.5z", class: "g-arrow up" })),
        s("marker", { id: "ah-down", viewBox: "0 0 10 10", refX: 8.5, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, s("path", { d: "M1 1.5 8.5 5 1 8.5z", class: "g-arrow down" }))),
      this.vp = s("g", { class: "g-vp" }, this.eg = s("g", { class: "g-edges" }), this.ng = s("g", { class: "g-nodes" })));
    this.zoomLabel = h("span", { class: "g-zoom" }, "100%");
    this.tools = h("div", { class: "g-tools", role: "toolbar", "aria-label": "Graph view" },
      h("button", { class: "btn icon sm ghost", type: "button", "aria-label": "Zoom out", onclick: () => this.zoomBy(1 / 1.25) }, icon("minus")),
      this.zoomLabel,
      h("button", { class: "btn icon sm ghost", type: "button", "aria-label": "Zoom in", onclick: () => this.zoomBy(1.25) }, icon("plus")),
      h("button", { class: "btn icon sm ghost", type: "button", "aria-label": "Fit to view", title: "Fit to view (0)", onclick: () => this.fit(true) }, icon("fit")));
    this.legend = h("div", { class: "g-legend", "aria-hidden": "true" },
      h("span", null, h("i", { class: "lg-dep" }), "slice waits on slice"), h("span", null, h("i", { class: "lg-link" }), "order waits on order"));
    this.panel = h("div", { class: "g-panel", hidden: true, "aria-live": "polite" });
    this.append(this.svg, this.legend, this.tools, this.panel);

    this.svg.addEventListener("wheel", (e) => { e.preventDefault(); const r = this.svg.getBoundingClientRect(); this.zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0016))); }, { passive: false });
    this.svg.addEventListener("pointerdown", (e) => this.#down(e));
    this.svg.addEventListener("pointermove", (e) => this.#move(e));
    this.svg.addEventListener("pointerup", (e) => this.#up(e));
    this.svg.addEventListener("pointercancel", (e) => this.#up(e));
    this.svg.addEventListener("keydown", (e) => this.#key(e));
    this.ro = new ResizeObserver(() => { if (!this.#fitted && this.svg.clientWidth) this.fit(false); }); this.ro.observe(this);
    if (this.#data.nodes.length) this.data = this.#data;
  }
  disconnectedCallback() { this.ro?.disconnect(); }

  set data(d) { this.#data = d; if (this.svg) this.#render(); }
  set dir(v) { v = v === "LR" ? "LR" : "TB"; if (v === this.#dir) return; this.#dir = v; if (this.svg) { this.#render(); this.fit(true); } }
  get dir() { return this.#dir; }
  get data() { return this.#data; }
  get focused() { return this.#focus; }

  /* ---- render: keyed, in place */
  #render() {
    const { nodes, edges } = this.#data;
    this.#lay = layoutDag(nodes, edges, { dir: this.#dir });
    if (this.#lay.shelf) {
      if (!this.shelfEl) { this.shelfEl = s("text", { class: "g-shelf" }, "No dependencies"); this.vp.prepend(this.shelfEl); }
      this.shelfEl.style.transform = `translate(${this.#lay.shelf.x}px, ${this.#lay.shelf.y}px)`; this.shelfEl.style.opacity = 1;
    } else if (this.shelfEl) this.shelfEl.style.opacity = 0;
    const seen = new Set();
    for (const n of nodes) {
      seen.add(n.id); let rec = this.#nodes.get(n.id);
      if (!rec) { rec = { g: this.#makeNode(n), data: n }; this.#nodes.set(n.id, rec); this.ng.append(rec.g); rec.g.classList.add("enter"); setTimeout(() => rec.g.classList.remove("enter"), 700); rec.fresh = true; }
      else this.#patchNode(rec, n);
      rec.data = n;
      const p = this.#lay.pos.get(n.id);
      if (rec.fresh) { rec.g.style.transition = "none"; }
      rec.g.style.transform = `translate(${p.x}px, ${p.y}px)`;
      rec.g.setAttribute("transform", `translate(${p.x} ${p.y})`);
      if (rec.fresh) { void rec.g.getBoundingClientRect(); rec.g.style.transition = ""; rec.fresh = false; }
      rec.p = p;
    }
    for (const [id, rec] of this.#nodes) if (!seen.has(id)) { rec.g.classList.add("leave"); setTimeout(() => rec.g.remove(), 360); this.#nodes.delete(id); }

    const eseen = new Set();
    for (const e of edges) {
      const a = this.#lay.pos.get(e.from), b = this.#lay.pos.get(e.to); if (!a || !b) continue;
      const key = `${e.from}>${e.to}`; eseen.add(key);
      let rec = this.#edges.get(key);
      if (!rec) {
        const path = s("path", { class: "g-edge " + e.kind, "marker-end": "url(#ah)" });
        rec = { path, label: null }; this.#edges.set(key, rec); this.eg.append(path); path.classList.add("enter");
        path.style.transition = "none"; path.style.d = `path("${this.#path(a, b)}")`; path.setAttribute("d", this.#path(a, b)); void path.getBoundingClientRect(); path.style.transition = "";
        setTimeout(() => path.classList.remove("enter"), 700);
      } else { rec.path.style.d = `path("${this.#path(a, b)}")`; rec.path.setAttribute("d", this.#path(a, b)); }
      rec.data = e;
    }
    for (const [k, rec] of this.#edges) if (!eseen.has(k)) { rec.path.classList.add("leave"); setTimeout(() => rec.path.remove(), 360); this.#edges.delete(k); }

    if (this.#focus && !this.#nodes.has(this.#focus)) this.#focus = null;
    this.#applyFocus();
    if (!this.#fitted && this.svg.clientWidth) this.fit(false);
  }
  #path(a, b) {
    if (this.#dir === "LR") {
      const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, dx = Math.max(28, (x2 - x1) * .5);
      return x2 <= x1 ? `M${x1} ${y1} C${x1 + 40} ${y1}, ${x2 - 40} ${y2}, ${x2} ${y2}` : `M${x1} ${y1} C${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    }
    const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y, dy = Math.max(24, (y2 - y1) * .5);
    return y2 <= y1 ? `M${x1} ${y1} C${x1} ${y1 + 40}, ${x2} ${y2 - 40}, ${x2} ${y2}` : `M${x1} ${y1} C${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
  }
  #makeNode(n) {
    const z = SIZE[n.kind] || SIZE.order;
    const g = s("g", { class: "gn " + n.kind, tabindex: 0, role: "button", "data-id": n.id });
    g.append(s("rect", { class: "gn-bg", width: z.w, height: z.h, rx: n.kind === "order" ? 12 : 9 }),
      s("rect", { class: "gn-bar", x: 11, y: 12, width: 3.5, height: z.h - 24, rx: 1.75 }),
      s("text", { class: "gn-id", x: 25, y: n.kind === "order" ? 25 : 23 }),
      s("text", { class: "gn-t", x: 25, y: n.kind === "order" ? 44 : 41 }),
      s("g", { class: "gn-strip", transform: `translate(25 ${z.h - 17})` }),
      s("circle", { class: "gn-pend", cx: z.w - 14, cy: 14, r: 4 }));
    g.addEventListener("click", (e) => { e.stopPropagation(); this.focusNode(g.dataset.id === this.#focus ? null : g.dataset.id); });
    g.addEventListener("dblclick", (e) => { e.stopPropagation(); this.#open(g.dataset.id); });
    g.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); this.focusNode(g.dataset.id === this.#focus ? null : g.dataset.id); }
      else if (e.key.toLowerCase() === "o") { e.preventDefault(); e.stopPropagation(); this.#open(g.dataset.id); }
    });
    this.#patchNode({ g, data: n }, n, true);
    return g;
  }
  #patchNode(rec, n) {
    const { g } = rec, z = SIZE[n.kind] || SIZE.order;
    const was = g.dataset.state, shown = n.state === "in-progress" ? "active" : n.state; g.dataset.state = shown;
    g.classList.toggle("dashed", !!n.dashed);
    const put = (cls, x, y, text, anchor) => { let t = g.querySelector("." + cls); if (!t) { t = s("text", { class: cls, x, y, "text-anchor": anchor }); g.append(t); } if (t.textContent !== text) t.textContent = text; return t; };
    const max = Math.floor((z.w - 40) / (n.kind === "order" ? 6.6 : 6.1));
    const label = n.label.length > max ? n.label.slice(0, max - 1).trimEnd() + "…" : n.label;
    const idEl = g.querySelector(".gn-id"); if (idEl.textContent !== n.code) idEl.textContent = n.code;
    const tEl = g.querySelector(".gn-t"); if (tEl.textContent !== label) tEl.textContent = label;
    put("gn-sub", z.w - 14, n.kind === "order" ? 25 : 23, LABELS[n.state] || n.state, "end");
    const st = g.querySelector(".gn-strip"), want = n.strip && n.strip.length ? n.strip : null;
    if (want) {
      const w = (z.w - 50 - (want.length - 1) * 2) / want.length;
      while (st.children.length > want.length) st.lastChild.remove();
      want.forEach((sv, i) => {
        let r = st.children[i]; if (!r) { r = s("rect", { class: "gs", height: 6, rx: 1.5 }); st.append(r); }
        r.setAttribute("x", i * (w + 2)); r.setAttribute("width", w);
        if (r.dataset.s !== sv) { const w2 = r.dataset.s; r.dataset.s = sv; if (w2 && sv === "landed") { r.classList.remove("pop"); void r.getBoundingClientRect(); r.classList.add("pop"); } }
      });
      g.querySelector(".gn-foot")?.remove();
    } else {
      st.textContent = "";
      if (n.foot) put("gn-foot", 25, z.h - 12, n.foot, "start");
    }
    g.querySelector(".gn-pend").classList.toggle("on", !!n.pending);
    g.setAttribute("aria-label", `${n.code}, ${n.label}, ${LABELS[n.state] || n.state}`);
    if (was && was !== shown) { g.classList.remove("changed"); void g.getBoundingClientRect(); g.classList.add("changed"); setTimeout(() => g.classList.remove("changed"), 1800); }
  }

  /* ---- focus: what a node waits on, and what waits on it */
  focusNode(id) { this.#focus = id; this.#applyFocus(); this.dispatchEvent(new CustomEvent("focus-change", { detail: id })); if (id) this.#reveal(id); }
  #related(id) {
    const n = this.#nodes.get(id)?.data; if (!n) return null;
    const { edges } = this.#data, byId = (i) => this.#nodes.get(i)?.data;
    const ups = new Set(), downs = new Set();
    const walk = (start, dirKey, set, kinds) => { const st = [start]; while (st.length) { const u = st.pop(); for (const e of edges) { if (!kinds.includes(e.kind)) continue; const [a, b] = dirKey === "up" ? [e.to, e.from] : [e.from, e.to]; if (a === u && !set.has(b)) { set.add(b); st.push(b); } } } };
    if (n.kind === "slice") { walk(id, "up", ups, ["dep", "link"]); walk(id, "down", downs, ["dep", "link"]); }
    else { walk(id, "up", ups, ["link"]); walk(id, "down", downs, ["link"]); for (const e of edges) if (e.kind === "has" && e.from === id) { downs.add(e.to); } for (const sl of [...this.#nodes.values()].filter((r) => r.data.orderId === n.orderId && r.data.kind === "slice")) downs.add(sl.data.id); }
    return { ups, downs, n, byId };
  }
  #applyFocus() {
    const id = this.#focus; this.classList.toggle("has-focus", !!id);
    for (const [, r] of this.#nodes) r.g.classList.remove("is-focus", "is-up", "is-down", "is-dim");
    for (const [, r] of this.#edges) r.path.classList.remove("up", "down", "dim"), r.path.setAttribute("marker-end", "url(#ah)");
    if (!id) { this.panel.hidden = true; this.panel.textContent = ""; return; }
    const rel = this.#related(id); if (!rel) return;
    const keep = new Set([id, ...rel.ups, ...rel.downs]);
    for (const [nid, r] of this.#nodes) { if (nid === id) r.g.classList.add("is-focus"); else if (rel.ups.has(nid)) r.g.classList.add("is-up"); else if (rel.downs.has(nid)) r.g.classList.add("is-down"); else r.g.classList.add("is-dim"); }
    for (const [, r] of this.#edges) {
      const { from, to } = r.data; const inUp = (rel.ups.has(from) || from === id) && (rel.ups.has(to) || to === id);
      const inDown = (rel.downs.has(to) || to === id) && (rel.downs.has(from) || from === id);
      if (inUp && !inDown) { r.path.classList.add("up"); r.path.setAttribute("marker-end", "url(#ah-up)"); }
      else if (inDown) { r.path.classList.add("down"); r.path.setAttribute("marker-end", "url(#ah-down)"); }
      else r.path.classList.add("dim");
    }
    // bring related edges and nodes forward
    for (const [, r] of this.#edges) if (!r.path.classList.contains("dim")) this.eg.append(r.path);
    this.#renderPanel(rel);
  }
  #renderPanel(rel) {
    const list = (set) => [...set].map((i) => rel.byId(i)).filter(Boolean);
    const chips = (arr) => arr.length ? arr.map((n) => h("button", { type: "button", class: "g-chip", onclick: () => this.focusNode(n.id) }, n.code)) : [h("span", { class: "g-none" }, "nothing")];
    this.panel.hidden = false; this.panel.textContent = "";
    this.panel.append(
      h("div", { class: "gp-head" }, h("div", null, h("div", { class: "gp-code" }, rel.n.code), h("div", { class: "gp-title" }, rel.n.label)),
        h("button", { class: "btn icon sm ghost", type: "button", "aria-label": "Clear focus", onclick: () => this.focusNode(null) }, icon("x"))),
      h("gb-badge", { state: rel.n.state }),
      h("div", { class: "gp-row" }, h("span", null, "Waits on"), h("div", null, ...chips(list(rel.ups)))),
      h("div", { class: "gp-row" }, h("span", null, "Waited on by"), h("div", null, ...chips(list(rel.downs)))),
      h("button", { class: "btn sm", type: "button", onclick: () => this.#open(rel.n.id) }, "Open order", icon("out")));
  }
  #open(id) { const n = this.#nodes.get(id)?.data; if (n) this.dispatchEvent(new CustomEvent("node-open", { detail: { id, orderId: n.orderId }, bubbles: true })); }
  #reveal(id) {
    const p = this.#nodes.get(id)?.p; if (!p) return;
    const W = this.svg.clientWidth, H = this.svg.clientHeight, m = 90;
    const sx = p.x * this.#k + this.#tx, sy = p.y * this.#k + this.#ty;
    let dx = 0, dy = 0;
    if (sx < m) dx = m - sx; else if (sx + p.w * this.#k > W - m - (innerWidth > 760 ? 300 : 0)) dx = W - m - (innerWidth > 760 ? 300 : 0) - (sx + p.w * this.#k);
    if (sy < m) dy = m - sy; else if (sy + p.h * this.#k > H - m) dy = H - m - (sy + p.h * this.#k);
    if (dx || dy) { this.#tx += dx; this.#ty += dy; this.#apply(true); }
  }

  /* ---- pan and zoom */
  #apply(animate) {
    this.vp.style.transition = animate && !reduced() ? "transform .45s cubic-bezier(.2,.8,.2,1)" : "none";
    this.vp.style.transform = `translate(${this.#tx}px, ${this.#ty}px) scale(${this.#k})`;
    this.zoomLabel.textContent = Math.round(this.#k * 100) + "%";
  }
  fit(animate) {
    if (!this.#lay || !this.svg.clientWidth) return;
    const W = this.svg.clientWidth, H = this.svg.clientHeight, narrow = innerWidth < 700, pad = narrow ? 20 : 48;
    const fitK = Math.min((W - pad * 2) / this.#lay.width, (H - pad * 2) / this.#lay.height);
    const k = Math.min(1.1, Math.max(narrow ? .55 : .35, fitK));
    this.#k = k;
    this.#tx = k > fitK + .001 ? pad : Math.round((W - this.#lay.width * k) / 2);
    this.#ty = k > fitK + .001 ? pad + 30 : Math.round(Math.max(pad * .8, (H - this.#lay.height * k) / 2));
    this.#fitted = true; this.#apply(animate);
  }
  zoomAt(px, py, f) {
    const k = Math.max(.2, Math.min(2.4, this.#k * f)); f = k / this.#k;
    this.#tx = px - (px - this.#tx) * f; this.#ty = py - (py - this.#ty) * f; this.#k = k; this.#apply(false);
  }
  zoomBy(f) { const W = this.svg.clientWidth, H = this.svg.clientHeight; const k = Math.max(.2, Math.min(2.4, this.#k * f)); const r = k / this.#k; this.#tx = W / 2 - (W / 2 - this.#tx) * r; this.#ty = H / 2 - (H / 2 - this.#ty) * r; this.#k = k; this.#apply(true); }
  #down(e) {
    if (e.target.closest(".gn")) return;
    this.svg.setPointerCapture(e.pointerId); this.#pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    this.#drag = { x: e.clientX, y: e.clientY, tx: this.#tx, ty: this.#ty, moved: false }; this.svg.classList.add("grab");
    if (this.#pts.size === 2) { const [a, b] = [...this.#pts.values()]; this.#pinch = Math.hypot(a.x - b.x, a.y - b.y); }
  }
  #move(e) {
    if (!this.#pts.has(e.pointerId)) return;
    this.#pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this.#pts.size === 2) {
      const [a, b] = [...this.#pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y), r = this.svg.getBoundingClientRect();
      if (this.#pinch) this.zoomAt((a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, d / this.#pinch); this.#pinch = d; return;
    }
    if (!this.#drag) return;
    const dx = e.clientX - this.#drag.x, dy = e.clientY - this.#drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) this.#drag.moved = true;
    this.#tx = this.#drag.tx + dx; this.#ty = this.#drag.ty + dy; this.#apply(false);
  }
  #up(e) {
    this.#pts.delete(e.pointerId); this.#pinch = 0;
    if (this.#drag && !this.#drag.moved && this.#pts.size === 0 && this.#focus) this.focusNode(null);
    if (!this.#pts.size) { this.#drag = null; this.svg.classList.remove("grab"); }
  }
  #key(e) {
    const step = 60; let h_ = true;
    if (e.key === "ArrowLeft") this.#tx += step; else if (e.key === "ArrowRight") this.#tx -= step;
    else if (e.key === "ArrowUp") this.#ty += step; else if (e.key === "ArrowDown") this.#ty -= step;
    else if (e.key === "+" || e.key === "=") { this.zoomBy(1.25); return; } else if (e.key === "-") { this.zoomBy(.8); return; }
    else if (e.key === "0") { this.fit(true); return; } else if (e.key === "Escape" && this.#focus) { this.focusNode(null); return; }
    else h_ = false;
    if (h_ && e.target === this.svg) { e.preventDefault(); this.#apply(true); }
  }
}
if (!customElements.get("gb-graph")) customElements.define("gb-graph", GbGraph);
