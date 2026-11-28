/* Decisions: the owner board's cards, and on the first tab the brain's decision records (metadata only) beside them. A decision, a plan or a send that Claude put to the owner, answered here: pick an option
   (saved at once, with the note), or save a note alone. Each card is built once and patched in place when the state changes, so a
   note being typed, a scrolled list and the focus all survive every live update. An answer binds to the card hash the card shows
   now (the patched card), and the board refuses it with 409 when the card changed after that. */
import { h, icon, setText, setAttr, reconcile, toast, fuzzy, highlight } from "../ui.js";
import { store } from "../store.js";
import { pageHead, queryParams, setQuery } from "../shared.js";

const ID = /^\d{8}-\d{6}-\d{6}-[0-9a-f]{4}$/;
const GROUPS = [["close", "Close or keep open"], ["decision", "Decisions"], ["action", "Your actions"], ["parked", "Parked work"]];
const STATUS = [["needs", "Needs you"], ["answered", "Answered"], ["closed", "Closed"]];
const RECORDS = ["records", "Records"];     // the brain's decision records: listed on the first tab only, they belong to no card tab
const RECORD_STATUS = [["active", "Active"], ["superseded", "Superseded"]];
const groupOf = (c) => (GROUPS.some(([g]) => g === c.group) ? c.group : "decision");
const when = (s) => { const d = new Date(s); return isNaN(d) ? String(s ?? "") : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };
const optLabel = (c, v) => c.options.find((o) => o.value === v)?.label ?? v;
const said = (c, a) => (a.option === null ? "with a note" : optLabel(c, a.option));
export const tabLabel = (t) => t.charAt(0).toUpperCase() + t.slice(1);

/* ---------------------------------------------------------------- one card */
function makeCard() {
  const r = {};
  r.kind = h("span", { class: "tag" }); r.seat = h("span", { class: "tag" }, "proposed by a seat"); r.ref = h("span", { class: "dc-ref" });
  r.title = h("h3", { class: "dc-q" });
  r.body = h("p", { class: "dc-ctx" }); r.where = h("p", { class: "dc-where" });
  r.table = h("div", { class: "dc-table" });
  r.details = h("pre", { class: "dc-pre" });
  r.tech = h("details", { class: "dc-tech" }, h("summary", null, "Technical details"), h("pre", { class: "dc-pre" }));
  r.warning = h("p", { class: "dc-warn" });
  r.sha = h("p", { class: "dc-fp" });
  r.opts = h("div", { class: "dc-opts", role: "group", "aria-label": "Answer" });
  r.note = h("textarea", { class: "textarea", rows: "2", placeholder: "Note. Press a choice to send it with that, or Save note to answer with the note alone." });
  r.save = h("button", { class: "btn", type: "button" }, "Save note");
  r.noteRow = h("div", { class: "dc-note" }, r.note, r.save);
  r.status = h("div", { class: "dc-status" });
  const el = h("article", { class: "dcard card" },
    h("div", { class: "dc-top" }, r.kind, r.seat, r.ref), r.title, r.body, r.where, r.table, r.details, r.tech, r.warning, r.sha, r.opts, r.noteRow, r.status);
  el.refs = r;
  r.note.addEventListener("input", () => { r.note.dataset.dirty = "1"; });
  r.save.addEventListener("click", () => {
    if (!r.note.value.trim()) { toast({ title: "Write a note first, or press a choice.", kind: "warn", icon: "alert", life: 3500 }); return; }
    answer(r, null);
  });
  r.opts.addEventListener("click", (e) => { const b = e.target.closest("button[data-v]"); if (b && !b.disabled) answer(r, b.dataset.v); });
  return el;
}

async function answer(r, option) {
  const c = r.card;
  if (!ID.test(c.id)) return;
  try {
    await store.post("/api/answer", { card: c.id, option, note: r.note.value, card_hash: c.card_hash });
  } catch (err) {
    toast({ title: "Not saved", body: err.message, kind: "warn", icon: "alert", life: 7000 });
    if (err.status === 409) store.reload().catch(() => {});
    return;
  }
  delete r.note.dataset.dirty;
  toast({ title: "Saved. Claude will read it.", kind: "action", icon: "checkc", life: 3000 });
  try { await store.reload(); } catch { /* the answer is saved; the stream brings the new state */ }
}

function patchCard(el, c) {
  const r = el.refs; r.card = c;
  const a = c.answer, closed = c.status === "closed", locked = !!c.locked, off = closed || locked;
  el.classList.toggle("void", !!c.voided && !closed);
  el.dataset.status = c.status;
  setText(r.kind, c.kind); r.seat.hidden = c.source !== "inbox";
  r.ref.hidden = !c.ref; setText(r.ref, c.ref || "");
  setText(r.title, c.title); setText(r.body, c.body);
  r.where.hidden = !c.where; setText(r.where, c.where ? "where: " + c.where : "");

  const tsig = JSON.stringify(c.table || []);
  if (r.table.dataset.sig !== tsig) {
    r.table.dataset.sig = tsig;
    r.table.replaceChildren(...(c.table && c.table.length ? [h("table", { class: "dc-t" },
      h("thead", null, h("tr", null, h("th", null, "What"), h("th", { class: "num" }, "Count"), h("th", null, "What goes there"))),
      h("tbody", null, ...c.table.map((row) => h("tr", null, h("td", null, row[0]), h("td", { class: "num" }, row[1]), h("td", null, row[2])))))] : []));
  }
  r.details.hidden = !c.details; setText(r.details, c.details || "");
  r.tech.hidden = !c.tech; setText(r.tech.querySelector("pre"), c.tech || "");
  r.warning.hidden = !c.warning; setText(r.warning, c.warning || "");
  r.sha.hidden = !c.sha256; setText(r.sha, c.sha256 ? `${c.kind === "send" ? "Draft" : "Plan"} ${c.sha256.slice(0, 12)}… (full SHA-256 bound)` : "");

  const osig = JSON.stringify(c.options.map((o) => [o.value, o.label, !!o.rec]));
  if (r.opts.dataset.sig !== osig) {
    r.opts.dataset.sig = osig;
    r.opts.replaceChildren(...c.options.map((o) => h("button", { class: "btn opt", type: "button", dataset: { v: o.value } }, o.label,
      o.rec ? h("span", { class: "rec" }, "recommended") : null)));
  }
  for (const b of r.opts.children) {
    const sel = !!a && a.option === b.dataset.v;
    b.classList.toggle("sel", sel); b.setAttribute("aria-pressed", String(sel)); b.disabled = off;
    b.classList.toggle("primary", sel);
  }
  r.noteRow.hidden = off;
  const served = a ? a.note : "";
  if (r.note.dataset.served !== served) {            // the note the board holds changed: show it unless the owner is typing one
    r.note.dataset.served = served;
    if (!r.note.dataset.dirty && document.activeElement !== r.note) r.note.value = served;
  }

  r.status.replaceChildren(...statusLines(c, a, closed));
}

function statusLines(c, a, closed) {
  const line = (cls, ...kids) => h("p", { class: cls }, ...kids);
  if (closed) {
    return [a ? line("dc-ans", `You answered ${said(c, a)} at ${when(a.at)}`) : null, line("dc-reply", `Claude: ${c.closed.outcome}`), line("dc-ans", `Closed ${when(c.closed.at)}`)];
  }
  if (c.voided) return [line("dc-warn", icon("alert", "ic-sm"), "This card changed after your answer, so your answer no longer counts. Read it again and answer.")];
  if (a && c.locked) {
    return [line("dc-ans", `Answered ${said(c, a)} at ${when(a.at)}`),
      line("dc-ans", icon("lock", "ic-sm"), `Locked: Claude read this at ${when(c.locked)}. To change it, write in "Anything else for Claude".`)];
  }
  if (a) return [line("dc-ans", `Answered ${said(c, a)} at ${when(a.at)}. Not read yet, so you can still change it.`)];
  return [];
}

/* ---------------------------------------------------------------- the view */
class ViewDecisions extends HTMLElement {
  connectedCallback() {
    this.className = "page";
    const p = queryParams(), st = store.state;
    this.tab = st.tabs.includes(p.get("tab")) ? p.get("tab") : st.tabs[0];
    this.sub = this.sections().some(([k]) => k === p.get("s")) ? p.get("s") : "needs";
    this.rq = p.get("q") || ""; this.rstatus = RECORD_STATUS.some(([k]) => k === p.get("status")) ? p.get("status") : "";
    this.grp = p.get("g") || "all";
    this.head = pageHead({ title: tabLabel(this.tab) });
    this.seg = h("gb-segmented", { class: "ph-tabs", "aria-label": "Show cards" });
    this.head.el.querySelector(".ph-tools").append(this.seg);
    this.seg.addEventListener("change", (e) => { this.sub = e.detail; this.persist(); this.render(); });
    this.problems = h("div", { class: "notice", role: "status" });
    this.chips = h("div", { class: "chips", role: "group", "aria-label": "Card groups" });
    this.list = h("div", { class: "dlist" });
    this.empty = h("gb-empty", { icon: "checkc", title: "Nothing needs you", desc: "Claude adds a card when something needs you." });
    this.emptyOther = h("gb-empty", { icon: "inbox", title: "Nothing here yet", desc: "Cards move here after you answer them or Claude closes them." });
    this.freeNote = h("textarea", { class: "textarea", rows: "3", placeholder: "Write it here", "aria-label": "Anything else for Claude" });
    this.freeSave = h("button", { class: "btn", type: "button" }, "Save note");
    this.copyBtn = h("button", { class: "btn ghost", type: "button" }, icon("copy"), "Copy my answers");
    this.freeSave.addEventListener("click", () => this.saveNote());
    this.copyBtn.addEventListener("click", () => this.copyAnswers());
    const note = h("section", { class: "card dc-free", "aria-label": "Anything else for Claude" },
      h("h3", { class: "dc-q" }, "Anything else for Claude"), h("p", { class: "dc-ctx" }, "A new instruction, a correction, or something the cards missed."),
      h("div", { class: "dc-note" }, this.freeNote, this.freeSave), h("div", { class: "dc-copy" }, this.copyBtn));
    this.cardsBody = h("div", { class: "dc-cards" }, h("div", { class: "toolbar" }, this.chips), this.list, this.empty, this.emptyOther, note);
    this.records = this.buildRecords();
    this.append(this.head.el, h("div", { class: "page-body narrow" }, this.problems, this.cardsBody, this.records));
    this.unsub = store.subscribe(() => this.render());
    this.render();
  }
  disconnectedCallback() { this.unsub?.(); }

  persist() {
    const p = new URLSearchParams();
    if (this.tab !== store.state.tabs[0]) p.set("tab", this.tab);
    if (this.sub !== "needs") p.set("s", this.sub);
    if (this.grp !== "all" && this.sub !== RECORDS[0]) p.set("g", this.grp);
    if (this.sub === RECORDS[0]) { if (this.rq) p.set("q", this.rq); if (this.rstatus) p.set("status", this.rstatus); }
    setQuery(p);
  }
  /* The sections of the segmented control: the card statuses, and Records on the first tab. */
  sections() { return this.tab === store.state.tabs[0] ? [...STATUS, RECORDS] : STATUS; }

  buildRecords() {
    const search = h("input", { class: "input", type: "search", placeholder: "Search decision records", "aria-label": "Search decision records", value: this.rq, id: "work-search" });
    search.addEventListener("input", () => { this.rq = search.value; this.persist(); this.renderRecords(); });
    this.rchips = RECORD_STATUS.map(([v, label]) => {
      const b = h("button", { class: "chip", type: "button", "aria-pressed": this.rstatus === v, dataset: { v } }, label);
      b.addEventListener("click", () => { this.rstatus = this.rstatus === v ? "" : v; this.persist(); this.renderRecords(); });
      return b;
    });
    this.rcount = h("span", { class: "result-count", role: "status" });
    this.table = h("gb-table", { class: "panel", label: "Decision records", static: "" });
    this.table.setColumns([
      { key: "title", label: "Record", width: "minmax(0,1fr)", cls: "title", m: "full", cell: {
        init: (td) => { const t = h("div", { class: "cell-title" }), d = h("div", { class: "cell-sub clamp" }); td.append(t, d); return { t, d, td }; },
        update: (r, x) => {
          const q = this.rq.trim(), key = x.title + "|" + q + "|" + (x.supersededBy || "");
          if (r.t.dataset.k !== key) { r.t.dataset.k = key; r.t.textContent = ""; const f = q ? fuzzy(q, x.title) : null; r.t.append(f && f.score > 0 ? highlight(x.title, f.ranges) : x.title, x.supersededBy ? h("span", { class: "sup" }, " superseded by " + x.supersededBy.replace(/-/g, " ")) : ""); }
          setText(r.d, x.description); return false;
        } } },
      { key: "date", label: "Updated", width: "104px", m: "", cell: { init: (td) => { const s = h("span", { class: "muted" }); td.append(s); return { s }; }, update: (r, x) => setText(r.s, x.date || "") } },
      { key: "status", label: "Status", width: "112px", m: "", cell: { init: (td) => { const b = h("gb-badge"); td.append(b); return { b }; }, update: (r, x) => setAttr(r.b, "state", x.status === "superseded" ? "superseded" : "record") } },
    ]);
    this.rempty = h("gb-empty", { icon: "search", title: "No records match", desc: "Try a word from the title or the description." });
    this.rnone = h("gb-empty", { icon: "inbox", title: "No decision records", desc: "A record appears here when the brain keeps one under wiki/decisions." });
    return h("section", { class: "dc-records", "aria-label": "Decision records" },
      h("p", { class: "sec-lede" }, "Each record says why a choice was made. The pages stay in the brain; only the title, description, date and status show here."),
      h("div", { class: "toolbar" }, h("label", { class: "search grow" }, h("span", { class: "sr-only" }, "Search decision records"), icon("search"), search),
        h("div", { class: "chips", role: "group", "aria-label": "Record status" }, ...this.rchips)),
      this.rcount, this.table, this.rempty, this.rnone);
  }
  renderRecords() {
    const all = store.state.records, q = this.rq.trim();
    const rows = all.filter((r) => (!this.rstatus || (r.status === "superseded" ? "superseded" : "active") === this.rstatus) && (!q || fuzzy(q, r.title + " " + r.description).score > 0))
      .sort((a, b) => (b.date || "").localeCompare(a.date || "") || a.title.localeCompare(b.title));
    this.table.rows = rows.map((r) => ({ ...r, id: r.slug }));
    this.table.hidden = !rows.length;
    this.rempty.hidden = !!rows.length || !all.length; this.rnone.hidden = !!all.length;
    for (const b of this.rchips) b.setAttribute("aria-pressed", String(b.dataset.v === this.rstatus));
    setText(this.rcount, all.length ? `${rows.length} of ${all.length} records` : "");
  }

  async saveNote() {
    const v = this.freeNote.value.trim(); if (!v) return;
    try {
      await store.post("/api/note", { note: v, tab: this.tab });
      this.freeNote.value = "";
      toast({ title: "Saved for Claude", kind: "action", icon: "checkc", life: 3000 });
    } catch (err) { toast({ title: "Not saved", body: err.message, kind: "warn", icon: "alert", life: 7000 }); }
  }
  async copyAnswers() {
    try { await navigator.clipboard.writeText(store.state.copy || "No answers yet."); toast({ title: "Copied", body: "Claude also reads your answers directly.", kind: "info", icon: "copy", life: 3000 }); }
    catch { toast({ title: "Copy failed", kind: "warn", icon: "alert", life: 4000 }); }
  }

  render() {
    const st = store.state;
    if (!st.tabs.includes(this.tab)) { this.tab = st.tabs[0]; this.head.title(tabLabel(this.tab)); }
    const inTab = st.cards.filter((c) => c.tab === this.tab);
    const count = (k) => inTab.filter((c) => c.status === k).length;
    const answered = inTab.filter((c) => c.status !== "closed" && c.answer).length, locked = inTab.filter((c) => c.status !== "closed" && c.locked).length;
    this.head.update(`${count("needs")} need you, ${answered} answered, ${locked} locked` + (this.tab === st.tabs[0] ? `, ${st.records.length} record${st.records.length === 1 ? "" : "s"}` : ""));

    if (!this.sections().some(([k]) => k === this.sub)) { this.sub = "needs"; this.persist(); }
    const opts = this.sections().map(([k, l]) => ({ value: k, label: `${l} ${k === RECORDS[0] ? st.records.length : count(k)}` }));
    const key = JSON.stringify(opts);
    if (key !== this.optKey) { this.optKey = key; this.seg.options = opts; }
    this.seg.value = this.sub;

    const probs = st.problems;
    this.problems.hidden = !probs.length;
    setText(this.problems, probs.length ? `Problems in the board's files (tell Claude): ${probs.join("; ")}` : "");

    const recs = this.sub === RECORDS[0];
    this.cardsBody.hidden = recs; this.records.hidden = !recs;
    if (recs) { this.renderRecords(); return; }      // the cards stay as they are, notes being typed included

    const view = inTab.filter((c) => c.status === this.sub), gcount = (g) => view.filter((c) => groupOf(c) === g).length;
    const live = GROUPS.filter(([g]) => gcount(g) > 0);
    if (this.grp !== "all" && !live.some(([g]) => g === this.grp)) this.grp = "all";
    const chips = live.length < 2 ? [] : [["all", "All"], ...live];
    const csig = JSON.stringify(chips.map(([g, l]) => [g, l, g === "all" ? view.length : gcount(g)]));
    if (this.chips.dataset.sig !== csig) {
      this.chips.dataset.sig = csig;
      this.chips.replaceChildren(...chips.map(([g, l]) => h("button", { class: "chip", type: "button", dataset: { g }, onclick: () => { this.grp = g; this.persist(); this.render(); } },
        l, h("span", { class: "n" }, String(g === "all" ? view.length : gcount(g))))));
    }
    for (const b of this.chips.children) b.setAttribute("aria-pressed", String(b.dataset.g === this.grp));

    const shown = view.filter((c) => this.grp === "all" || groupOf(c) === this.grp).filter((c) => ID.test(c.id)).reverse();
    if (this.sub === "needs") shown.sort((a, b) => (b.voided ? 1 : 0) - (a.voided ? 1 : 0));
    reconcile(this.list, shown, { key: (c) => c.id, create: () => makeCard(), update: (el, c) => patchCard(el, c) });
    this.empty.hidden = !(this.sub === "needs" && !shown.length);
    this.emptyOther.hidden = !(this.sub !== "needs" && !shown.length);
    this.list.hidden = !shown.length;
  }
}
customElements.define("gb-view-decisions", ViewDecisions);
