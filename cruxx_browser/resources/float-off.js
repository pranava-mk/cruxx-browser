(function () {
  // Remove the float style and the mark.
  var style = document.getElementById("cruxx-float-style");
  if (style) { style.remove(); }
  var marked = document.querySelectorAll("video[data-cruxx-float]");
  for (var i = 0; i < marked.length; i++) { marked[i].removeAttribute("data-cruxx-float"); }
  return true;
})()
