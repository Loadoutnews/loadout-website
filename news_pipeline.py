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
import random
import re
import sys
import difflib

import feedparser
import requests
from anthropic import Anthropic

MODEL = "claude-sonnet-5"
# Günstiges, schnelles Modell nur für die reine Ja/Nein-Klassifikation bei
# der Duplikat-Prüfung (siehe semantic_duplicate_filter) — dafür braucht es
# kein großes, teures Modell wie beim eigentlichen Artikel-Schreiben.
DEDUP_MODEL = "claude-haiku-4-5-20251001"
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
    {"url": "https://rockstarintel.com/feed/", "priority": True},          # GTA
    {"url": "https://gamerant.com/feed/minecraft-news", "priority": True},  # Minecraft
    {"url": "https://gamerant.com/feed/fortnite-news", "priority": True},   # Fortnite
    {"url": "https://charlieintel.com/feed", "priority": True},             # Call of Duty
    {"url": "https://dotesports.com/feed", "priority": True},               # Valorant/LoL
    {"url": "https://realsport101.com/feed.xml", "priority": True},         # FIFA/EA Sports FC
]

# Wie viele der pro Lauf geschriebenen Artikel mindestens aus den
# Franchise-Feeds oben kommen sollen (der Rest wird mit allgemeinen
# Gaming-News aufgefüllt).
PRIORITY_QUOTA = 1

MAX_ARTICLES_PER_RUN = 4    # wie viele neue Artikel pro Durchlauf geschrieben werden
MAX_ARTICLES_TOTAL = 60     # wie viele Artikel maximal in articles.json stehen (Homepage-Cache)

ARTICLES_FILE = "articles.json"
ARCHIVE_FILE = "archive.json"

# --- Eigenständige Analyse-Artikel ------------------------------------------
# Ein Teil der täglichen Artikel soll NICHT aus einer einzelnen RSS-Meldung
# entstehen, sondern echte, eigenständige Redaktionsarbeit sein: die KI
# recherchiert selbst über mehrere Quellen hinweg (Verkaufscharts, Streaming-
# Plattformen, Foren/Communities, mehrere Presseberichte) und verfasst daraus
# einen synthetisierten Artikel — nicht die Umformulierung einer einzelnen
# Meldung. Bewusst MEHR als nur 3-4 Formate, damit die Seite nicht immer auf
# dieselben 1-2 "einfachsten" Muster zurückfällt.
ANALYSIS_ARTICLES_PER_RUN = 1  # bewusst konservativ gestartet (Kostenkontrolle) — bei Bedarf auf 2 erhöhen
ANALYSIS_SEARCH_BUDGET = 8     # deutlich mehr Websuchen als bei normalen Artikeln (max_uses=3), da echte Multi-Quellen-Recherche nötig ist
ANALYSIS_FORMAT_CHOICES_PER_RUN = 4  # wie viele der Formate unten der KI pro Lauf zur Auswahl vorgelegt werden (Zufallsauswahl für Abwechslung)

ANALYSIS_FORMATS = [
    ("verkaufszahlen", "Verkaufszahlen & Markt-Analyse",
     "Wertet aktuelle Verkaufscharts (z. B. Steam-Bestseller, geschätzte Konsolen-Absatzzahlen) aus und ordnet ein, welche Titel gerade wirklich performen und warum."),
    ("streaming_trend", "Streaming-Trend-Watch",
     "Analysiert, welche Spiele gerade auf Twitch/YouTube Gaming besonders viele Zuschauer:innen/Views haben und was den Boom auslöst."),
    ("leak_rundschau", "Leak-Rundschau",
     "Sammelt mehrere aktuell kursierende Leaks/Gerüchte zu einem großen, kommenden Spiel, ordnet deren Glaubwürdigkeit ein und fasst zusammen, was davon wirklich belastbar ist."),
    ("community_puls", "Community-Puls",
     "Fasst zusammen, was in relevanten Subreddits/Foren/der Community gerade zu einem aktuellen Thema diskutiert wird — ein echtes Stimmungsbild, keine Einzelmeinung."),
    ("kaufberatung", "Kaufberatung & Preisvergleich",
     "Vergleicht Editionen/Preise eines aktuellen oder kommenden Spiels und gibt eine fundierte, eigene Einschätzung, ob sich Kauf oder Vorbestellung lohnt."),
    ("patch_einordnung", "Patch-Notes-Einordnung",
     "Nimmt aktuelle, umfangreiche Patch-Notes eines großen Spiels und erklärt für Spieler:innen, was die Änderungen WIRKLICH im Spielgefühl bedeuten, nicht nur was wörtlich drinsteht."),
    ("esport_rueckblick", "Esport-Wochenrückblick",
     "Fasst die wichtigsten Ergebnisse und Storylines eines aktuellen großen Esport-Turniers zusammen und ordnet sie ein."),
    ("branchen_watch", "Studio- & Branchen-Watch",
     "Ordnet eine aktuelle Branchenmeldung (Entlassungen, Übernahme, Studio-Schließung o. Ä.) ein und erklärt Hintergrund und Auswirkungen für Spieler:innen."),
    ("technik_deepdive", "Technik-Deep-Dive",
     "Vergleicht die technische Performance (Bildrate, Auflösung, Ladezeiten) eines aktuellen Spiels auf verschiedenen Plattformen — im Stil einer echten Technik-Analyse."),
    ("retrospektive", "Rückblick & Jubiläum",
     "Blickt anlässlich eines Jubiläums auf ein älteres, bedeutendes Spiel zurück und ordnet dessen Einfluss auf die Branche bis heute ein."),
    ("faktencheck", "Gerücht-Faktencheck",
     "Prüft ein aktuell kursierendes Gerücht anhand mehrerer unabhängiger Quellen und ordnet ein, wie glaubwürdig es wirklich ist."),
]

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
    """ERSTE, GÜNSTIGE Stufe der Duplikat-Prüfung: reiner Text-Abgleich,
    kostet keinen API-Aufruf. Fängt offensichtliche Fälle ab (z. B. exakt
    derselbe oder fast identisch formulierte Titel) und verkleinert damit
    die Kandidatenliste, bevor die teurere, aber deutlich zuverlässigere
    KI-gestützte Prüfung (semantic_duplicate_filter) läuft.

    WICHTIG: already_covered_titles muss die ENGLISCHEN Original-Quelltitel
    enthalten, nicht die fertigen deutschen Artikeltitel — sonst vergleicht
    die Prüfung Äpfel mit Birnen (Englisch gegen Deutsch)."""
    kept = []
    seen_titles = list(already_covered_titles)
    for entry in entries:
        if any(titles_similar(entry["title"], seen) for seen in seen_titles if seen):
            continue  # gleiches Thema wurde schon abgedeckt — überspringen
        kept.append(entry)
        seen_titles.append(entry["title"])
    return kept


def semantic_duplicate_filter(entries, recent_titles, max_recent=40):
    """ZWEITE, KI-GESTÜTZTE Stufe der Duplikat-Prüfung — der eigentliche
    Kern der Lösung. Reiner Text-Abgleich (filter_duplicate_topics oben)
    erkennt zuverlässig NUR fast identisch formulierte Titel. In der Praxis
    berichten aber z. B. IGN und PCGamer oft über dieselbe Meldung mit
    KOMPLETT unterschiedlichen Überschriften — das schlägt bei reinem
    Text-Vergleich so gut wie nie an, obwohl es inhaltlich dasselbe Thema
    ist. Deshalb lässt diese Stufe die KI selbst beurteilen, ob der
    inhaltliche KERN übereinstimmt, unabhängig vom Wortlaut.

    Prüft dabei sowohl gegen bereits veröffentlichte Themen als auch
    INNERHALB des aktuellen Kandidaten-Pools (falls z. B. zwei
    verschiedene Feeds im selben Lauf dieselbe Meldung liefern).

    Nutzt bewusst ein günstiges, schnelles Modell (Haiku) statt Sonnet —
    das ist eine reine Klassifikationsaufgabe, kein kreatives Schreiben,
    dafür genügt ein kleineres Modell locker, und es hält die Kosten
    niedrig (siehe Kostenoptimierung an anderer Stelle der Pipeline)."""
    if not entries:
        return entries

    recent = [t for t in recent_titles if t][-max_recent:]
    candidates_block = "\n".join(f"{i}: {e['title']}" for i, e in enumerate(entries))
    recent_block = "\n".join(f"- {t}" for t in recent) if recent else "(keine)"

    prompt = f"""Bereits kürzlich veröffentlichte Themen:
{recent_block}

Neue Kandidaten (nummeriert, 0-basiert):
{candidates_block}

Aufgabe: Finde alle Kandidaten, die INHALTLICH DASSELBE THEMA behandeln
wie entweder (a) eines der bereits veröffentlichten Themen, ODER (b) einen
ANDEREN Kandidaten in der obigen Liste (z. B. wenn zwei verschiedene
Quellen dieselbe Meldung nur unterschiedlich formuliert haben). Es zählt
der inhaltliche Kern, nicht der Wortlaut — unterschiedliche Quellen
formulieren dieselbe Meldung oft komplett anders.

Antworte AUSSCHLIESSLICH mit einem JSON-Array der Nummern, die als
Duplikat AUSSORTIERT werden sollen (bei mehreren Kandidaten zum selben
Thema: alle bis auf den ERSTEN in der Liste aussortieren). Beispiel:
[2, 5, 6]. Falls keine Duplikate gefunden wurden: []. Keine Erklärung,
kein Markdown, nur das JSON-Array."""

    try:
        response = client.messages.create(
            model=DEDUP_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            print("  ⚠ Semantische Duplikat-Prüfung: keine Antwort erhalten — überspringe diese Stufe.", file=sys.stderr)
            return entries
        raw = text_blocks[-1].strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        first_bracket = raw.find("[")
        if first_bracket > 0:
            raw = raw[first_bracket:]
        duplicate_indices = set(json.loads(raw, strict=False))
    except Exception as e:
        print(f"  ⚠ Semantische Duplikat-Prüfung fehlgeschlagen ({e}) — überspringe diese Stufe für diesen Lauf.", file=sys.stderr)
        return entries  # im Zweifel nichts wegfiltern, lieber ein seltenes Duplikat als fälschlich Artikel verlieren

    filtered = [e for i, e in enumerate(entries) if i not in duplicate_indices]
    removed = len(entries) - len(filtered)
    if removed:
        print(f"  {removed} weitere(s) Duplikat(e) durch KI-Prüfung erkannt (unterschiedlicher Wortlaut, gleiches Thema)")
    return filtered


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
(z. B. Mehrere Fachmedien loben..., oder: In der Community gibt es geteilte \
Reaktionen — während einige loben, kritisieren andere...).
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine Erklärungen, \
kein Markdown, keine Code-Fences.
- WICHTIG für gültiges JSON: Verwende in allen Textfeldern (title, teaser, \
body, editorial_take) NIEMALS gerade doppelte Anführungszeichen, auch nicht \
für Zitate oder Betonung — die brechen das JSON-Format. Nutze stattdessen \
deutsche Anführungszeichen oder verzichte ganz auf Anführungszeichen \
innerhalb der Texte. Verwende außerdem KEINE rohen Zeilenumbrüche innerhalb \
eines einzelnen Textfelds/Absatzes — jeder Absatz muss eine durchgehende \
Zeile ohne Zeilenumbruch sein (für mehrere Absätze stattdessen mehrere \
Einträge in der "body"-Liste verwenden).

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
        # Prompt-Caching: Der System-Prompt ist bei JEDEM der bis zu 4 Aufrufe
        # pro Lauf identisch (und läuft mehrmals täglich). Mit cache_control
        # merkt sich Anthropic diesen Textblock für 5 Minuten — innerhalb
        # eines Laufs (alle 4 Artikel kurz hintereinander) greift der Cache
        # fast immer, was die Eingabe-Tokens für diesen Teil deutlich
        # günstiger macht, ohne dass sich am Ergebnis irgendetwas ändert.
        system=[{"type": "text", "text": WRITER_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_prompt}],
        # max_uses begrenzt, wie oft die KI selbstständig nachsucht — weniger
        # Suchdurchläufe bedeuten weniger (teure) Suchergebnis-Tokens im
        # Kontext, ohne die Recherchequalität für einen einzelnen
        # Artikel spürbar zu verschlechtern.
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
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
        data = json.loads(raw_text, strict=False)
    except json.JSONDecodeError as e:
        error_pos = e.pos
        context_start = max(0, error_pos - 150)
        context_end = min(len(raw_text), error_pos + 150)
        print(f"  ! Konnte Antwort nicht parsen für: {entry['title']} — {e.msg} (Position {error_pos})", file=sys.stderr)
        print(f"    Kontext: ...{raw_text[context_start:error_pos]}▶▶▶HIER◀◀◀{raw_text[error_pos:context_end]}...", file=sys.stderr)
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


# --- Eigenständige Analyse-Artikel -------------------------------------------
# Zweistufiger Prozess, bewusst getrennt in "Thema vorschlagen" (günstig,
# Haiku) und "vollen Artikel schreiben" (teurer, Sonnet + viel Websuche) —
# so wird der teure Schritt nur ausgeführt, wenn das Thema nach der
# Duplikat-Prüfung wirklich neu ist. Ein bereits als Duplikat erkanntes
# Thema kostet uns so nur den günstigen Vorschlags-Aufruf, nicht den vollen
# Recherche- und Schreib-Aufwand.

def propose_analysis_topic(recent_titles, max_recent=40):
    """Lässt die KI aus einer zufälligen Auswahl von Formaten EIN Format +
    ein konkretes, aktuelles Thema dafür vorschlagen — noch OHNE den vollen
    Artikel zu recherchieren/schreiben. Gibt None zurück, falls kein
    sinnvoller Vorschlag zustande kam."""
    format_choices = random.sample(ANALYSIS_FORMATS, min(ANALYSIS_FORMAT_CHOICES_PER_RUN, len(ANALYSIS_FORMATS)))
    formats_block = "\n".join(f"- {key}: {label} — {desc}" for key, label, desc in format_choices)
    recent = [t for t in recent_titles if t][-max_recent:]
    recent_block = "\n".join(f"- {t}" for t in recent) if recent else "(noch keine)"

    prompt = f"""Wähle EINES der folgenden Artikel-Formate aus und schlage dafür \
ein konkretes, aktuelles Thema vor, über das es sich JETZT lohnt zu schreiben:

{formats_block}

Bereits kürzlich behandelte Themen (NICHT nochmal vorschlagen, auch nicht \
in einem anderen Format):
{recent_block}

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine Erklärung, \
kein Markdown:
{{
  "format_key": "<einer der obigen Format-Schlüssel>",
  "working_title": "<konkretes, spezifisches Arbeits-Thema, z. B. Name des Spiels/Turniers/Gerüchts>",
  "angle": "<1 Satz: welcher konkrete Blickwinkel/welche These dieser Artikel verfolgt>"
}}"""

    try:
        response = client.messages.create(
            model=DEDUP_MODEL,  # günstiges Modell — reine Themenfindung, kein finaler Artikeltext
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            return None
        raw = text_blocks[-1].strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        first_brace = raw.find("{")
        if first_brace > 0:
            raw = raw[first_brace:]
        data = json.loads(raw, strict=False)
    except Exception as e:
        print(f"  ⚠ Themenvorschlag für Analyse-Artikel fehlgeschlagen: {e}", file=sys.stderr)
        return None

    format_lookup = {key: (label, desc) for key, label, desc in ANALYSIS_FORMATS}
    format_key = data.get("format_key")
    if format_key not in format_lookup:
        print(f"  ⚠ Ungültiger format_key '{format_key}' im Themenvorschlag — übersprungen.", file=sys.stderr)
        return None

    label, desc = format_lookup[format_key]
    return {
        "format_key": format_key,
        "format_label": label,
        "format_desc": desc,
        "working_title": data.get("working_title", ""),
        "angle": data.get("angle", ""),
    }


ANALYSIS_WRITER_SYSTEM_PROMPT = """Du bist Redakteur:in bei LOADOUT, einer deutschsprachigen \
Gaming- und Tech-News-Seite. Du schreibst heute KEINE Umformulierung einer \
einzelnen Presse-Meldung, sondern einen EIGENSTÄNDIGEN Analyse-/Recherche- \
Artikel im Format "{format_label}": {format_desc}

Dein konkretes Thema für diesen Artikel: {working_title}
Dein Blickwinkel/These: {angle}

Regeln:
- Recherchiere aktiv mit der Websuche über MEHRERE unabhängige Quellen \
(z. B. mehrere Presseberichte, Verkaufscharts-Seiten, Foren/Reddit, \
Streaming-Statistiken — je nach Thema passend). Ein einzelner Artikel \
mit nur einer Quelle reicht hier NICHT aus.
- Führe die verschiedenen Quellen zu einem EIGENEN, zusammenhängenden \
Artikel zusammen — kein reines Aneinanderreihen von Zitaten.
- Schreibe komplett in eigenen Worten, lebendig und für Gaming-Fans, nicht trocken.
- Nenne im Text konkret, worauf sich deine Aussagen stützen (z. B. \
"Laut aktuellen Steam-Charts...", "Mehrere Community-Threads auf Reddit \
zeigen...") — ohne wörtliche Zitate zu übernehmen.
- Sei ehrlich, wenn Datenlage/Quellenlage für einen Aspekt dünn ist, \
statt Sicherheit vorzutäuschen, die nicht da ist.
- Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt, keine \
Erklärungen, kein Markdown, keine Code-Fences.
- WICHTIG für gültiges JSON: Verwende in allen Textfeldern NIEMALS gerade \
doppelte Anführungszeichen, auch nicht für Zitate oder Betonung. Nutze \
stattdessen deutsche Anführungszeichen oder verzichte ganz darauf. \
Verwende außerdem KEINE rohen Zeilenumbrüche innerhalb eines einzelnen \
Textfelds/Absatzes.

JSON-Format:
{{
  "cat": "pc" | "konsole" | "hardware" | "industrie",
  "game": "gta" | "minecraft" | "fortnite" | "cod" | "valorant" | "fifa" | null,
  "genre": "action" | "adventure" | "rpg" | "strategie" | "simulation" | "shooter" | "sport" | "rennspiel" | "horror" | "puzzle" | null,
  "title": "Deutscher, knackiger Titel (max. 90 Zeichen)",
  "teaser": "1-2 Sätze Anreißer (max. 200 Zeichen)",
  "body": ["Absatz 1", "Absatz 2", "Absatz 3", "..."],
  "editorial_take": "2-3 Sätze EIGENE redaktionelle Einschätzung/Meinung von LOADOUT, klar Position beziehend.",
  "hype": <Zahl 0-100, wie relevant/aufregend das Thema für Gaming-Fans ist>,
  "primary_source_url": "<die EINE wichtigste/verlässlichste URL, auf die 'Zur Originalquelle' verlinken soll>",
  "primary_source_label": "<Name dieser Quelle, z. B. 'SteamDB' oder 'IGN'>"
}}

Setze "game" nur, wenn der Artikel eindeutig zu einem dieser sechs großen \
Franchises gehört (GTA, Minecraft, Fortnite, Call of Duty, Valorant/League \
of Legends, FIFA/EA Sports FC). Sonst null. "genre" nur bei klarem Bezug \
zu einem einzelnen Spiel, sonst null.
"""


def write_analysis_article(topic):
    system_prompt = ANALYSIS_WRITER_SYSTEM_PROMPT.format(
        format_label=topic["format_label"],
        format_desc=topic["format_desc"],
        working_title=topic["working_title"],
        angle=topic["angle"],
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,  # etwas mehr als bei normalen Artikeln — Analyse-Stücke sind tendenziell länger
        system=system_prompt,  # kein cache_control — Prompt ändert sich pro Aufruf (anderes Thema), Caching würde hier nicht greifen
        messages=[{"role": "user", "content": f"Schreibe jetzt den Artikel zum Thema: {topic['working_title']}"}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": ANALYSIS_SEARCH_BUDGET}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        print(f"  ! Keine Textantwort für Analyse-Artikel: {topic['working_title']}", file=sys.stderr)
        return None

    raw_text = text_blocks[-1].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    first_brace = raw_text.find("{")
    if first_brace > 0:
        raw_text = raw_text[first_brace:]

    try:
        data = json.loads(raw_text, strict=False)
    except json.JSONDecodeError as e:
        error_pos = e.pos
        context_start = max(0, error_pos - 150)
        context_end = min(len(raw_text), error_pos + 150)
        print(f"  ! Konnte Analyse-Artikel nicht parsen: {topic['working_title']} — {e.msg} (Position {error_pos})", file=sys.stderr)
        print(f"    Kontext: ...{raw_text[context_start:error_pos]}▶▶▶HIER◀◀◀{raw_text[error_pos:context_end]}...", file=sys.stderr)
        return None

    VALID_CATS = {"pc", "konsole", "hardware", "industrie"}
    VALID_GAMES = {"gta", "minecraft", "fortnite", "cod", "valorant", "fifa"}
    VALID_GENRES = {"action", "adventure", "rpg", "strategie", "simulation",
                     "shooter", "sport", "rennspiel", "horror", "puzzle"}

    cat = data.get("cat")
    if cat not in VALID_CATS:
        cat = "industrie"
    game = data.get("game")
    if game is not None and game not in VALID_GAMES:
        game = None
    genre = data.get("genre")
    if genre is not None and genre not in VALID_GENRES:
        genre = None

    source_url = data.get("primary_source_url") or SITE_URL
    source_label = data.get("primary_source_label") or topic["format_label"]

    return {
        "id": hashlib.sha1(f"analysis-{topic['working_title']}-{datetime.date.today()}".encode("utf-8")).hexdigest()[:10],
        "cat": cat,
        "game": game,
        "genre": genre,
        "title": data.get("title", topic["working_title"]),
        "teaser": data.get("teaser", ""),
        "body": data.get("body", []),
        "editorial_take": data.get("editorial_take", ""),
        # Für die Dedup-Prüfung künftiger Läufe — bei Analyse-Artikeln das
        # Arbeits-Thema selbst, da es (anders als bei RSS-Artikeln) keinen
        # englischen Original-Quelltitel gibt.
        "source_title": topic["working_title"],
        "date": datetime.date.today().strftime("%d. %B %Y"),
        "platform": "LOADOUT-Analyse",
        "hype": int(data.get("hype", 50)),
        "source": source_url,
        "sourceLabel": source_label,
        "image": fetch_og_image(source_url),
        # Zusätzliche, rein informative Felder — bestehender Code (Website,
        # Sitemap etc.) ignoriert unbekannte Felder einfach, nichts bricht.
        "content_type": "analysis",
        "analysis_format": topic["format_key"],
    }


def try_write_analysis_article(recent_source_titles, max_attempts=3):
    """Versucht bis zu max_attempts-mal, ein NEUES (nicht dupliziertes)
    Analyse-Thema zu finden und vollständig zu schreiben. Gibt None zurück,
    falls das nach mehreren Versuchen nicht gelingt — dann füllt die
    normale RSS-Auswahl den entsprechenden Artikel-Platz stattdessen."""
    for attempt in range(1, max_attempts + 1):
        topic = propose_analysis_topic(recent_source_titles)
        if not topic or not topic.get("working_title"):
            continue

        # Das vorgeschlagene Thema durch dieselbe zweistufige Duplikat-
        # Prüfung schicken wie die RSS-Artikel — als "Mini-Kandidat" mit
        # nur einem Eintrag.
        fake_entry = {"title": topic["working_title"], "link": f"analysis:{topic['working_title']}"}
        after_text_filter = filter_duplicate_topics([fake_entry], recent_source_titles)
        if not after_text_filter:
            print(f"  ⚠ Analyse-Thema '{topic['working_title']}' ist Text-Duplikat — neuer Versuch ({attempt}/{max_attempts}).")
            continue
        after_semantic_filter = semantic_duplicate_filter([fake_entry], recent_source_titles)
        if not after_semantic_filter:
            print(f"  ⚠ Analyse-Thema '{topic['working_title']}' ist inhaltliches Duplikat — neuer Versuch ({attempt}/{max_attempts}).")
            continue

        print(f"  ✎ Schreibe Analyse-Artikel [{topic['format_label']}]: {topic['working_title'][:70]}")
        article = write_analysis_article(topic)
        if article:
            return article
        print("    ⚠ Schreiben fehlgeschlagen — neuer Themenversuch.")

    print(f"  ⚠ Kein neues Analyse-Thema nach {max_attempts} Versuchen gefunden — Platz wird stattdessen mit normalem Artikel gefüllt.")
    return None


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

    # Themen-Dopplung verhindern — ZWEISTUFIG:
    # 1) Günstiger Text-Abgleich (fängt offensichtliche Fälle kostenlos ab)
    # 2) KI-gestützte inhaltliche Prüfung (fängt Fälle ab, in denen
    #    verschiedene Quellen dieselbe Meldung unterschiedlich formulieren
    #    — das war die eigentliche Lücke der bisherigen, rein textbasierten
    #    Prüfung)
    #
    # WICHTIG: hier werden die ENGLISCHEN Original-Quelltitel verglichen
    # (source_title), NICHT die fertigen deutschen Artikeltitel! Ein
    # Vergleich Englisch-gegen-Deutsch würde so gut wie nie anschlagen,
    # selbst bei exakt demselben Thema, weil die KI die Meldung ja komplett
    # neu auf Deutsch formuliert.
    recent_source_titles = [
        a.get("source_title", a.get("title", ""))  # Fallback für ältere Artikel ohne source_title
        for a in (archive[-40:] + existing)
    ]

    written = []

    # Eigenständige Analyse-Artikel ZUERST schreiben (bevor die RSS-Auswahl
    # läuft) — deren Themen werden danach direkt zur Duplikat-Vergleichsliste
    # hinzugefügt, damit die RSS-Auswahl unten nicht versehentlich dasselbe
    # Thema nochmal aus einer Presse-Meldung heraus verarbeitet.
    print(f"→ Erstelle {ANALYSIS_ARTICLES_PER_RUN} eigenständige Analyse-Artikel...")
    for _ in range(ANALYSIS_ARTICLES_PER_RUN):
        analysis_article = try_write_analysis_article(recent_source_titles)
        if analysis_article:
            written.append(analysis_article)
            recent_source_titles.append(analysis_article["source_title"])

    before_count = len(new_raw)
    new_raw = filter_duplicate_topics(new_raw, recent_source_titles)
    new_raw = semantic_duplicate_filter(new_raw, recent_source_titles)
    skipped = before_count - len(new_raw)
    if skipped:
        print(f"  {skipped} Meldung(en) insgesamt als Themen-Duplikat übersprungen")

    # Auswahl mit garantierter Franchise-Quote UND garantierter Gesamtzahl:
    # Es wird so lange der jeweils nächste Kandidat aus dem Pool probiert,
    # bis entweder PRIORITY_QUOTA Franchise-Artikel bzw. MAX_ARTICLES_PER_RUN
    # Artikel insgesamt wirklich erfolgreich geschrieben wurden — nicht nur
    # ausgewählt. Schlägt das Schreiben eines einzelnen Kandidaten fehl,
    # wird automatisch der nächste Kandidat aus dem Pool nachgezogen.
    priority_entries = [e for e in new_raw if e.get("priority")]
    normal_entries = [e for e in new_raw if not e.get("priority")]

    print(f"  {len(new_raw)} mögliche Kandidaten verfügbar für die verbleibenden "
          f"{MAX_ARTICLES_PER_RUN - len(written)} Plätze ({len(priority_entries)} davon aus Franchise-Feeds)")

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
        print("    ⚠ Fehlgeschlagen — probiere nächsten Kandidaten aus dem Pool.")
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
