// Vercel Serverless Function: nimmt allgemeines Feedback zur Seite entgegen
// (Sternebewertung + optionaler Text), speichert es dauerhaft in Redis
// UND verschickt sofort eine E-Mail-Benachrichtigung an den Betreiber über
// Brevo (Transactional-E-Mail-API — nutzt dieselbe Absenderadresse und
// denselben API-Key wie der Newsletter).
//
// Voraussetzung: BREVO_API_KEY ist als Vercel-Umgebungsvariable bereits
// vorhanden (dieselbe wie bei api/subscribe.js).

import { Redis } from '@upstash/redis';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_KV_REST_API_URL,
  token: process.env.UPSTASH_REDIS_REST_KV_REST_API_TOKEN,
});

const OWNER_EMAIL = 'loadoutnews@gmail.com';
const SENDER_EMAIL = 'newsletter@loadout-news.com';
const MAX_TEXT_LENGTH = 1000;

export default async function handler(request, response) {
  if (request.method !== 'POST') {
    return response.status(405).json({ error: 'Method not allowed' });
  }

  const { rating, text, page, website } = request.body || {};

  // Honeypot — für Menschen unsichtbares Feld, Bots füllen es oft trotzdem aus
  if (website) {
    return response.status(200).json({ success: true });
  }

  const ratingNum = Number(rating);
  if (!Number.isInteger(ratingNum) || ratingNum < 1 || ratingNum > 5) {
    return response.status(400).json({ error: 'Ungültige Bewertung (1-5 erwartet)' });
  }

  const cleanText = String(text || '').replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '').trim().slice(0, MAX_TEXT_LENGTH);

  // Einfaches Rate-Limit pro IP-Adresse (1 Feedback alle 60 Sekunden)
  const ip = (request.headers['x-forwarded-for'] || 'unknown').split(',')[0].trim();
  try {
    const rateLimitKey = `feedback-ratelimit:${ip}`;
    const alreadySent = await redis.get(rateLimitKey);
    if (alreadySent) {
      return response.status(429).json({ error: 'Bitte kurz warten, bevor du erneut Feedback sendest.' });
    }
    await redis.set(rateLimitKey, '1', { ex: 60 });
  } catch (err) {
    // Rate-Limit-Prüfung fehlgeschlagen — im Zweifel trotzdem zulassen,
    // Spam-Schutz ist hier nicht sicherheitskritisch.
  }

  const feedback = {
    rating: ratingNum,
    text: cleanText,
    page: typeof page === 'string' ? page.slice(0, 200) : '',
    timestamp: new Date().toISOString(),
  };

  // Dauerhaft speichern, damit nichts verloren geht, selbst falls die
  // E-Mail mal nicht ankommt.
  try {
    await redis.rpush('site-feedback', JSON.stringify(feedback));
  } catch (err) {
    // Speichern fehlgeschlagen — trotzdem versuchen, wenigstens die E-Mail zu verschicken.
  }

  // E-Mail-Benachrichtigung über Brevo
  const apiKey = process.env.BREVO_API_KEY;
  if (apiKey) {
    try {
      await fetch('https://api.brevo.com/v3/smtp/email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'api-key': apiKey },
        body: JSON.stringify({
          sender: { name: 'LOADOUT-NEWS Feedback', email: SENDER_EMAIL },
          to: [{ email: OWNER_EMAIL, name: 'Marcel' }],
          subject: `${'⭐'.repeat(ratingNum)}${'☆'.repeat(5 - ratingNum)} Neues Feedback auf LOADOUT-NEWS`,
          htmlContent: `
            <div style="font-family:Arial,sans-serif; max-width:500px;">
              <h2>Neues Feedback erhalten</h2>
              <p><b>Bewertung:</b> ${'⭐'.repeat(ratingNum)}${'☆'.repeat(5 - ratingNum)} (${ratingNum}/5)</p>
              <p><b>Kommentar:</b><br>${cleanText ? cleanText.replace(/\n/g, '<br>') : '<i>(kein Text angegeben)</i>'}</p>
              <p><b>Seite:</b> ${feedback.page || '(unbekannt)'}</p>
              <p style="color:#888; font-size:12px;">${feedback.timestamp}</p>
            </div>
          `,
        }),
      });
    } catch (err) {
      // E-Mail fehlgeschlagen — Feedback ist trotzdem in Redis gespeichert,
      // daher kein harter Fehler an die Website zurückgeben.
    }
  }

  return response.status(200).json({ success: true });
}
