"""
LOADOUT-NEWS — Wöchentlicher Update-Kalender
==============================================
Recherchiert einmal pro Woche (per Anthropic-API mit echter Websuche)
angekündigte, aber noch nicht veröffentlichte Updates für grosse Spiele
(neue Seasons, grosse Patches, DLCs mit festem Termin).

Anders als der Release-Kalender wird hier NICHT jede Woche alles
überschrieben: Bereits bekannte Updates bleiben bestehen, bis ihr
Update-Datum erreicht ist — dann verschwinden sie automatisch, ganz
unabhängig davon, wann der nächste wöchentliche Lauf stattfindet. Neu
gefundene Updates werden einfach ergänzt (dedupliziert).

Setup:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY="dein-api-key"

Ausführen:
    python build_updates.py

Ergebnis:
    updates.json   -> alle aktuell noch gültigen (nicht abgelaufenen) Updates
    updates.html   -> die fertige Update-Kalender-Seite
"""

import json
import datetime
import hashlib
import os
import re
import sys

from anthropic import Anthropic
import requests

SITE_URL = "https://loadout-news.com"
MODEL = "claude-sonnet-5"
MAX_NEW_UPDATES_PER_RUN = 10
UPDATES_FILE = "updates.json"

client = Anthropic()


def update_id(game, update_title, update_date):
    """Stabile ID aus Spiel + Update-Name + Datum, damit dieselbe Meldung
    bei wiederholten Läufen nicht doppelt aufgenommen wird."""
    raw = f"{game}|{update_title}|{update_date}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def load_existing_updates():
    if os.path.exists(UPDATES_FILE):
        with open(UPDATES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def remove_expired(updates):
    """Wirft alle Updates raus, deren Datum bereits erreicht/vergangen ist —
    das ist der Kern des 'automatisch verschwinden'-Mechanismus."""
    today = datetime.date.today().isoformat()
    return [u for u in updates if u.get("update_date", "9999-99-99") >= today]


def research_updates(existing_titles):
    today_label = datetime.date.today().strftime("%d.%m.%Y")
    known_list = ", ".join(existing_titles) if existing_titles else "(noch keine bekannt)"

    system_prompt = f"""Du bist Redakteur:in bei LOADOUT-NEWS, einer Gaming-News-Seite.
Recherchiere mit der Websuche angekündigte, aber noch nicht veröffentlichte \
Updates für grosse, bekannte Spiele — z. B. neue Seasons, grosse Patches, \
DLCs oder Erweiterungen mit einem konkreten, offiziell bestätigten Termin \
in den nächsten 6 Wochen (Stand heute: {today_label}). Nur Updates mit \
einem echten, konkreten Datum — keine vagen "demnächst"-Ankündigungen.

Antworte AUSSCHLIESSLICH mit einem validen JSON-Array, keine Erklärungen, \
kein Markdown, keine Code-Fences. Jedes Element in diesem Format:

{{
  "game": "Spielname",
  "update_title": "z. B. 'Season 5: Aufbruch' oder 'Patch 2.3'",
  "update_date": "YYYY-MM-DD",
  "platforms": ["PC", "PS5", "Xbox Series X/S", ...],
  "content": "2-3 eigenständig formulierte Sätze, was das Update konkret bringt",
  "hype": <Zahl 0-100, wie gross das erwartete Interesse ist>,
  "source_url": "Link zu einer Seite MIT VORSCHAUBILD — bevorzugt IGN, GameSpot, PC Gamer, Eurogamer oder eine offizielle Spiele-/Store-Seite. Keine Wikipedia/Foren."
}}

Maximal {MAX_NEW_UPDATES_PER_RUN} Updates. Diese Updates sind bereits \
bekannt und sollen NICHT erneut ausgegeben werden, falls sie wieder \
auftauchen: {known_list}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=10000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Recherchiere anstehende, angekündigte Spiele-Updates, Stand {today_label}."}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print("! Keine Textantwort von Claude erhalten.", file=sys.stderr)
        return []

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    # Zusätzliche Absicherung: erklärenden Text vor dem eigentlichen
    # JSON-Array abschneiden, falls vorhanden. Das Ende bleibt bewusst
    # unangetastet, damit die Abschneide-Rettung (_recover_truncated_json_array)
    # bei abgebrochenen Antworten weiter korrekt greift.
    first_bracket = raw_text.find("[")
    if first_bracket > 0:
        raw_text = raw_text[first_bracket:]

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        recovered = _recover_truncated_json_array(raw_text)
        if recovered:
            print(f"  ⚠ Antwort war abgeschnitten — {len(recovered)} vollständige Einträge gerettet.", file=sys.stderr)
        else:
            print("! Antwort konnte nicht als JSON gelesen werden:", raw_text[:300], file=sys.stderr)
        return recovered


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
    """Dieselbe robuste Logik wie im News- und Release-System: übernimmt
    nur das echte Vorschaubild der Quelle, kein selbst ausgewähltes
    Spiele-Artwork (Urheberrecht!)."""
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
            return None
        for pattern in patterns:
            match = re.search(pattern, resp.text, re.I)
            if match:
                return urljoin(url, match.group(1))
    except Exception:
        pass
    return None


def update_image(u):
    img = fetch_og_image(u.get("source_url"))
    if img:
        return img
    seed = re.sub(r"[^a-zA-Z0-9]", "", (u.get("game", "") + u.get("update_title", "")) or "update")
    return f"https://picsum.photos/seed/loadout-update-{seed}/300/200"


def render_html(updates):
    updates_sorted = sorted(updates, key=lambda u: u.get("update_date", "9999-99-99"))

    cards = ""
    for u in updates_sorted:
        platforms = " · ".join(u.get("platforms", []))
        img = u.get("image") or update_image(u)
        update_date = u.get("update_date", "")
        cards += f"""
        <div class="release-card">
          <div class="release-art" style="background:linear-gradient(160deg, rgba(52,217,201,0.16), rgba(13,31,36,0.9)), url('{img}') center/cover;">
            <span class="badge hardware countdown-badge" data-update-date="{update_date}" style="position:absolute; top:10px; left:10px;"></span>
          </div>
          <div class="release-body">
            <h3>{u.get('game','')}</h3>
            <div class="release-meta mono">{u.get('update_title','')}</div>
            <p class="release-desc">{u.get('content','')}</p>
            <div class="release-footer">
              <span class="release-price mono">{u.get('update_date','')} · {platforms}</span>
              <div class="hype">
                <span class="hype-label mono">Hype</span>
                <div class="hype-bar"><div class="hype-fill" style="width:{u.get('hype',50)}%"></div></div>
                <span class="hype-pct mono">{u.get('hype',50)}%</span>
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
<title>Update-Kalender — LOADOUT-NEWS</title>
<meta name="description" content="Angekündigte Updates, Seasons und Patches grosser Spiele im Überblick — mit Termin, solange bis das Update erscheint.">
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
      <div><div class="logo-text display">LOAD<span>OUT</span><small class="mono">-NEWS</small></div></div>
    </div>
    <div class="nav-right" style="margin-left:auto;">
      <a href="index.html" class="xp-badge" style="text-decoration:none;">← Zum Feed</a>
    </div>
  </nav>
</div>

<main>
  <div class="ad-slot ad-header"><span class="ad-tag mono">Anzeige</span>Werbeplatz · 728×90</div>

  <div class="section-head" style="margin-top:24px;">
    <h2 class="mono">Update-Kalender</h2>
    <div class="rule"></div>
  </div>
  <h1 class="display" style="font-size:28px; margin-bottom:6px;">Angekündigte Updates & Seasons</h1>
  <p style="color:var(--muted); font-size:13.5px; margin-bottom:22px;">
    Diese Updates verschwinden automatisch von dieser Liste, sobald ihr Termin erreicht ist.
  </p>

  <div class="release-grid">
    {cards if cards else '<p style="color:var(--muted);">Aktuell sind keine angekündigten Updates mit festem Termin bekannt.</p>'}
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

<script>
  // Countdown wird bei JEDEM Seitenaufruf frisch berechnet — nicht einmalig
  // beim wöchentlichen Bauen der Seite. So bleibt "in X Tagen" auch dann
  // korrekt, wenn die Seite selbst erst wieder nächste Woche neu gebaut wird.
  document.querySelectorAll('.countdown-badge').forEach(el => {{
    const dateStr = el.dataset.updateDate;
    if(!dateStr) return;
    const target = new Date(dateStr + 'T00:00:00');
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diffDays = Math.round((target - today) / (1000 * 60 * 60 * 24));

    let text = `in ${{diffDays}} Tagen`;
    if(diffDays === 0) text = 'Heute';
    else if(diffDays === 1) text = 'Morgen';
    else if(diffDays < 0) text = 'Bereits da';
    el.textContent = text;
  }});
</script>

</body>
</html>
"""


def main():
    existing = load_existing_updates()
    existing = remove_expired(existing)
    print(f"→ {len(existing)} noch gültige Updates aus vorherigen Läufen (abgelaufene bereits entfernt)")

    existing_titles = [f"{u.get('game','')} – {u.get('update_title','')}" for u in existing]
    new_raw = research_updates(existing_titles)

    existing_ids = {u["id"] for u in existing if "id" in u}
    added = []
    for u in new_raw:
        uid = update_id(u.get("game", ""), u.get("update_title", ""), u.get("update_date", ""))
        if uid in existing_ids:
            continue
        u["id"] = uid
        added.append(u)
        existing_ids.add(uid)

    all_updates = existing + added
    all_updates = remove_expired(all_updates)

    # Bilder server-seitig auflösen und mitspeichern (siehe build_releases.py
    # für die Begründung — CORS verhindert das clientseitig im Browser).
    # Nur für neue Einträge nötig, bestehende haben ihr Bild schon gespeichert.
    for u in all_updates:
        if not u.get("image"):
            u["image"] = update_image(u)

    with open(UPDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(all_updates, f, ensure_ascii=False, indent=2)

    html = render_html(all_updates)
    with open("updates.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ {len(added)} neue Updates gefunden, {len(all_updates)} insgesamt aktuell gültig")


if __name__ == "__main__":
    main()
