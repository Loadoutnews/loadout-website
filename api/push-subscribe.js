// Vercel Serverless Function: verwaltet Push-Benachrichtigungs-Abos.
// POST speichert ein neues Abo (wird aufgerufen, sobald jemand im Browser
// zustimmt) ZUSAMMEN MIT den gewählten Präferenzen (welche Spiele/
// Kategorien jemand folgen möchte — Teil des "Folge nur deinen Spielen"-
// Features, PLUS der eigene Leaks & Gerüchte-Schalter, siehe unten),
// DELETE entfernt eines wieder (falls jemand abbestellt oder der Browser
// die Berechtigung zurückzieht).
//
// Abos werden als Redis-Hash gespeichert (Schlüssel = Endpoint-URL des
// Abos, das ist pro Gerät/Browser eindeutig), damit sich ein Gerät nicht
// mehrfach einträgt. Gespeicherter Wert ist jetzt ein Objekt
// { subscription, preferences } statt nur der rohen Subscription — so
// lässt sich beim Versenden gezielt filtern (siehe send-push.js).
//
// Präferenzen sind bewusst OPTIONAL: Wer nichts auswählt (preferences
// bleibt leer), bekommt weiterhin ALLE Benachrichtigungen — niemand wird
// durch dieses Feature unbeabsichtigt stummgeschaltet.
//
// NEU: preferences.rumors ist ein EIGENER, von games/categories
// UNABHÄNGIGER Ein/Aus-Schalter speziell für Leaks & Gerüchte-Tracker-
// Ereignisse (siehe send-push.js: contentType==="rumors"). Jemand kann
// z. B. GTA-News abonniert haben, aber trotzdem NUR bestätigte News
// wollen, keine unbestätigten Leaks — dafür reicht die Spiel-/Kategorie-
// Filterung allein nicht. Standard ist TRUE (nur ein EXPLIZITES false
// schaltet ab) — dieselbe "niemand wird unbeabsichtigt stummgeschaltet"-
// Philosophie wie bei games/categories, nur umgekehrt herum defaultet
// (dort: leer = alles bekommen; hier: nicht gesetzt = weiterhin an).

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

export default async function handler(request, response) {
  if (request.method === 'POST') {
    // Abwärtskompatibel: akzeptiert sowohl das neue Format
    // { subscription, preferences } als auch (falls irgendwo noch alter
    // Frontend-Code aktiv ist) die rohe Subscription direkt im Body.
    const body = request.body || {};
    const subscription = body.subscription || body;
    const preferences = body.preferences || {};

    if (!subscription || !subscription.endpoint) {
      return response.status(400).json({ error: 'Ungültiges Abo' });
    }

    // Präferenzen normalisieren — immer definiert, nie undefined, damit
    // send-push.js sich beim Filtern nicht um fehlende Felder kümmern muss.
    const normalizedPreferences = {
      games: Array.isArray(preferences.games) ? preferences.games : [],
      categories: Array.isArray(preferences.categories) ? preferences.categories : [],
      // preferences.rumors !== false statt preferences.rumors === true:
      // fehlt das Feld ganz (älterer Frontend-Stand, oder Nutzer:in hat
      // den Schalter nie angefasst) ODER ist es explizit true, bleibt der
      // Standard "an". Nur ein explizites false schaltet wirklich ab.
      rumors: preferences.rumors !== false,
    };

    try {
      const entry = { subscription, preferences: normalizedPreferences };
      // Der Endpoint selbst dient als eindeutiger Schlüssel im Hash.
      await redis.hset('push-subscriptions', { [subscription.endpoint]: JSON.stringify(entry) });
      return response.status(200).json({ success: true });
    } catch (err) {
      return response.status(500).json({ error: 'Konnte Abo nicht speichern' });
    }
  }

  if (request.method === 'DELETE') {
    const { endpoint } = request.body || {};
    if (!endpoint) return response.status(400).json({ error: 'endpoint fehlt' });
    try {
      await redis.hdel('push-subscriptions', endpoint);
      return response.status(200).json({ success: true });
    } catch (err) {
      return response.status(500).json({ error: 'Konnte Abo nicht entfernen' });
    }
  }

  return response.status(405).json({ error: 'Method not allowed' });
}
