// Early theme hint (avoids a flash); the account preference from the server is authoritative.
try {
  var t = localStorage.getItem("pd-theme");
  if (t) {
    document.documentElement.dataset.theme = t;
    var c = { blue: "#1d4e89", mono: "#111111", dark: "#0f1513", glass_light: "#eef4f1", glass_dark: "#0b1411" }[t];
    var m = document.querySelector('meta[name="theme-color"]');
    if (c && m) m.setAttribute("content", c);
  }
} catch (e) {}
