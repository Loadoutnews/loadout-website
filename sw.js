// LOADOUT-NEWS — Service Worker
// ================================
// Grundgerüst für die PWA-Funktionalität:
//   - Registriert die Seite als installierbare App
//   - Cached die wichtigsten Dateien fürs schnellere Laden / eingeschränkte
//     Offline-Nutzung
//   - Vorbereitet für Push-Benachrichtigungen (kommt als nächster Ausbauschritt)

const CACHE_NAME = "loadout-news-v1";
const PRECACHE_URLS = [
  "/index.html",
  "/styles.css",
  "/logo-icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Strategie: "Network first, fallback zu Cache" — zeigt immer die
// aktuellste Version, wenn Internet da ist, funktioniert aber auch mit
// eingeschränkter/keiner Verbindung, indem auf die zwischengespeicherte
// Version zurückgegriffen wird. Wichtig für eine News-Seite, bei der
// Aktualität wichtiger ist als eine starre Offline-Kopie.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// --- Push-Benachrichtigungen (Grundgerüst, wird im nächsten Schritt mit
// echten Abos verbunden) --------------------------------------------------
self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload;
  try {
    payload = event.data.json();
  } catch (e) {
    payload = { title: "LOADOUT-NEWS", body: event.data.text() };
  }

  event.waitUntil(
    self.registration.showNotification(payload.title || "LOADOUT-NEWS", {
      body: payload.body || "",
      icon: "/logo-icon-192.png",
      badge: "/logo-icon-192.png",
      data: { url: payload.url || "/index.html" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/index.html";
  event.waitUntil(clients.openWindow(url));
});
