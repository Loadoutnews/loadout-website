// Vercel Serverless Function: verschickt eine Push-Benachrichtigung.
// Wird von der Pipeline aufgerufen (nach neuen Artikeln, neuem Release-/
// Update-Kalender, Breaking News, Leaks & Gerüchte-Tracker-Ereignissen)
// — NICHT öffentlich zugänglich, sondern durch ein geheimes Passwort
// geschützt (PUSH_SECRET), damit nicht irgendwer beliebige Nachrichten an
// alle Nutzer:innen schicken kann.
//
// Kann optional gezielt nur an Abonnent:innen senden, die das betroffene
// Spiel/die Kategorie in ihren Präferenzen ausgewählt haben ("Folge nur
// deinen Spielen"-Feature). Ohne games/categories im Aufruf (z. B. bei
// Breaking News oder generischen Sammel-Benachrichtigungen) wird
// weiterhin an ALLE gesendet — genau wie bisher. Auch Abonnent:innen OHNE
// gesetzte Präferenzen bekommen weiterhin ausnahmslos alles, damit
// niemand durch dieses Feature unbeabsichtigt stummgeschaltet wird.
//
// NEU: contentType ist ein EIGENER, von games/categories UNABHÄNGIGER
// Filter — aktuell nur "rumors" für Leaks & Gerüchte-Tracker-Ereignisse
// (siehe post_to_social.py: post_rumor_event / push_helper.py). Wird
// contentType="rumors" mitgeschickt, wird zusätzlich zur Spiel-/
// Kategorie-Prüfung geprüft, ob die/der Abonnent:in den eigenen Leaks &
// Gerüchte-Schalter (preferences.rumors) nicht explizit ausgeschaltet hat
// — unabhängig davon, ob das betroffene Spiel/die Kategorie sonst
// abonniert wurde. So kann jemand z. B. GTA-News folgen, aber trotzdem
// nur bestätigte News wollen statt unbestätigter Leaks.
//
// Ungültig gewordene Abos (z. B. weil jemand die Benachrichtigungen im
// Browser blockiert oder deinstalliert hat) werden automatisch aus der
// Liste entfernt, statt bei jedem Versand erneut fehlzuschlagen.

import { Redis } from '@upstash/redis';
import webpush from 'web-push';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

webpush.setVapidDetails(
  'mailto:loadoutnews@gmail.com',
  process.env.VAPID_PUBLIC_KEY,
  process.env.VAPID_PRIVATE_KEY
);

export default async function handler(request, response) {
  if (request.method !== 'POST') {
    return response.status(405).json({ error: 'Method not allowed' });
  }

  const providedSecret = request.headers['x-push-secret'];
  if (!process.env.PUSH_SECRET || providedSecret !== process.env.PUSH_SECRET) {
    return response.status(401).json({ error: 'Nicht autorisiert' });
  }

  const { title, body, url, games, categories, contentType } = request.body || {};
  if (!title || !body) {
    return response.status(400).json({ error: 'title und body erforderlich' });
  }

  const payload = JSON.stringify({ title, body, url: url || '/index.html' });

  try {
    const subsRaw = await redis.hgetall('push-subscriptions');
    const endpoints = subsRaw ? Object.keys(subsRaw) : [];

    if (!endpoints.length) {
      return response.status(200).json({ sent: 0, note: 'Keine Abos vorhanden' });
    }

    let sent = 0;
    let removed = 0;
    let skipped = 0;

    await Promise.all(endpoints.map(async (endpoint) => {
      const raw = typeof subsRaw[endpoint] === 'string' ? JSON.parse(subsRaw[endpoint]) : subsRaw[endpoint];

      // Abwärtskompatibel: ältere Einträge (vor dem Präferenzen-Feature)
      // sind noch die rohe Subscription ohne { subscription, preferences }
      // -Hülle — die haben dann automatisch KEINE Präferenzen gesetzt und
      // bekommen dadurch weiterhin ausnahmslos alles.
      const subscription = raw.subscription || raw;
      const preferences = raw.preferences || {};
      const followedGames = Array.isArray(preferences.games) ? preferences.games : [];
      const followedCategories = Array.isArray(preferences.categories) ? preferences.categories : [];
      const hasPreferences = followedGames.length > 0 || followedCategories.length > 0;

      // Leaks & Gerüchte-Schalter: greift NUR bei contentType==="rumors",
      // unabhängig von games/categories. preferences.rumors fehlt bei
      // älteren Abos (vor diesem Feature) komplett — das ist absichtlich
      // KEIN Ausschlussgrund (undefined === false ist false), nur ein
      // EXPLIZITES false (bewusst abgeschaltet in "Meine Interessen")
      // blockt den Versand.
      if (contentType === 'rumors' && preferences.rumors === false) {
        skipped++;
        return;
      }

      // Gezieltes Filtern nach Spiel/Kategorie nur, wenn BEIDES zutrifft:
      // der Aufruf hat überhaupt Ziel-Spiele/-Kategorien angegeben UND
      // die/der Abonnent:in hat überhaupt eigene Präferenzen gesetzt.
      // Sonst (z. B. Breaking News ohne games/categories, oder eine
      // Person ohne gesetzte Präferenzen) wird immer zugestellt.
      if ((games || categories) && hasPreferences) {
        const matchesGame = Array.isArray(games) && games.some((g) => followedGames.includes(g));
        const matchesCategory = Array.isArray(categories) && categories.some((c) => followedCategories.includes(c));
        if (!matchesGame && !matchesCategory) {
          skipped++;
          return;
        }
      }

      try {
        await webpush.sendNotification(subscription, payload);
        sent++;
      } catch (err) {
        // 404/410 = Abo existiert nicht mehr (Nutzer:in hat deinstalliert,
        // Benachrichtigungen blockiert etc.) — aufräumen statt ignorieren.
        if (err.statusCode === 404 || err.statusCode === 410) {
          await redis.hdel('push-subscriptions', endpoint);
          removed++;
        }
      }
    }));

    return response.status(200).json({ sent, removed, skipped, total: endpoints.length });
  } catch (err) {
    return response.status(500).json({ error: 'Versand fehlgeschlagen' });
  }
}
