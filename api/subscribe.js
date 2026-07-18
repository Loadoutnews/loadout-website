// Vercel Serverless Function: meldet eine E-Mail-Adresse bei Brevo zum
// Newsletter an — inklusive Double-Opt-in (Brevo verschickt automatisch
// eine Bestätigungs-E-Mail, der Kontakt wird erst nach Klick auf den
// Bestätigungslink wirklich der Liste hinzugefügt).
//
// Voraussetzung: Ein kostenloses Brevo-Konto mit
//   - einer Kontaktliste (Contacts → Lists) — deren ID als BREVO_LIST_ID
//   - einer "Double opt-in"-Bestätigungs-E-Mail-Vorlage — deren ID als
//     BREVO_TEMPLATE_ID
//   - einem API-Key (Settings → SMTP & API → API Keys) als BREVO_API_KEY
// Alle drei als Umgebungsvariablen in Vercel hinterlegen (Settings →
// Environment Variables).

export default async function handler(request, response) {
  if (request.method !== 'POST') {
    return response.status(405).json({ error: 'Method not allowed' });
  }

  const { email } = request.body || {};
  const isValidEmail = typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  if (!isValidEmail) {
    return response.status(400).json({ success: false, error: 'Ungültige E-Mail-Adresse' });
  }

  const { BREVO_API_KEY, BREVO_LIST_ID, BREVO_TEMPLATE_ID } = process.env;
  if (!BREVO_API_KEY || !BREVO_LIST_ID || !BREVO_TEMPLATE_ID) {
    return response.status(200).json({ success: false, error: 'Newsletter noch nicht eingerichtet' });
  }

  try {
    const brevoRes = await fetch('https://api.brevo.com/v3/contacts/doubleOptinConfirmation', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'api-key': BREVO_API_KEY,
      },
      body: JSON.stringify({
        email,
        includeListIds: [Number(BREVO_LIST_ID)],
        templateId: Number(BREVO_TEMPLATE_ID),
        redirectionUrl: 'https://loadout-news.com/',
      }),
    });

    // Brevo liefert 201 (neu) oder 204 (schon vorhanden, erneut angestoßen)
    if (brevoRes.status === 201 || brevoRes.status === 204) {
      return response.status(200).json({ success: true });
    }

    const errorData = await brevoRes.json().catch(() => ({}));
    return response.status(200).json({ success: false, error: errorData.message || 'Unbekannter Fehler bei Brevo' });
  } catch (err) {
    return response.status(200).json({ success: false, error: 'Newsletter-Dienst gerade nicht erreichbar' });
  }
}
