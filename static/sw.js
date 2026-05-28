const META_CACHE = 'hlvm-meta';
const STATIC_CACHE_PREFIX = 'hlvm-static-';
const PAGES_CACHE_PREFIX = 'hlvm-pages-';

async function readMeta() {
  const cache = await caches.open(META_CACHE);
  const response = await cache.match('version');
  if (!response) {
    return null;
  }
  return response.json();
}

async function writeMeta(payload) {
  const cache = await caches.open(META_CACHE);
  await cache.put(
    'version',
    new Response(
      JSON.stringify({
        version: payload.version,
        offline_url: payload.offline_url,
      }),
    ),
  );
}

function staticCacheName(version) {
  return STATIC_CACHE_PREFIX + version;
}

function pagesCacheName(version) {
  return PAGES_CACHE_PREFIX + version;
}

function isNavigationRequest(request) {
  if (request.mode === 'navigate') {
    return true;
  }
  const accept = request.headers.get('accept') || '';
  return request.method === 'GET' && accept.includes('text/html');
}

function shouldBypassCache(pathname) {
  return (
    pathname.startsWith('/api/')
    || pathname.startsWith('/authentication/')
    || pathname.startsWith('/admin/')
    || pathname === '/sw-precache.json'
    || pathname === '/sw.js'
    || pathname === '/healthz/'
    || pathname === '/readyz/'
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    fetch('/sw-precache.json', { cache: 'no-store' })
      .then((response) => response.json())
      .then(async (payload) => {
        await writeMeta(payload);
        const staticCache = await caches.open(staticCacheName(payload.version));
        await staticCache.addAll(payload.precache);
        await caches.open(pagesCacheName(payload.version));
      })
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    readMeta()
      .then(async (meta) => {
        if (!meta) {
          return;
        }
        const allowed = new Set([
          META_CACHE,
          staticCacheName(meta.version),
          pagesCacheName(meta.version),
        ]);
        const keys = await caches.keys();
        await Promise.all(
          keys
            .filter((key) => !allowed.has(key))
            .filter(
              (key) =>
                key.startsWith(STATIC_CACHE_PREFIX)
                || key.startsWith(PAGES_CACHE_PREFIX),
            )
            .map((key) => caches.delete(key)),
        );
      })
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  if (shouldBypassCache(url.pathname)) {
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request, { ignoreSearch: true }).then((cached) => {
        if (cached) {
          return cached;
        }
        return fetch(request).then((response) => {
          if (!response.ok) {
            return response;
          }
          const copy = response.clone();
          readMeta().then((meta) => {
            if (!meta) {
              return;
            }
            caches
              .open(staticCacheName(meta.version))
              .then((cache) => cache.put(request, copy));
          });
          return response;
        });
      }),
    );
    return;
  }

  if (!isNavigationRequest(request)) {
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (!response.ok) {
          return response;
        }
        const copy = response.clone();
        readMeta().then((meta) => {
          if (!meta) {
            return;
          }
          caches
            .open(pagesCacheName(meta.version))
            .then((cache) => cache.put(request, copy));
        });
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(request);
        if (cached) {
          return cached;
        }
        const meta = await readMeta();
        const offlinePath = meta?.offline_url || '/offline/';
        return caches.match(offlinePath);
      }),
  );
});
