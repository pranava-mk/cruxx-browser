// Sign-in forms. Runs in the isolated world "cruxx", in the top frame only.
// It sends text to the handler "cruxxForms". Python checks every message.
// It never fills a field by itself. Python calls __cruxxPwFill after a click.
(function () {
  "use strict";
  if (window.__cruxxPw) return;
  window.__cruxxPw = true;
  var current = null;   // the password field that the user used last
  var hideTimer = 0;
  var scrollSent = 0;

  function post(message) {
    try {
      window.webkit.messageHandlers.cruxxForms.postMessage(JSON.stringify(message));
    } catch (e) { /* no handler: do nothing */ }
  }

  function isPassword(el) {
    return !!el && el.tagName === "INPUT" && (el.type || "").toLowerCase() === "password";
  }

  function isTextField(el) {
    if (!el || el.tagName !== "INPUT") return false;
    var type = (el.type || "text").toLowerCase();
    return type === "text" || type === "email" || type === "tel";
  }

  function visible(el) {
    if (!el || !el.isConnected) return false;
    var box = el.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) return false;
    var style = window.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  function passwordsOf(scope) {
    return Array.prototype.slice.call(scope.querySelectorAll("input[type=password]"));
  }

  // The user name field: the text or email input before the password field.
  function userFieldFor(pass) {
    var scope = pass.form || document;
    var inputs = Array.prototype.slice.call(scope.querySelectorAll("input"));
    var index = inputs.indexOf(pass);
    for (var i = index - 1; i >= 0; i--) {
      if (isTextField(inputs[i])) return inputs[i];
    }
    return null;
  }

  function capture(form) {
    if (!form) return;
    var filled = passwordsOf(form).filter(function (el) { return el.value !== ""; });
    if (!filled.length) return;
    var pass = filled[filled.length - 1];
    var user = userFieldFor(pass);
    post({ kind: "submit", username: user ? user.value : "", password: pass.value });
  }

  function announce(el) {
    var pass = isPassword(el) ? el : null;
    if (!pass && isTextField(el)) {
      var scope = el.form || document;
      var all = passwordsOf(scope);
      for (var i = 0; i < all.length; i++) {
        if (userFieldFor(all[i]) === el) { pass = all[i]; break; }
      }
    }
    if (!pass) return;
    current = pass;
    var box = el.getBoundingClientRect();
    post({ kind: "focus", rect: { x: box.left, y: box.top, w: box.width, h: box.height } });
  }

  document.addEventListener("focusin", function (event) {
    clearTimeout(hideTimer);
    announce(event.target);
  }, true);
  document.addEventListener("click", function (event) {
    if (!event.isTrusted) return;
    announce(event.target);
    var node = event.target && event.target.closest
      ? event.target.closest("button, input[type=submit], input[type=image]") : null;
    if (node && node.form) {
      var type = (node.getAttribute("type") || "submit").toLowerCase();
      if (type === "submit" || type === "image") capture(node.form);
    }
  }, true);
  document.addEventListener("focusout", function () {
    clearTimeout(hideTimer);
    // Wait: focus can move to another field of the form.
    hideTimer = setTimeout(function () {
      var now = document.activeElement;
      if (!isPassword(now) && !(isTextField(now) && now.form && passwordsOf(now.form).length)) {
        post({ kind: "hide" });
      }
    }, 150);
  }, true);
  document.addEventListener("scroll", function () {
    var now = Date.now();
    if (now - scrollSent > 100) { scrollSent = now; post({ kind: "hide" }); }
  }, true);
  document.addEventListener("keydown", function (event) {
    if (event.isTrusted && event.key === "Escape") post({ kind: "hide" });
  }, true);
  document.addEventListener("submit", function (event) {
    if (event.isTrusted) capture(event.target);
  }, true);

  function setValue(el, text) {
    var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // Python calls this after the user clicks an account.
  window.__cruxxPwFill = function (username, password) {
    var pass = current && current.isConnected ? current : null;
    if (!pass) {
      var all = passwordsOf(document).filter(visible);
      pass = all.length ? all[0] : null;
    }
    if (!pass) return false;
    var user = userFieldFor(pass);
    if (user && username !== "") setValue(user, username);
    setValue(pass, password);
    return true;
  };

  // Python asks this after a page load.
  window.__cruxxPwVisible = function () {
    return passwordsOf(document).some(visible);
  };

  // Test hooks. Only Python can call them: page script has another world.
  window.__cruxxPwTestSubmit = function (form) { capture(form); };
  window.__cruxxPwTestFocus = function (el) { announce(el); };
})();
