/* boot.js - runs before first paint so the page never flashes the wrong theme. A classic script (not a module) on purpose:
   the board serves it from 'self' under a CSP with no inline script. */
(function () {
  var t = null;
  try { t = new URLSearchParams(location.search).get("theme") || localStorage.getItem("gb-theme"); } catch (e) {}
  if (t !== "light" && t !== "dark") t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", t);
})();
