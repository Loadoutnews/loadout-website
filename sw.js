// LOADOUT-NEWS — Service Worker
// ================================
// Grundgerüst für die PWA-Funktionalität:
//   - Registriert die Seite als installierbare App
//   - Cached die wichtigsten Dateien fürs schnellere Laden / eingeschränkte
//     Offline-Nutzung
//   - Push-Benachrichtigungen

// v2: CACHE_NAME bewusst erhöht (v1 -> v2) — das sorgt dafür, dass ALLE
// Besucher:innen beim nächsten Service-Worker-Update einen komplett
// frischen, leeren Cache bekommen. Nötig, weil der alte Cache (siehe Fix
// im "fetch"-Handler unten) möglicherweise bereits eine fälschlich
// zwischengespeicherte 404-Antwort enthält (z. B. für eine Seite, die im
// Moment des ersten Aufrufs noch nicht existierte) — ein blosses Ändern
// der Caching-Logik würde diesen bereits vorhandenen, kaputten Eintrag
// NICHT von selbst entfernen, da "activate" nur ANDERS benannte Caches
// löscht, nicht den aktuell aktiven.
const CACHE_NAME = "loadout-news-v2";
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
        // WICHTIG: fetch() schlägt NUR bei echten Netzwerkfehlern fehl
        // (keine Verbindung, DNS-Fehler) — ein HTTP-Fehler wie 404 oder
        // 500 gilt für fetch() als "erfolgreich zugestelltes" Ergebnis!
        // Ohne diese Prüfung landete bisher auch eine 404-Antwort (z. B.
        // weil eine Seite kurzzeitig noch nicht existierte, während der
        // Cache noch alt war) im Cache und wurde danach so lange als
        // "letzte bekannte Version" ausgeliefert, bis der Service Worker
        // sich irgendwann von selbst aktualisierte — sichtbares Symptom:
        // ein Seitenaufruf schlägt mit 404 fehl, klappt aber nach einem
        // Neustart der App/des Browsers plötzlich wieder.
        //
        // response.type "opaque" betrifft cross-origin-Anfragen (z. B.
        // Artikelbilder von externen Quellen wie picsum.photos) — dort
        // kann das Skript den echten HTTP-Status aus Sicherheitsgründen
        // gar nicht auslesen (der Browser blendet ihn aus), response.ok
        // ist bei solchen Antworten IMMER false, selbst bei Erfolg. Die
        // werden deshalb weiterhin normal gecacht, nur "echte" (same-
        // origin bzw. CORS-sichtbare) Fehlerantworten werden ausgefiltert.
        if (response.ok || response.type === "opaque") {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// --- Push-Benachrichtigungen -----------------------------------------------
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
