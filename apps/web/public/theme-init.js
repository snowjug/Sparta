/* Sets the theme before first paint. Served as a same-origin file (not inline) so a strict Content-Security-Policy works. */
(function () {
  var root = document.documentElement;
  try {
    var pref = window.localStorage.getItem("sparta.theme");
    var explicit = pref === "light" || pref === "dark";
    var prefersLight = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
    root.setAttribute("data-theme", explicit ? pref : prefersLight ? "light" : "dark");
    root.setAttribute("data-theme-pref", explicit ? pref : "system");
    if (window.localStorage.getItem("sparta.motion") === "reduce") root.setAttribute("data-motion", "reduce");
  } catch {
    root.setAttribute("data-theme", "dark");
    root.setAttribute("data-theme-pref", "system");
  }
})();
