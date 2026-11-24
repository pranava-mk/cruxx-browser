(function () {
  // Make the marked video fill the view. float-off.js undoes this.
  var style = document.getElementById("cruxx-float-style");
  if (!style) {
    style = document.createElement("style");
    style.id = "cruxx-float-style";
    (document.head || document.documentElement).appendChild(style);
  }
  style.textContent =
    "video[data-cruxx-float]{position:fixed!important;inset:0!important;" +
    "width:100vw!important;height:100vh!important;max-width:none!important;" +
    "max-height:none!important;margin:0!important;transform:none!important;" +
    "object-fit:contain!important;z-index:2147483647!important;" +
    "background:#000!important}" +
    "html,body{background:#000!important;overflow:hidden!important}";
  return true;
})()
