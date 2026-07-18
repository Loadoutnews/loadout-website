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
  "source_url": "Link zu einer Seite MIT VORSCHAUBILD — bevorzugt ein Artikel bei IGN, GameSpot, PC Gamer, Eurogamer oder die offizielle Store-Seite (Steam/PlayStation Store/Xbox). Vermeide Wikipedia, Foren oder reine Text-Ankündigungen ohne Titelbild."
}}

Nutze für Preise, sofern verfügbar, Schweizer Franken (CHF); falls nur andere
Währungen bekannt sind, gib diese an. Sortiere nach Release-Datum, dann nach Hype."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Recherchiere die Spiele-Releases für {month_label}."}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    # Bei aktivierter Websuche enthält die Antwort mehrere Blöcke (Suchanfragen,
    # Suchergebnisse, ggf. Denk-Blöcke) — uns interessiert nur der/die finalen
    # Text-Block(e) mit dem eigentlichen JSON-Ergebnis.
    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print("! Keine Textantwort von Claude erhalten.", file=sys.stderr)
        return []

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        releases = json.loads(raw_text)
    except json.JSONDecodeError:
        # Falls die Antwort (z. B. durch ein Token-Limit) mitten im JSON
        # abgeschnitten wurde: die bereits vollständigen Objekte im Array
        # retten, statt alles zu verwerfen.
        releases = _recover_truncated_json_array(raw_text)
        if releases:
            print(f"  ⚠ Antwort war abgeschnitten — {len(releases)} vollständige Einträge gerettet.", file=sys.stderr)
        else:
            print("! Antwort konnte nicht als JSON gelesen werden:", raw_text[:300], file=sys.stderr)
            return []

    return releases[:MAX_RELEASES]


def _recover_truncated_json_array(raw_text):
    """Versucht, aus einem abgeschnittenen JSON-Array die letzten
    vollständigen {...}-Objekte zu retten, indem das Array nach dem letzten
    vollständigen '}' geschlossen wird."""
    last_brace = raw_text.rfind("}")
    if last_brace == -1:
        return []
    repaired = raw_text[: last_brace + 1] + "]"
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return []


def fetch_og_image(url, timeout=8):
    """Dieselbe robuste Logik wie in news_pipeline.py: versucht, das
    offizielle Vorschaubild der Quelle zu übernehmen, statt Spiele-Artwork
    selbst auszuwählen (Urheberrecht!). Prüft mehrere Meta-Tag-Varianten und
    löst relative Bild-Pfade zu vollständigen URLs auf."""
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
    cards = ""
    for r in releases:
        platforms = " · ".join(r.get("platforms", []))
        img = r.get("image") or release_image(r)
        cards += f"""
        <div class="release-card">
          <div class="release-art" style="background:linear-gradient(160deg, rgba(18,48,40,0.78), rgba(13,31,36,0.9)), url('{img}') center/cover;">
            <span class="badge pc" style="position:absolute; top:10px; left:10px;">{r.get('genre','')}</span>
          </div>
          <div class="release-body">
            <h3>{r.get('title','')}</h3>
            <div class="release-meta mono">{r.get('release_date','')} · {platforms}</div>
            <p class="release-desc">{r.get('description','')}</p>
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
  <div class="ad-slot ad-header"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 728×90</div>

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

    # Bilder einmal server-seitig auflösen und im Datensatz selbst
    # mitspeichern — Browser dürfen fremde Seiten aus Sicherheitsgründen
    # (CORS) nicht einfach per JavaScript nach og:image durchsuchen, daher
    # muss das fertige Bild schon in releases.json stehen.
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
