// very small service worker stub for offline caching (expand for production)
self.addEventListener('install', (evt)=>{
  self.skipWaiting()
})
self.addEventListener('activate', (evt)=>{
  self.clients.claim()
})
