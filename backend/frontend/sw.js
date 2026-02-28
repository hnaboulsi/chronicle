const CACHE = 'lm-v2';
const ASSETS = [
    '/dashboard/index.html',
    '/dashboard/style.css',
    '/dashboard/script.js',
    '/dashboard/manifest.json',
    '/dashboard/icon.svg',
    '/dashboard/apple-touch-icon.svg',
    '/dashboard/favicon.svg'
];

self.addEventListener('install', (e) => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => k !== CACHE).map(k => caches.delete(k))
        ))
    );
    self.clients.claim();
});

self.addEventListener('fetch', (e) => {
    if (e.request.url.includes('/api/')) return; // Never cache API calls
    e.respondWith(
        fetch(e.request).then(res => {
            // Only cache successful responses — don't cache 404s or errors
            if (res.ok) {
                const clone = res.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
            }
            return res;
        }).catch(() => caches.match(e.request))
    );
});
