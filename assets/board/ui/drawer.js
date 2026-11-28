/* drawer.js - order detail, shown in the side drawer over whatever view is open.
   Built once per order, then patched in place on every store update, so a slice landing under an open
   drawer changes one segment and one row, and the scroll position never moves. */
import { h, icon, setText, setAttr, reconcile, toast, relTime } from "./ui.js";
import { store } from "./store.js";
import { go } from "./shared.js";
import { actionLabel, actionsMenu, requestAction } from "./actions.js";

const chipLink = (label, onclick) => h("button", { class: "g-chip", type: "button", onclick }, label);

export function createOrderPanel(id, { onClose }) {
  const r = {};
  r.id = h("span", { class: "oid" }); r.sev = h("gb-sev"); r.state = h("gb-badge"); r.pend = h("gb-badge", { state: "pending", label: "Pending" });
  r.close = h("button", { class: "btn icon sm ghost", type: "button", "aria-label": "Close", "data-autofocus": "", onclick: onClose }, icon("x"));
  r.graph = h("button", { class: "btn sm ghost", type: "button", title: "Show this order in the graph", onclick: () => go("work/graph?focus=" + id) }, icon("graph"), h("span", null, "Show in graph"));
  r.title = h("h2", { class: "od-title" });
  r.strip = h("gb-strip", { size: "lg" }); r.prog = h("div", { class: "od-prog-text" });
  r.waits = h("div", { class: "od-chips" }); r.blocks = h("div", { class: "od-chips" });
  r.depsSec = h("section", { class: "od-sec" }, h("h3", null, "Dependencies"),
    h("div", { class: "od-deprow" }, h("span", null, "Waits on"), r.waits), h("div", { class: "od-deprow" }, h("span", null, "Waited on by"), r.blocks));
  r.slices = h("ol", { class: "od-slices" });
  r.slicesSec = h("section", { class: "od-sec" }, h("h3", null, "Slices"), r.slices);
  r.path = h("code", { class: "path" });
  r.copy = h("button", { class: "btn icon sm ghost", type: "button", "aria-label": "Copy file path", title: "Copy path" }, icon("copy"));
  r.dl = h("dl", { class: "od-dl" });
  r.acts = h("button", { class: "btn sm", type: "button", "aria-haspopup": "menu" }, "Owner actions", icon("down"));
  r.quick = h("div", { class: "od-quick" });
  r.act = h("ul", { class: "activity", "aria-label": "Requests on this order" });
  r.actEmpty = h("p", { class: "muted small" }, "No owner actions yet.");
  r.actSec = h("section", { class: "od-sec" }, h("h3", null, "Owner actions"), r.quick,
    h("p", { class: "muted small" }, "Actions are requests. The orchestrator applies them to the ledger; this board never edits an order file."), r.act, r.actEmpty);

  const el = h("div", { class: "od" },
    h("header", { class: "od-head" }, h("div", { class: "od-ids" }, r.id, r.sev, r.state, r.pend), h("div", { class: "od-btns" }, r.acts, r.graph, r.close)),
    h("div", { class: "od-body" }, r.title, h("div", { class: "od-prog" }, r.strip, r.prog), r.depsSec, r.slicesSec, r.actSec,
      h("section", { class: "od-sec" }, h("h3", null, "Details"), r.dl, h("div", { class: "od-path" }, r.path, r.copy))));
r.acts.addEventListener("click", () => { const o = store.order(id); if (o) actionsMenu(r.acts, o); });

  r.copy.addEventListener("click", () => { const o = store.order(id); navigator.clipboard?.writeText(o.path).catch(() => {}); toast({ title: "Path copied", body: o.path, kind: "info", icon: "copy", life: 2500 }); });

  function patch() {
    const o = store.order(id); if (!o) return;
    setText(r.id, "WO-" + o.id); setAttr(r.sev, "level", o.sev); setAttr(r.state, "state", o.status);
    r.pend.hidden = !o.pending;
    r.graph.hidden = !!o.resolved;
    setText(r.title, o.title);

    r.strip.hidden = !o.total; r.prog.hidden = !o.total;
    if (o.total) { r.strip.set(o.slices.map((s) => s.state), "", `${o.done} of ${o.total} slices landed`); setText(r.prog, o.resolved ? `All ${o.total} slices landed` : o.awaiting ? "All slices landed, acceptance open" : `${o.done} of ${o.total} slices landed`); }

    // dependencies
    const dep = (ids) => ids.length ? ids.map((x) => chipLink(x.includes("/") ? "WO-" + x.replace("/", " ") : "WO-" + x, () => go("order/" + x.split("/")[0]))) : [h("span", { class: "g-none" }, "nothing")];
    const wsig = o.waitsOn.join() + "|" + o.blocks.join();
    if (r.waits.dataset.sig !== wsig) {
      r.waits.dataset.sig = wsig;
      r.waits.replaceChildren(...dep(o.waitsOn));
      const bl = [...new Set(o.blocks.map((b) => b.split("/")[0]))].filter((b) => b !== o.id);
      r.blocks.replaceChildren(...dep(bl));
    }
    r.depsSec.hidden = !!o.resolved;

    // slices
    r.slicesSec.hidden = !o.total;
    reconcile(r.slices, o.slices, {
      move: false, key: (s) => s.key,
      create: (s) => {
        const b = h("button", { class: "sl-row", type: "button", "aria-expanded": "false" }, h("span", { class: "sl-code" }), h("span", { class: "sl-title" }), h("gb-badge"), icon("down", "sl-chev"));
        const more = h("div", { class: "sl-more" });
        const li = h("li", { class: "sl" }, b, more); li.refs = { b, more, code: b.children[0], t: b.children[1], badge: b.children[2] };
        b.addEventListener("click", () => { const on = b.getAttribute("aria-expanded") !== "true"; b.setAttribute("aria-expanded", on); li.classList.toggle("open", on); });
        return li;
      },
      update: (li, s, old) => {
        const f = li.refs;
        setText(f.code, s.id); setText(f.t, s.title); const c = setAttr(f.badge, "state", s.state);
        const after = s.dependsOn.length ? "After " + s.dependsOn.map((d) => d.split("/")[1]).join(", ") + ". " : "Starts the chain. ";
        setText(f.more, (s.scope ? s.scope + " " : "") + (o.resolved ? "" : after));
        if (c && old) { li.classList.remove("flash"); void li.offsetWidth; li.classList.add("flash"); }
      },
    });

    // details
    const items = [];
    if (o.resolved) items.push(["Released in", o.released || "not recorded"]);
    if (o.parked) items.push(["Restart trigger", o.trigger]);
    if (o.evidence) items.push(["Evidence", o.evidence]);
    if (o.origin) items.push(["Origin", o.origin]);
    const dsig = JSON.stringify(items);
    if (r.dl.dataset.sig !== dsig) { r.dl.dataset.sig = dsig; r.dl.replaceChildren(...items.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)])); }
    setText(r.path, o.path);

    // owner actions: the requests still open, then the newest closed ones, for this order
    r.acts.hidden = !!o.resolved; r.actSec.hidden = !!o.resolved;
    const rows = [
      ...store.state.pending.filter((p) => p.orderId === id).map((p) => ({ id: p.id, label: actionLabel(p), state: "pending", why: p.read ? "The orchestrator has read it." : "", ts: p.ts })),
      ...store.state.log.filter((p) => p.orderId === id).slice(0, 5).map((p) => ({ id: p.id, label: actionLabel(p), state: p.outcome, why: p.outcome === "rejected" ? p.reason : "", ts: p.doneAt })),
    ];
    r.actEmpty.hidden = rows.length > 0;
    reconcile(r.act, rows, {
      move: false, key: (a) => a.id,
      create: () => h("li", null, h("gb-badge"), h("span", { class: "a-label" }, h("span", { class: "a-text" }), h("span", { class: "a-why" })), h("span", { class: "a-when" })),
      update: (li, a) => {
        const lab = li.children[1];
        setAttr(li.children[0], "state", a.state); setText(lab.children[0], a.label); setText(lab.children[1], a.why); lab.children[1].hidden = !a.why;
        setText(li.children[2], relTime(Date.now() - a.ts));
      },
    });
    const qsig = [o.status, o.held, o.parked, o.approved, o.sev].join();
    if (r.quick.dataset.sig !== qsig) {
      r.quick.dataset.sig = qsig;
      const btn = (label, ic, kind) => h("button", { class: "btn sm", type: "button", onclick: () => requestAction(kind, store.order(id)) }, icon(ic), label);
      r.quick.replaceChildren(
        ...(o.parked ? [btn("Unpark", "play", "unpark")] : [btn("Reprioritize", "flag", "severity"), ...(o.status === "ready" && !o.approved ? [btn("Approve for dispatch", "check", "approve")] : []), btn(o.held ? "Release" : "Hold", o.held ? "play" : "pause", o.held ? "release" : "hold"), btn("Park", "park", "park")]),
        btn("Note", "note", "note"));
    }
  }
  patch();
  return { el, patch };
}
