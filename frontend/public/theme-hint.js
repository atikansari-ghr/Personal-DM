// Early theme hint (avoids a flash); the account preference from the server is authoritative.
try { var t = localStorage.getItem("pd-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
