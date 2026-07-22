// Vercel Serverless Function: verschickt eine Push-Benachrichtigung an
// ALLE gespeicherten Abos. Wird von der Pipeline aufgerufen (nach neuen
// Artikeln, neuem Release-/Update-Kalender) — NICHT öffentlich zugänglich,
// sondern durch ein geheimes Passwort geschützt (PUSH_SECRET), damit nicht
// irgendwer beliebige Nachrichten an alle Nutzer:innen schicken kann.
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

  const { title, body, url } = request.body || {};
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

    await Promise.all(endpoints.map(async (endpoint) => {
      const subscription = typeof subsRaw[endpoint] === 'string' ? JSON.parse(subsRaw[endpoint]) : subsRaw[endpoint];
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

    return response.status(200).json({ sent, removed, total: endpoints.length });
  } catch (err) {
    return response.status(500).json({ error: 'Versand fehlgeschlagen' });
  }
}
