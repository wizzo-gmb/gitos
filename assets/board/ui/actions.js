/* actions.js - owner actions on an order: reprioritize, park with a trigger, unpark, hold, release, approve for dispatch, add a note.
   An action is a request. `requestAction` opens the board's own confirm (the action and the state the owner saw), posts it to
   /api/action and shows it pending; the board writes no order file, the orchestrator applies it to the ledger and closes it, and
   the live state then says applied or why not. A repo view asks for an action only through here, never by posting itself. */
import { toast, confirmDialog, openMenu, LABELS } from "./ui.js";
import { store } from "./store.js";

const SEVERITIES = ["critical", "high", "medium", "low"];
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);

/* One action as a short line, for the drawer, a toast and the palette. `a` is {kind, value}. */
export function actionLabel(a) {
  switch (a.kind) {
    case "severity": return `Severity to ${a.value}`;
    case "park": return `Park until: ${a.value}`;
    case "unpark": return "Unpark";
    case "hold": return "Hold";
    case "release": return "Release";
    case "approve": return "Approve for dispatch";
    case "note": return `Note: ${a.value}`;
    default: return a.kind;
  }
}

/* The menu and palette entries for an order: only what makes sense for it now. */
export function orderActionItems(order, run = requestAction) {
  if (!order || order.resolved) return [];
  const it = [];
  if (!order.parked) it.push({ label: "Reprioritize", icon: "flag", run: () => run("severity", order.id) });
  if (order.status === "ready" && !order.approved && !order.parked) it.push({ label: "Approve for dispatch", icon: "check", run: () => run("approve", order.id) });
  if (order.held) it.push({ label: "Release", icon: "play", run: () => run("release", order.id) });
  else if (!order.parked) it.push({ label: "Hold", icon: "pause", run: () => run("hold", order.id) });
  if (order.parked) it.push({ label: "Unpark", icon: "play", run: () => run("unpark", order.id) });
  else it.push({ label: "Park with a trigger", icon: "park", run: () => run("park", order.id) });
  it.push({ sep: true }, { label: "Add a note", icon: "note", run: () => run("note", order.id) });
  return it;
}
export const actionsMenu = (anchor, order) => openMenu(anchor, orderActionItems(order));

/* What each action asks the owner: the dialog's title, text, button and fields. */
function dialogFor(kind, order) {
  const wo = "WO-" + order.id;
  switch (kind) {
    case "severity": return { title: `Reprioritize ${wo}`, body: "Changes the order's severity, which sets its place in every list.", confirm: "Reprioritize",
      fields: [{ name: "value", label: "Severity", type: "select", required: true, value: SEVERITIES.includes(order.sev) ? order.sev : "",
        options: [...(SEVERITIES.includes(order.sev) ? [] : [{ value: "", label: `Choose (now ${order.sev})` }]), ...SEVERITIES.map((s) => ({ value: s, label: cap(s) }))] }] };
    case "park": return { title: `Park ${wo}`, body: "A parked order waits for a trigger. Say what must be true before it restarts.", confirm: "Park order",
      fields: [{ name: "value", label: "Restart trigger", type: "textarea", required: true, placeholder: "For example: WO-153 resolved, and a repo asks for it" }] };
    case "unpark": return { title: `Unpark ${wo}`, body: order.trigger ? `Its trigger was: ${order.trigger}` : "", confirm: "Unpark" };
    case "hold": return { title: `Hold ${wo}`, body: "A held order is not dispatched until you release it.", confirm: "Hold order" };
    case "release": return { title: `Release ${wo}`, body: "The order returns to the queue.", confirm: "Release order" };
    case "approve": return { title: `Approve ${wo} for dispatch`, body: "The orchestrator may start this order without asking again.", confirm: "Approve" };
    case "note": return { title: `Add a note to ${wo}`, body: "The orchestrator reads it before the next step on this order.", confirm: "Add note",
      fields: [{ name: "value", label: "Note", type: "textarea", required: true, placeholder: "What should the orchestrator know?" }] };
    default: return null;
  }
}

/* Ask, then record. Resolves true when the board recorded the request. `order` is an order of the store, or its number. */
export async function requestAction(kind, order) {
  order = typeof order === "object" && order ? order : store.order(order);
  const dlg = order && !order.resolved ? dialogFor(kind, order) : null;
  if (!dlg) return false;
  const seen = { hash: order.hash, version: store.state.version }, tab = store.scope;   // the repo the owner is looking at now, not where the page is after the confirm
  const state = LABELS[order.status] || order.status;
  const got = await confirmDialog({ ...dlg, seen: `You are looking at WO-${order.id}: ${state.toLowerCase()}, ${order.sev} severity (state ${seen.hash.slice(0, 6)}, ${seen.version}). The request records that state.` });
  if (!got) return false;
  const value = "value" in got ? got.value : null;
  if (kind === "severity" && value === order.sev) {
    toast({ title: `WO-${order.id} is already ${order.sev} severity`, body: "Nothing was requested.", kind: "info", icon: "flag", life: 3500 });
    return false;
  }
  const label = actionLabel({ kind, value });
  try {
    await store.post("/api/action", { kind, order: order.id, value, order_hash: seen.hash, version: seen.version, ...(tab ? { tab } : {}) });   // on a hub the repo the order is of
  } catch (err) {
    toast({ title: "Not recorded", body: err.message, kind: "warn", icon: "alert", life: 7000 });
    if (err.status === 404 || err.status === 409) store.reload().catch(() => {});
    return false;
  }
  toast({ title: `Requested: ${label} on WO-${order.id}`, body: "Pending until the orchestrator applies it. The board never edits an order file.", kind: "action", icon: "history", life: 4200 });
  try { await store.reload(); } catch { /* recorded; the stream brings the new state */ }
  return true;
}
