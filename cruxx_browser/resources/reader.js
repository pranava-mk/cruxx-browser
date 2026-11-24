// Reading mode. Python calls this function expression with a theme object.
(function (theme) {
  "use strict";
  var doc = document;
  var skip = "script,style,iframe,frame,object,embed,form,input,button,textarea,select,meta,base,link,math,template,slot,noscript,nav,aside,footer,svg,canvas,dialog";
  var urlAttrs = ["href", "src", "srcset", "poster", "action", "formaction", "xlink:href", "data", "background", "cite"];
  var dropAttrs = ["ping", "target", "formaction", "style", "class", "id"];
  // Keep a URL only if it resolves to http, https or mailto.
  function okUrl(v) {
    try {
      var p = new URL(String(v).trim(), location.href).protocol;
      return p === "http:" || p === "https:" || p === "mailto:";
    } catch (e) { return false; }
  }
  function okSrcset(v) {
    var parts = String(v).split(",");
    for (var i = 0; i < parts.length; i++) {
      var candidate = parts[i].trim().split(/\s+/)[0];
      if (!candidate || !okUrl(candidate)) return false;
    }
    return true;
  }
  function textLen(el) {
    var n = 0, ps = el.querySelectorAll("p");
    for (var i = 0; i < ps.length; i++) n += ps[i].textContent.length;
    return n;
  }
  var best = null, bestLen = 0;
  var list = doc.querySelectorAll("article, main, [role=main], div, section");
  for (var i = 0; i < list.length; i++) {
    var len = textLen(list[i]);
    if (list[i].tagName === "ARTICLE") len *= 1.5;
    if (len > bestLen) { best = list[i]; bestLen = len; }
  }
  if (!best) best = doc.body;
  var copy = best.cloneNode(true);
  var junk = copy.querySelectorAll(skip);
  for (var j = 0; j < junk.length; j++) junk[j].remove();
  var all = copy.querySelectorAll("*");
  for (var k = 0; k < all.length; k++) {
    var attrs = Array.prototype.slice.call(all[k].attributes);
    for (var a = 0; a < attrs.length; a++) {
      var name = attrs[a].name.toLowerCase();
      var value = String(attrs[a].value);
      var bad = name.indexOf("on") === 0 || dropAttrs.indexOf(name) !== -1;
      if (!bad && urlAttrs.indexOf(name) !== -1) {
        bad = name === "srcset" ? !okSrcset(value) : !okUrl(value);
      }
      if (bad) all[k].removeAttribute(attrs[a].name);
    }
  }
  var title = doc.title || "";
  var css = "body{margin:0;background:" + theme.background + ";color:" + theme.foreground +
    ";font:18px/1.7 serif}main{max-width:70ch;margin:0 auto;padding:3rem 1.5rem}" +
    "a{color:" + theme.accent + "}img,video{max-width:100%;height:auto}" +
    "pre,code{background:" + theme.lighter_background + ";padding:.1em .3em;overflow:auto}" +
    "blockquote{border-left:3px solid " + theme.muted + ";margin-left:0;padding-left:1em;color:" + theme.light_foreground + "}" +
    "h1,h2,h3{line-height:1.25}";
  while (doc.head.firstChild) doc.head.removeChild(doc.head.firstChild);
  while (doc.body.firstChild) doc.body.removeChild(doc.body.firstChild);
  var meta = doc.createElement("meta");
  meta.name = "viewport"; meta.content = "width=device-width, initial-scale=1";
  var style = doc.createElement("style");
  style.textContent = css;
  var t = doc.createElement("title");
  t.textContent = title;
  doc.head.appendChild(meta); doc.head.appendChild(style); doc.head.appendChild(t);
  var main = doc.createElement("main");
  var h1 = doc.createElement("h1");
  h1.textContent = title;
  main.appendChild(h1);
  main.appendChild(copy);
  doc.body.removeAttribute("class");
  doc.body.removeAttribute("style");
  doc.body.appendChild(main);
  window.scrollTo(0, 0);
})
