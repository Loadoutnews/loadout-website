// Vercel Serverless Function: liefert die aktuellen Aufrufzahlen aller
// Artikel zurück, z. B. { "gta6price": 42, "halo001": 17 }.
// Die Website lädt das beim Öffnen und bestimmt daraus den wirklich
// meistgelesenen Artikel für Hero-Kachel und "Trending jetzt".

import { kv } from '@vercel/kv';

export default async function handler(request, response) {
  try {
    const keys = await kv.keys('views:*');
    if (!keys.length) {
      return response.status(200).json({});
    }
    const values = await kv.mget(...keys);
    const result = {};
    keys.forEach((key, i) => {
      const articleId = key.replace('views:', '');
      result[articleId] = values[i] || 0;
    });
    // Kurzzeitiges Caching am Edge, damit nicht jeder einzelne Seitenaufruf
    // die Datenbank direkt belastet.
    response.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=120');
    return response.status(200).json(result);
  } catch (err) {
    // KV noch nicht eingerichtet — Website fällt dann automatisch auf die
    // KI-Einschätzung (Hype-Wert) zurück, siehe index.html.
    return response.status(200).json({});
  }
}
