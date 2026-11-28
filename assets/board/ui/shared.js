/* shared.js - the small amount of app glue the engine views share: routing state and the page header. A repo view needs
   none of it: it imports only ui.js, store.js and, to ask for an owner action, actions.js. */
import { h, setText, toast, confirmDialog } from "./ui.js";
import { store } from "./store.js";

/* ---------------------------------------------------------------- routing state */
export const route = { view: "work/list", query: "", drawer: null, scope: null };   // scope: a hub's repo tab, in the address as #/r/<tab>/...
/* The address of a view: under the repo the page is in (a hub), or under `scope` when one is given (null: the board's own). */
export const hashOf = (path, scope = route.scope) => "#/" + (scope ? "r/" + scope + "/" : "") + path.replace(/^#?\/?/, "");
export function go(path, scope) { location.hash = hashOf(path, scope); }
export function openOrder(id) { go("order/" + String(id).replace(/^WO-/, "").split("/")[0]); }
export function viewHash() { return hashOf(route.view + (route.query ? "?" + route.query : "")); }
export function queryParams() { return new URLSearchParams(route.query); }
/* A view keeps its filters in the URL without adding history entries. */
export function setQuery(params) {
  const qs = params.toString();
  route.query = qs;
  if (!route.drawer) history.replaceState(null, "", viewHash());
}

/* ---------------------------------------------------------------- page header */
export const WORK_TABS = [
  { value: "work/list", label: "List", icon: "list" },
  { value: "work/board", label: "Board", icon: "board" },
  { value: "work/graph", label: "Graph", icon: "graph" },
];
export function pageHead({ title, tabs, active, actions }) {
  const sp = h("span", { class: "sub" });
  const head = h("header", { class: "page-head" },
    h("div", { class: "ph-main" }, h("h1", null, title), sp),
    h("div", { class: "ph-tools" }, actions || null));
  if (tabs) {
    const seg = h("gb-segmented", { class: "ph-tabs", "aria-label": "Work view" });
    seg.options = tabs; seg.value = active;
    seg.addEventListener("change", (e) => go(e.detail + (route.query && e.detail === route.view ? "?" + route.query : "")));
    head.querySelector(".ph-tools").prepend(seg);
  }
  return { el: head, update: (text) => setText(sp, text), title: (text) => setText(head.querySelector("h1"), text) };
}
export function workSummary() {
  const os = store.orders();
  const open = os.filter((o) => !o.parked).length, parked = os.filter((o) => o.parked).length, active = os.filter((o) => o.status === "active").length;
  const n = store.state.looseEnds.count;
  return `${open} open, ${active} in progress, ${parked} parked, ${n} loose end${n === 1 ? "" : "s"}`;
}

/* ---------------------------------------------------------------- stopping a sprint
   The sprint driver posts one Stop card per sprint (its id is `sprint.stopCard`). The board keeps it out of the owner's cards (a
   stop is a control, not a decision) and sends it as `controls`. Stop answers that card through the board's answer route, bound
   to the hash of the card shown, exactly as a card answered on the Decisions page. */
export const stopCardOf = (sp) => store.state.controls.find((c) => c.id === sp.stopCard && c.status !== "closed" && c.tab === "sprint" && (c.options || []).some((o) => o.value === "stop")) || null;
export const stopRequested = (sp) => { const c = stopCardOf(sp); return !!(c && c.answer && c.answer.option === "stop"); };
export async function stopSprint(sp) {
  const card = stopCardOf(sp);
  if (!card || card.answer || card.locked) return;
  const n = sp.orders.length;
  const r = await confirmDialog({ title: `Stop ${sp.exclusive ? "the exclusive sprint" : sp.name}`, danger: true, confirm: "Stop sprint",
    body: "The sprint finishes the order it is on, writes its state and stops. Orders it has not started stay in the ledger.",
    seen: `You are looking at ${sp.exclusive ? "the exclusive sprint" : sp.name}: ${sp.state}, ${n} order${n === 1 ? "" : "s"}.` });
  if (!r) return;
  try {
    await store.post("/api/answer", { card: card.id, option: "stop", note: "", card_hash: card.card_hash });
  } catch (err) {
    toast({ title: "Not saved", body: err.message, kind: "warn", icon: "alert", life: 7000 });
    if (err.status === 409) store.reload().catch(() => {});
    return;
  }
  toast({ title: `Stop requested for ${sp.exclusive ? "the exclusive sprint" : sp.name}`, body: "It stops after the order in hand.", kind: "sprint", icon: "stop", life: 4000 });
  try { await store.reload(); } catch { /* the answer is saved; the stream brings the new state */ }
}
