const version = 'pastpaper-device-v6';
const scoped = names => names.map(name => new URL(name, self.registration.scope).href);
const urls = scoped(['index.html','studio.css','studio.mjs','locale.mjs','vault.mjs','providers.mjs','text-search.mjs']);
const lazy = scoped(['pdf-engine/pdf.min.mjs','pdf-engine/pdf.worker.min.mjs']);
const fontDirectory = new URL('pdf-engine/standard-fonts/', self.registration.scope).href;
self.addEventListener('install', event => event.waitUntil(caches.open(version).then(cache => cache.addAll(urls))));
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const name of await caches.keys()) if (name.startsWith('pastpaper-device-') && name !== version) await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  const url = event.request.url, optional = lazy.includes(url) || url.startsWith(fontDirectory);
  if (event.request.method !== 'GET' || (!optional && !urls.includes(url))) return;
  event.respondWith((async () => {
    const cache = await caches.open(version);
    try {
      const response = await fetch(event.request);
      if (optional && response.ok) await cache.put(url, response.clone()).catch(() => {});
      return response;
    } catch { return await cache.match(url) || Response.error(); }
  })());
});
