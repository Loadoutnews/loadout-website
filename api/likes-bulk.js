// Vercel Serverless Function: liefert die aktuellen Like-Zahlen ALLER
// Artikel auf einmal zurück (ähnlich wie /api/views), damit die Startseite
// nach "Meiste Likes" sortieren kann, ohne für jeden Artikel einzeln
// nachfragen zu müssen.

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

export default async function handler(request, response) {
  try {
    const keys = await redis.keys('likes:*');
    if (!keys.length) {
      return response.status(200).json({});
    }
    const values = await redis.mget(...keys);
    const result = {};
    keys.forEach((key, i) => {
      const articleId = key.replace('likes:', '');
      result[articleId] = values[i] || 0;
    });
    response.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=120');
    return response.status(200).json(result);
  } catch (err) {
    return response.status(200).json({});
  }
}
