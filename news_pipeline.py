"""
LOADOUT News-Pipeline
======================
Ruft Gaming-News aus mehreren RSS-Feeds ab und lässt Claude daraus
eigenständige, deutsche Artikel im Format der LOADOUT-Website schreiben.

Setup:
    pip install feedparser anthropic

    export ANTHROPIC_API_KEY="dein-api-key"   # macOS/Linux
    setx ANTHROPIC_API_KEY "dein-api-key"      # Windows

Ausführen:
    python news_pipeline.py

Ergebnis:
    articles.json  -> wird von der Website (index.html) geladen
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

# ---------------------------------------------------------------------------
# 1. KONFIGURATION
# ---------------------------------------------------------------------------

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
    # URLs vor dem produktiven Einsatz gelegentlich prüfen — RSS-Adressen
    # kleinerer Fan-Seiten ändern sich mit der Zeit.
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
MAX_ARTICLES_TOTAL = 60           # wie viele in articles.json (Startseite/Suche) bleiben — der Rest verschwindet NICHT, sondern wandert ins unbegrenzte archive.json
OUTPUT_FILE = "articles.json"
ARCHIVE_FILE = "archive.json"     # unbegrenztes Archiv — jeder je geschriebene Artikel bleibt hier für immer auffindbar
MODEL = "claude-sonnet-5"

client = Anthropic()  # liest ANTHROPIC_API_KEY automatisch aus der Umgebung


# ---------------------------------------------------------------------------
# 2. NEWS SAMMELN
# ---------------------------------------------------------------------------

def fetch_raw_entries():
    """Holt die neuesten Einträge aus allen konfigurierten Feeds."""
    entries = []
    for feed in FEEDS:
        feed_url = feed["url"]
        try:
            parsed = feedparser.parse(
                feed_url,
                agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            source_name = parsed.feed.get("title", feed_url)
            for entry in parsed.entries[:6]:  # die letzten 6 pro Feed reichen
                entries.append({
                    "title": entry.get("title", "").strip(),
                    "summary": strip_html(entry.get("summary", "")),
                    "link": entry.get("link", ""),
                    "source": source_name,
                    "image": extract_feed_image(entry),
                    "priority": feed.get("priority", False),
                })
        except Exception as e:
            print(f"  ! Feed konnte nicht geladen werden ({feed_url}): {e}", file=sys.stderr)
    return entries


def extract_feed_image(entry):
    """Versucht, das im RSS-Eintrag mitgelieferte Bild der Original-Meldung
    zu finden (media:thumbnail, media:content oder ein Bild-Enclosure).
    Das ist genau das Bild, das der Original-Artikel selbst zeigt — also
    inhaltlich wirklich passend, nicht nur thematisch ähnlich."""
    thumb = entry.get("media_thumbnail")
    if thumb:
        return thumb[0].get("url")

    content = entry.get("media_content")
    if content:
        for item in content:
            if item.get("medium") == "image" or "image" in item.get("type", ""):
                return item.get("url")

    for enc in entry.get("links", []):
        if enc.get("rel") == "enclosure" and enc.get("type", "").startswith("image"):
            return enc.get("href")

    return None


def fetch_og_image(url, timeout=8):
    """Fallback, falls der Feed selbst kein Bild mitliefert: ruft die
    Original-Seite ab und liest das og:image (bzw. twitter:image) Meta-Tag
    aus — dasselbe Bild, das auch bei Facebook/Twitter-Vorschauen erscheint.
    Löst dabei auch relative Bild-Pfade zu vollständigen URLs auf."""
    from urllib.parse import urljoin

    patterns = [
        r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image:src["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
    ]

    # Ein Browser-typischer User-Agent statt eines erkennbaren Bot-Namens —
    # viele große Gaming-Seiten (IGN, PC Gamer etc.) blockieren Anfragen,
    # die sich klar als automatisierter Scraper zu erkennen geben.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(url, timeout=timeout, headers=headers)
        if resp.status_code != 200:
            print(f"  ! og:image-Abruf fehlgeschlagen (Status {resp.status_code}) für {url}", file=sys.stderr)
            return None

        for pattern in patterns:
            match = re.search(pattern, resp.text, re.I)
            if match:
                image_url = match.group(1)
                # Manche Seiten liefern relative Pfade (z. B. "/img/cover.jpg")
                # statt vollständiger URLs — hier zur echten, ladbaren URL auflösen.
                return urljoin(url, image_url)

        print(f"  ! Kein og:image-Tag gefunden auf {url}", file=sys.stderr)
    except Exception as e:
        print(f"  ! Konnte kein og:image laden von {url}: {e}", file=sys.stderr)
    return None


def strip_html(text):
    """Sehr einfache HTML-Bereinigung für RSS-Summaries."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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
    """Entfernt Meldungen, deren Titel einem bereits verarbeiteten Thema zu
    ähnlich ist — sowohl im Vergleich zu kürzlich geschriebenen Artikeln
    (verschiedene Läufe) als auch zu anderen Einträgen im selben Lauf
    (verschiedene Quellen, gleiches Thema, z. B. IGN und PCGamer berichten
    beide über dasselbe GTA-Update)."""
    kept = []
    seen_titles = list(already_covered_titles)
    for entry in entries:
        if any(titles_similar(entry["title"], seen) for seen in seen_titles):
            continue  # gleiches Thema wurde schon abgedeckt — überspringen
        kept.append(entry)
        seen_titles.append(entry["title"])
    return kept


# ---------------------------------------------------------------------------
# 3. ARTIKEL MIT CLAUDE SCHREIBEN
# ---------------------------------------------------------------------------

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
- Schreibe zusätzlich zur deutschen Version auch eine EIGENSTÄNDIGE englische \
Version (nicht einfach eine Übersetzung Wort für Wort, sondern genauso \
lebendig und eigenständig formuliert wie die deutsche — im Feld "en").

JSON-Format:
{
  "cat": "pc" | "konsole" | "hardware" | "industrie",
  "game": "gta" | "minecraft" | "fortnite" | "cod" | "valorant" | "fifa" | null,
  "genre": "action" | "adventure" | "rpg" | "strategie" | "simulation" | "shooter" | "sport" | "rennspiel" | "horror" | "puzzle" | null,
  "title": "Deutscher, knackiger Titel (max. 90 Zeichen)",
  "teaser": "1-2 Sätze Anreißer (max. 200 Zeichen)",
  "body": ["Absatz 1", "Absatz 2", "Absatz 3 — hier auch einordnen, was andere Quellen/Experten/die Community dazu sagen"],
  "editorial_take": "2-3 Sätze EIGENE redaktionelle Einschätzung/Meinung von LOADOUT — nicht nur zusammenfassen, sondern klar Position beziehen (z. B. 'Wir finden...', 'Aus unserer Sicht...'). Basierend auf dem, was du recherchiert hast, aber als eigene Stimme formuliert, nicht als weitere Zusammenfassung.",
  "en": {
    "title": "Englischer, ebenso eigenständig formulierter Titel (max. 90 Zeichen)",
    "teaser": "1-2 englische Sätze Anreißer (max. 200 Zeichen)",
    "body": ["Absatz 1 auf Englisch", "Absatz 2 auf Englisch", "Absatz 3 auf Englisch — inkl. Einordnung anderer Quellen"],
    "editorial_take": "2-3 Sätze redaktionelle Einschätzung auf Englisch — eigenständig formuliert, keine reine Übersetzung des deutschen Texts."
  },
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
        max_tokens=6000,
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

    return {
        "id": article_id(entry["link"]),
        "cat": data.get("cat", "industrie"),
        "game": data.get("game"),
        "genre": data.get("genre"),
        "title": data.get("title", entry["title"]),
        "teaser": data.get("teaser", ""),
        "body": data.get("body", []),
        "editorial_take": data.get("editorial_take", ""),
        "en": data.get("en"),  # englische Zusatzversion, siehe Prompt oben — kann bei alten Artikeln fehlen
        "date": datetime.date.today().strftime("%d. %B %Y"),
        "platform": entry["source"],
        "hype": int(data.get("hype", 50)),
        "source": entry["link"],
        "sourceLabel": entry["source"],
        "image": entry.get("image"),
    }


# ---------------------------------------------------------------------------
# 4. HAUPTABLAUF
# ---------------------------------------------------------------------------

def load_existing_articles():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def load_archive():
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def main():
    print("→ Sammle Feeds …")
    raw_entries = fetch_raw_entries()
    print(f"  {len(raw_entries)} Roheinträge gefunden")

    existing = load_existing_articles()
    archive = load_archive()
    # Gegen das komplette Archiv prüfen, nicht nur die gekürzte articles.json —
    # sonst könnte eine alte, von der Startseite gefallene Meldung fälschlich
    # nochmal als "neu" erkannt und doppelt geschrieben werden.
    existing_ids = {a["id"] for a in archive} | {a["id"] for a in existing}

    new_raw = [e for e in raw_entries if article_id(e["link"]) not in existing_ids]

    # Themen-Dopplung verhindern: Titel gegen die zuletzt geschriebenen
    # Artikel vergleichen (deckt auch Fälle ab, in denen zwei verschiedene
    # Quellen — z. B. IGN und PCGamer — über dieselbe Meldung berichten,
    # aber mit unterschiedlicher URL, was der reine Link-Vergleich oben
    # nicht erkennen würde).
    recent_titles = [a.get("title", "") for a in (archive[-40:] + existing)]
    before_count = len(new_raw)
    new_raw = filter_duplicate_topics(new_raw, recent_titles)
    skipped = before_count - len(new_raw)
    if skipped:
        print(f"  {skipped} Meldung(en) als Themen-Duplikat übersprungen")

    # Auswahl mit garantierter Franchise-Quote UND garantierter Gesamtzahl:
    # Es wird so lange der jeweils nächste Kandidat aus dem Pool probiert,
    # bis entweder PRIORITY_QUOTA Franchise-Artikel bzw. MAX_ARTICLES_PER_RUN
    # Artikel insgesamt wirklich erfolgreich geschrieben wurden — nicht nur
    # ausgewählt. Schlägt das Schreiben eines einzelnen Kandidaten fehl
    # (z. B. nicht parsebare KI-Antwort), wird automatisch der nächste
    # Kandidat aus dem Pool nachgezogen, statt einfach einen Platz frei zu
    # lassen. So kommen zuverlässig immer MAX_ARTICLES_PER_RUN Artikel pro
    # Lauf zustande, solange die Feeds insgesamt genug Material liefern.
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
        print(f"  ⚠ Fehlgeschlagen — probiere nächsten Kandidaten aus dem Pool.")
        return False

    # Schritt 1: mindestens PRIORITY_QUOTA Franchise-Artikel sicherstellen —
    # bei Fehlschlägen den nächsten Franchise-Kandidaten probieren, nicht
    # nach dem ersten Versuch aufgeben.
    franchise_written = 0
    for entry in priority_entries:
        if franchise_written >= PRIORITY_QUOTA:
            break
        if try_write(entry):
            franchise_written += 1

    # Schritt 2: restliche Plätze auffüllen — aus allen noch nicht
    # verwendeten Kandidaten (allgemeine zuerst, dann übrige Franchise-
    # Artikel), ebenfalls mit automatischem Nachziehen bei Fehlschlägen.
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
        print(f"  ⚠ Keine passende Franchise-Meldung (GTA/Minecraft/Fortnite/CoD/Valorant/FIFA) "
              f"in diesem Lauf gefunden.")

    all_articles = written + existing
    all_articles = all_articles[:MAX_ARTICLES_TOTAL]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    # Archiv: unbegrenzt, damit wirklich jeder je geschriebene Artikel
    # dauerhaft auffindbar bleibt (siehe archiv.html auf der Website).
    full_archive = written + archive
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(full_archive, f, ensure_ascii=False, indent=2)

    print(f"✓ {len(written)} neue Artikel geschrieben")
    print(f"  → {len(all_articles)} aktuell auf der Startseite ({OUTPUT_FILE})")
    print(f"  → {len(full_archive)} insgesamt im Archiv ({ARCHIVE_FILE})")


if __name__ == "__main__":
    main()
