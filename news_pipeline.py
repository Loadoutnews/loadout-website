"""
LOADOUT-NEWS — News-Pipeline
================================
Holt neue Gaming-News aus mehreren RSS-Feeds, lässt Claude daraus
eigenständige deutsche (und englische) Artikel schreiben, und schreibt
das Ergebnis nach articles.json (aktuelle Artikel, gedeckelt) und
archive.json (alle Artikel, für immer).

Läuft alle paar Stunden über GitHub Actions (per cron-job.org ausgelöst).
"""

import json
import hashlib
import datetime
import os
import re
import sys
import difflib

import feedparser
import requests
from anthropic import Anthropic

MODEL = "claude-sonnet-5"
SITE_URL = "https://loadout-news.com"

FEEDS = [
    {"url": "https://www.ign.com/rss/articles/feed?tags=games", "priority": False},
    {"url": "https://www.pcgamer.com/rss/", "priority": False},
    {"url": "https://www.eurogamer.net/feed", "priority": False},
    {"url": "https://www.nintendolife.com/feeds/latest", "priority": False},
    {"url": "https://kotaku.com/rss", "priority": False},
    {"url": "https://www.polygon.com/rss/index.xml", "priority": False},
    {"url": "https://www.gamespot.com/feeds/mashup/", "priority": False},
    {"url": "https://www.rockpapershotgun.com/feed", "priority": False},
    {"url": "https://www.vg247.com/feed", "priority": False},
    {"url": "https://www.pcgamesn.com/feed", "priority": False},
    {"url": "https://www.gamesradar.com/feeds/rss", "priority": False},

    # Spezialisierte Feeds für die 6 großen Franchise-Hubs (GTA, Minecraft,
    # Fortnite, Call of Duty, Valorant/LoL, FIFA/EA Sports FC). Diese werden
    # unten über PRIORITY_QUOTA bevorzugt behandelt, damit jeder Lauf
    # gezielt Artikel für diese Hubs liefert statt zufällig darauf zu warten.
    {"url": "https://rockstarintel.com/feed/", "priority": True},           # GTA
    {"url": "https://gamerant.com/feed/minecraft-news", "priority": True},  # Minecraft
    {"url": "https://gamerant.com/feed/fortnite-news", "priority": True},   # Fortnite
    {"url": "https://charlieintel.com/feed", "priority": True},            # Call of Duty
    {"url": "https://dotesports.com/feed", "priority": True},              # Valorant/LoL
    {"url": "https://realsport101.com/feed.xml", "priority": True},        # FIFA/EA Sports FC
]

# Wie viele der pro Lauf geschriebenen Artikel mindestens aus den
# Franchise-Feeds oben kommen sollen (der Rest wird mit allgemeinen
# Gaming-News aufgefüllt).
PRIORITY_QUOTA = 1

MAX_ARTICLES_PER_RUN = 4          # wie viele neue Artikel pro Durchlauf geschrieben werden
MAX_ARTICLES_TOTAL = 60           # wie viele Artikel maximal in articles.json stehen (Homepage-Cache)

ARTICLES_FILE = "articles.json"
ARCHIVE_FILE = "archive.json"

client = Anthropic()


def article_id(link):
    """Stabile, kurze ID aus dem Original-Link ableiten (verhindert Duplikate)."""
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:10]


TITLE_SIMILARITY_THRESHOLD = 0.6  # ab diesem Ähnlichkeitswert (0-1) gilt es als "gleiches Thema"


def normalize_title(title):
    """Titel auf reinen Wortkern reduzieren, damit z. B. unterschiedliche
    Satzzeichen/Groß-Kleinschreibung den Vergleich nicht verfälschen."""
    return re.sub(r"[^a-z0-9\s]", "", title.lower()).strip()


def titles_similar(a, b, threshold=TITLE_SIMILARITY_THRESHOLD):
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio() >= threshold


def filter_duplicate_topics(entries, already_covered_titles):
    """Entfernt Meldungen, deren (englischer Original-)Titel einem bereits
    verarbeiteten Thema zu ähnlich ist — sowohl im Vergleich zu kürzlich
    geschriebenen Artikeln (verschiedene Läufe) als auch zu anderen
    Einträgen im selben Lauf (verschiedene Quellen, gleiches Thema, z. B.
    IGN und PCGamer berichten beide über dasselbe GTA-Update).

    WICHTIG: already_covered_titles muss ebenfalls die ENGLISCHEN
    Original-Quelltitel enthalten, nicht die fertigen deutschen
    Artikeltitel — sonst vergleicht die Ähnlichkeitsprüfung Äpfel mit
    Birnen (Englisch gegen Deutsch) und schlägt praktisch nie an, egal
    wie ähnlich die Themen wirklich sind."""
    kept = []
    seen_titles = list(already_covered_titles)
    for entry in entries:
        if any(titles_similar(entry["title"], seen) for seen in seen_titles if seen):
            continue  # gleiches Thema wurde schon abgedeckt — überspringen
        kept.append(entry)
        seen_titles.append(entry["title"])
    return kept


def fetch_og_image(url, timeout=8):
    """Robuste og:image-Extraktion von der Original-Artikel-Seite, falls
    der RSS-Feed selbst kein Bild mitliefert."""
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


def fetch_raw_entries():
    """Liest alle konfigurierten RSS-Feeds und gibt eine flache Liste aller
    Einträge zurück (Titel, Link, Zusammenfassung, Quelle, Prioritäts-Flag)."""
    entries = []
    for feed_cfg in FEEDS:
        try:
            parsed = feedparser.parse(feed_cfg["url"])
            source_name = parsed.feed.get("title", feed_cfg["url"]) if parsed.feed else feed_cfg["url"]
            for e in parsed.entries[:20]:
                image = None
                if "media_content" in e and e.media_content:
                    image = e.media_content[0].get("url")
                elif "media_thumbnail" in e and e.media_thumbnail:
                    image = e.media_thumbnail[0].get("url")
                entries.append({
                    "title": e.get("title", ""),
                    "link": e.get("link", ""),
                    "summary": e.get("summary", e.get("description", "")),
                    "source": source_name,
                    "priority": feed_cfg["priority"],
                    "image": image,
                })
        except Exception as ex:
            print(f"  ! Feed konnte nicht gelesen werden ({feed_cfg['url']}): {ex}", file=sys.stderr)
    return entries


WRITER_SYSTEM_PROMPT = """Du bist Redakteur:in bei LOADOUT, einer deutschsprachigen Gaming- \
und Tech-News-Seite. Du bekommst Titel, Kurzbeschreibung und Quelle einer \
englischsprachigen News-Meldung und schreibst daraus einen eigenständigen, \
spannend geschriebenen deutschen Artikel.

Regeln:
- Schreibe komplett in eigenen Worten. Übersetze NICHT wörtlich, formuliere neu.
- Keine wörtlichen Zitate aus der Quelle übernehmen.
- Ton: informativ, aber lebendig und für Gaming-Fans geschrieben, nicht trocken.
- Ordne die Meldung ein (Warum ist das relevant? Was bedeutet es für Spieler:innen?).
- Nutze die Websuche, um herauszufinden, was ANDERE Quellen, Fachpresse und die \
Community zu diesem Thema sagen — nicht nur die eine gegebene Quelle. Fasse \
diese verschiedenen Einschätzungen in eigenen Worten in den Artikel mit ein \
(z. B. "Mehrere Fachmedien loben..." / "In der Community gibt es geteilte \
Reaktionen: Während... loben, kritisieren andere...").
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine Erklärungen, \
kein Markdown, keine Code-Fences.

JSON-Format:
{
  "cat": "pc" | "konsole" | "hardware" | "industrie",
  "game": "gta" | "minecraft" | "fortnite" | "cod" | "valorant" | "fifa" | null,
  "genre": "action" | "adventure" | "rpg" | "strategie" | "simulation" | "shooter" | "sport" | "rennspiel" | "horror" | "puzzle" | null,
  "title": "Deutscher, knackiger Titel (max. 90 Zeichen)",
  "teaser": "1-2 Sätze Anreißer (max. 200 Zeichen)",
  "body": ["Absatz 1", "Absatz 2", "Absatz 3 — hier auch einordnen, was andere Quellen/Experten/die Community dazu sagen"],
  "editorial_take": "2-3 Sätze EIGENE redaktionelle Einschätzung/Meinung von LOADOUT — nicht nur zusammenfassen, sondern klar Position beziehen (z. B. 'Wir finden...', 'Aus unserer Sicht...'). Basierend auf dem, was du recherchiert hast, aber als eigene Stimme formuliert, nicht als weitere Zusammenfassung.",
  "hype": <Zahl 0-100, wie aufregend/relevant die News für Gaming-Fans ist>
}

Setze "game" nur, wenn die Meldung eindeutig zu einem dieser sechs großen \
Franchises gehört (GTA, Minecraft, Fortnite, Call of Duty, Valorant/League of \
Legends, FIFA/EA Sports FC). Bei allen anderen Themen: null.

Setze "genre" nur, wenn die Meldung sich klar auf ein konkretes Spiel mit \
erkennbarem Genre bezieht (z. B. Ankündigung, Release, Update zu einem \
bestimmten Spiel). Bei allgemeinen Branchen-/Hardware-/Unternehmensmeldungen \
ohne Bezug zu einem einzelnen Spiel: null.
"""


def write_article(entry):
    user_prompt = f"""Titel: {entry['title']}
Kurzbeschreibung: {entry['summary'][:600]}
Quelle: {entry['source']}
Original-Link: {entry['link']}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=3500,
        system=WRITER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    # Bei aktivierter Websuche enthält die Antwort mehrere Blöcke (Suchanfragen,
    # Suchergebnisse, ggf. Denk-Blöcke) — uns interessiert nur der letzte,
    # finale Text-Block mit dem eigentlichen JSON-Ergebnis.
    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print(f"  ! Keine Textantwort erhalten für: {entry['title']}", file=sys.stderr)
        return None
    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    # Absicherung: erklärenden Text vor dem eigentlichen JSON-Objekt abschneiden,
    # falls Claude trotz Anweisung noch welchen hinzufügt.
    first_brace = raw_text.find("{")
    if first_brace > 0:
        raw_text = raw_text[first_brace:]

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"  ! Konnte Antwort nicht parsen für: {entry['title']}", file=sys.stderr)
        return None

    # Absicherung gegen ungültige Aufzählungswerte: Die KI soll laut Prompt
    # nur bestimmte feste Werte für "cat", "game" und "genre" liefern, hält
    # sich aber nicht immer zuverlässig daran (z. B. "league of legends"
    # statt "valorant"). Ein ungültiger Wert hier würde auf der Website
    # NICHT einfach nur falsch aussehen, sondern die komplette Seite zum
    # Absturz bringen (JavaScript bricht beim Nachschlagen des Labels ab,
    # noch bevor die Klick-Funktionen eingerichtet sind) — deshalb wird
    # hier klar validiert statt der KI blind zu vertrauen.
    VALID_CATS = {"pc", "konsole", "hardware", "industrie"}
    VALID_GAMES = {"gta", "minecraft", "fortnite", "cod", "valorant", "fifa"}
    VALID_GENRES = {"action", "adventure", "rpg", "strategie", "simulation",
                     "shooter", "sport", "rennspiel", "horror", "puzzle"}

    cat = data.get("cat")
    if cat not in VALID_CATS:
        print(f"  ⚠ Ungültiger cat-Wert '{cat}' — auf 'industrie' zurückgesetzt.", file=sys.stderr)
        cat = "industrie"

    game = data.get("game")
    if game is not None and game not in VALID_GAMES:
        print(f"  ⚠ Ungültiger game-Wert '{game}' — auf None zurückgesetzt.", file=sys.stderr)
        game = None

    genre = data.get("genre")
    if genre is not None and genre not in VALID_GENRES:
        print(f"  ⚠ Ungültiger genre-Wert '{genre}' — auf None zurückgesetzt.", file=sys.stderr)
        genre = None

    return {
        "id": article_id(entry["link"]),
        "cat": cat,
        "game": game,
        "genre": genre,
        "title": data.get("title", entry["title"]),
        "teaser": data.get("teaser", ""),
        "body": data.get("body", []),
        "editorial_take": data.get("editorial_take", ""),
        "source_title": entry["title"],  # das ORIGINALE, englische Quelltitel — wichtig für die Themen-Dedup-Prüfung künftiger Läufe!
        "date": datetime.date.today().strftime("%d. %B %Y"),
        "platform": entry["source"],
        "hype": int(data.get("hype", 50)),
        "source": entry["link"],
        "sourceLabel": entry["source"],
        "image": entry.get("image"),
    }


def main():
    existing = []
    if os.path.exists(ARTICLES_FILE):
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)

    archive = []
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            archive = json.load(f)

    print("→ Lese RSS-Feeds...")
    raw_entries = fetch_raw_entries()
    print(f"  {len(raw_entries)} Einträge insgesamt aus {len(FEEDS)} Feeds gelesen")

    existing_ids = {a["id"] for a in archive} | {a["id"] for a in existing}
    new_raw = [e for e in raw_entries if article_id(e["link"]) not in existing_ids]

    # Themen-Dopplung verhindern: Titel gegen die zuletzt geschriebenen
    # Artikel vergleichen — WICHTIG: hier werden die ENGLISCHEN
    # Original-Quelltitel verglichen (source_title), NICHT die fertigen
    # deutschen Artikeltitel! Ein Vergleich Englisch-gegen-Deutsch würde
    # so gut wie nie anschlagen, selbst bei exakt demselben Thema, weil
    # die KI die Meldung ja komplett neu auf Deutsch formuliert.
    recent_source_titles = [
        a.get("source_title", a.get("title", ""))  # Fallback für ältere Artikel ohne source_title
        for a in (archive[-40:] + existing)
    ]
    before_count = len(new_raw)
    new_raw = filter_duplicate_topics(new_raw, recent_source_titles)
    skipped = before_count - len(new_raw)
    if skipped:
        print(f"  {skipped} Meldung(en) als Themen-Duplikat übersprungen")

    # Auswahl mit garantierter Franchise-Quote UND garantierter Gesamtzahl:
    # Es wird so lange der jeweils nächste Kandidat aus dem Pool probiert,
    # bis entweder PRIORITY_QUOTA Franchise-Artikel bzw. MAX_ARTICLES_PER_RUN
    # Artikel insgesamt wirklich erfolgreich geschrieben wurden — nicht nur
    # ausgewählt. Schlägt das Schreiben eines einzelnen Kandidaten fehl,
    # wird automatisch der nächste Kandidat aus dem Pool nachgezogen.
    priority_entries = [e for e in new_raw if e.get("priority")]
    normal_entries = [e for e in new_raw if not e.get("priority")]

    print(f"  {len(new_raw)} mögliche Kandidaten verfügbar für {MAX_ARTICLES_PER_RUN} Plätze "
          f"({len(priority_entries)} davon aus Franchise-Feeds)")

    written = []
    used_links = set()

    def try_write(entry):
        if not entry.get("image"):
            entry["image"] = fetch_og_image(entry["link"])
        print(f"  ✎ Schreibe: {entry['title'][:70]}")
        article = write_article(entry)
        if article:
            written.append(article)
            used_links.add(entry["link"])
            return True
        print("  ⚠ Fehlgeschlagen — probiere nächsten Kandidaten aus dem Pool.")
        return False

    franchise_written = 0
    for entry in priority_entries:
        if franchise_written >= PRIORITY_QUOTA:
            break
        if try_write(entry):
            franchise_written += 1

    remaining_pool = [e for e in (normal_entries + priority_entries) if e["link"] not in used_links]
    seen_links = set()
    dedup_pool = []
    for e in remaining_pool:
        if e["link"] in seen_links:
            continue
        seen_links.add(e["link"])
        dedup_pool.append(e)

    for entry in dedup_pool:
        if len(written) >= MAX_ARTICLES_PER_RUN:
            break
        try_write(entry)

    if len(written) < MAX_ARTICLES_PER_RUN:
        print(f"  ⚠ Nur {len(written)} von {MAX_ARTICLES_PER_RUN} Artikeln konnten erstellt "
              f"werden — nicht genug neue, einzigartige Meldungen in den Feeds gefunden.")
    if franchise_written < PRIORITY_QUOTA:
        print("  ⚠ Keine passende Franchise-Meldung (GTA/Minecraft/Fortnite/CoD/Valorant/FIFA) "
              "in diesem Lauf gefunden.")

    all_articles = written + existing
    all_articles = all_articles[:MAX_ARTICLES_TOTAL]

    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    archive = written + archive
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)

    print(f"✓ {len(written)} neue Artikel geschrieben. "
          f"{len(all_articles)} aktuell in articles.json, {len(archive)} insgesamt im Archiv.")


if __name__ == "__main__":
    main()
