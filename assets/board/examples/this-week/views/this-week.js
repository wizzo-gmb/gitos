/* views/this-week.js - an example repo view: the open orders the ledger touched this week, live, with an action on each.
   It is built only from the engine's kit and the repo's own data: `/ui/ui.js` (components and helpers), `/ui/store.js` (the live
   state, including `state.ext.week` from providers/week.py) and `/ui/actions.js` (`requestAction`, the only way a view asks for an
   owner action: the board's own confirm decides). A view never posts an answer or an action itself: the store's `post` is
   reachable from any same-origin code, so the contract forbids that use; the kit does not prevent it. Copy this file to <home>/board/views/ and
   providers/week.py to <home>/board/providers/ and it appears in the sidebar. The module exports `meta` and registers the element
   `gb-repo-<file name>`. */
import { h, setText, setAttr, reconcile } from "/ui/ui.js";
import { store } from "/ui/store.js";
import { requestAction } from "/ui/actions.js";

export const meta = { title: "This week", icon: "calendar", position: 10 };

class RepoThisWeek extends HTMLElement {
  connectedCallback() {
    if (this.stats) return;
    this.className = "page";
    this.stats = ["Open orders", "In progress", "Touched this week"].map((label) => h("gb-stat", { label, value: "-" }));
    this.sub = h("span", { class: "sub" });
    this.list = h("div", { class: "grid-cards" });
    this.empty = h("gb-empty", { icon: "calendar", title: "Nothing touched this week", desc: "An order shows here when its file or one of its slices changes." });
    this.append(
      h("header", { class: "page-head" }, h("div", { class: "ph-main" }, h("h1", null, meta.title), this.sub)),
      h("div", { class: "page-body" }, h("div", { class: "stack" }, h("div", { class: "panel stat-row" }, ...this.stats), this.list, this.empty)));
    this.unsub = store.subscribe(() => this.render());
    this.render();
  }
  disconnectedCallback() { this.unsub?.(); }

  render() {
    const week = store.state.ext.week;                       // undefined until the provider's first run, and when it fails with no good output
    const orders = store.orders(), mine = (week?.touched || []).map((t) => store.order(t.id)).filter(Boolean);
    setText(this.sub, week ? `Orders changed in the last ${week.days} days` : "Waiting for the week provider");
    [orders.filter((o) => !o.parked).length, orders.filter((o) => o.status === "active").length, mine.length]
      .forEach((v, i) => setAttr(this.stats[i], "value", v));
    this.empty.hidden = !week || mine.length > 0;
    reconcile(this.list, mine, {
      move: false, key: (o) => o.id,
      create: (o) => {
        const card = h("gb-order-card"), ask = h("button", { class: "btn sm", type: "button" }, "Add a note");
        ask.addEventListener("click", () => requestAction("note", card.order.id));
        const box = h("div", { class: "stack tight" }, card, ask);
        box.card = card;
        return box;
      },
      update: (box, o) => { box.card.order = o; },
    });
  }
}
customElements.define("gb-repo-this-week", RepoThisWeek);
