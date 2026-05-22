/*
 * Tazkirati — minimal service worker.
 * Goal: enable PWA install + offline shell. We intentionally do NOT cache
 * the API responses (seats / bookings / auth) because they must always
 * be fresh.
 */

const CACHE = 'tazkirati-shell-v1';
const SHELL = [
  '/app/',
  '/app/index.html',
  '/app/manifest.json',
  '/app/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls — always go live.
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/auth/') ||
    url.pathname.startsWith('/bookings/') ||
    url.pathname.startsWith('/trips/') ||
    url.pathname.startsWith('/admin/')
  ) {
    return; // default network behavior
  }

  // For everything else (static shell), try network first, fall back to cache.
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});
