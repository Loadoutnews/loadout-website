// Vercel Serverless Function: verwaltet Push-Benachrichtigungs-Abos.
// POST speichert ein neues Abo (wird aufgerufen, sobald jemand im Browser
// zustimmt), DELETE entfernt eines wieder (falls jemand abbestellt oder der
// Browser die Berechtigung zurückzieht).
//
// Abos werden als Redis-Hash gespeichert (Schlüssel = Endpoint-URL des
// Abos, das ist pro Gerät/Browser eindeutig), damit sich ein Gerät nicht
// mehrfach einträgt.

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

export default async function handler(request, response) {
  if (request.method === 'POST') {
    const subscription = request.body;
    if (!subscription || !subscription.endpoint) {
      return response.status(400).json({ error: 'Ungültiges Abo' });
    }
    try {
      // Der Endpoint selbst dient als eindeutiger Schlüssel im Hash.
      await redis.hset('push-subscriptions', { [subscription.endpoint]: JSON.stringify(subscription) });
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
