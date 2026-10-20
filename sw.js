const CACHE = 'stream-radar-v2.3';
const ASSETS = ['./', './index.html', './app.js?v=20261020-autoaudio', './styles.css', './manifest.webmanifest', './icons/icon.svg'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith('stream-radar-') && key !== CACHE).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  // Network first for app and data: installations must see later published versions.
  // Strip only the data cache-buster so the last successful catalogue works offline.
  const key = url.pathname.endsWith('/data.json') ? new URL('./data.json', self.registration.scope).href : event.request;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const response = await fetch(event.request, {cache: 'no-cache'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      await cache.put(key, response.clone());
      return response;
    } catch (error) {
      const saved = await cache.match(key);
      if (saved) return saved;
      throw error;
    }
  })());
});
