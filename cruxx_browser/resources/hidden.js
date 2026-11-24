// Apply saved selectors. Python calls this with a map of site -> selectors.
(function (rules) {
  "use strict";
  var host = location.hostname.toLowerCase();
  var list = [];
  for (var site in rules) {
    if (host === site || host.endsWith("." + site)) list = list.concat(rules[site]);
  }
  if (!list.length) return;
  var old = document.getElementById("cruxx-hidden");
  if (old) old.remove();
  var style = document.createElement("style");
  style.id = "cruxx-hidden";
  (document.head || document.documentElement).appendChild(style);
  var sheet = style.sheet;
  if (!sheet) return;
  // Insert each rule alone. One bad selector must not break the others.
  list.forEach(function (sel) {
    try { sheet.insertRule(sel + "{display:none!important}", sheet.cssRules.length); } catch (e) { /* skip */ }
  });
})
