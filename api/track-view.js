// Vercel Serverless Function: zählt einen echten Seitenaufruf für einen
// Artikel hoch. Wird aufgerufen, sobald jemand einen Artikel tatsächlich
// öffnet — sowohl von der Hauptseite (index.html) als auch von den
// einzelnen statischen Artikel-Seiten aus.
//
// Voraussetzung: Die "Upstash"-Integration muss im Vercel-Dashboard unter
// Storage → Create Database → Upstash mit diesem Projekt verbunden sein.
// Vercel/Upstash setzen die nötigen Umgebungsvariablen dann automatisch.

import { Redis } from '@upstash/redis';

const redis = Redis.fromEnv();

export default async function handler(request, response) {
  if (request.method !== 'POST') {
    return response.status(405).json({ error: 'Method not allowed' });
  }

  const { articleId } = request.body || {};
  if (!articleId || typeof articleId !== 'string' || articleId.length > 100) {
    return response.status(400).json({ error: 'Ungültige articleId' });
  }

  try {
    const newCount = await redis.incr(`views:${articleId}`);
    return response.status(200).json({ articleId, views: newCount });
  } catch (err) {
    // Upstash noch nicht eingerichtet oder vorübergehend nicht erreichbar —
    // das darf die Website selbst nie kaputt machen, deshalb hier nur
    // ein stiller Fehler ohne Auswirkung auf das Nutzererlebnis.
    return response.status(200).json({ articleId, views: null, note: 'Redis nicht verfügbar' });
  }
}
