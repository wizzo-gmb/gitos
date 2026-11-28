/* ui.js - the component kit. Native custom elements (light DOM, so a repo's theme.css reaches every part),
   plus the small helpers every view uses. No framework, no dependency. A repo view imports this file and
   composes: <gb-badge>, <gb-sev>, <gb-strip>, <gb-order-card>, <gb-table>, <gb-segmented>, <gb-stat>,
   <gb-empty>, <gb-skeleton>, <gb-drawer>, <gb-palette>, <gb-conn>, <gb-graph> (graph.js), toast(), openMenu(),
   confirmDialog(), reconcile(). */

/* ---------------------------------------------------------------- helpers */
export const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null) continue;
    if (k.startsWith("aria-")) { el.setAttribute(k, String(v)); continue; }
    if (v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") { for (const [sk, sv] of Object.entries(v)) { if (sk.startsWith("--")) el.style.setProperty(sk, sv); else el.style[sk] = sv; } }
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
}

const ICONS = {
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" stroke-width="2.4"/>',
  board: '<rect x="3.5" y="4" width="5" height="16" rx="1.5"/><rect x="10" y="4" width="5" height="10" rx="1.5"/><rect x="16.5" y="4" width="4" height="13" rx="1.5"/>',
  graph: '<circle cx="5.5" cy="12" r="2.5"/><circle cx="18.5" cy="5.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/><path d="m8 10.8 8.2-4M8 13.2l8.2 4"/>',
  sprint: '<path d="M4 12a8 8 0 0 1 14-5.3L20 9"/><path d="M20 4v5h-5"/><path d="M20 12a8 8 0 0 1-14 5.3L4 15"/><path d="M4 20v-5h5"/>',
  decision: '<path d="M12 3v18M8 21h8"/><path d="M12 5.5h6l2 2.5-2 2.5h-6M12 12.5H6L4 15l2 2.5h6"/>',
  inbox: '<path d="M4 13l2-7h12l2 7v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M4 13h5l1 2h4l1-2h5"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M8 3v4M16 3v4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  command: '<path d="M9 9V6.5A2.5 2.5 0 1 0 6.5 9H9zm0 0h6m-6 0v6m6-6V6.5A2.5 2.5 0 1 1 17.5 9H15zm0 0v6m0 0H9m6 0h2.5a2.5 2.5 0 1 1-2.5 2.5V15zm-6 0H6.5A2.5 2.5 0 1 0 9 17.5V15z"/>',
  right: '<path d="m9 6 6 6-6 6"/>', down: '<path d="m6 9 6 6 6-6"/>', up: '<path d="m6 15 6-6 6 6"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>', plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>',
  fit: '<path d="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4h-7A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8"/>',
  pause: '<path d="M9 5.5v13M15 5.5v13"/>', play: '<path d="M8 5.5v13l11-6.5z"/>',
  park: '<rect x="3.5" y="4" width="17" height="4.5" rx="1.5"/><path d="M5 8.5V19a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8.5M10 12.5h4"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  checkc: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  zap: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  file: '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  note: '<path d="M5 4h14v11.5L14.5 20H5z"/><path d="M14 20v-5h5M8 9h8M8 12.5h4"/>',
  out: '<path d="M7 17 17 7M8.5 7H17v8.5"/>',
  sort: '<path d="M12 5v14m0 0-5-5m5 5 5-5"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/>',
  alert: '<path d="M12 4 3 19.5h18z"/><path d="M12 10v4.5M12 17.2v.3"/>',
  wifi: '<path d="M2.5 9.5a14 14 0 0 1 19 0M5.5 13a9.5 9.5 0 0 1 13 0M8.8 16.4a5 5 0 0 1 6.4 0"/><path d="M12 19.5v.01" stroke-width="2.4"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>',
  layers: '<path d="m12 3.5 9 4.5-9 4.5L3 8z"/><path d="m3 12.5 9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>',
  folder: '<path d="M3.5 7.5a1.5 1.5 0 0 1 1.5-1.5h4l2 2.5h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
  home: '<path d="M4 11 12 4l8 7M6 9.5V20h12V9.5M10 20v-5h4v5"/>',
  flag: '<path d="M5 21V4M5 5h12l-2 4 2 4H5"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
  sparkle: '<path d="M12 3.5 14 10l6.5 2-6.5 2L12 20.5 10 14l-6.5-2L10 10z"/>',
  tag: '<path d="M3.5 12.5V4.5a1 1 0 0 1 1-1h8l8 8-9 9z"/><path d="M8.5 8.5h.01" stroke-width="2.4"/>',
  history: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 4v4.5h4.5M12 8v4.5l3 1.5"/>',
};
export function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "ic " + cls); s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false");
  s.innerHTML = ICONS[name] || ICONS.dot;
  return s;
}

export function setText(el, text) {
  text = text == null ? "" : String(text);
  if (el.textContent === text) return false;
  el.textContent = text; return true;
}
export function setAttr(el, name, value) {
  const cur = el.getAttribute(name);
  if (value == null || value === false) { if (cur == null) return false; el.removeAttribute(name); return true; }
  const v = value === true ? "" : String(value);
  if (cur === v) return false;
  el.setAttribute(name, v); return true;
}
/* Restart a one-shot CSS animation class on an element (a row that just changed under the operator's eyes). */
export function flash(el, cls = "flash") {
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
  el.addEventListener("animationend", () => el.classList.remove(cls), { once: true });
}

export function relTime(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 5) return "just now";
  if (s < 60) return s + " s ago";
  const m = Math.round(s / 60);
  if (m < 60) return m + " min ago";
  return Math.round(m / 60) + " h ago";
}

export function fuzzy(q, text) {
  q = q.trim().toLowerCase(); if (!q) return { score: 1, ranges: [] };
  const t = text.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) return { score: 100 - at + (at === 0 ? 40 : 0) - (t.length - q.length) * .05, ranges: [[at, at + q.length]] };
  const words = q.split(/\s+/); const ranges = []; let score = 50;
  for (const w of words) { const i = t.indexOf(w); if (i < 0) { ranges.length = 0; score = 0; break; } ranges.push([i, i + w.length]); score += 10; }
  if (score) return { score, ranges: ranges.sort((a, b) => a[0] - b[0]) };
  return { score: 0, ranges: [] };
}
export function highlight(text, ranges) {
  if (!ranges || !ranges.length) return document.createTextNode(text);
  const f = document.createDocumentFragment(); let p = 0;
  for (const [a, b] of ranges) { if (a < p) continue; f.append(text.slice(p, a)); f.append(h("mark", null, text.slice(a, b))); p = b; }
  f.append(text.slice(p)); return f;
}

/* Wrap a DOM change in the View Transitions API where the browser has it; apply it plainly where it does not. */
export function viewTransition(update) {
  if (!document.startViewTransition || reduced()) { update(); return null; }
  try { return document.startViewTransition(() => { update(); }); } catch { update(); return null; }
}

/* ---------------------------------------------------------------- keyed reconciliation
   Patch a container to match `items` without rebuilding it: existing rows are updated in place,
   new rows animate in, removed rows animate out, moved rows glide (FLIP). Scroll, focus and open
   state live on the elements, so they survive every update. */
export function reconcile(parent, items, { key, create, update, move = true }) {
  const have = new Map();
  for (const el of parent.children) if (el.__key !== undefined && !el.classList.contains("is-leaving")) have.set(el.__key, el);
  const animate = move && !reduced();
  const first = animate ? new Map([...have].map(([k, el]) => [k, el.getBoundingClientRect()])) : null;
  const seen = new Set();
  let prev = null;
  for (const item of items) {
    const k = key(item);
    let el = have.get(k);
    if (!el) {
      el = create(item); el.__key = k; el.__item = item;
      update?.(el, item, null);
      el.classList.add("is-entering");
      el.addEventListener("animationend", (e) => { if (e.target === el) el.classList.remove("is-entering"); }, { once: true });
      setTimeout(() => el.classList.remove("is-entering"), 700);
    } else {
      const old = el.__item; el.__item = item;
      update?.(el, item, old);
    }
    const ref = prev ? prev.nextSibling : parent.firstChild;
    if (el !== ref) parent.insertBefore(el, ref);
    prev = el; seen.add(k);
  }
  for (const [k, el] of have) if (!seen.has(k)) {
    el.classList.add("is-leaving");
    el.removeAttribute("tabindex");
    const rm = () => el.remove();
    el.addEventListener("animationend", rm, { once: true });
    setTimeout(rm, 450);
  }
  if (animate) for (const [k, el] of have) {
    if (!seen.has(k)) continue;
    const a = first.get(k), b = el.getBoundingClientRect();
    const dx = a.left - b.left, dy = a.top - b.top;
    if ((Math.abs(dx) > 1 || Math.abs(dy) > 1) && !el.classList.contains("is-entering")) {
      el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
  }
}

/* ---------------------------------------------------------------- labels */
export const LABELS = {
  active: "In progress", "in-progress": "In progress", awaiting: "Awaiting accept", ready: "Can start", waiting: "Waiting", held: "Held", parked: "Parked",
  landed: "Landed", implemented: "Implemented", proposed: "Proposed", dropped: "Dropped",
  running: "Running", closing: "Stopping", gate: "Needs you", stopped: "Stopped", stale: "No driver",
  open: "Open", answered: "Answered", superseded: "Superseded", record: "Active", pending: "Pending", confirmed: "Confirmed", applied: "Applied", rejected: "Rejected", sample: "Sample",
};

/* ---------------------------------------------------------------- <gb-badge state="active"> */
class GbBadge extends HTMLElement {
  static observedAttributes = ["state", "label"];
  connectedCallback() { this.render(); }
  attributeChangedCallback() { this.render(); }
  render() {
    const st = this.getAttribute("state") === "in-progress" ? "active" : this.getAttribute("state");
    if (st !== this.getAttribute("state") && st) { this.setAttribute("state", st); return; }
    if (this.hasAttribute("compact")) { this.title = LABELS[st] || st; this.textContent = ""; return; }
    setText(this, this.getAttribute("label") ?? LABELS[st] ?? st ?? "");
  }
}

/* <gb-sev level="medium"> */
class GbSev extends HTMLElement {
  static observedAttributes = ["level"];
  connectedCallback() { if (!this.firstChild) { this.append(h("i", null, h("b"), h("b"), h("b")), h("span")); } this.render(); }
  attributeChangedCallback() { if (this.firstChild) this.render(); }
  render() { const l = this.getAttribute("level") || ""; setText(this.querySelector("span"), l.charAt(0).toUpperCase() + l.slice(1)); this.setAttribute("aria-label", "Severity " + l); }
}

/* <gb-strip> one segment per slice, in the slice's state; .set(["landed","in-progress",...], "1/8 slices").
   When the segments would each fall below STRIP_MIN px in the room the strip has (re-measured when that room changes), they become
   one continuous bar: a run of equal states is one piece sized by its length, so the strip fits its container at any count and
   the label beside it is never covered. */
const STRIP_MIN = 6, STRIP_SEGS = 8;   // STRIP_SEGS: the count past which a strip is a bar while its room is still unknown
class GbStrip extends HTMLElement {
  #args = null;
  connectedCallback() {
    if (this.querySelector(".segs")) return;
    const segs = h("span", { class: "segs", role: "img" });
    this.append(segs, h("span", { class: "num" }));
    new ResizeObserver(() => { if (this.#args) this.set(...this.#args); }).observe(segs);
  }
  set(states, text, label) {
    this.connectedCallback();
    this.#args = [states, text, label];
    const segs = this.querySelector(".segs"), room = segs.clientWidth;
    const bar = room ? states.length * (STRIP_MIN + 2) - 2 > room : states.length > STRIP_SEGS;
    const items = [];
    for (const s of states) { const last = items[items.length - 1]; if (bar && last && last[0] === s) last[1]++; else items.push([s, 1]); }
    if (segs.hasAttribute("data-bar") !== bar) { segs.toggleAttribute("data-bar", bar); segs.replaceChildren(); }
    while (segs.children.length < items.length) segs.append(h("i", { class: "seg" }));
    while (segs.children.length > items.length) segs.lastChild.remove();
    items.forEach(([s, n], i) => {
      const seg = segs.children[i];
      const was = seg.dataset.s;
      if (bar) seg.style.flexGrow = n; else seg.style.removeProperty("flex-grow");
      if (was !== s) { seg.dataset.s = s; if (!bar && was && s === "landed") { seg.classList.remove("pop"); void seg.offsetWidth; seg.classList.add("pop"); } }
    });
    const num = this.querySelector(".num"); setText(num, text || ""); num.hidden = !text;
    segs.setAttribute("aria-label", label || states.map((s) => LABELS[s] || s).join(", "));
  }
}

/* <gb-stat label value hint> */
class GbStat extends HTMLElement {
  static observedAttributes = ["label", "value", "hint"];
  connectedCallback() { if (!this.firstChild) this.append(h("span", { class: "s-v" }), h("span", { class: "s-l" }), h("span", { class: "s-h" })); this.render(); }
  attributeChangedCallback() { if (this.firstChild) this.render(); }
  render() {
    const v = this.querySelector(".s-v"), had = v.textContent;
    if (setText(v, this.getAttribute("value")) && had && had !== "-") flash(v);
    setText(this.querySelector(".s-l"), this.getAttribute("label")); const hi = this.querySelector(".s-h"); setText(hi, this.getAttribute("hint")); hi.hidden = !this.hasAttribute("hint");
  }
}

/* <gb-empty icon title desc> + slotted action */
class GbEmpty extends HTMLElement {
  connectedCallback() {
    if (this.querySelector(".e-t")) return;
    const kids = [...this.childNodes];
    this.textContent = "";
    this.append(h("div", { class: "e-ic" }, icon(this.getAttribute("icon") || "sparkle")), h("div", { class: "e-t" }, this.getAttribute("title") || ""), h("div", { class: "e-d" }, this.getAttribute("desc") || ""), ...kids);
  }
}

/* <gb-skeleton lines="3"> */
class GbSkeleton extends HTMLElement {
  connectedCallback() {
    const n = +this.getAttribute("lines") || 3; const w = [88, 64, 76, 52, 70];
    this.setAttribute("aria-hidden", "true");
    this.style.display = "grid"; this.style.gap = "10px";
    for (let i = 0; i < n; i++) this.append(h("i", { class: "sk", style: { width: w[i % w.length] + "%", height: i === 0 ? "16px" : "12px" } }));
  }
}

/* <gb-segmented> .options=[{value,label,icon}] .value */
class GbSegmented extends HTMLElement {
  #value; #options = [];
  connectedCallback() { this.setAttribute("role", "radiogroup"); this.addEventListener("keydown", this.#key); this.ro ||= new ResizeObserver(() => this.#thumb(false)); this.ro.observe(this); }
  disconnectedCallback() { this.ro?.disconnect(); }
  set options(o) {
    this.#options = o; this.textContent = ""; this.append(h("span", { class: "thumb" }));
    for (const op of o) this.append(h("button", { type: "button", role: "radio", dataset: { v: op.value }, "aria-label": op.label, onclick: () => this.set(op.value, true) }, op.icon ? icon(op.icon) : null, h("span", null, op.label)));
    this.#sync(false);
  }
  get value() { return this.#value; }
  set value(v) { this.set(v, false); }
  set(v, user) { if (v === this.#value) return; this.#value = v; this.#sync(!!user && this.isConnected); if (user) this.dispatchEvent(new CustomEvent("change", { detail: v, bubbles: true })); }
  #sync(animate) {
    for (const b of this.querySelectorAll("button")) { const on = b.dataset.v === this.#value; b.setAttribute("aria-checked", on); b.tabIndex = on || (!this.#value && b === this.querySelector("button")) ? 0 : -1; }
    this.#thumb(animate);
  }
  #thumb(animate) {
    const t = this.querySelector(".thumb"), b = this.querySelector('button[aria-checked="true"]');
    if (!t || !b || !b.offsetWidth) { if (t) t.style.width = "0"; return; }
    if (!animate) t.style.transition = "none";
    t.style.width = b.offsetWidth + "px"; t.style.transform = `translateX(${b.offsetLeft}px)`;
    if (!animate) { void t.offsetWidth; t.style.transition = ""; }
  }
  #key = (e) => {
    const i = this.#options.findIndex((o) => o.value === this.#value); let n = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % this.#options.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + this.#options.length) % this.#options.length;
    if (n >= 0) { e.preventDefault(); this.set(this.#options[n].value, true); this.querySelectorAll("button")[n].focus(); }
  };
}

/* ---------------------------------------------------------------- <gb-order-card> */
class GbOrderCard extends HTMLElement {
  connectedCallback() {
    if (this.refs) return;
    this.tabIndex = 0; this.setAttribute("role", "button");
    const r = this.refs = {
      id: h("span", { class: "oc-id" }), sev: h("gb-sev"), pend: h("gb-badge", { state: "pending", compact: "" }), sp: h("span", { class: "spacer" }),
      title: h("div", { class: "oc-title" }), strip: h("gb-strip"), note: h("div", { class: "oc-note" }),
    };
    r.foot = h("div", { class: "oc-foot" }, r.strip);
    r.pend.hidden = true;
    this.append(h("div", { class: "oc-top" }, r.id, r.sp, r.pend, r.sev), r.title, r.foot, r.note);
    this.addEventListener("click", () => this.#open());
    this.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.#open(); } });
    if (this._order) this.render();
  }
  #open() { this.dispatchEvent(new CustomEvent("open-order", { detail: this._order.id, bubbles: true })); }
  set order(o) { const prev = this._order; this._order = o; if (this.refs) this.render(prev); }
  get order() { return this._order; }
  render(prev) {
    const o = this._order, r = this.refs;
    setText(r.id, "WO-" + o.id);
    setAttr(r.sev, "level", o.sev);
    setText(r.title, o.title); setAttr(r.title, "title", o.title);
    r.pend.hidden = !o.pending;
    r.strip.hidden = r.foot.hidden = !o.total;
    if (o.total) r.strip.set(o.slices.map((s) => s.state), o.awaiting ? "acceptance open" : `${o.done}/${o.total}`, `${o.done} of ${o.total} slices landed`);
    r.note.textContent = "";
    if (o.parked && o.trigger) r.note.append(icon("park"), h("span", null, "Until: " + o.trigger));
    else if (o.waitsOn.length) r.note.append(icon("link"), h("span", null, "Waits on " + o.waitsOn.map((i) => "WO-" + i).join(", ")));
    else if (o.status === "ready" && o.approved) r.note.append(icon("check"), h("span", null, "Approved for dispatch"));
    r.note.hidden = !r.note.childNodes.length;
    if (prev && (prev.status !== o.status || prev.done !== o.done || prev.sev !== o.sev)) flash(this, "flash-ring");
  }
}

/* ---------------------------------------------------------------- <gb-table> */
class GbTable extends HTMLElement {
  columns = []; rowKey = (r) => r.id; sortKey = null; sortDir = "asc"; label = "Table";
  connectedCallback() {
    if (this.head) return;
    this.setAttribute("role", "table"); this.setAttribute("aria-label", this.label);
    this.head = h("div", { class: "thead", role: "row" }); this.body = h("div", { class: "tbody", role: "rowgroup" });
    this.append(this.head, this.body);
    this.body.addEventListener("keydown", (e) => {
      const row = e.target.closest?.(".tr"); if (!row) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const rows = [...this.body.querySelectorAll(".tr:not(.is-leaving)")]; rows[rows.indexOf(row) + (e.key === "ArrowDown" ? 1 : -1)]?.focus(); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.#activate(row); }
    });
    this.body.addEventListener("click", (e) => { const row = e.target.closest(".tr"); if (row && !e.target.closest("a,button")) this.#activate(row); });
    this.#buildHead(); if (this._rows) this.rows = this._rows;
  }
  #activate(row) { this.dispatchEvent(new CustomEvent("row-open", { detail: row.__item, bubbles: true })); }
  setColumns(cols) { this.columns = cols; if (this.head) this.#buildHead(); }
  #buildHead() {
    this.style.setProperty("--cols", this.columns.map((c) => c.width || "1fr").join(" "));
    this.head.textContent = "";
    for (const c of this.columns) {
      const th = h(c.sortable ? "button" : "div", { class: "th", role: "columnheader", type: c.sortable ? "button" : null, dataset: c.sortable ? { sortable: "", k: c.key } : { k: c.key }, "data-m": c.m },
        c.label, c.sortable ? icon("sort") : null);
      if (c.align === "end") th.style.justifyContent = "flex-end";
      if (c.sortable) th.addEventListener("click", () => {
        this.sortDir = this.sortKey === c.key && this.sortDir === "asc" ? "desc" : "asc"; this.sortKey = c.key; this.#markSort();
        this.dispatchEvent(new CustomEvent("sort", { detail: { key: c.key, dir: this.sortDir }, bubbles: true }));
      });
      this.head.append(th);
    }
    this.#markSort();
  }
  #markSort() { for (const th of this.head.children) { if (th.dataset.k === this.sortKey) th.setAttribute("aria-sort", this.sortDir === "asc" ? "ascending" : "descending"); else th.removeAttribute("aria-sort"); } }
  setSort(key, dir) { this.sortKey = key; this.sortDir = dir; if (this.head) this.#markSort(); }
  set rows(r) {
    this._rows = r; if (!this.body) return;
    reconcile(this.body, r, {
      key: this.rowKey,
      create: (row) => {
        const tr = h("div", { class: "tr", role: "row", tabindex: 0 }); tr.cells = [];
        this.columns.forEach((c) => { const td = h("div", { class: "td " + (c.cls || ""), role: "cell", "data-m": c.m }); tr.cells.push(c.cell.init(td, row)); tr.append(td); });
        this.columns.forEach((c, i) => c.cell.update(tr.cells[i], row, null));
        if (this.selected === this.rowKey(row)) tr.dataset.selected = "";
        return tr;
      },
      update: (tr, row, old) => {
        let changed = false;
        this.columns.forEach((c, i) => { if (c.cell.update(tr.cells[i], row, old)) changed = true; });
        if (changed) flash(tr);
        if (this.selected === this.rowKey(row)) tr.dataset.selected = ""; else delete tr.dataset.selected;
      },
    });
  }
  get rows() { return this._rows || []; }
  select(key) { this.selected = key; for (const tr of this.body?.children || []) { if (tr.__key === key) tr.dataset.selected = ""; else delete tr.dataset.selected; } }
}

/* ---------------------------------------------------------------- <gb-drawer> */
class GbDrawer extends HTMLElement {
  connectedCallback() {
    if (this.sheet) return;
    this.backdrop = h("div", { class: "backdrop", onclick: () => this.close(true) });
    this.body = h("div", { class: "sheet-body" });
    this.sheet = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", tabindex: -1 }, this.body);
    this.append(this.backdrop, this.sheet);
    this.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.hasAttribute("open")) { e.stopPropagation(); this.close(true); }
      if (e.key === "Tab" && this.hasAttribute("open")) {
        const f = [...this.sheet.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,[tabindex="0"]')].filter((x) => x.offsetParent !== null);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === this.sheet)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
  }
  get isOpen() { return this.hasAttribute("open"); }
  open(label) {
    if (label) this.sheet.setAttribute("aria-label", label);
    if (!this.isOpen) { this.restore = document.activeElement; this.setAttribute("open", ""); setTimeout(() => (this.sheet.querySelector("[data-autofocus]") || this.sheet).focus({ preventScroll: true }), 30); }
  }
  close(user) {
    if (!this.isOpen) return;
    this.removeAttribute("open");
    this.dispatchEvent(new CustomEvent("close", { detail: { user }, bubbles: true }));
    const r = this.restore; this.restore = null; if (r && r.isConnected) r.focus({ preventScroll: true });
  }
}

/* ---------------------------------------------------------------- toasts, menus, dialogs */
class GbToasts extends HTMLElement {
  connectedCallback() { this.setAttribute("role", "region"); this.setAttribute("aria-label", "Notifications"); this.setAttribute("aria-live", "polite"); }
}
export function toast({ title, body, kind = "info", icon: ic = "bell", action, life = 6500 }) {
  const host = document.querySelector("gb-toasts"); if (!host) return;
  while (host.children.length >= 4) host.firstElementChild.remove();
  const el = h("div", { class: "toast", dataset: { kind }, style: { "--life": life + "ms" } },
    icon(ic), h("div", null, h("div", { class: "tt" }, title), body ? h("div", { class: "tb" }, body) : null),
    h("div", { class: "ta" },
      action ? h("button", { class: "btn sm", type: "button", onclick: () => { action.onClick(); dismiss(); } }, action.label) : null,
      h("button", { class: "btn sm icon ghost", type: "button", "aria-label": "Dismiss", onclick: () => dismiss() }, icon("x"))),
    h("i", { class: "timer" }));
  const dismiss = () => { if (el.classList.contains("out")) return; el.classList.add("out"); setTimeout(() => el.remove(), 300); };
  const t = setTimeout(dismiss, life);
  el.addEventListener("mouseenter", () => clearTimeout(t), { once: true });
  host.append(el);
  return dismiss;
}

let openMenuEl = null, menuCleanup = null;
export function closeMenu() { openMenuEl?.remove(); openMenuEl = null; menuCleanup?.(); menuCleanup = null; }
export function openMenu(anchor, items, { align = "end" } = {}) {
  closeMenu();
  const m = h("div", { class: "menu", role: "menu" });
  const btns = [];
  for (const it of items) {
    if (it.sep) { m.append(h("div", { class: "menu-sep", role: "separator" })); continue; }
    if (it.heading) { m.append(h("div", { class: "menu-label" }, it.heading)); continue; }
    const b = h("button", { class: "menu-item", role: "menuitem", type: "button", onclick: () => { closeMenu(); it.run(); } }, it.icon ? icon(it.icon) : null, h("span", null, it.label), it.hint ? h("span", { class: "hint" }, it.hint) : null);
    btns.push(b); m.append(b);
  }
  document.body.append(m); openMenuEl = m;
  const r = anchor.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;
  let left = align === "end" ? r.right - mw : r.left; left = Math.max(8, Math.min(left, innerWidth - mw - 8));
  let top = r.bottom + 6; if (top + mh > innerHeight - 8) top = Math.max(8, r.top - mh - 6);
  m.style.left = left + "px"; m.style.top = top + "px";
  btns[0]?.focus();
  const off = (e) => { if (!m.contains(e.target)) { closeMenu(); cleanup(); } };
  const key = (e) => {
    if (e.key === "Escape") { e.preventDefault(); closeMenu(); cleanup(); anchor.focus?.(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const i = btns.indexOf(document.activeElement); btns[(i + (e.key === "ArrowDown" ? 1 : -1) + btns.length) % btns.length]?.focus(); }
    else if (e.key === "Tab") { closeMenu(); cleanup(); }
  };
  const cleanup = () => { document.removeEventListener("pointerdown", off, true); document.removeEventListener("keydown", key, true); };
  menuCleanup = cleanup;
  setTimeout(() => { if (openMenuEl === m) { document.addEventListener("pointerdown", off, true); document.addEventListener("keydown", key, true); } }, 0);
  return m;
}

/* The board's own confirm. Resolves to the field values, or null when cancelled. Shows the state the owner saw. */
export function confirmDialog({ title, body, fields = [], confirm = "Confirm", danger = false, seen }) {
  return new Promise((resolve) => {
    const dlg = h("dialog", { class: "dlg", "aria-labelledby": "dlg-t" });
    const inputs = {};
    const fieldEls = fields.map((f) => {
      let ctl;
      if (f.type === "select") ctl = h("select", { class: "select", id: "f-" + f.name }, f.options.map((o) => h("option", { value: o.value ?? o, selected: (o.value ?? o) === f.value }, o.label ?? o)));
      else if (f.type === "textarea") ctl = h("textarea", { class: "textarea", id: "f-" + f.name, placeholder: f.placeholder || "", rows: 3 }, f.value || "");
      else ctl = h("input", { class: "input", id: "f-" + f.name, placeholder: f.placeholder || "", value: f.value || "" });
      if (f.required) ctl.required = true;
      inputs[f.name] = ctl;
      return h("div", { class: "field" }, h("label", { for: "f-" + f.name }, f.label), ctl);
    });
    const ok = h("button", { class: "btn " + (danger ? "danger" : "primary"), type: "submit" }, confirm);
    const cancel = h("button", { class: "btn", type: "button", onclick: () => dlg.close("cancel") }, "Cancel");
    const form = h("form", { method: "dialog" },
      h("div", { class: "dlg-head" }, h("h2", { id: "dlg-t" }, title), body ? h("p", null, body) : null),
      h("div", { class: "dlg-body" }, ...fieldEls, seen ? h("div", { class: "dlg-seen" }, icon("check", "ic-sm"), h("span", null, seen)) : null),
      h("div", { class: "dlg-foot" }, cancel, ok));
    dlg.append(form);
    let result = null;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      for (const c of Object.values(inputs)) if (!c.reportValidity()) return;
      result = Object.fromEntries(Object.entries(inputs).map(([k, c]) => [k, c.value.trim()]));
      dlg.close("ok");
    });
    dlg.addEventListener("close", () => { dlg.remove(); resolve(result); });
    document.body.append(dlg);
    dlg.showModal();
    (danger ? cancel : Object.values(inputs)[0] || ok).focus();   // a destructive confirm starts on Cancel: Enter does not do it
  });
}

/* ---------------------------------------------------------------- <gb-conn> */
class GbConn extends HTMLElement {
  connectedCallback() {
    if (this.firstChild) return;
    this.setAttribute("role", "status");
    this.append(h("span", { class: "pip" }), h("span", { class: "lbl" }), h("span", { class: "age" }));
    this.render();
  }
  static observedAttributes = ["state"];
  attributeChangedCallback() { if (this.firstChild) this.render(); }
  render() { setText(this.querySelector(".lbl"), { reconnecting: "Reconnecting", down: "Offline" }[this.getAttribute("state")] || "Live"); }
  age(text) { const a = this.querySelector(".age"); if (a) setText(a, this.getAttribute("state") === "live" ? text : ""); }
}

/* ---------------------------------------------------------------- <gb-palette> (command palette)
   .source = (query) => [{ group, items: [{ id, label, sub, icon, hint, run }] }]; the host decides what exists. */
class GbPalette extends HTMLElement {
  source = () => []; flat = []; idx = 0;
  connectedCallback() {
    if (this.box) return;
    this.input = h("input", { type: "text", placeholder: "Jump to an order, a view or an action", "aria-label": "Command palette", role: "combobox", "aria-expanded": "true", "aria-controls": "pal-list", autocomplete: "off", spellcheck: "false" });
    this.list = h("div", { class: "list", role: "listbox", id: "pal-list" });
    this.box = h("div", { class: "box", role: "dialog", "aria-modal": "true", "aria-label": "Command palette" },
      h("div", { class: "q" }, icon("search"), this.input, h("kbd", null, "Esc")), this.list,
      h("div", { class: "foot" }, h("span", null, h("kbd", null, "↑"), h("kbd", null, "↓"), "move"), h("span", null, h("kbd", null, "↵"), "run"), h("span", null, h("kbd", null, "Esc"), "close")));
    this.append(h("div", { class: "backdrop", onclick: () => this.close() }), this.box);
    this.input.addEventListener("input", () => { this.idx = 0; this.render(); });
    this.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); this.close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); this.move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); this.move(-1); }
      else if (e.key === "Enter") { e.preventDefault(); this.run(this.idx); }
      else if (e.key === "Tab") { e.preventDefault(); }
    });
  }
  open(initial = "") { this.restore = document.activeElement; this.setAttribute("open", ""); this.input.value = initial; this.idx = 0; this.render(); this.input.focus(); }
  close() { if (!this.hasAttribute("open")) return; this.removeAttribute("open"); this.restore?.focus?.({ preventScroll: true }); }
  move(d) { if (!this.flat.length) return; this.idx = (this.idx + d + this.flat.length) % this.flat.length; this.mark(true); }
  mark(scroll) {
    this.list.querySelectorAll(".opt").forEach((o, i) => o.setAttribute("aria-selected", i === this.idx));
    const cur = this.list.querySelectorAll(".opt")[this.idx]; if (cur) { this.input.setAttribute("aria-activedescendant", cur.id); if (scroll) cur.scrollIntoView({ block: "nearest" }); }
  }
  run(i) { const it = this.flat[i]; if (!it) return; this.close(); it.run(); }
  render() {
    const q = this.input.value; const groups = this.source(q);
    this.list.textContent = ""; this.flat = [];
    for (const g of groups) {
      if (!g.items.length) continue;
      this.list.append(h("div", { class: "grp", role: "presentation" }, g.group));
      for (const it of g.items) {
        const i = this.flat.length; this.flat.push(it);
        this.list.append(h("div", { class: "opt", role: "option", id: "pal-" + i, onclick: () => this.run(i), onpointermove: () => { if (this.idx !== i) { this.idx = i; this.mark(false); } } },
          icon(it.icon || "dot"), h("span", { class: "o-main" }, it.ranges ? highlight(it.label, it.ranges) : it.label), it.sub ? h("span", { class: "o-sub" }, it.sub) : null, it.hint ? h("kbd", null, it.hint) : null));
      }
    }
    if (!this.flat.length) this.list.append(h("gb-empty", { dense: "", title: "Nothing matches", desc: "Try an order number, a view name, or a word from a title." }));
    this.idx = Math.min(this.idx, Math.max(0, this.flat.length - 1)); this.mark(false);
  }
}

for (const [n, c] of Object.entries({ "gb-badge": GbBadge, "gb-sev": GbSev, "gb-strip": GbStrip, "gb-stat": GbStat, "gb-empty": GbEmpty, "gb-skeleton": GbSkeleton, "gb-segmented": GbSegmented, "gb-order-card": GbOrderCard, "gb-table": GbTable, "gb-drawer": GbDrawer, "gb-toasts": GbToasts, "gb-conn": GbConn, "gb-palette": GbPalette }))
  if (!customElements.get(n)) customElements.define(n, c);
