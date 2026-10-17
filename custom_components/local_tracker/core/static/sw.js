// Caches the app shell so it opens instantly; API calls always go to the server.
const CACHE = "local-tracker-v3";
const SHELL = ["/", "/static/app.css", "/static/app.js", "/static/icon.svg", "/static/manifest.webmanifest",
  "/static/fonts/poppins-300.woff", "/static/fonts/poppins-400.woff", "/static/fonts/poppins-500.woff", "/static/fonts/poppins-600.woff"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Network first, cache as fallback, so updates show up right away when the server is reachable.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
