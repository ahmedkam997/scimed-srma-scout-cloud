// Network first: phone users receive newly deployed JS even after PWA installation.
const CACHE='scimed-review-scout-v21';
const ASSETS=['./','./index.html','./styles.css?v=20261123-gemini-route','./app.js?v=20261123-gemini-route','./manifest.webmanifest','./config.js?v=20261123-gemini-route'];
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