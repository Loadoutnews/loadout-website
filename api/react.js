// Vercel Serverless Function: verwaltet Like/Dislike-Reaktionen pro
// Artikel. GET liefert die aktuellen Zahlen (z. B. beim Laden der Seite),
// POST zählt eine Reaktion hoch. Ob jemand schon reagiert hat, wird NICHT
// hier serverseitig geprüft (dafür bräuchte es Nutzerkonten) — das
// übernimmt das Frontend über localStorage, um Mehrfach-Klicks vom
// gleichen Gerät zu verhindern.

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

export default async function handler(request, response) {
  const articleId = request.method === 'GET' ? request.query.articleId : request.body?.articleId;

  if (!articleId || typeof articleId !== 'string' || articleId.length > 100) {
    return response.status(400).json({ error: 'Ungültige articleId' });
  }

  try {
    if (request.method === 'GET') {
      const [likes, dislikes] = await Promise.all([
        redis.get(`likes:${articleId}`),
        redis.get(`dislikes:${articleId}`),
      ]);
      return response.status(200).json({ likes: likes || 0, dislikes: dislikes || 0 });
    }

    if (request.method === 'POST') {
      const { type } = request.body || {};
      if (type !== 'like' && type !== 'dislike') {
        return response.status(400).json({ error: 'type muss "like" oder "dislike" sein' });
      }
      const newCount = await redis.incr(`${type}s:${articleId}`);
      return response.status(200).json({ articleId, type, count: newCount });
    }

    return response.status(405).json({ error: 'Method not allowed' });
  } catch (err) {
    return response.status(200).json({ likes: 0, dislikes: 0, note: 'Redis nicht verfügbar' });
  }
}
