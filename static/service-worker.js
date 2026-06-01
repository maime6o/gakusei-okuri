/* Minimal service worker — launch-path only, no offline cache needed. */
const CACHE = "gakusei-v1";

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

/* Network-first: always fetch fresh, fall back to cache for navigation. */
self.addEventListener("fetch", (e) => {
  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request).catch(() => caches.match("/"))
    );
  }
});
