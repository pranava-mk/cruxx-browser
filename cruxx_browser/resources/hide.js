// Element picker. Click sends a CSS selector to the cruxxHide handler.
(function () {
  "use strict";
  if (window.__cruxxPick) { window.__cruxxPick.stop(); }
  var box = document.createElement("div");
  box.style.cssText = "position:fixed;pointer-events:none;z-index:2147483647;" +
    "outline:2px solid #f7768e;background:rgba(247,118,142,.2);display:none";
  document.documentElement.appendChild(box);
  var current = null;
  var plain = /^[A-Za-z_][A-Za-z0-9_-]*$/;
  function unique(sel) {
    try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; }
  }
  function part(el) {
    var tag = el.tagName.toLowerCase();
    if (el.id && plain.test(el.id) && unique("#" + el.id)) return "#" + el.id;
    var sel = tag;
    var classes = (el.getAttribute("class") || "").split(/\s+/).filter(function (c) { return plain.test(c); });
    if (classes.length) sel += "." + classes.slice(0, 2).join(".");
    var parent = el.parentElement;
    if (parent) {
      var same = Array.prototype.filter.call(parent.children, function (c) { return c.tagName === el.tagName; });
      if (same.length > 1) sel += ":nth-of-type(" + (same.indexOf(el) + 1) + ")";
    }
    return sel;
  }
  function selectorFor(el) {
    var parts = [];
    while (el && el !== document.body && el !== document.documentElement) {
      parts.unshift(part(el));
      var sel = parts.join(" > ");
      if (parts[0].charAt(0) === "#" || unique(sel)) return sel;
      el = el.parentElement;
    }
    return parts.join(" > ");
  }
  function over(e) {
    current = e.target;
    var r = current.getBoundingClientRect();
    box.style.display = "block";
    box.style.left = r.left + "px"; box.style.top = r.top + "px";
    box.style.width = r.width + "px"; box.style.height = r.height + "px";
  }
  function click(e) {
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    var el = e.target;
    stop();
    if (el && el !== document.body && el !== document.documentElement) {
      window.webkit.messageHandlers.cruxxHide.postMessage(selectorFor(el));
    }
  }
  function key(e) { if (e.key === "Escape") stop(); }
  function stop() {
    document.removeEventListener("mouseover", over, true);
    document.removeEventListener("click", click, true);
    document.removeEventListener("keydown", key, true);
    box.remove();
    window.__cruxxPick = null;
  }
  document.addEventListener("mouseover", over, true);
  document.addEventListener("click", click, true);
  document.addEventListener("keydown", key, true);
  window.__cruxxPick = { stop: stop };
})();
