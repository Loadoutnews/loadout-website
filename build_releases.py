"""
LOADOUT-NEWS — Monatlicher Release-Kalender
=============================================
Recherchiert einmal im Monat (per Anthropic-API mit echter Web-Suche) die
bedeutendsten anstehenden Spiele-Releases für den aktuellen Monat und baut
daraus die Seite releases.html.

Setup:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY="dein-api-key"

Ausführen:
    python build_releases.py

Ergebnis:
    releases.json   -> die recherchierten Daten
    releases.html   -> die fertige Release-Kalender-Seite
"""

import json
import datetime
import re
import sys

from anthropic import Anthropic
import requests

SITE_URL = "https://loadout-news.com"
MODEL = "claude-sonnet-5"
MAX_RELEASES = 14

client = Anthropic()

MONTHS_DE = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}


def current_month_label():
    today = datetime.date.today()
    return f"{MONTHS_DE[today.month]} {today.year}", today.month, today.year


def research_releases(month_label):
    """Lässt Claude mit echter Web-Suche die wichtigsten Releases des Monats
    recherchieren und als striktes JSON zurückgeben."""
    system_prompt = f"""Du bist Redakteur:in bei LOADOUT-NEWS, einer Gaming-News-Seite.
Recherchiere mit der Websuche die bedeutendsten, meist erwarteten Spiele-Releases
für {month_label} — nur AAA-Titel bzw. Spiele mit erkennbar hohem Interesse
(nicht jedes kleine Indie-Spiel), maximal {MAX_RELEASES} Stück.

Recherchiere für jedes Spiel zusätzlich, wie hoch die Vorfreude/Nachfrage \
ist (z. B. Wishlist-Zahlen, Vorbestellungen, Community-Reaktionen auf \
Trailer/Ankündigungen) und wie es von Fachpresse/Expert:innen bisher \
eingeschätzt wird (Preview-Berichte, Hands-on-Eindrücke, falls vorhanden). \
Bilde dir daraus eine EIGENE redaktionelle Meinung: Lohnt sich der Kauf für \
das verlangte Geld — ja, nein, oder eher abwarten (z. B. auf einen Sale \
oder auf Reviews nach Release)?

Antworte AUSSCHLIESSLICH mit einem validen JSON-Array, keine Erklärungen,
kein Markdown, keine Code-Fences. Jedes Element im folgenden Format:

{{
  "title": "Spielname",
  "release_date": "YYYY-MM-DD",
  "platforms": ["PC", "PS5", "Xbox Series X/S", ...],
  "price": "z. B. CHF 79.90 (Standard) / CHF 99.90 (Deluxe) — oder 'noch nicht bekannt'",
  "genre": "z. B. Action-RPG",
  "description": "2-3 eigenständig formulierte Sätze — NICHT aus einer Quelle kopiert",
  "hype": <Zahl 0-100, wie gross das erwartete Interesse ist>,
  "recommendation": "ja" | "nein" | "abwarten",
  "recommendation_reason": "2-3 Sätze EIGENE Begründung, gestützt auf recherchierte Nachfrage/Experteneinschätzungen — als klare Position formuliert, nicht als reine Zusammenfassung.",
  "source_url": "Link zu einer Seite MIT VORSCHAUBILD — bevorzugt ein Artikel bei IGN, GameSpot, PC Gamer, Eurogamer oder die offizielle Store-Seite (Steam/PlayStation Store/Xbox). Vermeide Wikipedia, Foren oder reine Text-Ankündigungen ohne Titelbild."
}}

Nutze für Preise, sofern verfügbar, Schweizer Franken (CHF); falls nur andere
Währungen bekannt sind, gib diese an. Sortiere nach Release-Datum, dann nach Hype."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Recherchiere die Spiele-Releases für {month_label}."}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print("! Keine Textantwort von Claude erhalten.", file=sys.stderr)
        return []

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    first_bracket = raw_text.find("[")
    if first_bracket > 0:
        raw_text = raw_text[first_bracket:]

    try:
        releases = json.loads(raw_text)
    except json.JSONDecodeError:
        releases = _recover_truncated_json_array(raw_text)
        if releases:
            print(f"  ⚠ Antwort war abgeschnitten — {len(releases)} vollständige Einträge gerettet.", file=sys.stderr)
        else:
            print("! Antwort konnte nicht als JSON gelesen werden:", raw_text[:300], file=sys.stderr)
            return []

    return releases[:MAX_RELEASES]


def _recover_truncated_json_array(raw_text):
    last_brace = raw_text.rfind("}")
    if last_brace == -1:
        return []
    repaired = raw_text[: last_brace + 1] + "]"
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return []


def fetch_og_image(url, timeout=8):
    if not url:
        return None
    from urllib.parse import urljoin

    patterns = [
        r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image:src["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
    ]
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            },
        )
        if resp.status_code != 200:
            print(f"  ! og:image-Abruf fehlgeschlagen (Status {resp.status_code}) für {url}", file=sys.stderr)
            return None
        for pattern in patterns:
            match = re.search(pattern, resp.text, re.I)
            if match:
                return urljoin(url, match.group(1))
        print(f"  ! Kein og:image-Tag gefunden auf {url}", file=sys.stderr)
    except Exception as e:
        print(f"  ! Konnte kein og:image laden von {url}: {e}", file=sys.stderr)
        pass
    return None


def release_image(r):
    img = fetch_og_image(r.get("source_url"))
    if img:
        return img
    seed = re.sub(r"[^a-zA-Z0-9]", "", r.get("title", "release"))
    return f"https://picsum.photos/seed/loadout-release-{seed}/300/200"


def render_html(month_label, releases):
    REC_LABELS = {
        "ja": ("✅ Kaufen lohnt sich", "rec-yes"),
        "nein": ("❌ Eher nicht", "rec-no"),
        "abwarten": ("⏳ Abwarten empfohlen", "rec-wait"),
    }
    cards = ""
    for r in releases:
        platforms = " · ".join(r.get("platforms", []))
        img = r.get("image") or release_image(r)
        rec_key = (r.get("recommendation") or "").lower()
        rec_label, rec_class = REC_LABELS.get(rec_key, (None, None))
        rec_html = ""
        if rec_label:
            rec_html = f"""
            <div class="editorial-box {rec_class}">
              <div class="editorial-label mono">🗣️ Einschätzung der Redaktion — {rec_label}</div>
              <p>{r.get('recommendation_reason','')}</p>
            </div>
            """
        cards += f"""
        <div class="release-card">
          <div class="release-art" style="background:linear-gradient(160deg, rgba(18,48,40,0.78), rgba(13,31,36,0.9)), url('{img}') center/cover;">
            <span class="badge pc" style="position:absolute; top:10px; left:10px;">{r.get('genre','')}</span>
          </div>
          <div class="release-body">
            <h3>{r.get('title','')}</h3>
            <div class="release-meta mono">{r.get('release_date','')} · {platforms}</div>
            <p class="release-desc">{r.get('description','')}</p>
            {rec_html}
            <div class="release-footer">
              <span class="release-price mono">{r.get('price','')}</span>
              <div class="hype">
                <span class="hype-label mono">Hype</span>
                <div class="hype-bar"><div class="hype-fill" style="width:{r.get('hype',50)}%"></div></div>
                <span class="hype-pct mono">{r.get('hype',50)}%</span>
              </div>
            </div>
          </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Release-Kalender {month_label} — LOADOUT-NEWS</title>
<meta name="description" content="Alle wichtigen Spiele-Releases im {month_label} im Überblick — Termine, Plattformen, Preise.">
<link rel="stylesheet" href="styles.css">
</head>
<body>

<div class="nav-wrap">
  <nav>
    <div class="logo-lockup" onclick="location.href='index.html'">
      <svg class="logo-icon" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs><linearGradient id="navMarkGradient" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7C5CFC"/><stop offset="100%" stop-color="#FF4D8D"/></linearGradient></defs>
        <rect width="120" height="120" rx="26" fill="#0A0C16"/>
        <rect x="24" y="24" width="14" height="68" rx="6" fill="url(#navMarkGradient)"/>
        <rect x="24" y="80" width="72" height="12" rx="6" fill="url(#navMarkGradient)"/>
        <rect x="44" y="62" width="12" height="18" rx="5" fill="url(#navMarkGradient)"/>
        <rect x="60" y="50" width="12" height="30" rx="5" fill="url(#navMarkGradient)"/>
        <rect x="76" y="36" width="12" height="44" rx="5" fill="url(#navMarkGradient)"/>
      </svg>
      <div>
        <div class="logo-text display">LOAD<span>OUT</span><small class="mono">-NEWS</small></div>
      </div>
    </div>
    <div class="nav-right" style="margin-left:auto;">
      <a href="index.html" class="xp-badge" style="text-decoration:none;">← Zum Feed</a>
    </div>
  </nav>
</div>

<main>
  <div class="ad-slot ad-header">
    <span class="ad-tag mono">Anzeige</span>
    <!-- START ADVERTISER: Kinguin DE from awin.com -->
    <a rel="sponsored" href="https://www.awin1.com/cread.php?s=3562320&v=9862&q=417917&r=3000881">
      <img src="https://www.awin1.com/cshow.php?s=3562320&v=9862&q=417917&r=3000881" border="0">
    </a>
    <!-- END ADVERTISER: Kinguin DE from awin.com -->
  </div>

  <div class="section-head" style="margin-top:24px;">
    <h2 class="mono">Release-Kalender</h2>
    <div class="rule"></div>
  </div>
  <h1 class="display" style="font-size:28px; margin-bottom:22px;">Diese Spiele erscheinen im {month_label}</h1>

  <div class="release-grid">
    {cards}
  </div>

  <div class="ad-slot ad-footer" style="margin-top:30px;"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 728×90</div>
</main>

<footer>
  <div class="social-icons">
    <a href="https://instagram.com/loadoutnews" target="_blank" rel="noopener" title="Instagram" aria-label="Instagram">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.3" cy="6.7" r="1.1" fill="currentColor" stroke="none"/></svg>
    </a>
    <a href="https://reddit.com/r/LoadoutNews" target="_blank" rel="noopener" title="Reddit" aria-label="Reddit">
      <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="13" r="7"/><circle cx="9" cy="13" r="1.1" fill="#0A0C16"/><circle cx="15" cy="13" r="1.1" fill="#0A0C16"/><path d="M8.7 16.2c1 .9 5.6.9 6.6 0" stroke="#0A0C16" stroke-width="1" fill="none" stroke-linecap="round"/><circle cx="18.2" cy="8" r="1.4"/><line x1="12" y1="6" x2="12" y2="3.3" stroke="currentColor" stroke-width="1.1"/><circle cx="12" cy="2.7" r="0.9"/></svg>
    </a>
    <a href="https://loadout-news.tumblr.com" target="_blank" rel="noopener" title="Tumblr" aria-label="Tumblr">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.5 3v4.2h3.2v3.3h-3.2v6.1c0 1.4.7 1.9 1.8 1.9.4 0 .9-.1 1.4-.3v3.3c-.6.3-1.6.5-2.8.5-3 0-4.6-1.7-4.6-4.5v-6H8v-2.5c2.1-.1 3.2-1.5 3.4-3.9V3h3.1z"/></svg>
    </a>
    <a href="https://bsky.app/profile/loadout-news.bsky.social" target="_blank" rel="noopener" title="Bluesky" aria-label="Bluesky">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 9.6c-1.2-2.4-3.7-4.6-6.3-5.3C4.1 3.9 3.2 4.4 3.2 5.8c0 2.9 1.5 6.5 3.9 8-1 .1-1.9.5-1.9 1.6 0 1.4 1.7 2.2 3.4 1.6 1-.4 2.4-1.4 3.4-3.1 1 1.7 2.4 2.7 3.4 3.1 1.7.6 3.4-.2 3.4-1.6 0-1.1-.9-1.5-1.9-1.6 2.4-1.5 3.9-5.1 3.9-8 0-1.4-.9-1.9-2.5-1.5-2.6.7-5.1 2.9-6.3 5.3z"/></svg>
    </a>
  </div>
  <div class="footer-links mono">
    <a href="index.html">Zur Startseite</a>
    <a href="impressum.html">Impressum</a>
    <a href="datenschutz.html">Datenschutz</a>
    <span>© 2026 LOADOUT-NEWS</span>
  </div>
</footer>

</body>
</html>
"""


def main():
    month_label, month, year = current_month_label()
    print(f"→ Recherchiere Releases für {month_label} …")

    releases = research_releases(month_label)
    if not releases:
        print("! Keine Releases gefunden, breche ab.", file=sys.stderr)
        sys.exit(1)

    for r in releases:
        r["image"] = release_image(r)

    with open("releases.json", "w", encoding="utf-8") as f:
        json.dump({"month": month_label, "month_num": month, "year": year, "releases": releases},
                   f, ensure_ascii=False, indent=2)

    html = render_html(month_label, releases)
    with open("releases.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ {len(releases)} Releases für {month_label} gefunden, releases.html erzeugt")


if __name__ == "__main__":
    main()
