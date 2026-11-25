// Network first: phone users receive newly deployed JS even after PWA installation.
const CACHE='scimed-review-scout-v33';
const ASSETS=['./','./index.html','./styles.css?v=20261125-lightweight-sync','./app.js?v=20261125-lightweight-sync','./gap-verification.js?v=20261125-lightweight-sync','./final-audit-evidence.js?v=20261125-lightweight-sync','./final-evidence-audit.js?v=20261125-lightweight-sync','./manifest.webmanifest','./config.js?v=20261125-lightweight-sync'];
self.addEventListener('install',e=>e.waitUntil(
  caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())
));
self.addEventListener('activate',e=>e.waitUntil(
  caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())
));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET'||new URL(e.request.url).origin!==self.location.origin)return;
  e.respondWith(
    fetch(e.request, {cache:'no-store'}).then(response=>{
      if(response.ok){
        const copy=response.clone();
        e.waitUntil(caches.open(CACHE).then(cache=>cache.put(e.request,copy)).catch(()=>{}));
      }
      return response;
    }).catch(()=>caches.match(e.request))
  );
});