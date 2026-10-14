// First-launch setup: remembers the Matkoll server address and opens it.
// The web app itself is served by your Matkoll server, so it updates with `matkoll-update`.
(function () {
  const KEY = "matkoll.server";
  const params = new URLSearchParams(location.search);
  let saved = "";
  try { saved = localStorage.getItem(KEY) || ""; } catch (e) { /* storage unavailable */ }

  if (saved && !params.has("setup")) {
    location.replace(saved);
    return;
  }

  const main = document.getElementById("setup");
  const input = document.getElementById("url");
  const err = document.getElementById("err");
  main.classList.remove("hidden");
  input.value = saved || "http://";

  function normalize(v) {
    v = v.trim();
    if (!v) return "";
    if (!/^https?:\/\//i.test(v)) v = "http://" + v;
    let u;
    try { u = new URL(v); } catch (e) { return ""; }
    if (!u.hostname) return "";
    return (u.origin + u.pathname).replace(/\/+$/, "");
  }

  document.getElementById("form").addEventListener("submit", function (e) {
    e.preventDefault();
    const url = normalize(input.value);
    if (!url) {
      err.textContent = "That doesn't look like an address. Try something like http://192.168.1.77:8080";
      err.classList.remove("hidden");
      return;
    }
    try { localStorage.setItem(KEY, url); } catch (e2) { /* ignore */ }
    location.replace(url);
  });
})();
