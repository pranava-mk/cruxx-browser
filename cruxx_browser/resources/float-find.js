(function () {
  // Find the biggest playing video. If none plays, find the biggest visible one.
  // Mark it with a data attribute. Return true if one was found.
  var old = document.querySelectorAll("video[data-cruxx-float]");
  for (var i = 0; i < old.length; i++) { old[i].removeAttribute("data-cruxx-float"); }
  var best = null, bestArea = 0, bestPlaying = false;
  var videos = document.querySelectorAll("video");
  for (var j = 0; j < videos.length; j++) {
    var v = videos[j], r = v.getBoundingClientRect();
    var w = Math.min(r.right, window.innerWidth) - Math.max(r.left, 0);
    var h = Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0);
    if (w <= 0 || h <= 0) { continue; }
    if (getComputedStyle(v).visibility === "hidden") { continue; }
    var playing = !v.paused && !v.ended && v.readyState > 2;
    var area = w * h;
    if ((playing && !bestPlaying) || (playing === bestPlaying && area > bestArea)) {
      best = v; bestArea = area; bestPlaying = playing;
    }
  }
  if (best) { best.setAttribute("data-cruxx-float", "1"); }
  return best !== null;
})()
