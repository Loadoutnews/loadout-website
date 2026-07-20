// Vercel Serverless Function: verwaltet Kommentare pro Artikel.
// GET liefert alle Kommentare, POST fügt einen neuen hinzu.
//
// Eingebauter Basis-Spamschutz:
//   - Längen-Begrenzung bei Name und Text
//   - Honeypot-Feld ("website") — für Menschen unsichtbar, Bots füllen es
//     oft trotzdem aus; ist es ausgefüllt, wird der Kommentar stillschweigend
//     verworfen
//   - Rate-Limit: max. 1 Kommentar pro IP-Adresse alle 30 Sekunden
//
// Moderation: Es gibt (bewusst, um die Sache einfach zu halten) keine
// eigene Lösch-Oberfläche. Einzelne Kommentare können direkt über die
// Upstash-Weboberfläche (Konsole → Datenbank → Data Browser) gefunden und
// entfernt werden, falls nötig — dort einfach nach "comments:<artikel-id>"
// suchen.

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

const MAX_NAME_LENGTH = 40;
const MAX_TEXT_LENGTH = 500;
const MAX_COMMENTS_RETURNED = 200;

function escapeForStorage(str) {
  // Kommentare werden im Frontend über textContent angezeigt, nie über
  // innerHTML — trotzdem sicherheitshalber auch hier schon Kontrollzeichen
  // entfernen.
  return str.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '').trim();
}

export default async function handler(request, response) {
  const articleId = request.method === 'GET' ? request.query.articleId : request.body?.articleId;
  if (!articleId || typeof articleId !== 'string' || articleId.length > 100) {
    return response.status(400).json({ error: 'Ungültige articleId' });
  }

  try {
    if (request.method === 'GET') {
      const raw = await redis.lrange(`comments:${articleId}`, 0, MAX_COMMENTS_RETURNED - 1);
      const comments = (raw || []).map(c => (typeof c === 'string' ? JSON.parse(c) : c));
      return response.status(200).json({ comments });
    }

    if (request.method === 'POST') {
      const { name, text, website } = request.body || {};

      // Honeypot — für echte Nutzer:innen unsichtbares Feld im Formular.
      if (website) {
        return response.status(200).json({ success: true }); // Bot bekommt "Erfolg" vorgetäuscht, damit er nicht nachbessert
      }

      const cleanText = escapeForStorage(String(text || ''));
      const cleanName = escapeForStorage(String(name || '')).slice(0, MAX_NAME_LENGTH) || 'Anonym';

      if (!cleanText || cleanText.length > MAX_TEXT_LENGTH) {
        return response.status(400).json({ error: 'Kommentar fehlt oder ist zu lang' });
      }

      // Einfaches Rate-Limit pro IP-Adresse
      const ip = (request.headers['x-forwarded-for'] || 'unknown').split(',')[0].trim();
      const rateLimitKey = `comment-ratelimit:${ip}`;
      const alreadyPosted = await redis.get(rateLimitKey);
      if (alreadyPosted) {
        return response.status(429).json({ error: 'Bitte kurz warten, bevor du erneut kommentierst.' });
      }
      await redis.set(rateLimitKey, '1', { ex: 30 });

      const comment = {
        name: cleanName,
        text: cleanText,
        timestamp: new Date().toISOString(),
      };
      await redis.rpush(`comments:${articleId}`, JSON.stringify(comment));

      return response.status(200).json({ success: true, comment });
    }

    return response.status(405).json({ error: 'Method not allowed' });
  } catch (err) {
    return response.status(500).json({ error: 'Kommentar konnte nicht gespeichert werden' });
  }
}
