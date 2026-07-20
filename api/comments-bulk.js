// Vercel Serverless Function: liefert die Anzahl der Kommentare pro
// Artikel auf einmal zurück (ähnlich wie /api/views und /api/likes-bulk),
// damit die Trending-Berechnung auf der Startseite Kommentare mit
// einbeziehen kann, ohne für jeden Artikel einzeln nachzufragen.

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

export default async function handler(request, response) {
  try {
    const keys = await redis.keys('comments:*');
    if (!keys.length) {
      return response.status(200).json({});
    }
    const counts = await Promise.all(keys.map(key => redis.llen(key)));
    const result = {};
    keys.forEach((key, i) => {
      const articleId = key.replace('comments:', '');
      result[articleId] = counts[i] || 0;
    });
    response.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=120');
    return response.status(200).json(result);
  } catch (err) {
    return response.status(200).json({});
  }
}
